#!/usr/bin/env python3
"""Prove scheduled-memory transaction replay across abrupt process loss."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = REPO_ROOT / "skills/update-my-precious/scripts/run_scheduled_memory_transaction.py"
REPORT_KIND = "scheduled_reboot_replay_gate"
REPORT_VERSION = 1
RAW_SOURCE_SENTINEL = "PRIVATE_REBOOT_REPLAY_RAW_SOURCE_SENTINEL"
WAIT_TIMEOUT_SECONDS = 20.0


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def run_command(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )
    if check and result.returncode != 0:
        raise GateFailure("command", "command_failed")
    return result


def git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *arguments], cwd=repo, check=check)


def wait_until(predicate: Callable[[], bool], stage: str) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise GateFailure(stage, "timeout")


def parse_adapter_report(result: subprocess.CompletedProcess[str], stage: str) -> dict[str, object]:
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise GateFailure(stage, "adapter_report_line_count")
    try:
        report = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise GateFailure(stage, "adapter_report_malformed") from exc
    if not isinstance(report, dict) or report.get("report_kind") != "scheduled_memory_transaction":
        raise GateFailure(stage, "adapter_report_kind")
    return report


def install_synthetic_runtime(repository: Path) -> None:
    tools = repository / "tools"
    tools.mkdir()
    (tools / "run_memory_updates.py").write_text(
        """#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
mode = os.environ.get('SYNTHETIC_TRANSACTION_MODE', 'change')
if mode != 'noop':
    (repo / 'INDEX.md').write_text('synthetic scheduled update\\n', encoding='utf-8')
if '--report-json' in args:
    print(json.dumps({
        'report_kind': 'memory_update_batch_report',
        'report_version': 1,
        'status': 'updated',
        'reason': 'updated',
        'failure_stage': 'none',
        'source_batch_complete': True,
        'metrics': {
            'inventory_worker_count': 1,
            'projects_updated_count': 1,
            'source_streams_updated_count': 0,
            'archive_finalization_count': 1,
            'records_deferred_count': 0,
            'targets_deferred_count': 0,
            'child_failure_count': 0,
        },
        'privacy': {
            'aggregate_only': True,
            'paths_rendered': False,
            'source_content_rendered': False,
            'child_output_rendered': False,
        },
    }, sort_keys=True, separators=(',', ':')), flush=True)
if mode == 'nested_writer':
    import fcntl
    uid = os.getuid() if hasattr(os, 'getuid') else 0
    lock_root = Path(tempfile.gettempdir()) / f'my-precious-update-locks-{uid}'
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256(str(repo.resolve()).encode('utf-8')).hexdigest()
    descriptor = os.open(lock_root / f'{digest}.lock', os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    child = subprocess.Popen(
        [sys.executable, str(repo / 'tools' / 'synthetic_nested_writer.py')],
        cwd=repo,
        pass_fds=(descriptor,),
        start_new_session=True,
    )
    try:
        raise SystemExit(child.wait())
    finally:
        os.close(descriptor)
marker = os.environ.get('SYNTHETIC_UPDATE_STARTED')
if marker:
    Path(marker).write_text('started\\n', encoding='utf-8')
    release = Path(os.environ['SYNTHETIC_UPDATE_RELEASE'])
    while not release.exists():
        time.sleep(0.02)
""",
        encoding="utf-8",
    )
    (tools / "synthetic_nested_writer.py").write_text(
        """#!/usr/bin/env python3
import os
import time
from pathlib import Path

marker = Path(os.environ['SYNTHETIC_NESTED_CHILD_STARTED'])
release = Path(os.environ['SYNTHETIC_NESTED_CHILD_RELEASE'])
marker.write_text(str(os.getpid()) + '\\n', encoding='utf-8')
while not release.exists():
    time.sleep(0.02)
""",
        encoding="utf-8",
    )
    for name in ("audit_memory_archive.py", "audit_publish_readiness.py", "repair_publish_surfaces.py"):
        (tools / name).write_text("raise SystemExit(0)\n", encoding="utf-8")
    (tools / "search_memory.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (tools / "sync_memory_archive.py").write_text(
        """#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
status = subprocess.run(
    ['git', 'status', '--porcelain=v1', '--untracked-files=all'],
    cwd=repo,
    text=True,
    stdout=subprocess.PIPE,
    check=True,
).stdout
if '--dry-run' in args:
    print('Would commit: synthetic scheduled update' if status else 'No memory archive changes to sync.')
    raise SystemExit(0)
if not status:
    print('No memory archive changes to sync.')
    raise SystemExit(0)
subprocess.run(['git', 'add', '--', 'INDEX.md'], cwd=repo, check=True)
subprocess.run(['git', 'commit', '-m', 'Synthetic scheduled update'], cwd=repo, check=True)
marker = os.environ.get('SYNTHETIC_BEFORE_PUSH')
if marker:
    Path(marker).write_text('ready\\n', encoding='utf-8')
    release = Path(os.environ['SYNTHETIC_PUSH_RELEASE'])
    while not release.exists():
        time.sleep(0.02)
if '--push' in args:
    raise SystemExit(subprocess.run(['git', 'push', 'origin', 'main'], cwd=repo).returncode)
""",
        encoding="utf-8",
    )


class SyntheticArchive:
    def __init__(self, parent: Path, name: str) -> None:
        self.root = parent / name
        self.remote = self.root / "remote.git"
        self.canonical = self.root / "canonical"
        self.source = self.root / "source"
        self.state = self.root / "state"
        self.root.mkdir()
        self.remote.mkdir()
        self.canonical.mkdir()
        self.source.mkdir()
        (self.source / "raw-record.jsonl").write_text(RAW_SOURCE_SENTINEL + "\n", encoding="utf-8")
        git(self.remote, "init", "--bare", "--initial-branch=main")
        git(self.canonical, "init", "--initial-branch=main")
        git(self.canonical, "config", "user.email", "synthetic@example.invalid")
        git(self.canonical, "config", "user.name", "Synthetic Replay Gate")
        (self.canonical / "baseline.txt").write_text("synthetic baseline\n", encoding="utf-8")
        install_synthetic_runtime(self.canonical)
        git(self.canonical, "add", ".")
        git(self.canonical, "commit", "-m", "Synthetic V2.38 runtime baseline")
        git(self.canonical, "remote", "add", "origin", str(self.remote))
        git(self.canonical, "push", "-u", "origin", "main")
        self.base_sha = self.canonical_head()
        self.tool_hashes = self.current_tool_hashes()

    def command(
        self,
        *,
        state_dir: Path | None = None,
        memory_repo: Path | None = None,
    ) -> list[str]:
        selected_repo = memory_repo or self.canonical
        return [
            sys.executable,
            str(ADAPTER),
            "--memory-repo",
            str(selected_repo),
            "--source-dir",
            str(self.source),
            "--state-dir",
            str(state_dir or self.state),
            "--push",
        ]

    def environment(self, **overrides: str) -> dict[str, str]:
        return {**os.environ, **overrides}

    def invoke(
        self,
        *,
        state_dir: Path | None = None,
        memory_repo: Path | None = None,
        **overrides: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        selected_repo = memory_repo or self.canonical
        result = run_command(
            self.command(state_dir=state_dir, memory_repo=selected_repo),
            cwd=selected_repo,
            check=False,
            env=self.environment(**overrides),
        )
        return result, parse_adapter_report(result, self.root.name)

    def start(
        self,
        *,
        state_dir: Path | None = None,
        memory_repo: Path | None = None,
        **overrides: str,
    ) -> subprocess.Popen[str]:
        selected_repo = memory_repo or self.canonical
        return subprocess.Popen(
            self.command(state_dir=state_dir, memory_repo=selected_repo),
            cwd=selected_repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(**overrides),
            start_new_session=True,
        )

    def canonical_head(self) -> str:
        return git(self.canonical, "rev-parse", "HEAD").stdout.strip()

    def canonical_tracking_head(self) -> str:
        return git(self.canonical, "rev-parse", "origin/main").stdout.strip()

    def remote_head(self) -> str:
        return git(self.remote, "rev-parse", "main").stdout.strip()

    def staging_head(self) -> str:
        return git(self.state / "staging", "rev-parse", "HEAD").stdout.strip()

    def canonical_clean(self) -> bool:
        return not git(
            self.canonical,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout

    def remote_commit_count(self) -> int:
        value = git(self.remote, "rev-list", "--count", f"{self.base_sha}..main").stdout.strip()
        return int(value)

    def current_tool_hashes(self) -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.canonical / "tools").glob("*.py"))
        }

    def tool_mutation_count(self) -> int:
        return int(self.current_tool_hashes() != self.tool_hashes)

    def raw_source_copy_count(self) -> int:
        count = 0
        raw_bytes = RAW_SOURCE_SENTINEL.encode("utf-8")
        for path in self.root.rglob("*"):
            if not path.is_file() or self.source == path or self.source in path.parents:
                continue
            try:
                if raw_bytes in path.read_bytes():
                    count += 1
            except OSError:
                count += 1
        return count

    def wait_for_file(self, path: Path, stage: str) -> None:
        wait_until(path.is_file, stage)

    def wait_for_phase(self, phase: str, stage: str) -> None:
        state_path = self.state / "transaction.json"

        def phase_matches() -> bool:
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            return payload.get("phase") == phase

        wait_until(phase_matches, stage)


def kill_process_group(process: subprocess.Popen[str], stage: str) -> None:
    if process.poll() is not None:
        raise GateFailure(stage, "process_exited_before_sigkill")
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    try:
        process.communicate(timeout=WAIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise GateFailure(stage, "sigkill_did_not_terminate") from exc


def finish_process(process: subprocess.Popen[str], stage: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    try:
        stdout, stderr = process.communicate(timeout=WAIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise GateFailure(stage, "process_did_not_finish") from exc
    result = subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    return result, parse_adapter_report(result, stage)


class ReplayGate:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.cases: dict[str, dict[str, object]] = {}
        self.fixtures: list[SyntheticArchive] = []
        self.reboot_results: list[bool] = []
        self.interruption_clean_results: list[bool] = []
        self.stale_replay_results: list[bool] = []
        self.privacy_leak_count = 0
        self.partial_remote_publish_count = 0
        self.duplicate_publish_commit_count = 0
        self.canonical_unverified_mutation_count = 0
        self.receipted_remote_tracked_overlap_count = 0
        self.receipted_remote_untracked_overlap_count = 0

    def archive(self, name: str) -> SyntheticArchive:
        fixture = SyntheticArchive(self.root, name)
        self.fixtures.append(fixture)
        return fixture

    def record_report(self, fixture: SyntheticArchive, report: dict[str, object]) -> None:
        rendered = json.dumps(report, sort_keys=True)
        self.privacy_leak_count += int(str(fixture.root) in rendered)
        self.privacy_leak_count += int(RAW_SOURCE_SENTINEL in rendered)

    def add_case(self, name: str, passed: bool, status: str, reason: str) -> None:
        if not passed:
            raise GateFailure(name, "case_failed")
        self.cases[name] = {"passed": True, "status": status, "reason": reason}

    def run_clean_publish(self) -> bool:
        fixture = self.archive("clean-publish")
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        passed = (
            result.returncode == 0
            and report.get("status") == "published"
            and fixture.canonical_head() == fixture.remote_head()
            and fixture.canonical_head() != fixture.base_sha
            and fixture.canonical_clean()
        )
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case("clean_publish", passed, str(report.get("status")), str(report.get("reason")))
        return passed

    def run_no_op(self) -> bool:
        fixture = self.archive("no-op")
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="noop")
        self.record_report(fixture, report)
        passed = (
            result.returncode == 0
            and report.get("status") == "no_op_current"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.remote_head() == fixture.base_sha
            and fixture.canonical_clean()
        )
        self.add_case("no_op_current", passed, str(report.get("status")), str(report.get("reason")))
        return passed

    def run_kill_during_update(self) -> None:
        fixture = self.archive("kill-during-update")
        marker = fixture.root / "update-started"
        release = fixture.root / "update-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            SYNTHETIC_UPDATE_STARTED=str(marker),
            SYNTHETIC_UPDATE_RELEASE=str(release),
        )
        fixture.wait_for_file(marker, "kill_during_update:marker")
        kill_process_group(process, "kill_during_update")
        clean_after_kill = fixture.canonical_clean() and fixture.canonical_head() == fixture.base_sha
        remote_unchanged = fixture.remote_head() == fixture.base_sha
        self.interruption_clean_results.append(clean_after_kill)
        self.partial_remote_publish_count += int(not remote_unchanged)
        self.canonical_unverified_mutation_count += int(fixture.canonical_head() != fixture.base_sha)

        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        replayed = (
            result.returncode == 0
            and report.get("status") == "published"
            and report.get("recovery_action") == "stale_staging_replayed"
            and fixture.canonical_head() == fixture.remote_head()
        )
        self.reboot_results.append(replayed)
        self.stale_replay_results.append(replayed)
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case(
            "kill_during_update",
            clean_after_kill and remote_unchanged and replayed,
            str(report.get("status")),
            str(report.get("recovery_action")),
        )

    def run_interrupted_update_receipted_remote_advance(self) -> bool:
        fixture = self.archive("interrupted-update-receipted-remote-advance")
        marker = fixture.root / "update-started"
        release = fixture.root / "update-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            SYNTHETIC_UPDATE_STARTED=str(marker),
            SYNTHETIC_UPDATE_RELEASE=str(release),
        )
        fixture.wait_for_file(marker, "receipted_remote_advance:marker")
        kill_process_group(process, "receipted_remote_advance")
        clean_after_kill = fixture.canonical_clean() and fixture.canonical_head() == fixture.base_sha

        transaction_path = fixture.state / "transaction.json"
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        staging = fixture.state / "staging"
        (staging / "baseline.txt").write_text("stale tracked update\n", encoding="utf-8")
        status_lines = git(
            staging,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout.splitlines()
        dirty_tracked = {line[3:] for line in status_lines if not line.startswith("?? ")}
        dirty_untracked = {line[3:] for line in status_lines if line.startswith("?? ")}

        racer = fixture.root / "racer"
        git(fixture.root, "clone", "--quiet", str(fixture.remote), str(racer))
        git(racer, "config", "user.email", "racer@example.invalid")
        git(racer, "config", "user.name", "Synthetic Remote Receipt")
        (racer / "baseline.txt").write_text("receipted tracked update\n", encoding="utf-8")
        (racer / "INDEX.md").write_text("receipted untracked update\n", encoding="utf-8")
        git(racer, "add", "baseline.txt", "INDEX.md")
        git(racer, "commit", "-m", "Synthetic receipted remote advance")
        remote_changed = set(
            git(
                racer,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "HEAD",
            ).stdout.splitlines()
        )
        git(racer, "push", "--quiet", "origin", "main")
        self.receipted_remote_tracked_overlap_count += len(dirty_tracked & remote_changed)
        self.receipted_remote_untracked_overlap_count += len(dirty_untracked & remote_changed)

        git(fixture.canonical, "fetch", "--quiet", "origin", "main")
        git(fixture.canonical, "merge", "--ff-only", "origin/main")
        receipted_head = fixture.remote_head()
        clean_receipt = (
            fixture.canonical_clean()
            and fixture.canonical_head() == receipted_head
            and fixture.canonical_tracking_head() == receipted_head
        )
        retained_update = (
            transaction.get("phase") == "updating"
            and "candidate_sha" not in transaction
            and bool(dirty_tracked)
            and bool(dirty_untracked)
        )

        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="noop")
        self.record_report(fixture, report)
        replayed = (
            result.returncode == 0
            and report.get("status") == "no_op_current"
            and report.get("recovery_action") == "stale_staging_replayed"
            and isinstance(report.get("metrics"), dict)
            and report["metrics"].get("recovery_count") == 1
            and report["metrics"].get("remote_publish_count") == 0
            and report["metrics"].get("canonical_mutation_count") == 0
            and not transaction_path.exists()
            and fixture.canonical_clean()
            and fixture.canonical_head() == receipted_head
            and fixture.canonical_tracking_head() == receipted_head
            and fixture.staging_head() == receipted_head
            and not git(staging, "status", "--porcelain=v1", "--untracked-files=all").stdout
            and fixture.remote_commit_count() == 1
        )
        passed = (
            retained_update
            and clean_after_kill
            and clean_receipt
            and self.receipted_remote_tracked_overlap_count >= 1
            and self.receipted_remote_untracked_overlap_count >= 1
            and replayed
        )
        self.reboot_results.append(passed)
        self.interruption_clean_results.append(clean_after_kill)
        self.stale_replay_results.append(passed)
        self.add_case(
            "interrupted_update_receipted_remote_advance",
            passed,
            str(report.get("status")),
            str(report.get("recovery_action")),
        )
        return passed

    def run_kill_before_push(self) -> None:
        fixture = self.archive("kill-before-push")
        marker = fixture.root / "before-push"
        release = fixture.root / "push-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            SYNTHETIC_BEFORE_PUSH=str(marker),
            SYNTHETIC_PUSH_RELEASE=str(release),
        )
        fixture.wait_for_file(marker, "kill_before_push:marker")
        kill_process_group(process, "kill_before_push")
        clean_after_kill = fixture.canonical_clean() and fixture.canonical_head() == fixture.base_sha
        remote_unchanged = fixture.remote_head() == fixture.base_sha
        self.interruption_clean_results.append(clean_after_kill)
        self.partial_remote_publish_count += int(not remote_unchanged)
        self.canonical_unverified_mutation_count += int(fixture.canonical_head() != fixture.base_sha)

        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        replayed = (
            result.returncode == 0
            and report.get("status") == "published"
            and report.get("recovery_action") == "stale_staging_replayed"
            and fixture.canonical_head() == fixture.remote_head()
        )
        self.reboot_results.append(replayed)
        self.stale_replay_results.append(replayed)
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case(
            "kill_after_commit_before_push",
            clean_after_kill and remote_unchanged and replayed,
            str(report.get("status")),
            str(report.get("recovery_action")),
        )

    def run_kill_after_push(self) -> bool:
        fixture = self.archive("kill-after-push")
        release = fixture.root / "receipt-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE="remote_receipt",
            MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE=str(release),
        )
        fixture.wait_for_phase("remote_receipt", "kill_after_push:phase")
        kill_process_group(process, "kill_after_push")
        clean_after_kill = fixture.canonical_clean() and fixture.canonical_head() == fixture.base_sha
        complete_remote_receipt = fixture.remote_head() == fixture.staging_head() != fixture.base_sha
        self.interruption_clean_results.append(clean_after_kill)
        self.partial_remote_publish_count += int(not complete_remote_receipt)
        self.canonical_unverified_mutation_count += int(fixture.canonical_head() != fixture.base_sha)

        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        reconciled = (
            result.returncode == 0
            and report.get("status") == "published"
            and report.get("recovery_action") == "post_push_reconciled"
            and fixture.canonical_head() == fixture.remote_head()
        )
        self.reboot_results.append(reconciled)
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case(
            "kill_after_push_before_fast_forward",
            clean_after_kill and complete_remote_receipt and reconciled,
            str(report.get("status")),
            str(report.get("recovery_action")),
        )
        return reconciled

    def run_kill_during_canonical_fast_forward(self) -> bool:
        fixture = self.archive("kill-during-canonical-fast-forward")
        release = fixture.root / "canonical-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE="canonical_checkout_applied",
            MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE=str(release),
        )
        fixture.wait_for_phase(
            "canonical_checkout_applied",
            "kill_during_canonical_fast_forward:phase",
        )
        state = json.loads((fixture.state / "transaction.json").read_text(encoding="utf-8"))
        candidate = str(state["candidate_sha"])
        kill_process_group(process, "kill_during_canonical_fast_forward")
        complete_remote_receipt = fixture.remote_head() == candidate != fixture.base_sha
        interrupted_verified_checkout = (
            not fixture.canonical_clean()
            and fixture.canonical_head() == fixture.base_sha
            and fixture.canonical_tracking_head() == candidate
        )
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        recovered = (
            result.returncode == 0
            and report.get("status") == "published"
            and report.get("recovery_action") == "post_push_reconciled"
            and fixture.canonical_head() == fixture.remote_head() == candidate
            and fixture.canonical_clean()
        )
        self.reboot_results.append(recovered)
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case(
            "kill_during_canonical_fast_forward",
            complete_remote_receipt and interrupted_verified_checkout and recovered,
            str(report.get("status")),
            str(report.get("recovery_action")),
        )
        return recovered

    def run_concurrent(self) -> tuple[bool, bool, bool]:
        fixture = self.archive("concurrent")
        linked = fixture.root / "linked-worktree"
        git(
            fixture.canonical,
            "worktree",
            "add",
            "-b",
            "synthetic-linked-worktree",
            str(linked),
            fixture.base_sha,
        )
        release = fixture.root / "concurrent-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE="updating",
            MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE=str(release),
        )
        fixture.wait_for_phase("updating", "concurrent:phase")
        second_result, second_report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, second_report)
        rejected = second_result.returncode != 0 and second_report.get("reason") == "concurrent_transaction"
        alternate_result, alternate_report = fixture.invoke(
            state_dir=fixture.root / "alternate-state",
            SYNTHETIC_TRANSACTION_MODE="change",
        )
        self.record_report(fixture, alternate_report)
        alternate_rejected = (
            alternate_result.returncode != 0
            and alternate_report.get("reason") == "concurrent_transaction"
        )
        linked_result, linked_report = fixture.invoke(
            state_dir=fixture.root / "linked-state",
            memory_repo=linked,
            SYNTHETIC_TRANSACTION_MODE="change",
        )
        self.record_report(fixture, linked_report)
        linked_rejected = (
            linked_result.returncode != 0
            and linked_report.get("reason") == "concurrent_transaction"
        )
        release.write_text("release\n", encoding="utf-8")
        first_result, first_report = finish_process(process, "concurrent:first")
        self.record_report(fixture, first_report)
        passed = rejected and first_result.returncode == 0 and first_report.get("status") == "published"
        self.add_case(
            "concurrent_transaction",
            passed and alternate_rejected and linked_rejected,
            str(second_report.get("status")),
            str(second_report.get("reason")),
        )
        self.add_case(
            "concurrent_different_state_dir",
            alternate_rejected and first_result.returncode == 0,
            str(alternate_report.get("status")),
            str(alternate_report.get("reason")),
        )
        self.add_case(
            "concurrent_linked_worktree",
            linked_rejected and first_result.returncode == 0,
            str(linked_report.get("status")),
            str(linked_report.get("reason")),
        )
        return rejected, alternate_rejected, linked_rejected

    def run_orphan_nested_writer(self) -> bool:
        fixture = self.archive("orphan-nested-writer")
        marker = fixture.root / "nested-child-started"
        release = fixture.root / "nested-child-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="nested_writer",
            SYNTHETIC_NESTED_CHILD_STARTED=str(marker),
            SYNTHETIC_NESTED_CHILD_RELEASE=str(release),
        )
        fixture.wait_for_file(marker, "orphan_nested_writer:marker")
        nested_pid = int(marker.read_text(encoding="utf-8").strip())
        kill_process_group(process, "orphan_nested_writer")
        clean_after_kill = fixture.canonical_clean() and fixture.canonical_head() == fixture.base_sha
        remote_unchanged = fixture.remote_head() == fixture.base_sha
        self.interruption_clean_results.append(clean_after_kill)
        try:
            blocked_result, blocked_report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
            self.record_report(fixture, blocked_report)
            rejected = (
                blocked_result.returncode != 0
                and blocked_report.get("reason") == "concurrent_transaction"
            )
        finally:
            release.write_text("release\n", encoding="utf-8")

        def nested_child_exited() -> bool:
            try:
                os.kill(nested_pid, 0)
            except ProcessLookupError:
                return True
            return False

        wait_until(nested_child_exited, "orphan_nested_writer:child_exit")
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        replayed = (
            result.returncode == 0
            and report.get("status") == "published"
            and report.get("recovery_action") == "stale_staging_replayed"
            and fixture.canonical_head() == fixture.remote_head()
            and fixture.canonical_clean()
        )
        self.reboot_results.append(replayed)
        self.stale_replay_results.append(replayed)
        self.duplicate_publish_commit_count += max(0, fixture.remote_commit_count() - 1)
        self.add_case(
            "orphan_nested_writer",
            clean_after_kill and remote_unchanged and rejected and replayed,
            str(blocked_report.get("status")),
            str(blocked_report.get("reason")),
        )
        return rejected

    def run_dirty_canonical(self) -> bool:
        fixture = self.archive("dirty-canonical")
        (fixture.canonical / "baseline.txt").write_text("intentionally dirty\n", encoding="utf-8")
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        rejected = (
            result.returncode != 0
            and report.get("reason") == "dirty_canonical"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.remote_head() == fixture.base_sha
        )
        self.add_case("dirty_canonical", rejected, str(report.get("status")), str(report.get("reason")))
        return rejected

    def run_malformed_state(self) -> bool:
        fixture = self.archive("malformed-state")
        fixture.state.mkdir(mode=0o700)
        (fixture.state / "transaction.json").write_text("{malformed", encoding="utf-8")
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        rejected = (
            result.returncode != 0
            and report.get("reason") == "malformed_state"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.remote_head() == fixture.base_sha
        )
        self.add_case("malformed_state", rejected, str(report.get("status")), str(report.get("reason")))
        return rejected

    def run_unsafe_staging(self) -> bool:
        fixture = self.archive("unsafe-staging")
        fixture.state.mkdir(mode=0o700)
        outside = fixture.root / "outside"
        outside.mkdir()
        sentinel = outside / "preserve.txt"
        sentinel.write_text("preserve\n", encoding="utf-8")
        (fixture.state / "staging").symlink_to(outside, target_is_directory=True)
        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        rejected = (
            result.returncode != 0
            and report.get("reason") == "unsafe_staging"
            and sentinel.read_text(encoding="utf-8") == "preserve\n"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.remote_head() == fixture.base_sha
        )
        self.add_case("unsafe_staging_path", rejected, str(report.get("status")), str(report.get("reason")))
        return rejected

    def run_remote_race(self) -> bool:
        fixture = self.archive("remote-race")
        release = fixture.root / "sync-release"
        process = fixture.start(
            SYNTHETIC_TRANSACTION_MODE="change",
            MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE="sync_live",
            MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE=str(release),
        )
        fixture.wait_for_phase("sync_live", "remote_race:phase")

        racer = fixture.root / "racer"
        git(fixture.root, "clone", "--quiet", str(fixture.remote), str(racer))
        git(racer, "config", "user.email", "racer@example.invalid")
        git(racer, "config", "user.name", "Synthetic Remote Racer")
        (racer / "remote-race.txt").write_text("synthetic remote race\n", encoding="utf-8")
        git(racer, "add", "remote-race.txt")
        git(racer, "commit", "-m", "Synthetic competing publication")
        git(racer, "push", "origin", "main")
        release.write_text("release\n", encoding="utf-8")

        result, report = finish_process(process, "remote_race")
        self.record_report(fixture, report)
        rejected = (
            result.returncode != 0
            and report.get("reason") == "remote_race"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.canonical_tracking_head() == fixture.base_sha
            and fixture.canonical_clean()
        )
        self.canonical_unverified_mutation_count += int(
            fixture.canonical_head() != fixture.base_sha
            or fixture.canonical_tracking_head() != fixture.base_sha
        )
        self.add_case("remote_race", rejected, str(report.get("status")), str(report.get("reason")))
        return rejected

    def run_unreceipted_remote_advance(self) -> bool:
        fixture = self.archive("unreceipted-remote-advance")
        racer = fixture.root / "racer"
        git(fixture.root, "clone", "--quiet", str(fixture.remote), str(racer))
        git(racer, "config", "user.email", "racer@example.invalid")
        git(racer, "config", "user.name", "Synthetic Remote Racer")
        (racer / "unreceipted.txt").write_text("synthetic unreceipted remote advance\n", encoding="utf-8")
        git(racer, "add", "unreceipted.txt")
        git(racer, "commit", "-m", "Synthetic unreceipted remote advance")
        git(racer, "push", "origin", "main")

        result, report = fixture.invoke(SYNTHETIC_TRANSACTION_MODE="change")
        self.record_report(fixture, report)
        rejected = (
            result.returncode != 0
            and report.get("reason") == "canonical_remote_mismatch"
            and fixture.canonical_head() == fixture.base_sha
            and fixture.canonical_tracking_head() == fixture.base_sha
            and fixture.canonical_clean()
        )
        self.canonical_unverified_mutation_count += int(
            fixture.canonical_head() != fixture.base_sha
            or fixture.canonical_tracking_head() != fixture.base_sha
        )
        self.add_case(
            "unreceipted_remote_advance",
            rejected,
            str(report.get("status")),
            str(report.get("reason")),
        )
        return rejected

    @staticmethod
    def rate(values: list[bool]) -> float:
        return sum(values) / len(values) if values else 0.0

    def run(self) -> dict[str, object]:
        clean_publish = self.run_clean_publish()
        no_op = self.run_no_op()
        self.run_kill_during_update()
        receipted_remote_advance_replayed = self.run_interrupted_update_receipted_remote_advance()
        self.run_kill_before_push()
        post_push_reconciled = self.run_kill_after_push()
        canonical_fast_forward_recovered = self.run_kill_during_canonical_fast_forward()
        (
            concurrent_rejected,
            repository_scoped_lock_rejected,
            git_common_dir_lock_rejected,
        ) = self.run_concurrent()
        nested_writer_rejected = self.run_orphan_nested_writer()
        dirty_rejected = self.run_dirty_canonical()
        malformed_rejected = self.run_malformed_state()
        unsafe_rejected = self.run_unsafe_staging()
        remote_race_rejected = self.run_remote_race()
        unreceipted_remote_rejected = self.run_unreceipted_remote_advance()

        deployed_tool_mutations = sum(fixture.tool_mutation_count() for fixture in self.fixtures)
        raw_source_copies = sum(fixture.raw_source_copy_count() for fixture in self.fixtures)
        metrics: dict[str, int | float] = {
            "transaction_case_count": len(self.cases),
            "clean_publish_accuracy": float(clean_publish),
            "no_op_decision_accuracy": float(no_op),
            "reboot_replay_success_rate": self.rate(self.reboot_results),
            "canonical_clean_after_interruption_rate": self.rate(self.interruption_clean_results),
            "stale_staging_recovery_rate": self.rate(self.stale_replay_results),
            "post_push_receipt_reconciliation_rate": float(post_push_reconciled),
            "concurrent_transaction_rejection_rate": float(concurrent_rejected),
            "dirty_canonical_rejection_rate": float(dirty_rejected),
            "malformed_state_rejection_rate": float(malformed_rejected),
            "unsafe_state_path_rejection_rate": float(unsafe_rejected),
            "remote_race_rejection_rate": float(remote_race_rejected),
            "repository_scoped_lock_rejection_rate": float(repository_scoped_lock_rejected),
            "git_common_dir_lock_rejection_rate": float(git_common_dir_lock_rejected),
            "nested_writer_lock_rejection_rate": float(nested_writer_rejected),
            "canonical_fast_forward_recovery_rate": float(canonical_fast_forward_recovered),
            "unreceipted_remote_rejection_rate": float(unreceipted_remote_rejected),
            "receipted_remote_advance_replay_rate": float(receipted_remote_advance_replayed),
            "receipted_remote_tracked_overlap_count": self.receipted_remote_tracked_overlap_count,
            "receipted_remote_untracked_overlap_count": self.receipted_remote_untracked_overlap_count,
            "partial_remote_publish_count": self.partial_remote_publish_count,
            "duplicate_publish_commit_count": self.duplicate_publish_commit_count,
            "canonical_unverified_mutation_count": self.canonical_unverified_mutation_count,
            "deployed_v238_tool_mutation_count": deployed_tool_mutations,
            "raw_source_copy_count": raw_source_copies,
            "privacy_leak_count": self.privacy_leak_count,
        }
        required_one = (
            "clean_publish_accuracy",
            "no_op_decision_accuracy",
            "reboot_replay_success_rate",
            "canonical_clean_after_interruption_rate",
            "stale_staging_recovery_rate",
            "post_push_receipt_reconciliation_rate",
            "concurrent_transaction_rejection_rate",
            "dirty_canonical_rejection_rate",
            "malformed_state_rejection_rate",
            "unsafe_state_path_rejection_rate",
            "remote_race_rejection_rate",
            "repository_scoped_lock_rejection_rate",
            "git_common_dir_lock_rejection_rate",
            "nested_writer_lock_rejection_rate",
            "canonical_fast_forward_recovery_rate",
            "unreceipted_remote_rejection_rate",
            "receipted_remote_advance_replay_rate",
        )
        required_zero = (
            "partial_remote_publish_count",
            "duplicate_publish_commit_count",
            "canonical_unverified_mutation_count",
            "deployed_v238_tool_mutation_count",
            "raw_source_copy_count",
            "privacy_leak_count",
        )
        passed = (
            metrics["transaction_case_count"] == 16
            and metrics["receipted_remote_tracked_overlap_count"] >= 1
            and metrics["receipted_remote_untracked_overlap_count"] >= 1
            and all(metrics[name] == 1.0 for name in required_one)
            and all(metrics[name] == 0 for name in required_zero)
        )
        return {
            "report_kind": REPORT_KIND,
            "report_version": REPORT_VERSION,
            "status": "passed" if passed else "failed",
            "cases": self.cases,
            "metrics": metrics,
            "privacy": {
                "aggregate_only": True,
                "raw_source_committed": False,
                "private_archive_used": False,
            },
            "claim_boundary": {
                "proves": (
                    "synthetic single-host Git transaction replay, repository-scoped serialization, "
                    "nested-writer exclusion, receipted remote-advance staging replay, and verified receipt handling"
                ),
                "does_not_prove": [
                    "scheduler or host uptime",
                    "distributed locking",
                    "network or GitHub availability",
                    "memory, retrieval, ranking, or answer quality",
                    "V2.39 or V2.40 deployment readiness",
                ],
            },
        }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="scheduled-reboot-replay-") as tmpdir:
            report = ReplayGate(Path(tmpdir)).run()
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": REPORT_VERSION,
            "status": "failed",
            "failure": {"stage": exc.stage, "reason": exc.reason},
            "privacy": {"aggregate_only": True},
        }
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
