#!/usr/bin/env python3
"""Run a scheduled memory update in an isolated, reboot-replayable clone."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Callable

if os.name == "posix":
    import fcntl
elif os.name == "nt":
    import msvcrt


REPORT_KIND = "scheduled_memory_transaction"
REPORT_VERSION = 1
CONCURRENT_EXIT = getattr(os, "EX_TEMPFAIL", 75)
OWNER_KIND = "scheduled_memory_transaction_staging_owner"
OWNER_VERSION = 1
STATE_KIND = "scheduled_memory_transaction_state"
STATE_VERSION = 1
RECOVERABLE_PUBLISH_PHASES = {
    "sync_live",
    "remote_receipt",
    "canonical_fast_forward",
    "canonical_checkout_applied",
    "complete",
}
KNOWN_PHASES = {
    "preflight",
    "updating",
    "auditing",
    "repairing",
    "validating",
    "sync_dry_run",
    "sync_live",
    "remote_receipt",
    "canonical_fast_forward",
    "canonical_checkout_applied",
    "complete",
}
SCP_STYLE_REMOTE = re.compile(r"^(?:[^/@:\s]+@)?[^/:\s]+:.+$")
_ACTIVE_TRANSACTION_LOCK_FD: int | None = None


class TransactionBlocked(Exception):
    def __init__(self, reason: str, *, exit_code: int = 1) -> None:
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


class TransactionLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: IO[bytes] | None = None
        self.previous_active_fd: int | None = None

    def __enter__(self) -> "TransactionLock":
        global _ACTIVE_TRANSACTION_LOCK_FD
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            if os.name == "posix":
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif os.name == "nt":
                if not handle.read(1):
                    handle.write(b"\0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise OSError("unsupported platform")
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise TransactionBlocked("concurrent_transaction", exit_code=CONCURRENT_EXIT) from exc
        self.handle = handle
        self.previous_active_fd = _ACTIVE_TRANSACTION_LOCK_FD
        _ACTIVE_TRANSACTION_LOCK_FD = handle.fileno()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        global _ACTIVE_TRANSACTION_LOCK_FD
        if self.handle is None:
            return
        descriptor = self.handle.fileno()
        try:
            if os.name == "posix":
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None
            if _ACTIVE_TRANSACTION_LOCK_FD == descriptor:
                _ACTIVE_TRANSACTION_LOCK_FD = self.previous_active_fd
            self.previous_active_fd = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--include-reviewed-memory-nodes", action="store_true")
    parser.add_argument("--allow-redacted-secrets", action="store_true")
    return parser.parse_args(argv)


def subprocess_lock_kwargs() -> dict[str, object]:
    if os.name != "posix" or _ACTIVE_TRANSACTION_LOCK_FD is None:
        return {}
    return {"pass_fds": (_ACTIVE_TRANSACTION_LOCK_FD,)}


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **subprocess_lock_kwargs(),
    )


def path_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(path.expanduser().resolve()).encode("utf-8")).hexdigest()


def normalized_remote_url(url: str, base: Path) -> str:
    value = url.strip()
    if not value:
        raise TransactionBlocked("remote_unavailable")
    path = Path(value)
    if path.is_absolute():
        return str(path.resolve())
    if "://" in value or SCP_STYLE_REMOTE.match(value):
        return value.rstrip("/")
    return str((base / value).expanduser().resolve())


def remote_fingerprint(url: str, base: Path) -> str:
    normalized = normalized_remote_url(url, base)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def canonical_remote_url(memory_repo: Path) -> str:
    result = run_git(memory_repo, "remote", "get-url", "origin")
    if result.returncode != 0 or not result.stdout.strip():
        raise TransactionBlocked("remote_unavailable")
    return result.stdout.strip()


def repository_lock_path(memory_repo: Path) -> Path:
    result = run_git(memory_repo, "rev-parse", "--git-common-dir")
    if result.returncode != 0 or not result.stdout.strip():
        raise TransactionBlocked("canonical_unavailable")
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = memory_repo / git_dir
    resolved = git_dir.resolve()
    if not resolved.is_dir():
        raise TransactionBlocked("canonical_unavailable")
    return resolved / "my-precious-scheduled-transaction.lock"


def v238_update_lock_path(memory_repo: Path) -> Path:
    digest = hashlib.sha256(str(memory_repo.resolve()).encode("utf-8")).hexdigest()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    lock_root = Path(tempfile.gettempdir()) / f"my-precious-update-locks-{uid}"
    if lock_root.exists() and lock_root.is_symlink():
        raise TransactionBlocked("unsafe_staging")
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        lock_root.chmod(0o700)
    lock_path = lock_root / f"{digest}.lock"
    if lock_path.is_symlink():
        raise TransactionBlocked("unsafe_staging")
    return lock_path


def ensure_v238_update_idle(staging: Path) -> None:
    with TransactionLock(v238_update_lock_path(staging)):
        pass


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def expected_owner(repository_fingerprint: str, expected_remote_fingerprint: str) -> dict[str, object]:
    return {
        "report_kind": OWNER_KIND,
        "report_version": OWNER_VERSION,
        "repository_fingerprint": repository_fingerprint,
        "remote_fingerprint": expected_remote_fingerprint,
    }


def load_owner(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise TransactionBlocked("unsafe_staging")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionBlocked("unsafe_staging") from exc
    if not isinstance(payload, dict):
        raise TransactionBlocked("unsafe_staging")
    return payload


def clone_staging(remote_url: str, staging: Path, state_dir: Path) -> None:
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--branch", "main", "--single-branch", remote_url, str(staging)],
        cwd=state_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **subprocess_lock_kwargs(),
    )
    if clone.returncode != 0:
        raise TransactionBlocked("staging_clone_failed")


def copy_git_identity(canonical: Path, staging: Path) -> None:
    for key in ("user.name", "user.email"):
        value = run_git(canonical, "config", "--get", key)
        if value.returncode == 0 and value.stdout.strip():
            configured = run_git(staging, "config", key, value.stdout.strip())
            if configured.returncode != 0:
                raise TransactionBlocked("staging_identity_failed")


def prepare_staging(
    canonical: Path,
    state_dir: Path,
    remote_url: str,
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
) -> tuple[Path, bool]:
    staging = ensure_safe_staging_path(state_dir)
    owner_path = state_dir / "staging-owner.json"
    expected = expected_owner(repository_fingerprint, expected_remote_fingerprint)
    existed = staging.exists()
    dirty_before = False

    if owner_path.exists() or owner_path.is_symlink():
        if load_owner(owner_path) != expected:
            raise TransactionBlocked("unsafe_staging")
    else:
        if existed:
            raise TransactionBlocked("unsafe_staging")
        write_json_atomic(owner_path, expected)

    ensure_v238_update_idle(staging)

    if existed:
        if staging.is_symlink() or not staging.is_dir():
            raise TransactionBlocked("unsafe_staging")
        remote = run_git(staging, "remote", "get-url", "origin")
        if remote.returncode != 0:
            shutil.rmtree(staging)
            existed = False
        elif remote_fingerprint(remote.stdout.strip(), staging) != expected_remote_fingerprint:
            raise TransactionBlocked("unexpected_remote")
        else:
            status = run_git(staging, "status", "--porcelain=v1", "--untracked-files=all")
            if status.returncode != 0:
                raise TransactionBlocked("staging_status_failed")
            dirty_before = bool(status.stdout)

    if not staging.exists():
        clone_staging(remote_url, staging, state_dir)

    remote = run_git(staging, "remote", "get-url", "origin")
    if remote.returncode != 0 or remote_fingerprint(remote.stdout.strip(), staging) != expected_remote_fingerprint:
        raise TransactionBlocked("unexpected_remote")
    fetch = run_git(staging, "fetch", "--quiet", "origin", "main")
    if fetch.returncode != 0:
        raise TransactionBlocked("staging_fetch_failed")
    for command in (
        ("reset", "--hard", "origin/main"),
        ("clean", "-fdx"),
        ("checkout", "-B", "main", "origin/main"),
        ("branch", "--set-upstream-to=origin/main", "main"),
    ):
        if run_git(staging, *command).returncode != 0:
            raise TransactionBlocked("staging_reset_failed")
    copy_git_identity(canonical, staging)
    return staging, existed and dirty_before


def prepare_state_dir(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise TransactionBlocked("unsafe_state_dir")
    expanded.mkdir(mode=0o700, parents=True, exist_ok=True)
    if expanded.is_symlink() or not expanded.is_dir():
        raise TransactionBlocked("unsafe_state_dir")
    expanded.chmod(0o700)
    return expanded.resolve()


def paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_state_location(path: Path, memory_repo: Path, source_dir: Path) -> None:
    resolved = path.expanduser().resolve()
    if paths_overlap(resolved, memory_repo) or paths_overlap(resolved, source_dir):
        raise TransactionBlocked("unsafe_state_dir")


def load_state(state_dir: Path) -> dict[str, object] | None:
    path = state_dir / "transaction.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise TransactionBlocked("malformed_state")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransactionBlocked("malformed_state") from exc
    if not isinstance(payload, dict):
        raise TransactionBlocked("malformed_state")
    required = {
        "report_kind": STATE_KIND,
        "report_version": STATE_VERSION,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise TransactionBlocked("malformed_state")
    if payload.get("phase") not in KNOWN_PHASES:
        raise TransactionBlocked("malformed_state")
    for key in ("repository_fingerprint", "remote_fingerprint", "base_sha"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise TransactionBlocked("malformed_state")
    candidate = payload.get("candidate_sha")
    if candidate is not None and (not isinstance(candidate, str) or not candidate):
        raise TransactionBlocked("malformed_state")
    return payload


def write_state(
    state_dir: Path,
    *,
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
    base_sha: str,
    phase: str,
    candidate_sha: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "report_kind": STATE_KIND,
        "report_version": STATE_VERSION,
        "repository_fingerprint": repository_fingerprint,
        "remote_fingerprint": expected_remote_fingerprint,
        "base_sha": base_sha,
        "phase": phase,
    }
    if candidate_sha is not None:
        payload["candidate_sha"] = candidate_sha
    write_json_atomic(state_dir / "transaction.json", payload)
    pause_at_phase(phase)
    return payload


def clear_state(state_dir: Path) -> None:
    path = state_dir / "transaction.json"
    if path.is_symlink():
        raise TransactionBlocked("malformed_state")
    path.unlink(missing_ok=True)


def pause_at_phase(phase: str) -> None:
    if os.environ.get("MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE") != phase:
        return
    release_value = os.environ.get("MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE")
    if not release_value:
        raise TransactionBlocked("test_pause_configuration_invalid")
    release = Path(release_value)
    while not release.exists():
        time.sleep(0.02)


def ensure_clean_canonical(memory_repo: Path) -> None:
    status = run_git(memory_repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise TransactionBlocked("canonical_unavailable")
    if status.stdout:
        raise TransactionBlocked("dirty_canonical")


def git_value(repo: Path, *args: str, reason: str) -> str:
    result = run_git(repo, *args)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise TransactionBlocked(reason)
    return value


def remote_main_head(remote_url: str, *, cwd: Path, reason: str) -> str:
    result = run_git(cwd, "ls-remote", "--exit-code", remote_url, "refs/heads/main")
    lines = [line for line in result.stdout.splitlines() if line]
    if result.returncode != 0 or len(lines) != 1:
        raise TransactionBlocked(reason)
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != "refs/heads/main":
        raise TransactionBlocked(reason)
    return fields[0]


def install_verified_candidate(
    canonical: Path,
    staging: Path,
    *,
    base_sha: str,
    candidate_sha: str,
) -> None:
    tracking_head = git_value(canonical, "rev-parse", "origin/main", reason="canonical_unavailable")
    if tracking_head not in {base_sha, candidate_sha}:
        raise TransactionBlocked("canonical_changed_during_transaction")
    fetch = run_git(
        canonical,
        "fetch",
        "--quiet",
        "--no-write-fetch-head",
        str(staging),
        candidate_sha,
    )
    if fetch.returncode != 0:
        raise TransactionBlocked("canonical_receipt_failed")
    if run_git(canonical, "cat-file", "-e", f"{candidate_sha}^{{commit}}").returncode != 0:
        raise TransactionBlocked("canonical_receipt_failed")
    if tracking_head == base_sha:
        update = run_git(
            canonical,
            "update-ref",
            "refs/remotes/origin/main",
            candidate_sha,
            base_sha,
        )
        if update.returncode != 0:
            raise TransactionBlocked("canonical_receipt_failed")
    if git_value(canonical, "rev-parse", "origin/main", reason="canonical_receipt_failed") != candidate_sha:
        raise TransactionBlocked("canonical_receipt_failed")


def ensure_main_branch(repo: Path) -> None:
    if git_value(repo, "branch", "--show-current", reason="canonical_unavailable") != "main":
        raise TransactionBlocked("canonical_branch_mismatch")


def changed_paths(repo: Path, *args: str, reason: str) -> set[str]:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise TransactionBlocked(reason)
    return {path for path in result.stdout.split("\0") if path}


def parse_single_entry(output: str, path: str, *, index: bool) -> tuple[str, str] | None:
    records = [record for record in output.split("\0") if record]
    if not records:
        return None
    if len(records) != 1 or "\t" not in records[0]:
        raise TransactionBlocked("canonical_recovery_failed")
    header, rendered_path = records[0].split("\t", 1)
    if rendered_path != path:
        raise TransactionBlocked("canonical_recovery_failed")
    fields = header.split()
    if index:
        if len(fields) != 3 or fields[2] != "0":
            raise TransactionBlocked("canonical_recovery_failed")
        return fields[0], fields[1]
    if len(fields) != 3:
        raise TransactionBlocked("canonical_recovery_failed")
    return fields[0], fields[2]


def tree_entry(canonical: Path, revision: str, path: str) -> tuple[str, str] | None:
    result = run_git(canonical, "ls-tree", "-z", revision, "--", path)
    if result.returncode != 0:
        raise TransactionBlocked("canonical_recovery_failed")
    return parse_single_entry(result.stdout, path, index=False)


def index_entry(canonical: Path, path: str) -> tuple[str, str] | None:
    result = run_git(canonical, "ls-files", "--stage", "-z", "--", path)
    if result.returncode != 0:
        raise TransactionBlocked("canonical_recovery_failed")
    return parse_single_entry(result.stdout, path, index=True)


def hash_symlink(canonical: Path, target: str) -> str:
    result = subprocess.run(
        ["git", "hash-object", "--stdin"],
        cwd=canonical,
        input=os.fsencode(target),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **subprocess_lock_kwargs(),
    )
    if result.returncode != 0:
        raise TransactionBlocked("canonical_recovery_failed")
    return result.stdout.decode("ascii").strip()


def worktree_entry(canonical: Path, path: str) -> tuple[str, str] | None:
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise TransactionBlocked("canonical_recovery_failed")
    parent = canonical
    for part in relative.parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise TransactionBlocked("dirty_canonical")
    target = canonical / relative
    if target.is_symlink():
        return "120000", hash_symlink(canonical, os.readlink(target))
    if not target.exists():
        return None
    if not target.is_file():
        raise TransactionBlocked("dirty_canonical")
    hashed = run_git(canonical, "hash-object", f"--path={path}", "--", path)
    if hashed.returncode != 0 or not hashed.stdout.strip():
        raise TransactionBlocked("canonical_recovery_failed")
    mode = "100755" if stat.S_IMODE(target.stat().st_mode) & 0o111 else "100644"
    return mode, hashed.stdout.strip()


def ensure_receipt_bounded_canonical_changes(canonical: Path, base_sha: str, candidate_sha: str) -> None:
    allowed = changed_paths(
        canonical,
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        base_sha,
        candidate_sha,
        reason="canonical_recovery_failed",
    )
    actual = set()
    actual.update(
        changed_paths(
            canonical,
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            reason="canonical_recovery_failed",
        )
    )
    actual.update(
        changed_paths(
            canonical,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--no-renames",
            reason="canonical_recovery_failed",
        )
    )
    actual.update(
        changed_paths(
            canonical,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            reason="canonical_recovery_failed",
        )
    )
    if not actual or not actual.issubset(allowed):
        raise TransactionBlocked("dirty_canonical")
    for path in actual:
        valid_entries = {
            tree_entry(canonical, base_sha, path),
            tree_entry(canonical, candidate_sha, path),
        }
        if index_entry(canonical, path) not in valid_entries:
            raise TransactionBlocked("dirty_canonical")
        if worktree_entry(canonical, path) not in valid_entries:
            raise TransactionBlocked("dirty_canonical")


def apply_verified_canonical(
    canonical: Path,
    *,
    base_sha: str,
    candidate_sha: str,
    allow_interrupted_repair: bool,
    checkpoint: Callable[[], None] | None = None,
) -> None:
    ensure_main_branch(canonical)
    remote_head = git_value(canonical, "rev-parse", "origin/main", reason="canonical_receipt_failed")
    if remote_head != candidate_sha:
        raise TransactionBlocked("canonical_receipt_failed")
    canonical_head = git_value(canonical, "rev-parse", "HEAD", reason="canonical_unavailable")
    if canonical_head not in {base_sha, candidate_sha}:
        raise TransactionBlocked("canonical_changed_during_transaction")
    if run_git(canonical, "merge-base", "--is-ancestor", base_sha, candidate_sha).returncode != 0:
        raise TransactionBlocked("canonical_fast_forward_failed")
    status = run_git(canonical, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise TransactionBlocked("canonical_unavailable")
    if status.stdout:
        if not allow_interrupted_repair:
            raise TransactionBlocked("dirty_canonical")
        ensure_receipt_bounded_canonical_changes(canonical, base_sha, candidate_sha)
    if canonical_head == base_sha:
        checkout = run_git(canonical, "read-tree", "--reset", "-u", candidate_sha)
        if checkout.returncode != 0:
            raise TransactionBlocked("canonical_fast_forward_failed")
        if checkpoint is not None:
            checkpoint()
        update_ref = run_git(canonical, "update-ref", "refs/heads/main", candidate_sha, base_sha)
        if update_ref.returncode != 0:
            raise TransactionBlocked("canonical_fast_forward_failed")
    else:
        reset = run_git(canonical, "reset", "--hard", candidate_sha)
        if reset.returncode != 0:
            raise TransactionBlocked("canonical_fast_forward_failed")
    ensure_clean_canonical(canonical)
    if git_value(canonical, "rev-parse", "HEAD", reason="canonical_receipt_failed") != candidate_sha:
        raise TransactionBlocked("canonical_receipt_failed")


def ensure_safe_staging_path(state_dir: Path) -> Path:
    staging = state_dir / "staging"
    if staging.is_symlink():
        raise TransactionBlocked("unsafe_staging")
    return staging


def empty_metrics() -> dict[str, int]:
    return {
        "recovery_count": 0,
        "canonical_mutation_count": 0,
        "remote_publish_count": 0,
        "repair_attempt_count": 0,
        "privacy_leak_count": 0,
    }


def report(
    status: str,
    reason: str,
    *,
    recovery_action: str = "none",
    metrics: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "status": status,
        "reason": reason,
        "recovery_action": recovery_action,
        "metrics": metrics or empty_metrics(),
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "source_content_rendered": False,
            "archive_content_rendered": False,
        },
    }


def run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **subprocess_lock_kwargs(),
    )


def run_python_tool(staging: Path, name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    script = staging / "tools" / name
    if not script.is_file() or script.is_symlink():
        raise TransactionBlocked("runtime_tool_missing")
    return run_command([sys.executable, str(script), *arguments], cwd=staging)


def verify_state_identity(
    state: dict[str, object],
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
) -> None:
    if (
        state.get("repository_fingerprint") != repository_fingerprint
        or state.get("remote_fingerprint") != expected_remote_fingerprint
    ):
        raise TransactionBlocked("state_identity_mismatch")


def staging_head_if_owned(
    state_dir: Path,
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
) -> str | None:
    staging = ensure_safe_staging_path(state_dir)
    owner_path = state_dir / "staging-owner.json"
    if not staging.exists() or not owner_path.exists():
        return None
    expected = expected_owner(repository_fingerprint, expected_remote_fingerprint)
    if load_owner(owner_path) != expected or not staging.is_dir():
        raise TransactionBlocked("unsafe_staging")
    remote = run_git(staging, "remote", "get-url", "origin")
    if remote.returncode != 0 or remote_fingerprint(remote.stdout.strip(), staging) != expected_remote_fingerprint:
        raise TransactionBlocked("unexpected_remote")
    return git_value(staging, "rev-parse", "HEAD", reason="staging_status_failed")


def reconcile_post_push(
    canonical: Path,
    state_dir: Path,
    state: dict[str, object],
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
    remote_head: str,
) -> dict[str, object] | None:
    phase = state.get("phase")
    if phase not in RECOVERABLE_PUBLISH_PHASES:
        return None
    base_sha = str(state["base_sha"])
    staging_head = staging_head_if_owned(state_dir, repository_fingerprint, expected_remote_fingerprint)
    candidate = str(state.get("candidate_sha") or staging_head or "")
    if remote_head == base_sha:
        if phase in {"remote_receipt", "canonical_fast_forward", "complete"}:
            raise TransactionBlocked("remote_receipt_failed")
        return None
    if not candidate or remote_head != candidate or staging_head != candidate:
        raise TransactionBlocked("remote_race")
    ancestor = run_git(state_dir / "staging", "merge-base", "--is-ancestor", base_sha, remote_head)
    if ancestor.returncode != 0:
        raise TransactionBlocked("remote_race")
    install_verified_candidate(
        canonical,
        state_dir / "staging",
        base_sha=base_sha,
        candidate_sha=remote_head,
    )
    apply_verified_canonical(
        canonical,
        base_sha=base_sha,
        candidate_sha=remote_head,
        allow_interrupted_repair=phase
        in {"canonical_fast_forward", "canonical_checkout_applied", "complete"},
    )
    metrics = empty_metrics()
    metrics["recovery_count"] = 1
    metrics["canonical_mutation_count"] = 1
    clear_state(state_dir)
    return report(
        "published",
        "published",
        recovery_action="post_push_reconciled",
        metrics=metrics,
    )


def sync_arguments(args: argparse.Namespace, staging: Path, *, dry_run: bool) -> list[str]:
    values = ["--memory-repo", str(staging)]
    if args.include_reviewed_memory_nodes:
        values.append("--include-reviewed-memory-nodes")
    if dry_run:
        values.append("--dry-run")
    if args.push:
        values.append("--push")
    return values


def execute(args: argparse.Namespace) -> dict[str, object]:
    memory_repo = Path(args.memory_repo).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()
    if not memory_repo.is_dir() or not source_dir.is_dir():
        raise TransactionBlocked("input_unavailable")
    state_path = Path(args.state_dir)
    validate_state_location(state_path, memory_repo, source_dir)
    with TransactionLock(repository_lock_path(memory_repo)):
        state_dir = prepare_state_dir(state_path)
        state = load_state(state_dir)
        ensure_main_branch(memory_repo)
        remote_url = canonical_remote_url(memory_repo)
        resolved_remote_url = normalized_remote_url(remote_url, memory_repo)
        repository_fingerprint = path_fingerprint(memory_repo)
        expected_remote_fingerprint = remote_fingerprint(remote_url, memory_repo)
        if state is not None:
            verify_state_identity(state, repository_fingerprint, expected_remote_fingerprint)
        remote_head = remote_main_head(
            resolved_remote_url,
            cwd=memory_repo,
            reason="canonical_fetch_failed",
        )
        reconciled = (
            reconcile_post_push(
                memory_repo,
                state_dir,
                state,
                repository_fingerprint,
                expected_remote_fingerprint,
                remote_head,
            )
            if state is not None
            else None
        )
        if reconciled is not None:
            return reconciled

        ensure_clean_canonical(memory_repo)
        canonical_head = git_value(memory_repo, "rev-parse", "HEAD", reason="canonical_unavailable")
        tracking_head = git_value(memory_repo, "rev-parse", "origin/main", reason="canonical_unavailable")
        if canonical_head != remote_head or tracking_head != canonical_head:
            raise TransactionBlocked("remote_race" if state is not None else "canonical_remote_mismatch")

        staging, staging_was_dirty = prepare_staging(
            memory_repo,
            state_dir,
            resolved_remote_url,
            repository_fingerprint,
            expected_remote_fingerprint,
        )
        stale_replay = state is not None or staging_was_dirty
        recovery_action = "stale_staging_replayed" if stale_replay else "none"
        metrics = empty_metrics()
        metrics["recovery_count"] = int(stale_replay)
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="preflight",
        )

        update_arguments = [
            "--memory-repo",
            str(staging),
            "--source-dir",
            str(source_dir),
            "--require-clean-worktree",
        ]
        if args.allow_redacted_secrets:
            update_arguments.append("--allow-redacted-secrets")
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="updating",
        )
        if run_python_tool(staging, "run_memory_updates.py", *update_arguments).returncode != 0:
            raise TransactionBlocked("update_failed")

        audit_arguments = ("--memory-repo", str(staging))
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="auditing",
        )
        if run_python_tool(staging, "audit_memory_archive.py", *audit_arguments).returncode != 0:
            raise TransactionBlocked("archive_audit_failed")
        readiness = run_python_tool(staging, "audit_publish_readiness.py", *audit_arguments)
        if readiness.returncode != 0:
            metrics["repair_attempt_count"] = 1
            write_state(
                state_dir,
                repository_fingerprint=repository_fingerprint,
                expected_remote_fingerprint=expected_remote_fingerprint,
                base_sha=remote_head,
                phase="repairing",
            )
            repair = run_python_tool(
                staging,
                "repair_publish_surfaces.py",
                "--memory-repo",
                str(staging),
                "--apply",
            )
            if repair.returncode != 0:
                raise TransactionBlocked("publish_repair_failed")
            write_state(
                state_dir,
                repository_fingerprint=repository_fingerprint,
                expected_remote_fingerprint=expected_remote_fingerprint,
                base_sha=remote_head,
                phase="validating",
            )
            if run_python_tool(staging, "audit_memory_archive.py", *audit_arguments).returncode != 0:
                raise TransactionBlocked("archive_audit_failed")
            if run_python_tool(staging, "audit_publish_readiness.py", *audit_arguments).returncode != 0:
                raise TransactionBlocked("publish_readiness_failed")

        if run_python_tool(staging, "search_memory.py", "--health-check").returncode != 0:
            raise TransactionBlocked("search_health_failed")

        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="sync_dry_run",
        )
        dry_sync = run_python_tool(
            staging,
            "sync_memory_archive.py",
            *sync_arguments(args, staging, dry_run=True),
        )
        if dry_sync.returncode != 0:
            raise TransactionBlocked("sync_dry_run_failed")
        if "No memory archive changes to sync." in dry_sync.stdout:
            if remote_main_head(
                resolved_remote_url,
                cwd=memory_repo,
                reason="canonical_fetch_failed",
            ) != remote_head:
                raise TransactionBlocked("remote_race")
            if git_value(memory_repo, "rev-parse", "HEAD", reason="canonical_unavailable") != remote_head:
                raise TransactionBlocked("canonical_remote_mismatch")
            write_state(
                state_dir,
                repository_fingerprint=repository_fingerprint,
                expected_remote_fingerprint=expected_remote_fingerprint,
                base_sha=remote_head,
                phase="complete",
                candidate_sha=remote_head,
            )
            clear_state(state_dir)
            return report(
                "no_op_current",
                "no_op_current",
                recovery_action=recovery_action,
                metrics=metrics,
            )
        if "Would commit:" not in dry_sync.stdout:
            raise TransactionBlocked("sync_dry_run_ambiguous")
        if not args.push:
            raise TransactionBlocked("push_not_requested")

        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="sync_live",
        )
        live_sync = run_python_tool(
            staging,
            "sync_memory_archive.py",
            *sync_arguments(args, staging, dry_run=False),
        )
        if live_sync.returncode != 0:
            observed_remote = remote_main_head(
                resolved_remote_url,
                cwd=memory_repo,
                reason="canonical_fetch_failed",
            )
            raise TransactionBlocked("remote_race" if observed_remote != remote_head else "sync_live_failed")
        candidate_sha = git_value(staging, "rev-parse", "HEAD", reason="staging_status_failed")
        if candidate_sha == remote_head:
            raise TransactionBlocked("sync_live_no_commit")
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="remote_receipt",
            candidate_sha=candidate_sha,
        )
        if remote_main_head(
            resolved_remote_url,
            cwd=memory_repo,
            reason="canonical_fetch_failed",
        ) != candidate_sha:
            raise TransactionBlocked("remote_receipt_failed")
        install_verified_candidate(
            memory_repo,
            staging,
            base_sha=remote_head,
            candidate_sha=candidate_sha,
        )
        ensure_clean_canonical(memory_repo)
        if git_value(memory_repo, "rev-parse", "HEAD", reason="canonical_unavailable") != canonical_head:
            raise TransactionBlocked("canonical_changed_during_transaction")
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="canonical_fast_forward",
            candidate_sha=candidate_sha,
        )
        def checkpoint_canonical_checkout() -> None:
            write_state(
                state_dir,
                repository_fingerprint=repository_fingerprint,
                expected_remote_fingerprint=expected_remote_fingerprint,
                base_sha=remote_head,
                phase="canonical_checkout_applied",
                candidate_sha=candidate_sha,
            )

        apply_verified_canonical(
            memory_repo,
            base_sha=remote_head,
            candidate_sha=candidate_sha,
            allow_interrupted_repair=False,
            checkpoint=checkpoint_canonical_checkout,
        )
        metrics["remote_publish_count"] = 1
        metrics["canonical_mutation_count"] = 1
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="complete",
            candidate_sha=candidate_sha,
        )
        clear_state(state_dir)
        return report(
            "published",
            "published",
            recovery_action=recovery_action,
            metrics=metrics,
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = execute(args)
        exit_code = 0
    except TransactionBlocked as exc:
        payload = report("blocked", exc.reason)
        exit_code = exc.exit_code
    except Exception:
        payload = report("blocked", "transaction_internal_error")
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
