#!/usr/bin/env python3
"""Run memory archive updates for registered projects and source streams.

This runner bootstraps an empty deployment repository by scanning a shared
source-record directory, discovering project paths from record metadata, and
then invoking the per-project updater for each enabled project. Deployments can
also register stable source streams whose archive scope and source partition do
not depend on a project registry row.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

if os.name == "posix":
    import fcntl
elif os.name == "nt":
    import msvcrt


CONFIG_CANDIDATES = (
    "MY_PRECIOUS_CONFIG",
    "AGENT_SESSION_MEMORY_CONFIG",
)
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
DEFAULT_PATTERNS = ("*.jsonl", "*.json")
PROJECT_PATH_KEYS = {
    "cwd",
    "project_path",
    "working_directory",
    "current_working_directory",
    "workspace",
    "repo_path",
    "repository_path",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env"}
PROJECT_REGISTRY = Path("config/projects.jsonl")
SOURCE_STREAM_REGISTRY = Path("config/source_streams.jsonl")
UNSAFE_PATH = "[unsafe-path]"
UNSAFE_IDENTIFIER = "[unsafe-identifier]"
CONCURRENT_UPDATE_EXIT = getattr(os, "EX_TEMPFAIL", 75)
CHILD_TERMINATION_TIMEOUT_SECONDS = 5.0


class RunnerInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(f"runner interrupted by signal {signum}")
        self.signum = signum


class UpdateRunLock:
    def __init__(self, memory_repo: Path) -> None:
        canonical_repo = str(memory_repo.resolve())
        digest = hashlib.sha256(canonical_repo.encode("utf-8")).hexdigest()
        uid = os.getuid() if hasattr(os, "getuid") else 0
        self.lock_root = Path(tempfile.gettempdir()) / f"my-precious-update-locks-{uid}"
        self.lock_path = self.lock_root / f"{digest}.lock"
        self.handle = None

    def acquire(self) -> bool:
        if self.lock_root.exists() and self.lock_root.is_symlink():
            raise OSError("unsafe update lock root")
        self.lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            self.lock_root.chmod(0o700)
        if self.lock_path.is_symlink():
            raise OSError("unsafe update lock file")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_path, flags, 0o600)
        handle = None
        try:
            handle = os.fdopen(fd, "r+b", buffering=0)
            fd = -1
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            if os.name == "posix":
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    return False
            elif os.name == "nt":
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        handle.close()
                        return False
                    raise
            else:
                raise OSError("unsupported update lock platform")
            os.set_inheritable(handle.fileno(), True)
        except BaseException:
            if handle is not None:
                handle.close()
            elif fd >= 0:
                os.close(fd)
            raise
        self.handle = handle
        return True

    def child_process_options(self) -> dict[str, object]:
        if self.handle is None:
            raise RuntimeError("update lock is not held")
        if os.name == "posix":
            return {
                "pass_fds": (self.handle.fileno(),),
                "start_new_session": True,
            }
        return {
            "close_fds": False,
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
        }

    def release(self) -> bool:
        if self.handle is None:
            return True
        released = True
        try:
            if os.name == "posix":
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            released = False
        finally:
            self.handle.close()
            self.handle = None
        return released

    def close_parent_handle(self) -> None:
        if self.handle is None:
            return
        self.handle.close()
        self.handle = None


class ChildProcessController:
    def __init__(self, update_lock: UpdateRunLock) -> None:
        self.update_lock = update_lock
        self.current: subprocess.Popen[str] | None = None

    def run(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        with (
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file,
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file,
        ):
            child = subprocess.Popen(
                command,
                cwd=cwd,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                **self.update_lock.child_process_options(),
            )
            self.current = child
            try:
                returncode = child.wait()
            finally:
                if child.poll() is not None:
                    self.current = None
            return subprocess.CompletedProcess(
                command,
                returncode,
                "",
                "",
            )

    def signal_current(self) -> None:
        child = self.current
        if child is None or child.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except PermissionError:
                try:
                    child.terminate()
                except ProcessLookupError:
                    return
        else:
            try:
                child.terminate()
            except OSError:
                return

    def terminate_current(self) -> bool:
        child = self.current
        if child is None or child.poll() is not None:
            self.current = None
            return True
        self.signal_current()
        try:
            child.wait(timeout=CHILD_TERMINATION_TIMEOUT_SECONDS)
            self.current = None
            return True
        except subprocess.TimeoutExpired:
            pass
        if os.name == "posix":
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                self.current = None
                return True
            except PermissionError:
                try:
                    child.kill()
                except ProcessLookupError:
                    self.current = None
                    return True
        else:
            try:
                child.kill()
            except OSError:
                return child.poll() is not None
        try:
            child.wait(timeout=CHILD_TERMINATION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return False
        self.current = None
        return True


def has_sensitive_identifier_token(text: str) -> bool:
    tokens = re.split(r"[^a-z0-9]+", text.lower().replace("_", " "))
    token_set = set(tokens)
    token_pairs = set(zip(tokens, tokens[1:]))
    return bool(
        token_set.intersection(
            {
                "apikey",
                "authorization",
                "bearer",
                "cookie",
                "credential",
                "password",
            }
        )
        or token_pairs.intersection(
            {
                ("api", "key"),
                ("auth", "token"),
                ("bearer", "token"),
                ("private", "key"),
                ("secret", "key"),
                ("session", "id"),
            }
        )
    )


def safe_diagnostic_path(path: Path) -> str:
    text = str(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in text) or has_sensitive_identifier_token(text):
        return UNSAFE_PATH
    return text


def safe_diagnostic_identifier(value: object) -> str:
    text = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text) or has_sensitive_identifier_token(text):
        return UNSAFE_IDENTIFIER
    return text


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def configured_memory_repos() -> list[str]:
    config_paths: list[str] = []
    for name in CONFIG_CANDIDATES:
        value = os.environ.get(name)
        if value:
            config_paths.append(value)
    config_paths.append(str(DEFAULT_CONFIG_PATH))

    repos: list[str] = []
    for candidate in config_paths:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        value = payload.get("memory_repo")
        if isinstance(value, str) and value.strip():
            repos.append(value)
    return repos


def resolve_memory_repo(repo_arg: str | None) -> Path:
    if repo_arg:
        repo = Path(repo_arg).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
        raise SystemExit("update_status=blocked reason=memory_repo_unavailable")

    candidates: list[str] = []
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(configured_memory_repos())
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit("update_status=blocked reason=memory_repo_unavailable")


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def iter_candidate_files(source_dir: Path, patterns: tuple[str, ...]) -> Iterable[Path]:
    for pattern in patterns:
        for path in source_dir.rglob(pattern):
            if path.is_file() and not should_skip(path.relative_to(source_dir)):
                yield path


def iter_json_values(path: Path, text: str) -> Iterable[object]:
    if path.suffix == ".jsonl":
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                continue
        return

    if path.suffix == ".json":
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            return
        return

    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            yield json.loads(raw_line)
        except json.JSONDecodeError:
            continue


def walk_json_values(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_values(child)


def discover_projects(source_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    discovered: set[Path] = set()
    if not source_dir.exists() or not source_dir.is_dir():
        return []
    for path in iter_candidate_files(source_dir, patterns):
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        for value in iter_json_values(path, text):
            for key, child in walk_json_values(value):
                if key in PROJECT_PATH_KEYS and isinstance(child, str) and child.strip():
                    candidate = Path(child).expanduser()
                    if candidate.is_absolute():
                        discovered.add(candidate.resolve())
    return sorted(discovered, key=lambda item: item.as_posix())


def registry_path(memory_repo: Path) -> Path:
    return memory_repo / PROJECT_REGISTRY


def source_stream_registry_path(memory_repo: Path) -> Path:
    return memory_repo / SOURCE_STREAM_REGISTRY


def is_safe_repo_path(memory_repo: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(memory_repo.resolve())
    except (OSError, ValueError):
        return False
    return True


def ensure_safe_project_registry_path(memory_repo: Path, path: Path) -> None:
    if not is_safe_repo_path(memory_repo, path):
        raise SystemExit("Refusing to access unsafe project registry path: [redacted]")


def ensure_safe_source_stream_registry_path(memory_repo: Path, path: Path) -> None:
    if not is_safe_repo_path(memory_repo, path):
        raise SystemExit("Refusing to access unsafe source stream registry path: [redacted]")


def load_registry(memory_repo: Path) -> dict[str, dict[str, object]]:
    projects: dict[str, dict[str, object]] = {}
    path = registry_path(memory_repo)
    if path.exists() or path.is_symlink():
        ensure_safe_project_registry_path(memory_repo, path)
    if not path.exists():
        return projects
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            project_path = row.get("project_path")
            if not isinstance(project_path, str) or not project_path.strip():
                continue
            resolved = Path(project_path).expanduser()
            if resolved.is_absolute():
                key = str(resolved.resolve())
            else:
                key = str(resolved)
            normalized = dict(row)
            normalized["project_path"] = key
            projects[key] = normalized
    return projects


def load_source_stream_registry(memory_repo: Path) -> dict[str, dict[str, object]]:
    streams: dict[str, dict[str, object]] = {}
    path = source_stream_registry_path(memory_repo)
    if path.exists() or path.is_symlink():
        ensure_safe_source_stream_registry_path(memory_repo, path)
    if not path.exists():
        return streams
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            stream_id = row.get("stream_id")
            if not isinstance(stream_id, str) or not stream_id.strip():
                continue
            normalized = dict(row)
            normalized["stream_id"] = stream_id.strip()
            if normalized.get("enabled", True) is not False:
                for key in ("archive_scope", "source_partition"):
                    value = normalized.get(key)
                    if not isinstance(value, str) or not value.strip():
                        raise SystemExit(
                            f"source stream configuration line {line_no} requires {key}"
                        )
                    normalized[key] = value.strip()
            streams[stream_id.strip()] = normalized
    return streams


def merge_discovered_projects(
    registered: dict[str, dict[str, object]],
    discovered: Iterable[Path],
    source_dir: Path,
) -> tuple[dict[str, dict[str, object]], int]:
    merged = dict(registered)
    now = utc_now_text()
    added = 0
    for project_path in discovered:
        key = str(project_path.resolve())
        if key in merged:
            continue
        merged[key] = {
            "project_path": key,
            "source_dir": str(source_dir),
            "enabled": True,
            "source": "discovered",
            "discovered_at": now,
        }
        added += 1
    return merged, added


def write_registry(memory_repo: Path, projects: dict[str, dict[str, object]], dry_run: bool) -> None:
    path = registry_path(memory_repo)
    if dry_run:
        print("dry-run: project registry write planned")
        return
    ensure_safe_project_registry_path(memory_repo, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(projects[key], sort_keys=True) for key in sorted(projects)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def enabled_projects(projects: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(projects):
        row = projects[key]
        if row.get("enabled", True) is False:
            continue
        rows.append(row)
    return rows


def enabled_source_streams(streams: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(streams):
        row = streams[key]
        if row.get("enabled", True) is False:
            continue
        rows.append(row)
    return rows


def require_clean_worktree(memory_repo: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=memory_repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        print(
            "update_status=blocked reason=clean_worktree_unavailable",
            file=sys.stderr,
        )
        return False
    dirty_entry_count = len(result.stdout.splitlines())
    if dirty_entry_count:
        print(
            f"update_status=blocked reason=dirty_worktree dirty_entry_count={dirty_entry_count}",
            file=sys.stderr,
        )
        return False
    return True


def run_project_update(
    controller: ChildProcessController,
    memory_repo: Path,
    project: dict[str, object],
    default_source_dir: Path,
    dry_run: bool,
    max_records: int | None,
    patterns: tuple[str, ...],
    allow_redacted_secrets: bool,
    rewrite_existing: bool,
    defer_memory_ref_reconciliation: bool,
) -> int:
    project_path = str(project["project_path"])
    source_dir = Path(str(project.get("source_dir") or default_source_dir)).expanduser().resolve()
    command = [
        sys.executable,
        str(memory_repo / "tools" / "update_memory_archive.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        project_path,
        "--require-project-metadata",
    ]
    project_name = project.get("project")
    if isinstance(project_name, str) and project_name.strip():
        command.extend(["--project", project_name])
    archive_scope = project.get("archive_scope")
    if isinstance(archive_scope, str) and archive_scope.strip():
        command.extend(["--archive-scope", archive_scope.strip()])
    source_partition = project.get("source_partition")
    if isinstance(source_partition, str) and source_partition.strip():
        command.extend(["--source-partition", source_partition.strip()])
    if max_records is not None:
        command.extend(["--max-records", str(max_records)])
    for pattern in patterns:
        command.extend(["--pattern", pattern])
    if allow_redacted_secrets:
        command.append("--allow-redacted-secrets")
    if rewrite_existing:
        command.append("--rewrite-existing")
    if defer_memory_ref_reconciliation:
        command.append("--defer-memory-ref-reconciliation")
    if dry_run:
        command.append("--dry-run")

    print("Updating project.")
    result = controller.run(command, memory_repo)
    if result.returncode:
        print("update_status=failed reason=project_update_failed", file=sys.stderr)
    return result.returncode


def run_source_stream_update(
    controller: ChildProcessController,
    memory_repo: Path,
    stream: dict[str, object],
    default_source_dir: Path,
    dry_run: bool,
    max_records: int | None,
    patterns: tuple[str, ...],
    allow_redacted_secrets: bool,
    rewrite_existing: bool,
    defer_memory_ref_reconciliation: bool,
) -> int:
    stream_id = str(stream["stream_id"])
    source_dir = Path(str(stream.get("source_dir") or default_source_dir)).expanduser().resolve()
    project_path = Path(str(stream.get("project_path") or source_dir)).expanduser().resolve()
    archive_scope = str(stream["archive_scope"]).strip()
    source_partition = str(stream["source_partition"]).strip()
    project_name = stream.get("project")
    if not isinstance(project_name, str) or not project_name.strip():
        project_name = stream_id
    command = [
        sys.executable,
        str(memory_repo / "tools" / "update_memory_archive.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--archive-scope",
        archive_scope,
        "--source-partition",
        source_partition,
        "--project",
        project_name.strip(),
    ]
    if stream.get("require_project_metadata") is True:
        command.append("--require-project-metadata")
    if max_records is not None:
        command.extend(["--max-records", str(max_records)])
    for pattern in patterns:
        command.extend(["--pattern", pattern])
    if allow_redacted_secrets:
        command.append("--allow-redacted-secrets")
    if rewrite_existing:
        command.append("--rewrite-existing")
    if defer_memory_ref_reconciliation:
        command.append("--defer-memory-ref-reconciliation")
    if dry_run:
        command.append("--dry-run")

    print("Updating source stream.")
    result = controller.run(command, memory_repo)
    if result.returncode:
        print("update_status=failed reason=source_stream_update_failed", file=sys.stderr)
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--source-dir", required=True, help="Shared source record directory to scan")
    parser.add_argument("--pattern", action="append", help="Discovery glob pattern; may be repeated")
    parser.add_argument("--max-records", type=int, help="Maximum records to archive per project")
    parser.add_argument(
        "--allow-redacted-secrets",
        action="store_true",
        help="Allow per-project updates to archive records with detected secrets after redaction",
    )
    parser.add_argument(
        "--rewrite-existing",
        action="store_true",
        help="Rebuild matching source records and replace older archive entries for each project/source record",
    )
    parser.add_argument(
        "--require-clean-worktree",
        action="store_true",
        help="Block before mutation unless a Git-backed memory repository is clean",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover and run project updates without writing records")
    return parser.parse_args(argv)


def run_updates(
    args: argparse.Namespace,
    memory_repo: Path,
    source_dir: Path,
    patterns: tuple[str, ...],
    controller: ChildProcessController,
) -> int:
    if args.require_clean_worktree and not require_clean_worktree(memory_repo):
        return 1

    registered = load_registry(memory_repo)
    source_streams = load_source_stream_registry(memory_repo)
    discovered = discover_projects(source_dir, patterns)
    projects, added = merge_discovered_projects(registered, discovered, source_dir)
    write_registry(memory_repo, projects, args.dry_run)

    runnable = enabled_projects(projects)
    runnable_streams = enabled_source_streams(source_streams)
    print("Memory repo: configured")
    print("Source dir: configured")
    print(f"Discovered projects: {len(discovered)}")
    print(f"Registered new projects: {added}")
    print(f"Enabled projects: {len(runnable)}")
    print(f"Enabled source streams: {len(runnable_streams)}")

    if not runnable and not runnable_streams:
        print("Projects updated: 0")
        if not discovered and not registered:
            print("No registered projects and no project paths discovered from source records.")
        return 0

    updated = 0
    for project_index, project in enumerate(runnable):
        returncode = run_project_update(
            controller,
            memory_repo,
            project,
            source_dir,
            args.dry_run,
            args.max_records,
            patterns,
            args.allow_redacted_secrets,
            args.rewrite_existing,
            project_index < len(runnable) - 1 or bool(runnable_streams),
        )
        if returncode:
            print(f"Projects updated: {updated}")
            print("Source streams updated: 0")
            print("Projects failed: 1", file=sys.stderr)
            return 1
        updated += 1

    streams_updated = 0
    for stream_index, stream in enumerate(runnable_streams):
        returncode = run_source_stream_update(
            controller,
            memory_repo,
            stream,
            source_dir,
            args.dry_run,
            args.max_records,
            patterns,
            args.allow_redacted_secrets,
            args.rewrite_existing,
            stream_index < len(runnable_streams) - 1,
        )
        if returncode:
            print(f"Projects updated: {updated}")
            print(f"Source streams updated: {streams_updated}")
            print("Source streams failed: 1", file=sys.stderr)
            return 1
        streams_updated += 1

    print(f"Projects updated: {updated}")
    print(f"Source streams updated: {streams_updated}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    source_dir = Path(args.source_dir).expanduser().resolve()
    patterns = tuple(args.pattern or DEFAULT_PATTERNS)
    update_lock = UpdateRunLock(memory_repo)
    try:
        acquired = update_lock.acquire()
    except OSError:
        print("update_status=blocked reason=lock_unavailable", file=sys.stderr)
        return CONCURRENT_UPDATE_EXIT
    if not acquired:
        print("update_status=blocked reason=concurrent_update", file=sys.stderr)
        return CONCURRENT_UPDATE_EXIT

    controller = ChildProcessController(update_lock)
    previous_handlers: dict[int, object] = {}
    interrupted_signum: int | None = None

    def handle_signal(signum: int, _frame: object) -> None:
        nonlocal interrupted_signum
        controller.signal_current()
        if interrupted_signum is not None:
            return
        interrupted_signum = signum
        raise RunnerInterrupted(signum)

    exit_code = 1
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, handle_signal)
        exit_code = run_updates(args, memory_repo, source_dir, patterns, controller)
    except RunnerInterrupted as exc:
        print("update_status=blocked reason=interrupted", file=sys.stderr)
        exit_code = 128 + exc.signum
    except Exception:
        print("update_status=failed reason=runner_internal_error", file=sys.stderr)
        exit_code = 1
    finally:
        child_stopped = controller.terminate_current()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if child_stopped:
            if not update_lock.release():
                print("update_status=blocked reason=lock_release_failed", file=sys.stderr)
                exit_code = 1
        else:
            update_lock.close_parent_handle()
            print("update_status=blocked reason=child_cleanup_failed", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
