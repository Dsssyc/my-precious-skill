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
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
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
SOURCE_INVENTORY_REPORT_KIND = "memory_source_inventory"
SOURCE_INVENTORY_REPORT_VERSION = 2
SOURCE_INVENTORY_MANIFEST_KIND = "memory_source_inventory_manifest"
SOURCE_INVENTORY_MANIFEST_VERSION = 1
UPDATE_TARGET_REPORT_KIND = "memory_update_target_report"
UPDATE_TARGET_REPORT_VERSION = 1
UPDATE_BATCH_REPORT_KIND = "memory_update_batch_report"
UPDATE_BATCH_REPORT_VERSION = 1
MAX_CHILD_REPORT_BYTES = 64 * 1024
MAX_INVENTORY_MANIFEST_BYTES = 256 * 1024 * 1024
TIMESTAMP_KEYS = {"timestamp", "created_at", "updated_at", "started_at", "ended_at", "date"}


@dataclass(frozen=True)
class SourceInventoryRecord:
    relative_path: str
    sha256: str
    size: int
    mtime_ns: int
    source_updated_at: str
    project_paths: tuple[Path, ...]


class SourceInventoryError(ValueError):
    pass


def empty_batch_metrics() -> dict[str, int]:
    return {
        "inventory_worker_count": 0,
        "projects_updated_count": 0,
        "source_streams_updated_count": 0,
        "archive_finalization_count": 0,
        "records_deferred_count": 0,
        "targets_deferred_count": 0,
        "child_failure_count": 0,
    }


def update_batch_report(
    status: str,
    reason: str,
    metrics: dict[str, int] | None = None,
    *,
    failure_stage: str = "none",
) -> dict[str, object]:
    values = dict(metrics or empty_batch_metrics())
    return {
        "report_kind": UPDATE_BATCH_REPORT_KIND,
        "report_version": UPDATE_BATCH_REPORT_VERSION,
        "status": status,
        "reason": reason,
        "failure_stage": failure_stage,
        "source_batch_complete": status == "updated" and values["records_deferred_count"] == 0,
        "metrics": values,
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "source_content_rendered": False,
            "child_output_rendered": False,
        },
    }


def emit_update_batch_report(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


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

    def run(
        self,
        command: list[str],
        cwd: Path,
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with (
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file,
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file,
        ):
            child = subprocess.Popen(
                command,
                cwd=cwd,
                text=True,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                **self.update_lock.child_process_options(),
            )
            self.current = child
            try:
                child.communicate(input=input_text)
                returncode = child.returncode
            finally:
                if child.poll() is not None:
                    self.current = None
            stdout_file.flush()
            stdout_size = stdout_file.seek(0, os.SEEK_END)
            stdout = ""
            if stdout_size <= MAX_CHILD_REPORT_BYTES:
                stdout_file.seek(0)
                stdout = stdout_file.read()
            return subprocess.CompletedProcess(command, returncode, stdout, "")

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
            except json.JSONDecodeError as exc:
                raise SourceInventoryError("source_inventory_malformed") from exc
        return

    if path.suffix == ".json":
        try:
            yield json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceInventoryError("source_inventory_malformed") from exc
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
        except json.JSONDecodeError as exc:
            raise SourceInventoryError("source_inventory_malformed") from exc


def walk_json_values(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_values(child)


def source_value_is_automation(value: object) -> bool:
    if not isinstance(value, dict) or value.get("type") != "session_meta":
        return False
    payload = value.get("payload")
    if not isinstance(payload, dict):
        return False
    return str(payload.get("thread_source") or "").strip().lower() == "automation"


def parse_source_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def direct_source_timestamps(value: object) -> Iterable[datetime]:
    if isinstance(value, dict):
        for key in TIMESTAMP_KEYS:
            parsed = parse_source_timestamp(value.get(key))
            if parsed:
                yield parsed
    elif isinstance(value, list):
        for item in value:
            yield from direct_source_timestamps(item)


def timestamp_from_source_filename(path: Path) -> datetime | None:
    for pattern in (
        r"\d{4}-\d{2}-\d{2}T\d{2}[:_-]\d{2}[:_-]\d{2}Z?",
        r"\d{4}-\d{2}-\d{2}",
    ):
        match = re.search(pattern, path.as_posix())
        if not match:
            continue
        value = match.group(0)
        if "T" in value:
            date_part, time_part = value.split("T", 1)
            suffix = "Z" if time_part.endswith("Z") else ""
            if suffix:
                time_part = time_part[:-1]
            value = f"{date_part}T{re.sub(r'[-_]', ':', time_part)}{suffix}"
        parsed = parse_source_timestamp(value)
        if parsed:
            return parsed
    return None


def source_updated_at_from_values(path: Path, values: Iterable[object], mtime: float) -> str:
    timestamps = [timestamp for value in values for timestamp in direct_source_timestamps(value)]
    filename_timestamp = timestamp_from_source_filename(path)
    if filename_timestamp:
        timestamps.append(filename_timestamp)
    selected = max(timestamps) if timestamps else datetime.fromtimestamp(mtime, tz=UTC)
    return selected.isoformat().replace("+00:00", "Z")


def build_source_inventory(
    source_dir: Path,
    patterns: tuple[str, ...],
) -> list[SourceInventoryRecord]:
    if not source_dir.exists() or not source_dir.is_dir():
        return []
    source_root = source_dir.resolve()
    inventory: list[SourceInventoryRecord] = []
    seen: set[Path] = set()
    for path in iter_candidate_files(source_root, patterns):
        resolved = path.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise SourceInventoryError("source_inventory_unsafe") from exc
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            relative_path = resolved.relative_to(source_root).as_posix()
            initial_stat = resolved.stat()
            raw = resolved.read_bytes()
            final_stat = resolved.stat()
        except OSError as exc:
            raise SourceInventoryError("source_inventory_unavailable") from exc
        if (
            initial_stat.st_size != len(raw)
            or initial_stat.st_size != final_stat.st_size
            or initial_stat.st_mtime_ns != final_stat.st_mtime_ns
        ):
            raise SourceInventoryError("source_inventory_changed")
        text = raw.decode("utf-8", errors="replace")
        project_paths: set[Path] = set()
        latest_source_timestamp: datetime | None = None
        automation_source = False
        for value in iter_json_values(resolved, text):
            if source_value_is_automation(value):
                automation_source = True
                break
            for timestamp in direct_source_timestamps(value):
                if latest_source_timestamp is None or timestamp > latest_source_timestamp:
                    latest_source_timestamp = timestamp
            for key, child in walk_json_values(value):
                if key not in PROJECT_PATH_KEYS or not isinstance(child, str) or not child.strip():
                    continue
                candidate = Path(child).expanduser()
                if candidate.is_absolute():
                    project_paths.add(candidate.resolve())
        if automation_source:
            continue
        filename_timestamp = timestamp_from_source_filename(resolved)
        if filename_timestamp and (
            latest_source_timestamp is None or filename_timestamp > latest_source_timestamp
        ):
            latest_source_timestamp = filename_timestamp
        if latest_source_timestamp is None:
            latest_source_timestamp = datetime.fromtimestamp(final_stat.st_mtime, tz=UTC)
        inventory.append(
            SourceInventoryRecord(
                relative_path=relative_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                size=final_stat.st_size,
                mtime_ns=final_stat.st_mtime_ns,
                source_updated_at=latest_source_timestamp.isoformat().replace("+00:00", "Z"),
                project_paths=tuple(sorted(project_paths, key=lambda item: item.as_posix())),
            )
        )
    return sorted(inventory, key=lambda record: record.relative_path)


def discover_projects_from_inventory(inventory: Iterable[SourceInventoryRecord]) -> list[Path]:
    discovered = {project_path for record in inventory for project_path in record.project_paths}
    return sorted(discovered, key=lambda item: item.as_posix())


def inventory_records_for_target(
    inventory: Iterable[SourceInventoryRecord],
    project_path: Path,
    *,
    require_project_metadata: bool,
) -> list[SourceInventoryRecord]:
    project_key = project_path.resolve()
    return [
        record
        for record in inventory
        if project_key in record.project_paths
        or (not record.project_paths and not require_project_metadata)
    ]


def source_inventory_payload(inventory: Iterable[SourceInventoryRecord]) -> str:
    return json.dumps(
        {
            "report_kind": SOURCE_INVENTORY_REPORT_KIND,
            "report_version": SOURCE_INVENTORY_REPORT_VERSION,
            "records": [
                {
                    "relative_path": record.relative_path,
                    "sha256": record.sha256,
                    "size": record.size,
                    "mtime_ns": record.mtime_ns,
                    "source_updated_at": record.source_updated_at,
                }
                for record in inventory
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def source_inventory_manifest_payload(inventory: Iterable[SourceInventoryRecord]) -> dict[str, object]:
    return {
        "report_kind": SOURCE_INVENTORY_MANIFEST_KIND,
        "report_version": SOURCE_INVENTORY_MANIFEST_VERSION,
        "records": [
            {
                "relative_path": record.relative_path,
                "sha256": record.sha256,
                "size": record.size,
                "mtime_ns": record.mtime_ns,
                "source_updated_at": record.source_updated_at,
                "project_paths": [str(path) for path in record.project_paths],
            }
            for record in inventory
        ],
    }


def write_source_inventory_manifest(path: Path, inventory: Iterable[SourceInventoryRecord]) -> None:
    parent = path.parent.resolve(strict=True)
    if path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise SourceInventoryError("source_inventory_manifest_unsafe")
    parent_stat = parent.stat()
    if stat.S_IMODE(parent_stat.st_mode) & 0o077 or (
        hasattr(os, "getuid") and parent_stat.st_uid != os.getuid()
    ):
        raise SourceInventoryError("source_inventory_manifest_unsafe")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".inventory-", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                source_inventory_manifest_payload(inventory),
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_source_inventory_manifest(path: Path) -> list[SourceInventoryRecord]:
    try:
        if path.is_symlink() or not path.is_file():
            raise SourceInventoryError("source_inventory_manifest_invalid")
        file_stat = path.stat()
        if (
            stat.S_IMODE(file_stat.st_mode) & 0o077
            or (hasattr(os, "getuid") and file_stat.st_uid != os.getuid())
            or file_stat.st_size > MAX_INVENTORY_MANIFEST_BYTES
        ):
            raise SourceInventoryError("source_inventory_manifest_invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except SourceInventoryError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceInventoryError("source_inventory_manifest_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("report_kind") != SOURCE_INVENTORY_MANIFEST_KIND
        or payload.get("report_version") != SOURCE_INVENTORY_MANIFEST_VERSION
        or not isinstance(payload.get("records"), list)
    ):
        raise SourceInventoryError("source_inventory_manifest_invalid")
    inventory: list[SourceInventoryRecord] = []
    seen: set[str] = set()
    for row in payload["records"]:
        if not isinstance(row, dict) or set(row) != {
            "relative_path",
            "sha256",
            "size",
            "mtime_ns",
            "source_updated_at",
            "project_paths",
        }:
            raise SourceInventoryError("source_inventory_manifest_invalid")
        relative_path = row["relative_path"]
        digest = row["sha256"]
        size = row["size"]
        mtime_ns = row["mtime_ns"]
        source_updated_at = row["source_updated_at"]
        project_paths = row["project_paths"]
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or Path(relative_path).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(relative_path).parts)
            or relative_path in seen
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(mtime_ns, int)
            or mtime_ns < 0
            or not isinstance(source_updated_at, str)
            or parse_source_timestamp(source_updated_at) is None
            or not isinstance(project_paths, list)
            or any(not isinstance(value, str) or not Path(value).is_absolute() for value in project_paths)
        ):
            raise SourceInventoryError("source_inventory_manifest_invalid")
        seen.add(relative_path)
        inventory.append(
            SourceInventoryRecord(
                relative_path=relative_path,
                sha256=digest,
                size=size,
                mtime_ns=mtime_ns,
                source_updated_at=source_updated_at,
                project_paths=tuple(Path(value).resolve() for value in project_paths),
            )
        )
    return sorted(inventory, key=lambda record: record.relative_path)


def build_source_inventory_isolated(
    controller: ChildProcessController,
    memory_repo: Path,
    source_dir: Path,
    patterns: tuple[str, ...],
    manifest_path: Path,
) -> list[SourceInventoryRecord]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--source-dir",
        str(source_dir),
        "--inventory-worker-manifest",
        str(manifest_path),
    ]
    for pattern in patterns:
        command.extend(["--pattern", pattern])
    result = controller.run(command, memory_repo)
    if result.returncode != 0:
        raise SourceInventoryError("source_inventory_worker_failed")
    return load_source_inventory_manifest(manifest_path)


def discover_projects(source_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    return discover_projects_from_inventory(build_source_inventory(source_dir, patterns))


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


def write_registry(
    memory_repo: Path,
    projects: dict[str, dict[str, object]],
    dry_run: bool,
    *,
    quiet: bool = False,
) -> None:
    path = registry_path(memory_repo)
    if dry_run:
        if not quiet:
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


def parse_update_target_report(result: subprocess.CompletedProcess[str]) -> dict[str, object] | None:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != {
            "report_kind",
            "report_version",
            "status",
            "reason",
            "source_batch_complete",
            "metrics",
            "privacy",
        }
        or payload.get("report_kind") != UPDATE_TARGET_REPORT_KIND
        or payload.get("report_version") != UPDATE_TARGET_REPORT_VERSION
        or payload.get("status") not in {"updated", "deferred", "blocked"}
        or payload.get("reason")
        not in {"updated", "source_records_deferred", "source_inventory_invalid", "secret_records_rejected"}
        or not isinstance(payload.get("source_batch_complete"), bool)
    ):
        return None
    metrics = payload.get("metrics")
    expected_metric_keys = {
        "records_selected_count",
        "records_processed_count",
        "records_deferred_count",
        "records_skipped_count",
        "entries_removed_count",
    }
    if (
        not isinstance(metrics, dict)
        or set(metrics) != expected_metric_keys
        or any(not isinstance(metrics[key], int) or metrics[key] < 0 for key in expected_metric_keys)
    ):
        return None
    privacy = payload.get("privacy")
    if privacy != {
        "aggregate_only": True,
        "paths_rendered": False,
        "source_content_rendered": False,
    }:
        return None
    if payload["source_batch_complete"] != (
        payload["status"] == "updated" and metrics["records_deferred_count"] == 0
    ):
        return None
    valid_reasons = {
        "updated": {"updated"},
        "deferred": {"source_records_deferred"},
        "blocked": {"source_inventory_invalid", "secret_records_rejected"},
    }
    if payload["reason"] not in valid_reasons[payload["status"]]:
        return None
    if metrics["records_skipped_count"] > metrics["records_processed_count"]:
        return None
    if payload["status"] == "deferred" and metrics["records_deferred_count"] == 0:
        return None
    if payload["status"] == "updated" and metrics["records_deferred_count"] != 0:
        return None
    if payload["status"] != "blocked" and (
        metrics["records_processed_count"] + metrics["records_deferred_count"]
        != metrics["records_selected_count"]
    ):
        return None
    return payload


def merge_target_report(metrics: dict[str, int], payload: dict[str, object]) -> None:
    target_metrics = payload["metrics"]
    assert isinstance(target_metrics, dict)
    deferred = int(target_metrics["records_deferred_count"])
    metrics["records_deferred_count"] += deferred
    metrics["targets_deferred_count"] += int(deferred > 0)


def run_project_update(
    controller: ChildProcessController,
    memory_repo: Path,
    project: dict[str, object],
    inventory: list[SourceInventoryRecord],
    default_source_dir: Path,
    dry_run: bool,
    max_records: int | None,
    patterns: tuple[str, ...],
    allow_redacted_secrets: bool,
    rewrite_existing: bool,
    report_json: bool,
) -> subprocess.CompletedProcess[str]:
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
        "--source-inventory-stdin",
        "--defer-global-rebuild",
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
    if dry_run:
        command.append("--dry-run")
    if report_json:
        command.append("--report-json")

    if not report_json:
        print("Updating project.")
    result = controller.run(
        command,
        memory_repo,
        input_text=source_inventory_payload(inventory),
    )
    if result.returncode and not report_json:
        print("update_status=failed reason=project_update_failed", file=sys.stderr)
    return result


def run_source_stream_update(
    controller: ChildProcessController,
    memory_repo: Path,
    stream: dict[str, object],
    inventory: list[SourceInventoryRecord],
    default_source_dir: Path,
    dry_run: bool,
    max_records: int | None,
    patterns: tuple[str, ...],
    allow_redacted_secrets: bool,
    rewrite_existing: bool,
    report_json: bool,
) -> subprocess.CompletedProcess[str]:
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
        "--source-inventory-stdin",
        "--defer-global-rebuild",
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
    if dry_run:
        command.append("--dry-run")
    if report_json:
        command.append("--report-json")

    if not report_json:
        print("Updating source stream.")
    result = controller.run(
        command,
        memory_repo,
        input_text=source_inventory_payload(inventory),
    )
    if result.returncode and not report_json:
        print("update_status=failed reason=source_stream_update_failed", file=sys.stderr)
    return result


def run_archive_finalization(
    controller: ChildProcessController,
    memory_repo: Path,
    *,
    report_json: bool,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(memory_repo / "tools" / "update_memory_archive.py"),
        "--memory-repo",
        str(memory_repo),
        "--finalize-archive",
    ]
    if report_json:
        command.append("--report-json")
    else:
        print("Finalizing archive.")
    result = controller.run(command, memory_repo)
    if result.returncode and not report_json:
        print("update_status=failed reason=archive_finalization_failed", file=sys.stderr)
    return result


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
    parser.add_argument(
        "--report-json",
        action="store_true",
        help="Emit one aggregate machine-readable batch report",
    )
    parser.add_argument(
        "--inventory-worker-manifest",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover and run project updates without writing records")
    return parser.parse_args(argv)


def run_updates(
    args: argparse.Namespace,
    memory_repo: Path,
    source_dir: Path,
    patterns: tuple[str, ...],
    controller: ChildProcessController,
) -> tuple[int, dict[str, object]]:
    metrics = empty_batch_metrics()
    if args.require_clean_worktree and not require_clean_worktree(memory_repo):
        return 1, update_batch_report(
            "blocked",
            "clean_worktree_unavailable",
            metrics,
            failure_stage="preflight",
        )

    registered = load_registry(memory_repo)
    source_streams = load_source_stream_registry(memory_repo)
    inventories: dict[Path, list[SourceInventoryRecord]] = {}
    with tempfile.TemporaryDirectory(prefix="my-precious-inventory-") as manifest_dir_text:
        manifest_dir = Path(manifest_dir_text)
        manifest_dir.chmod(0o700)

        def inventory_for(candidate: Path) -> list[SourceInventoryRecord]:
            source_root = candidate.expanduser().resolve()
            if source_root not in inventories:
                manifest_path = manifest_dir / f"inventory-{len(inventories):04d}.json"
                metrics["inventory_worker_count"] += 1
                inventories[source_root] = build_source_inventory_isolated(
                    controller,
                    memory_repo,
                    source_root,
                    patterns,
                    manifest_path,
                )
            return inventories[source_root]

        discovered = discover_projects_from_inventory(inventory_for(source_dir))
        projects, added = merge_discovered_projects(registered, discovered, source_dir)
        write_registry(memory_repo, projects, args.dry_run, quiet=args.report_json)

        runnable = enabled_projects(projects)
        runnable_streams = enabled_source_streams(source_streams)
        for project in runnable:
            inventory_for(Path(str(project.get("source_dir") or source_dir)))
        for stream in runnable_streams:
            inventory_for(Path(str(stream.get("source_dir") or source_dir)))
        if not args.report_json:
            print("Memory repo: configured")
            print("Source dir: configured")
            print(f"Discovered projects: {len(discovered)}")
            print(f"Registered new projects: {added}")
            print(f"Enabled projects: {len(runnable)}")
            print(f"Enabled source streams: {len(runnable_streams)}")
            print(f"Source inventories built: {len(inventories)}")
            print("Source root rescans: 0")

        if not runnable and not runnable_streams:
            if not args.report_json:
                print("Projects updated: 0")
                print("Archive finalizations: 0")
                if not discovered and not registered:
                    print("No registered projects and no project paths discovered from source records.")
            return 0, update_batch_report("updated", "updated", metrics)

        def accept_child_result(result: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
            if not args.report_json:
                return result.returncode == 0, "child_failure_unclassified"
            payload = parse_update_target_report(result)
            if (
                payload is None
                or (result.returncode == 0 and payload["status"] == "blocked")
                or (result.returncode != 0 and payload["status"] != "blocked")
            ):
                return False, "child_failure_unclassified"
            if result.returncode != 0:
                return False, str(payload["reason"])
            merge_target_report(metrics, payload)
            return True, "updated"

        updated = 0
        for project in runnable:
            project_source_dir = Path(str(project.get("source_dir") or source_dir)).expanduser().resolve()
            project_inventory = inventory_records_for_target(
                inventory_for(project_source_dir),
                Path(str(project["project_path"])),
                require_project_metadata=True,
            )
            result = run_project_update(
                controller,
                memory_repo,
                project,
                project_inventory,
                source_dir,
                args.dry_run,
                args.max_records,
                patterns,
                args.allow_redacted_secrets,
                args.rewrite_existing,
                args.report_json,
            )
            accepted, failure_reason = accept_child_result(result)
            if not accepted:
                metrics["child_failure_count"] += 1
                if not args.report_json:
                    print(f"Projects updated: {updated}")
                    print("Source streams updated: 0")
                    print("Archive finalizations: 0")
                    print("Projects failed: 1", file=sys.stderr)
                return 1, update_batch_report(
                    "blocked",
                    failure_reason,
                    metrics,
                    failure_stage="project_update",
                )
            updated += 1
            metrics["projects_updated_count"] = updated

        streams_updated = 0
        for stream in runnable_streams:
            stream_source_dir = Path(str(stream.get("source_dir") or source_dir)).expanduser().resolve()
            stream_project_path = Path(str(stream.get("project_path") or stream_source_dir)).expanduser().resolve()
            stream_inventory = inventory_records_for_target(
                inventory_for(stream_source_dir),
                stream_project_path,
                require_project_metadata=stream.get("require_project_metadata") is True,
            )
            result = run_source_stream_update(
                controller,
                memory_repo,
                stream,
                stream_inventory,
                source_dir,
                args.dry_run,
                args.max_records,
                patterns,
                args.allow_redacted_secrets,
                args.rewrite_existing,
                args.report_json,
            )
            accepted, failure_reason = accept_child_result(result)
            if not accepted:
                metrics["child_failure_count"] += 1
                if not args.report_json:
                    print(f"Projects updated: {updated}")
                    print(f"Source streams updated: {streams_updated}")
                    print("Archive finalizations: 0")
                    print("Source streams failed: 1", file=sys.stderr)
                return 1, update_batch_report(
                    "blocked",
                    failure_reason,
                    metrics,
                    failure_stage="source_stream_update",
                )
            streams_updated += 1
            metrics["source_streams_updated_count"] = streams_updated

        finalizations = 0
        if not args.dry_run:
            result = run_archive_finalization(
                controller,
                memory_repo,
                report_json=args.report_json,
            )
            accepted, failure_reason = accept_child_result(result)
            if not accepted:
                metrics["child_failure_count"] += 1
                if not args.report_json:
                    print(f"Projects updated: {updated}")
                    print(f"Source streams updated: {streams_updated}")
                    print("Archive finalizations: 0")
                return 1, update_batch_report(
                    "blocked",
                    failure_reason,
                    metrics,
                    failure_stage="archive_finalization",
                )
            finalizations = 1
            metrics["archive_finalization_count"] = 1
        if not args.report_json:
            print(f"Projects updated: {updated}")
            print(f"Source streams updated: {streams_updated}")
            print(f"Archive finalizations: {finalizations}")
        status = "deferred" if metrics["records_deferred_count"] else "updated"
        reason = "source_records_deferred" if status == "deferred" else "updated"
        return 0, update_batch_report(status, reason, metrics)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_dir = Path(args.source_dir).expanduser().resolve()
    patterns = tuple(args.pattern or DEFAULT_PATTERNS)
    if args.inventory_worker_manifest:
        try:
            inventory = build_source_inventory(source_dir, patterns)
            write_source_inventory_manifest(
                Path(args.inventory_worker_manifest).expanduser(),
                inventory,
            )
        except SourceInventoryError:
            print("update_status=blocked reason=source_inventory_invalid", file=sys.stderr)
            return 1
        except Exception:
            print("update_status=failed reason=inventory_worker_internal_error", file=sys.stderr)
            return 1
        return 0

    memory_repo = resolve_memory_repo(args.memory_repo)
    update_lock = UpdateRunLock(memory_repo)
    payload = update_batch_report("blocked", "runner_internal_error", failure_stage="runner")
    try:
        acquired = update_lock.acquire()
    except OSError:
        if args.report_json:
            emit_update_batch_report(
                update_batch_report("blocked", "lock_unavailable", failure_stage="lock_acquire")
            )
        else:
            print("update_status=blocked reason=lock_unavailable", file=sys.stderr)
        return CONCURRENT_UPDATE_EXIT
    if not acquired:
        if args.report_json:
            emit_update_batch_report(
                update_batch_report("blocked", "concurrent_update", failure_stage="lock_acquire")
            )
        else:
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
        exit_code, payload = run_updates(args, memory_repo, source_dir, patterns, controller)
    except RunnerInterrupted as exc:
        payload = update_batch_report("blocked", "interrupted", failure_stage="runner")
        if not args.report_json:
            print("update_status=blocked reason=interrupted", file=sys.stderr)
        exit_code = 128 + exc.signum
    except SourceInventoryError:
        payload = update_batch_report(
            "blocked",
            "source_inventory_invalid",
            failure_stage="source_inventory",
        )
        if not args.report_json:
            print("update_status=blocked reason=source_inventory_invalid", file=sys.stderr)
        exit_code = 1
    except Exception:
        payload = update_batch_report("blocked", "runner_internal_error", failure_stage="runner")
        if not args.report_json:
            print("update_status=failed reason=runner_internal_error", file=sys.stderr)
        exit_code = 1
    finally:
        child_stopped = controller.terminate_current()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        if child_stopped:
            if not update_lock.release():
                payload = update_batch_report(
                    "blocked",
                    "lock_release_failed",
                    failure_stage="lock_release",
                )
                if not args.report_json:
                    print("update_status=blocked reason=lock_release_failed", file=sys.stderr)
                exit_code = 1
        else:
            update_lock.close_parent_handle()
            payload = update_batch_report(
                "blocked",
                "child_cleanup_failed",
                failure_stage="child_cleanup",
            )
            if not args.report_json:
                print("update_status=blocked reason=child_cleanup_failed", file=sys.stderr)
            exit_code = 1
    if args.report_json:
        emit_update_batch_report(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
