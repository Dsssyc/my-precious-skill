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
UPDATE_BATCH_REPORT_KIND = "memory_update_batch_report"
UPDATE_BATCH_REPORT_VERSION = 1
UPDATE_BATCH_METRIC_KEYS = {
    "inventory_worker_count",
    "projects_updated_count",
    "source_streams_updated_count",
    "archive_finalization_count",
    "records_deferred_count",
    "targets_deferred_count",
    "child_failure_count",
}
KNOWN_UPDATE_BLOCK_REASONS = {
    "source_inventory_invalid",
    "secret_records_rejected",
    "memory_review_decision_invalid",
    "archive_finalization_failed",
    "child_failure_unclassified",
    "clean_worktree_unavailable",
    "lock_unavailable",
    "concurrent_update",
    "interrupted",
    "runner_internal_error",
    "lock_release_failed",
    "child_cleanup_failed",
}
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
COMMIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
DIAGNOSTIC_KIND = "scheduled_memory_transaction_sync_diagnostics"
SYNC_OPERATIONS = {"sync_dry_run", "sync_commit", "candidate_validation", "sync_push"}
_ACTIVE_TRANSACTION_LOCK_FD: int | None = None


class TransactionBlocked(Exception):
    def __init__(
        self,
        reason: str,
        *,
        exit_code: int = 1,
        failure_stage: str | None = None,
        metrics: dict[str, int] | None = None,
        source_batch_complete: bool | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code
        self.failure_stage = failure_stage
        self.metrics = metrics
        self.source_batch_complete = source_batch_complete
        self.diagnostics = diagnostics


class ScopedPowerAssertion:
    """Best-effort idle/AC sleep prevention, scoped to this adapter's PID."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "ScopedPowerAssertion":
        if self.enabled and sys.platform == "darwin" and os.access("/usr/bin/caffeinate", os.X_OK):
            try:
                # This read-only helper must never inherit the transaction lock.
                self.process = subprocess.Popen(
                    ["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except OSError:
                pass
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        except OSError:
            # -w also releases assertions when the adapter exits.
            pass


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
    parser.add_argument("--no-power-assertion", action="store_true")
    return parser.parse_args(argv)


def subprocess_lock_kwargs() -> dict[str, object]:
    if os.name != "posix" or _ACTIVE_TRANSACTION_LOCK_FD is None:
        return {}
    return {"pass_fds": (_ACTIVE_TRANSACTION_LOCK_FD,)}


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
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
    if COMMIT_SHA.fullmatch(str(payload["base_sha"])) is None:
        raise TransactionBlocked("malformed_state")
    candidate = payload.get("candidate_sha")
    if candidate is not None and (not isinstance(candidate, str) or COMMIT_SHA.fullmatch(candidate) is None):
        raise TransactionBlocked("malformed_state")
    for key in ("source_record_deferred_count", "source_target_deferred_count"):
        value = payload.get(key, 0)
        if not isinstance(value, int) or value < 0:
            raise TransactionBlocked("malformed_state")
    source_batch_complete = payload.get("source_batch_complete", True)
    if not isinstance(source_batch_complete, bool):
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
    source_record_deferred_count: int | None = None,
    source_target_deferred_count: int | None = None,
    source_batch_complete: bool | None = None,
) -> dict[str, object]:
    existing: dict[str, object] = {}
    state_path = state_dir / "transaction.json"
    if state_path.is_file() and not state_path.is_symlink():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            existing = loaded
    if source_record_deferred_count is None:
        source_record_deferred_count = int(existing.get("source_record_deferred_count", 0))
    if source_target_deferred_count is None:
        source_target_deferred_count = int(existing.get("source_target_deferred_count", 0))
    if source_batch_complete is None:
        source_batch_complete = bool(existing.get("source_batch_complete", True))
    payload: dict[str, object] = {
        "report_kind": STATE_KIND,
        "report_version": STATE_VERSION,
        "repository_fingerprint": repository_fingerprint,
        "remote_fingerprint": expected_remote_fingerprint,
        "base_sha": base_sha,
        "phase": phase,
        "source_record_deferred_count": source_record_deferred_count,
        "source_target_deferred_count": source_target_deferred_count,
        "source_batch_complete": source_batch_complete,
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
    if len(fields) != 2 or fields[1] != "refs/heads/main" or COMMIT_SHA.fullmatch(fields[0]) is None:
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
        "source_record_deferred_count": 0,
        "source_target_deferred_count": 0,
        "update_inventory_worker_count": 0,
        "update_project_processed_count": 0,
        "update_source_stream_processed_count": 0,
        "update_child_failure_count": 0,
        "privacy_leak_count": 0,
    }


def failure_stage_for_reason(reason: str) -> str:
    if reason in KNOWN_UPDATE_BLOCK_REASONS:
        return "update"
    if reason.startswith("archive_audit"):
        return "archive_audit"
    if reason.startswith("publish_"):
        return "publish_readiness"
    if reason.startswith("search_"):
        return "search_health"
    if reason.startswith("sync_dry"):
        return "sync_dry_run"
    if reason.startswith("sync_live") or reason == "push_not_requested":
        return "sync_live"
    if reason.startswith("remote_"):
        return "remote_receipt"
    if reason.startswith("canonical_") or reason == "dirty_canonical":
        return "canonical"
    if "staging" in reason or "state" in reason or reason in {
        "input_unavailable",
        "concurrent_transaction",
    }:
        return "preflight"
    return "transaction"


def report(
    status: str,
    reason: str,
    *,
    recovery_action: str = "none",
    metrics: dict[str, int] | None = None,
    source_batch_complete: bool | None = None,
    failure_stage: str | None = None,
    diagnostics: dict[str, object] | None = None,
) -> dict[str, object]:
    values = metrics or empty_metrics()
    if source_batch_complete is None:
        source_batch_complete = (
            status in {"published", "no_op_current"}
            and values["source_record_deferred_count"] == 0
        )
    payload: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "status": status,
        "reason": reason,
        "failure_stage": failure_stage or (
            failure_stage_for_reason(reason) if status == "blocked" else "none"
        ),
        "recovery_action": recovery_action,
        "source_batch_complete": source_batch_complete,
        "metrics": values,
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "source_content_rendered": False,
            "archive_content_rendered": False,
        },
    }
    if diagnostics is not None:
        payload["sync_diagnostics"] = diagnostics
    return payload


def run_command(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
        **subprocess_lock_kwargs(),
    )


def run_python_tool(
    staging: Path, name: str, *arguments: str, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = staging / "tools" / name
    if not script.is_file() or script.is_symlink():
        raise TransactionBlocked("runtime_tool_missing")
    return run_command([sys.executable, str(script), *arguments], cwd=staging, env=env)


def sync_error_category(output: str) -> str:
    """Classify child text without returning any part of that untrusted text."""
    value = output.lower()
    if any(token in value for token in (
        "authentication failed", "permission denied", "could not read username",
        "terminal prompts disabled", "authorization failed",
    )):
        return "auth"
    if any(token in value for token in (
        "could not resolve", "connection reset", "connection timed out", "operation timed out",
        "network is unreachable", "failed to connect", "connection refused",
        "remote end hung up", "connection closed", "unable to access",
    )):
        return "network"
    if any(token in value for token in ("rejected", "non-fast-forward", "stale info", "hook declined")):
        return "rejected"
    if "refusing to sync" in value:
        return "policy"
    return "unknown"


def run_sync_step(
    context: dict[str, object],
    operation: str,
    command: Callable[[], subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    assert operation in SYNC_OPERATIONS
    started = time.monotonic()
    try:
        result = command()
    except OSError as exc:
        result = None
        error = exc
    if result is None or result.returncode != 0:
        context.setdefault("sync_diagnostics", {
            "report_kind": DIAGNOSTIC_KIND,
            "report_version": 1,
            "primary_failure": {
                "operation": operation,
                "exit_code": result.returncode if result is not None else None,
                "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
                "error_category": (
                    sync_error_category(result.stderr + "\n" + result.stdout)
                    if result is not None else "unknown"
                ),
            },
            "remote_observation": "not_checked",
        })
    if result is None:
        reason = "sync_live_failed" if operation in {"sync_commit", "sync_push"} else "sync_dry_run_failed"
        raise TransactionBlocked(reason) from error
    return result


def observe_sync_remote(
    remote_url: str, canonical: Path, base_sha: str, candidate_sha: str,
    context: dict[str, object],
) -> str:
    diagnostic = context.get("sync_diagnostics")
    try:
        head = remote_main_head(remote_url, cwd=canonical, reason="remote_receipt_failed")
    except (TransactionBlocked, OSError) as exc:
        if isinstance(diagnostic, dict):
            diagnostic["remote_observation"] = "unavailable"
            raise TransactionBlocked("sync_live_failed", failure_stage="sync_live") from exc
        raise
    if isinstance(diagnostic, dict):
        diagnostic["remote_observation"] = (
            "base" if head == base_sha else "candidate" if head == candidate_sha else "other"
        )
    return head


def parse_update_batch_report(result: subprocess.CompletedProcess[str]) -> dict[str, object] | None:
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
            "failure_stage",
            "source_batch_complete",
            "metrics",
            "privacy",
        }
        or payload.get("report_kind") != UPDATE_BATCH_REPORT_KIND
        or payload.get("report_version") != UPDATE_BATCH_REPORT_VERSION
        or payload.get("status") not in {"updated", "deferred", "blocked"}
        or not isinstance(payload.get("reason"), str)
        or payload.get("failure_stage")
        not in {
            "none",
            "preflight",
            "source_inventory",
            "project_update",
            "source_stream_update",
            "archive_finalization",
            "runner",
            "lock_acquire",
            "lock_release",
            "child_cleanup",
        }
        or not isinstance(payload.get("source_batch_complete"), bool)
    ):
        return None
    metrics = payload.get("metrics")
    if (
        not isinstance(metrics, dict)
        or set(metrics) != UPDATE_BATCH_METRIC_KEYS
        or any(not isinstance(metrics[key], int) or metrics[key] < 0 for key in UPDATE_BATCH_METRIC_KEYS)
    ):
        return None
    privacy = payload.get("privacy")
    if privacy != {
        "aggregate_only": True,
        "paths_rendered": False,
        "source_content_rendered": False,
        "child_output_rendered": False,
    }:
        return None
    deferred_count = metrics["records_deferred_count"]
    if payload["source_batch_complete"] != (payload["status"] == "updated" and deferred_count == 0):
        return None
    if payload["status"] == "updated" and payload["reason"] != "updated":
        return None
    if payload["status"] == "deferred" and (
        payload["reason"] != "source_records_deferred" or deferred_count == 0
    ):
        return None
    if payload["status"] == "blocked" and payload["reason"] not in KNOWN_UPDATE_BLOCK_REASONS:
        return None
    if payload["status"] == "blocked" and payload["failure_stage"] == "none":
        return None
    if payload["status"] != "blocked" and payload["failure_stage"] != "none":
        return None
    return payload


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
    if (staging / ".git").is_symlink() or not (staging / ".git").is_dir():
        raise TransactionBlocked("unsafe_staging")
    remote = run_git(staging, "remote", "get-url", "origin")
    if remote.returncode != 0 or remote_fingerprint(remote.stdout.strip(), staging) != expected_remote_fingerprint:
        raise TransactionBlocked("unexpected_remote")
    return git_value(staging, "rev-parse", "HEAD", reason="staging_status_failed")


def ensure_candidate(staging: Path, base_sha: str, candidate_sha: str) -> None:
    if candidate_sha == base_sha or COMMIT_SHA.fullmatch(candidate_sha) is None:
        raise TransactionBlocked("sync_live_no_commit")
    if git_value(staging, "rev-parse", "HEAD", reason="staging_status_failed") != candidate_sha:
        raise TransactionBlocked("sync_live_candidate_mismatch")
    if git_value(staging, "branch", "--show-current", reason="staging_status_failed") != "main":
        raise TransactionBlocked("sync_live_candidate_mismatch")
    parents = git_value(
        staging, "rev-list", "--parents", "-n", "1", candidate_sha,
        reason="sync_live_candidate_mismatch",
    ).split()
    if parents != [candidate_sha, base_sha]:
        raise TransactionBlocked("sync_live_candidate_mismatch")
    status = run_git(staging, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0 or status.stdout:
        raise TransactionBlocked("sync_live_candidate_dirty")
    # Policy validation executes deployed helpers. Anchor that entire tool bundle
    # to the known base before running anything from the retained commit.
    base_tools = git_value(staging, "rev-parse", f"{base_sha}:tools", reason="runtime_tool_missing")
    candidate_tools = git_value(staging, "rev-parse", f"{candidate_sha}:tools", reason="runtime_tool_missing")
    if candidate_tools != base_tools:
        raise TransactionBlocked("sync_live_candidate_tools_changed")
    # The real index can hide worktree edits with skip-worktree, assume-unchanged
    # or cached stat data. A fresh candidate index checks actual tracked bytes
    # and modes before any deployed helper is executed, without refreshing or
    # changing the real index.
    with tempfile.TemporaryDirectory(prefix="candidate-worktree-") as temporary:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index"), "GIT_OPTIONAL_LOCKS": "0"}
        if run_git(staging, "-c", "core.sparseCheckout=false", "read-tree", candidate_sha, env=environment).returncode != 0:
            raise TransactionBlocked("sync_live_candidate_dirty")
        if run_git(staging, "update-index", "--really-refresh", env=environment).returncode != 0:
            raise TransactionBlocked("sync_live_candidate_dirty")
        if run_git(
            staging, "diff-files", "--quiet", "--no-ext-diff", "--no-textconv",
            "--ignore-submodules=none", env=environment,
        ).returncode != 0:
            raise TransactionBlocked("sync_live_candidate_dirty")


def validate_committed_candidate(
    args: argparse.Namespace, staging: Path, base_sha: str, candidate_sha: str,
    context: dict[str, object],
) -> None:
    ensure_candidate(staging, base_sha, candidate_sha)
    # Project the committed delta through the deployed policy, without changing
    # HEAD, the real index or the worktree. Never duplicate its allowed paths.
    with tempfile.TemporaryDirectory(prefix="candidate-validation-") as temporary:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index"), "GIT_OPTIONAL_LOCKS": "0"}
        if run_git(staging, "read-tree", base_sha, env=environment).returncode != 0:
            raise TransactionBlocked("sync_live_candidate_validation_failed")
        for tool, arguments, reason in (
            ("audit_memory_archive.py", ["--memory-repo", str(staging)], "archive_audit_failed"),
            ("audit_publish_readiness.py", ["--memory-repo", str(staging)], "publish_readiness_failed"),
            ("search_memory.py", ["--repo", str(staging), "--health-check"], "search_health_failed"),
            ("sync_memory_archive.py", sync_arguments(args, staging, dry_run=True), "sync_dry_run_failed"),
        ):
            result = run_sync_step(context, "candidate_validation", lambda: run_python_tool(
                staging, tool, *arguments, env=environment,
            ))
            if result.returncode != 0:
                raise TransactionBlocked(reason)
        if "Would commit:" not in result.stdout or "No memory archive changes to sync." in result.stdout:
            raise TransactionBlocked("sync_live_candidate_validation_failed")
    ensure_candidate(staging, base_sha, candidate_sha)


def publish_candidate_once(
    args: argparse.Namespace, canonical: Path, staging: Path,
    remote_url: str, expected_remote_fingerprint: str,
    base_sha: str, candidate_sha: str, context: dict[str, object],
) -> bool:
    ensure_candidate(staging, base_sha, candidate_sha)
    # An origin can have separate or multiple push URLs. A fixed refspec alone
    # would not constrain those destinations to the receipted remote.
    for arguments in (("remote", "get-url", "origin"), ("remote", "get-url", "--push", "--all", "origin")):
        result = run_git(staging, *arguments)
        urls = result.stdout.splitlines()
        if result.returncode != 0 or len(urls) != 1 or remote_fingerprint(urls[0], staging) != expected_remote_fingerprint:
            raise TransactionBlocked("unexpected_remote")
    observed = observe_sync_remote(remote_url, canonical, base_sha, candidate_sha, context)
    if observed == candidate_sha:
        return False
    if observed != base_sha:
        raise TransactionBlocked("remote_race")
    if not args.push:
        raise TransactionBlocked("push_not_requested")
    ensure_clean_canonical(canonical)
    for revision in ("HEAD", "origin/main"):
        if git_value(canonical, "rev-parse", revision, reason="canonical_unavailable") != base_sha:
            raise TransactionBlocked("canonical_changed_during_transaction")
    result = run_sync_step(context, "sync_push", lambda: run_git(
        staging, "push", "--porcelain", "--no-follow-tags",
        f"--force-with-lease=refs/heads/main:{base_sha}",
        "origin", f"{candidate_sha}:refs/heads/main",
    ))
    observed = observe_sync_remote(remote_url, canonical, base_sha, candidate_sha, context)
    if observed == candidate_sha:
        return True
    if observed != base_sha:
        raise TransactionBlocked("remote_race")
    raise TransactionBlocked("sync_live_failed" if result.returncode else "remote_receipt_failed")


def reconcile_post_push(
    canonical: Path,
    state_dir: Path,
    state: dict[str, object],
    repository_fingerprint: str,
    expected_remote_fingerprint: str,
    remote_head: str,
    *,
    args: argparse.Namespace,
    remote_url: str,
    context: dict[str, object],
) -> dict[str, object] | None:
    phase = state.get("phase")
    if phase not in RECOVERABLE_PUBLISH_PHASES:
        return None
    base_sha = str(state["base_sha"])
    staging_head = staging_head_if_owned(state_dir, repository_fingerprint, expected_remote_fingerprint)
    if staging_head is None:
        raise TransactionBlocked("unsafe_staging")
    staging = state_dir / "staging"
    ensure_v238_update_idle(staging)
    candidate = str(state.get("candidate_sha") or staging_head or "")
    metrics = empty_metrics()
    metrics["recovery_count"] = 1
    metrics["source_record_deferred_count"] = int(state.get("source_record_deferred_count", 0))
    metrics["source_target_deferred_count"] = int(state.get("source_target_deferred_count", 0))
    source_batch_complete = bool(state.get("source_batch_complete", True))
    context["metrics"] = metrics
    context["source_batch_complete"] = source_batch_complete
    if remote_head == base_sha:
        if phase == "complete" and candidate == base_sha and staging_head == base_sha:
            ensure_clean_canonical(canonical)
            canonical_head = git_value(
                canonical,
                "rev-parse",
                "HEAD",
                reason="canonical_unavailable",
            )
            tracking_head = git_value(
                canonical,
                "rev-parse",
                "origin/main",
                reason="canonical_unavailable",
            )
            if canonical_head != base_sha or tracking_head != base_sha:
                raise TransactionBlocked("canonical_remote_mismatch")
            staging_status = run_git(
                state_dir / "staging",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            )
            if staging_status.returncode != 0 or staging_status.stdout:
                raise TransactionBlocked("staging_status_failed")
            metrics = empty_metrics()
            metrics["recovery_count"] = 1
            metrics["source_record_deferred_count"] = int(
                state.get("source_record_deferred_count", 0)
            )
            metrics["source_target_deferred_count"] = int(
                state.get("source_target_deferred_count", 0)
            )
            source_batch_complete = bool(state.get("source_batch_complete", True))
            clear_state(state_dir)
            status = "no_op_current" if source_batch_complete else "deferred"
            reason = "no_op_current" if source_batch_complete else "source_records_deferred"
            return report(
                status,
                reason,
                recovery_action="completed_no_publish_reconciled",
                metrics=metrics,
                source_batch_complete=source_batch_complete,
            )
        if phase in {"remote_receipt", "canonical_fast_forward", "complete"}:
            raise TransactionBlocked("remote_receipt_failed")
        if phase == "sync_live" and "candidate_sha" not in state and staging_head == base_sha:
            # No commit was created; the pre-commit updater replay remains valid.
            return None
    if remote_head not in {base_sha, candidate} or staging_head != candidate:
        raise TransactionBlocked("remote_race")
    if remote_head == base_sha or phase == "sync_live":
        if phase != "sync_live":
            raise TransactionBlocked("remote_receipt_failed")
        ensure_clean_canonical(canonical)
        for revision in ("HEAD", "origin/main"):
            if git_value(canonical, "rev-parse", revision, reason="canonical_unavailable") != base_sha:
                raise TransactionBlocked("canonical_remote_mismatch")
    ensure_candidate(staging, base_sha, candidate)
    # Pin a legacy candidate before content validation, so a failed check cannot
    # leave it eligible for replacement by a different direct child on replay.
    if phase == "sync_live":
        write_state(
            state_dir, repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=base_sha, phase="sync_live", candidate_sha=candidate,
        )
    validate_committed_candidate(args, staging, base_sha, candidate, context)
    pushed = False
    if remote_head == base_sha:
        pushed = publish_candidate_once(
            args, canonical, staging, remote_url, expected_remote_fingerprint,
            base_sha, candidate, context,
        )
    elif observe_sync_remote(remote_url, canonical, base_sha, candidate, context) != candidate:
        raise TransactionBlocked("remote_race")
    metrics["remote_publish_count"] = int(pushed)
    if phase == "sync_live":
        write_state(
            state_dir, repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=base_sha, phase="remote_receipt", candidate_sha=candidate,
        )
    install_verified_candidate(
        canonical,
        state_dir / "staging",
        base_sha=base_sha,
        candidate_sha=candidate,
    )
    write_state(
        state_dir, repository_fingerprint=repository_fingerprint,
        expected_remote_fingerprint=expected_remote_fingerprint,
        base_sha=base_sha, phase="canonical_fast_forward", candidate_sha=candidate,
    )

    def checkpoint_canonical_checkout() -> None:
        write_state(
            state_dir, repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=base_sha, phase="canonical_checkout_applied", candidate_sha=candidate,
        )

    apply_verified_canonical(
        canonical,
        base_sha=base_sha,
        candidate_sha=candidate,
        allow_interrupted_repair=phase
        in {"canonical_fast_forward", "canonical_checkout_applied", "complete"},
        checkpoint=checkpoint_canonical_checkout,
    )
    metrics["canonical_mutation_count"] = 1
    write_state(
        state_dir, repository_fingerprint=repository_fingerprint,
        expected_remote_fingerprint=expected_remote_fingerprint,
        base_sha=base_sha, phase="complete", candidate_sha=candidate,
    )
    clear_state(state_dir)
    return report(
        "published",
        "published",
        recovery_action=(
            "stale_staging_replayed" if pushed and "candidate_sha" not in state else
            "unpublished_candidate_resumed" if pushed else "post_push_reconciled"
        ),
        metrics=metrics,
        source_batch_complete=source_batch_complete,
    )


def sync_arguments(args: argparse.Namespace, staging: Path, *, dry_run: bool) -> list[str]:
    values = ["--memory-repo", str(staging)]
    if args.include_reviewed_memory_nodes:
        values.append("--include-reviewed-memory-nodes")
    if dry_run:
        values.append("--dry-run")
    return values


def _execute(
    args: argparse.Namespace,
    update_context: dict[str, object],
) -> dict[str, object]:
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
                args=args,
                remote_url=resolved_remote_url,
                context=update_context,
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
            "--report-json",
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
        update_result = run_python_tool(staging, "run_memory_updates.py", *update_arguments)
        update_report = parse_update_batch_report(update_result)
        if update_report is None:
            raise TransactionBlocked(
                "child_failure_unclassified",
                failure_stage="update",
                metrics=dict(metrics),
            )
        update_metrics = update_report["metrics"]
        assert isinstance(update_metrics, dict)
        metrics["source_record_deferred_count"] = int(update_metrics["records_deferred_count"])
        metrics["source_target_deferred_count"] = int(update_metrics["targets_deferred_count"])
        metrics["update_inventory_worker_count"] = int(update_metrics["inventory_worker_count"])
        metrics["update_project_processed_count"] = int(update_metrics["projects_updated_count"])
        metrics["update_source_stream_processed_count"] = int(
            update_metrics["source_streams_updated_count"]
        )
        metrics["update_child_failure_count"] = int(update_metrics["child_failure_count"])
        source_batch_complete = bool(update_report["source_batch_complete"])
        update_context["metrics"] = metrics
        update_context["source_batch_complete"] = source_batch_complete
        if update_result.returncode != 0:
            if update_report["status"] != "blocked":
                raise TransactionBlocked(
                    "child_failure_unclassified",
                    failure_stage="update",
                    metrics=dict(metrics),
                    source_batch_complete=source_batch_complete,
                )
            raise TransactionBlocked(
                str(update_report["reason"]),
                failure_stage=str(update_report["failure_stage"]),
                metrics=dict(metrics),
                source_batch_complete=source_batch_complete,
            )
        if update_report["status"] not in {"updated", "deferred"}:
            raise TransactionBlocked(
                "child_failure_unclassified",
                failure_stage="update",
                metrics=dict(metrics),
                source_batch_complete=source_batch_complete,
            )

        audit_arguments = ("--memory-repo", str(staging))
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="auditing",
            source_record_deferred_count=metrics["source_record_deferred_count"],
            source_target_deferred_count=metrics["source_target_deferred_count"],
            source_batch_complete=source_batch_complete,
        )
        archive_audit = run_python_tool(staging, "audit_memory_archive.py", *audit_arguments)
        readiness = run_python_tool(staging, "audit_publish_readiness.py", *audit_arguments)
        if archive_audit.returncode != 0 or readiness.returncode != 0:
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
        dry_sync = run_sync_step(update_context, "sync_dry_run", lambda: run_python_tool(
            staging, "sync_memory_archive.py", *sync_arguments(args, staging, dry_run=True),
        ))
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
            status = "no_op_current" if source_batch_complete else "deferred"
            reason = "no_op_current" if source_batch_complete else "source_records_deferred"
            return report(
                status,
                reason,
                recovery_action=recovery_action,
                metrics=metrics,
                source_batch_complete=source_batch_complete,
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
        live_sync = run_sync_step(update_context, "sync_commit", lambda: run_python_tool(
            staging, "sync_memory_archive.py", *sync_arguments(args, staging, dry_run=False),
        ))
        candidate_sha = git_value(staging, "rev-parse", "HEAD", reason="staging_status_failed")
        if candidate_sha == remote_head:
            if live_sync.returncode != 0:
                observe_sync_remote(resolved_remote_url, memory_repo, remote_head, candidate_sha, update_context)
                raise TransactionBlocked("sync_live_failed")
            raise TransactionBlocked("sync_live_no_commit")
        ensure_candidate(staging, remote_head, candidate_sha)
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="sync_live",
            candidate_sha=candidate_sha,
        )
        validate_committed_candidate(args, staging, remote_head, candidate_sha, update_context)
        if live_sync.returncode != 0:
            observed = observe_sync_remote(
                resolved_remote_url, memory_repo, remote_head, candidate_sha, update_context,
            )
            if observed != candidate_sha:
                raise TransactionBlocked("sync_live_failed" if observed == remote_head else "remote_race")
        else:
            publish_candidate_once(
                args, memory_repo, staging, resolved_remote_url, expected_remote_fingerprint,
                remote_head, candidate_sha, update_context,
            )
        write_state(
            state_dir,
            repository_fingerprint=repository_fingerprint,
            expected_remote_fingerprint=expected_remote_fingerprint,
            base_sha=remote_head,
            phase="remote_receipt",
            candidate_sha=candidate_sha,
        )
        if observe_sync_remote(
            resolved_remote_url, memory_repo, remote_head, candidate_sha, update_context,
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
            source_batch_complete=source_batch_complete,
        )


def execute(args: argparse.Namespace) -> dict[str, object]:
    update_context: dict[str, object] = {}
    try:
        with ScopedPowerAssertion(enabled=not args.no_power_assertion):
            payload = _execute(args, update_context)
        diagnostics = update_context.get("sync_diagnostics")
        if isinstance(diagnostics, dict):
            payload["sync_diagnostics"] = diagnostics
        return payload
    except TransactionBlocked as exc:
        metrics = update_context.get("metrics")
        if exc.metrics is None and isinstance(metrics, dict):
            exc.metrics = dict(metrics)
        source_batch_complete = update_context.get("source_batch_complete")
        if exc.source_batch_complete is None and isinstance(source_batch_complete, bool):
            exc.source_batch_complete = source_batch_complete
        diagnostics = update_context.get("sync_diagnostics")
        if exc.diagnostics is None and isinstance(diagnostics, dict):
            exc.diagnostics = diagnostics
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = execute(args)
        exit_code = 0
    except TransactionBlocked as exc:
        payload = report(
            "blocked",
            exc.reason,
            metrics=exc.metrics,
            source_batch_complete=exc.source_batch_complete,
            failure_stage=exc.failure_stage,
            diagnostics=exc.diagnostics,
        )
        exit_code = exc.exit_code
    except Exception:
        payload = report("blocked", "transaction_internal_error")
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
