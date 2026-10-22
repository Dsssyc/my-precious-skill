import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path("skills/update-my-precious/scripts/run_scheduled_memory_transaction.py").resolve()


def load_module():
    spec = importlib.util.spec_from_file_location("scheduled_memory_transaction_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=repo)


def setup_archive(root: Path) -> tuple[Path, Path, Path]:
    remote = root / "remote.git"
    canonical = root / "canonical"
    source = root / "source"
    remote.mkdir()
    canonical.mkdir()
    source.mkdir()
    assert git(remote, "init", "--bare", "--initial-branch=main").returncode == 0
    assert git(canonical, "init", "--initial-branch=main").returncode == 0
    assert git(canonical, "config", "user.email", "synthetic@example.invalid").returncode == 0
    assert git(canonical, "config", "user.name", "Synthetic Transaction").returncode == 0
    (canonical / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    assert git(canonical, "add", "baseline.txt").returncode == 0
    assert git(canonical, "commit", "-m", "Synthetic baseline").returncode == 0
    assert git(canonical, "remote", "add", "origin", str(remote)).returncode == 0
    assert git(canonical, "push", "-u", "origin", "main").returncode == 0
    return canonical, source, remote


def invoke(
    canonical: Path,
    source: Path,
    state: Path,
    *,
    env: dict[str, str] | None = None,
    push: bool = True,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = run(
        [
            sys.executable,
            str(SCRIPT),
            "--memory-repo",
            str(canonical),
            "--source-dir",
            str(source),
            "--state-dir",
            str(state),
            *(["--push"] if push else []),
        ],
        cwd=canonical,
        env=env,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"expected one JSON line, got stdout={result.stdout!r} stderr={result.stderr!r}")
    return result, json.loads(lines[0])


def install_synthetic_runtime(canonical: Path, *, real_sync: bool = False) -> None:
    tools = canonical / "tools"
    tools.mkdir()
    (tools / "run_memory_updates.py").write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
mode = os.environ.get('SYNTHETIC_TRANSACTION_MODE', 'change')
if mode == 'update_fail':
    raise SystemExit(7)
if mode == 'structured_update_fail':
    print(json.dumps({
        'report_kind': 'memory_update_batch_report',
        'report_version': 1,
        'status': 'blocked',
        'reason': 'child_failure_unclassified',
        'failure_stage': 'project_update',
        'source_batch_complete': False,
        'metrics': {
            'records_deferred_count': 0,
            'targets_deferred_count': 0,
            'child_failure_count': 1,
            'inventory_worker_count': 1,
            'projects_updated_count': 0,
            'source_streams_updated_count': 0,
            'archive_finalization_count': 0,
        },
        'privacy': {
            'aggregate_only': True,
            'paths_rendered': False,
            'source_content_rendered': False,
            'child_output_rendered': False,
        },
    }, sort_keys=True, separators=(',', ':')))
    raise SystemExit(7)
if mode not in {'noop', 'deferred_noop'}:
    value = 'needs-repair\\n' if mode == 'repair' else 'updated\\n'
    (repo / 'INDEX.md').write_text(value, encoding='utf-8')
deferred = 1 if mode in {'deferred_noop', 'deferred_change'} else 0
if '--report-json' in args:
    print(json.dumps({
        'report_kind': 'memory_update_batch_report',
        'report_version': 1,
        'status': 'deferred' if deferred else 'updated',
        'reason': 'source_records_deferred' if deferred else 'updated',
        'failure_stage': 'none',
        'source_batch_complete': not deferred,
        'metrics': {
            'records_deferred_count': deferred,
            'targets_deferred_count': deferred,
            'child_failure_count': 0,
            'inventory_worker_count': 1,
            'projects_updated_count': 1,
            'source_streams_updated_count': 0,
            'archive_finalization_count': 1,
        },
        'privacy': {
            'aggregate_only': True,
            'paths_rendered': False,
            'source_content_rendered': False,
            'child_output_rendered': False,
        },
    }, sort_keys=True, separators=(',', ':')))
marker = os.environ.get('SYNTHETIC_UPDATE_STARTED')
if marker:
    Path(marker).write_text('started\\n', encoding='utf-8')
    release = Path(os.environ['SYNTHETIC_UPDATE_RELEASE'])
    while not release.exists():
        time.sleep(0.02)
""",
        encoding="utf-8",
    )
    (tools / "audit_memory_archive.py").write_text(
        """import os
import sys
from pathlib import Path
args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
index = repo / 'INDEX.md'
always_fail = bool(os.environ.get('SYNTHETIC_AUDIT_FAIL'))
repairable_fail = bool(os.environ.get('SYNTHETIC_AUDIT_REPAIRABLE')) and index.exists() and index.read_text(encoding='utf-8') == 'needs-repair\\n'
raise SystemExit(1 if always_fail or repairable_fail else 0)
""",
        encoding="utf-8",
    )
    (tools / "audit_publish_readiness.py").write_text(
        """import sys
from pathlib import Path
args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
index = repo / 'INDEX.md'
raise SystemExit(1 if index.exists() and index.read_text(encoding='utf-8') == 'needs-repair\\n' else 0)
""",
        encoding="utf-8",
    )
    (tools / "repair_publish_surfaces.py").write_text(
        """import sys
from pathlib import Path
args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
(repo / 'INDEX.md').write_text('repaired\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    (tools / "search_memory.py").write_text(
        "import sys\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    (tools / "sync_memory_archive.py").write_text(
        """#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1]) if '--memory-repo' in args else Path.cwd()
status = subprocess.run(
    ['git', 'status', '--porcelain=v1', '--untracked-files=all'],
    cwd=repo,
    text=True,
    stdout=subprocess.PIPE,
    check=True,
).stdout
if '--dry-run' in args:
    print('Would commit: synthetic' if status else 'No memory archive changes to sync.')
    raise SystemExit(0)
if os.environ.get('SYNTHETIC_SYNC_MODE') == 'live_noop':
    print('No memory archive changes to sync.')
    raise SystemExit(0)
subprocess.run(['git', 'add', '--', 'INDEX.md'], cwd=repo, check=True)
staged = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=repo)
if staged.returncode == 0:
    print('No memory archive changes to sync.')
    raise SystemExit(0)
subprocess.run(['git', 'commit', '-m', 'Synthetic memory update'], cwd=repo, check=True)
marker = os.environ.get('SYNTHETIC_BEFORE_PUSH')
if marker:
    Path(marker).write_text('ready\\n', encoding='utf-8')
    release = Path(os.environ['SYNTHETIC_PUSH_RELEASE'])
    while not release.exists():
        time.sleep(0.02)
if '--push' in args:
    subprocess.run(['git', 'push'], cwd=repo, check=True)
""",
        encoding="utf-8",
    )
    if real_sync:
        (tools / "sync_memory_archive.py").write_bytes(
            Path("templates/agent-memory-repo/tools/sync_memory_archive.py").read_bytes()
        )
        (tools / "update_memory_archive.py").write_text("# Synthetic resolver marker.\n", encoding="utf-8")
    assert git(canonical, "add", "tools").returncode == 0
    assert git(canonical, "commit", "-m", "Install synthetic runtime").returncode == 0
    assert git(canonical, "push").returncode == 0


def interrupt_at_canonical_fast_forward(
    canonical: Path,
    source: Path,
    state: Path,
    root: Path,
) -> dict[str, object]:
    release = root / "canonical-release"
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--memory-repo",
            str(canonical),
            "--source-dir",
            str(source),
            "--state-dir",
            str(state),
            "--push",
        ],
        cwd=canonical,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "SYNTHETIC_TRANSACTION_MODE": "change",
            "MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE": "canonical_fast_forward",
            "MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE": str(release),
        },
        start_new_session=True,
    )
    state_file = state / "transaction.json"
    deadline = time.monotonic() + 10.0
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.02)
            continue
        if payload.get("phase") == "canonical_fast_forward":
            break
        time.sleep(0.02)
    if payload.get("phase") != "canonical_fast_forward":
        process.kill()
        process.communicate()
        raise AssertionError("transaction did not reach canonical_fast_forward")
    os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=10)
    return payload


def interrupt_at_completed_deferred_no_publish(
    canonical: Path,
    source: Path,
    state: Path,
    root: Path,
) -> dict[str, object]:
    release = root / "complete-release"
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--memory-repo",
            str(canonical),
            "--source-dir",
            str(source),
            "--state-dir",
            str(state),
            "--push",
        ],
        cwd=canonical,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "SYNTHETIC_TRANSACTION_MODE": "deferred_noop",
            "MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE": "complete",
            "MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE": str(release),
        },
        start_new_session=True,
    )
    state_file = state / "transaction.json"
    deadline = time.monotonic() + 10.0
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.02)
            continue
        if payload.get("phase") == "complete":
            break
        time.sleep(0.02)
    if payload.get("phase") != "complete":
        process.kill()
        process.communicate()
        raise AssertionError("transaction did not reach complete no-publish state")
    os.killpg(process.pid, signal.SIGKILL)
    process.communicate(timeout=10)
    return payload


class ScheduledCandidateReliabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.canonical, self.source, self.remote = setup_archive(self.root)
        install_synthetic_runtime(self.canonical, real_sync=True)
        self.state = self.root / "state"
        self.base = git(self.canonical, "rev-parse", "HEAD").stdout.strip()
        self.module = load_module()

    def arguments(self, *, push=True):
        return self.module.parse_args([
            "--memory-repo", str(self.canonical),
            "--source-dir", str(self.source),
            "--state-dir", str(self.state),
            *(["--push"] if push else []),
        ])

    def seed_candidate(self, *, explicit=False, relative="INDEX.md", content="computed once\n"):
        module = self.module
        state = module.prepare_state_dir(self.state)
        remote_url = module.canonical_remote_url(self.canonical)
        repository = module.path_fingerprint(self.canonical)
        remote = module.remote_fingerprint(remote_url, self.canonical)
        staging, _ = module.prepare_staging(self.canonical, state, remote_url, repository, remote)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.assertEqual(git(staging, "add", "--", relative).returncode, 0)
        self.assertEqual(git(staging, "commit", "-m", "Synthetic retained candidate").returncode, 0)
        candidate = git(staging, "rev-parse", "HEAD").stdout.strip()
        module.write_state(
            state, repository_fingerprint=repository, expected_remote_fingerprint=remote,
            base_sha=self.base, phase="sync_live", candidate_sha=candidate if explicit else None,
            source_record_deferred_count=1, source_target_deferred_count=1,
            source_batch_complete=False,
        )
        return staging, candidate

    def remote_head(self):
        return git(self.remote, "rev-parse", "refs/heads/main").stdout.strip()

    def test_failed_push_persists_candidate_then_resumes_same_sha_without_update_or_commit(self):
        reject = self.remote / "hooks" / "pre-receive"
        reject.write_text("#!/bin/sh\necho 'synthetic rejection' >&2\nexit 1\n", encoding="utf-8")
        reject.chmod(0o700)
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["status"], "blocked")
        staging = self.state / "staging"
        candidate = git(staging, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(candidate, self.base)
        state = json.loads((self.state / "transaction.json").read_text(encoding="utf-8"))
        self.assertEqual(state.get("candidate_sha"), candidate)
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(git(staging, "status", "--porcelain=v1").stdout, "")
        reject.unlink()
        with mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            recovered = self.module.execute(self.arguments())
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(self.remote_head(), candidate)
        self.assertEqual(git(self.canonical, "rev-parse", "HEAD").stdout.strip(), candidate)
        self.assertFalse(any(call.args[1] in {"run_memory_updates.py", "repair_publish_surfaces.py"}
                             for call in tools.call_args_list))
        self.assertTrue(all("--dry-run" in call.args for call in tools.call_args_list
                            if call.args[1] == "sync_memory_archive.py"))

    def test_legacy_sync_live_candidate_migrates_and_publishes_without_recommit(self):
        staging, candidate = self.seed_candidate()
        index = (staging / ".git" / "index").read_bytes()
        with mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            recovered = self.module.execute(self.arguments())
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(self.remote_head(), candidate)
        self.assertEqual(git(staging, "rev-parse", "HEAD").stdout.strip(), candidate)
        self.assertFalse(recovered["source_batch_complete"])
        self.assertEqual(recovered["metrics"]["source_record_deferred_count"], 1)
        self.assertEqual((staging / ".git" / "index").read_bytes(), index)
        self.assertFalse(any(call.args[1] in {"run_memory_updates.py", "repair_publish_surfaces.py"}
                             for call in tools.call_args_list))

    def test_legacy_candidate_without_push_authorization_is_preserved(self):
        staging, candidate = self.seed_candidate()
        result, report = invoke(self.canonical, self.source, self.state, push=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "push_not_requested")
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(git(staging, "rev-parse", "HEAD").stdout.strip(), candidate)

    def assert_preserved(self, staging, candidate):
        self.assertEqual(git(staging, "rev-parse", "HEAD").stdout.strip(), candidate)
        self.assertEqual(git(self.canonical, "rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(git(self.canonical, "rev-parse", "origin/main").stdout.strip(), self.base)
        self.assertTrue((self.state / "transaction.json").is_file())

    def test_commit_handoff_persists_sha_before_one_exact_leased_push(self):
        original = self.module.run_git
        pushes = []

        def checked_git(repo, *arguments, **kwargs):
            if arguments[0] == "push":
                state = json.loads((self.state / "transaction.json").read_text(encoding="utf-8"))
                candidate = git(repo, "rev-parse", "HEAD").stdout.strip()
                self.assertEqual(state["phase"], "sync_live")
                self.assertEqual(state["candidate_sha"], candidate)
                self.assertEqual(arguments, (
                    "push", "--porcelain", "--no-follow-tags",
                    f"--force-with-lease=refs/heads/main:{self.base}",
                    "origin", f"{candidate}:refs/heads/main",
                ))
                pushes.append(candidate)
            return original(repo, *arguments, **kwargs)

        with mock.patch.object(self.module, "run_git", side_effect=checked_git), \
                mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            report = self.module.execute(self.arguments())
        self.assertEqual(report["status"], "published")
        self.assertEqual(pushes, [self.remote_head()])
        sync_calls = [call for call in tools.call_args_list if call.args[1] == "sync_memory_archive.py"]
        self.assertTrue(sync_calls)
        self.assertTrue(all("--push" not in call.args for call in sync_calls))
        self.assertEqual(sum("--dry-run" not in call.args for call in sync_calls), 1)

    def test_accepted_push_with_nonzero_exit_uses_receipt_without_second_push(self):
        original = self.module.run_git
        pushes = []

        def accepted_nonzero(repo, *arguments, **kwargs):
            result = original(repo, *arguments, **kwargs)
            if arguments[0] == "push":
                self.assertEqual(result.returncode, 0)
                pushes.append(arguments[-1])
                return subprocess.CompletedProcess(result.args, 23, result.stdout, "connection reset synthetic-secret")
            return result

        with mock.patch.object(self.module, "run_git", side_effect=accepted_nonzero):
            report = self.module.execute(self.arguments())
        self.assertEqual(report["status"], "published")
        self.assertEqual(len(pushes), 1)
        self.assertEqual(git(self.canonical, "rev-parse", "HEAD").stdout.strip(), self.remote_head())
        diagnostic = report["sync_diagnostics"]
        self.assertEqual(diagnostic["remote_observation"], "candidate")
        self.assertEqual(diagnostic["primary_failure"]["exit_code"], 23)
        self.assertEqual(diagnostic["primary_failure"]["operation"], "sync_push")
        self.assertNotIn("synthetic-secret", json.dumps(report))

    def test_failed_remote_requery_keeps_primary_diagnostic_then_recovers_receipt_only(self):
        original_git = self.module.run_git
        original_remote = self.module.remote_main_head
        pushed = False
        private_diagnostic = "connection reset https://synthetic.invalid/private?token=synthetic-secret /private/source"

        def accepted_nonzero(repo, *arguments, **kwargs):
            nonlocal pushed
            result = original_git(repo, *arguments, **kwargs)
            if arguments[0] == "push":
                self.assertEqual(result.returncode, 0)
                pushed = True
                return subprocess.CompletedProcess(result.args, 31, result.stdout, private_diagnostic)
            return result

        def unavailable_after_push(*args, **kwargs):
            if pushed:
                raise self.module.TransactionBlocked("remote_receipt_failed")
            return original_remote(*args, **kwargs)

        output = io.StringIO()
        argv = ["--memory-repo", str(self.canonical), "--source-dir", str(self.source),
                "--state-dir", str(self.state), "--push"]
        with mock.patch.object(self.module, "run_git", side_effect=accepted_nonzero), \
                mock.patch.object(self.module, "remote_main_head", side_effect=unavailable_after_push), \
                mock.patch("sys.stdout", output):
            exit_code = self.module.main(argv)
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["reason"], "sync_live_failed")
        self.assertEqual(report["failure_stage"], "sync_live")
        diagnostic = report["sync_diagnostics"]
        self.assertEqual(set(diagnostic), {"report_kind", "report_version", "primary_failure", "remote_observation"})
        self.assertEqual(diagnostic["report_kind"], "scheduled_memory_transaction_sync_diagnostics")
        self.assertEqual(diagnostic["report_version"], 1)
        self.assertEqual(diagnostic["remote_observation"], "unavailable")
        primary = diagnostic["primary_failure"]
        self.assertEqual(set(primary), {"operation", "exit_code", "duration_ms", "error_category"})
        self.assertEqual(primary["exit_code"], 31)
        self.assertEqual(primary["operation"], "sync_push")
        self.assertEqual(primary["error_category"], "network")
        self.assertIsInstance(primary["duration_ms"], int)
        self.assertGreaterEqual(primary["duration_ms"], 0)
        for forbidden in (str(self.root), "synthetic-secret", "https://", "/private/source"):
            self.assertNotIn(forbidden, output.getvalue())
        state = json.loads((self.state / "transaction.json").read_text(encoding="utf-8"))
        candidate = self.remote_head()
        self.assertEqual(state["candidate_sha"], candidate)
        self.assert_preserved(self.state / "staging", candidate)
        with mock.patch.object(self.module, "run_git", wraps=original_git) as commands, \
                mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            recovered = self.module.execute(self.arguments(push=False))
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(recovered["recovery_action"], "post_push_reconciled")
        self.assertEqual(recovered["metrics"]["remote_publish_count"], 0)
        self.assertFalse(any(call.args[1] == "push" for call in commands.call_args_list))
        self.assertFalse(any(call.args[1] in {"run_memory_updates.py", "repair_publish_surfaces.py"}
                             for call in tools.call_args_list))
        self.assertTrue(all("--dry-run" in call.args for call in tools.call_args_list
                            if call.args[1] == "sync_memory_archive.py"))

    def test_nonzero_commit_child_retains_candidate_and_primary_on_query_failure(self):
        original_tool = self.module.run_python_tool
        original_remote = self.module.remote_main_head
        failed_commit = False

        def failed_after_commit(staging, name, *arguments, **kwargs):
            nonlocal failed_commit
            result = original_tool(staging, name, *arguments, **kwargs)
            if name == "sync_memory_archive.py" and "--dry-run" not in arguments:
                self.assertEqual(result.returncode, 0)
                failed_commit = True
                return subprocess.CompletedProcess(result.args, 19, result.stdout, "authentication failed synthetic-secret")
            return result

        def unavailable_after_commit(*args, **kwargs):
            if failed_commit:
                raise self.module.TransactionBlocked("remote_receipt_failed")
            return original_remote(*args, **kwargs)

        with mock.patch.object(self.module, "run_python_tool", side_effect=failed_after_commit), \
                mock.patch.object(self.module, "remote_main_head", side_effect=unavailable_after_commit):
            with self.assertRaises(self.module.TransactionBlocked) as blocked:
                self.module.execute(self.arguments())
        self.assertEqual(blocked.exception.reason, "sync_live_failed")
        primary = blocked.exception.diagnostics["primary_failure"]
        self.assertEqual(primary["operation"], "sync_commit")
        self.assertEqual(primary["exit_code"], 19)
        self.assertEqual(primary["error_category"], "auth")
        self.assertEqual(blocked.exception.diagnostics["remote_observation"], "unavailable")
        self.assertEqual(self.remote_head(), self.base)
        candidate = git(self.state / "staging", "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(json.loads((self.state / "transaction.json").read_text())["candidate_sha"], candidate)
        with mock.patch.object(self.module, "run_python_tool", wraps=original_tool) as tools:
            report = self.module.execute(self.arguments())
        self.assertEqual(report["status"], "published")
        self.assertEqual(self.remote_head(), candidate)
        self.assertFalse(any(call.args[1] == "run_memory_updates.py" for call in tools.call_args_list))

    def test_dirty_candidate_is_blocked_without_touching_index_or_worktree(self):
        staging, candidate = self.seed_candidate(explicit=True)
        for kind in ("unstaged", "staged", "untracked"):
            with self.subTest(kind=kind):
                target = staging / ("sentinel.txt" if kind == "untracked" else "INDEX.md")
                target.write_text("preserve this edit\n", encoding="utf-8")
                if kind == "staged":
                    self.assertEqual(git(staging, "add", "INDEX.md").returncode, 0)
                index = (staging / ".git" / "index").read_bytes()
                result, report = invoke(self.canonical, self.source, self.state)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(report["reason"], "sync_live_candidate_dirty")
                self.assertEqual(target.read_text(), "preserve this edit\n")
                self.assertEqual((staging / ".git" / "index").read_bytes(), index)
                self.assert_preserved(staging, candidate)
                self.assertEqual(self.remote_head(), self.base)
                target.unlink()
                self.assertEqual(git(staging, "reset", "--hard", candidate).returncode, 0)

    def test_unowned_candidate_is_blocked_without_discard(self):
        staging, candidate = self.seed_candidate()
        (self.state / "staging-owner.json").unlink()
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "unsafe_staging")
        self.assert_preserved(staging, candidate)

    def test_candidate_owner_and_state_fingerprints_must_still_match(self):
        staging, candidate = self.seed_candidate(explicit=True)
        for filename, key, reason in (
            ("staging-owner.json", "repository_fingerprint", "unsafe_staging"),
            ("staging-owner.json", "remote_fingerprint", "unsafe_staging"),
            ("transaction.json", "repository_fingerprint", "state_identity_mismatch"),
            ("transaction.json", "remote_fingerprint", "state_identity_mismatch"),
        ):
            with self.subTest(filename=filename, key=key):
                path = self.state / filename
                original = path.read_text()
                payload = json.loads(original)
                payload[key] = "0" * 64
                path.write_text(json.dumps(payload))
                result, report = invoke(self.canonical, self.source, self.state)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(report["reason"], reason)
                self.assert_preserved(staging, candidate)
                path.write_text(original)

    def test_unpublished_candidate_requires_clean_canonical_at_the_recorded_base(self):
        staging, candidate = self.seed_candidate(explicit=True)
        target = self.canonical / "baseline.txt"
        target.write_text("preserve canonical edit\n")
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "dirty_canonical")
        self.assertEqual(target.read_text(), "preserve canonical edit\n")
        self.assert_preserved(staging, candidate)
        self.assertEqual(git(self.canonical, "commit", "-am", "Unexpected local advance").returncode, 0)
        local_head = git(self.canonical, "rev-parse", "HEAD").stdout.strip()
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "canonical_remote_mismatch")
        self.assertEqual(git(staging, "rev-parse", "HEAD").stdout.strip(), candidate)
        self.assertEqual(git(self.canonical, "rev-parse", "HEAD").stdout.strip(), local_head)
        self.assertEqual(self.remote_head(), self.base)

    def test_reviewed_memory_node_policy_requires_explicit_current_option(self):
        staging, candidate = self.seed_candidate(relative="memories/global.jsonl", content="{}\n")
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "sync_dry_run_failed")
        self.assert_preserved(staging, candidate)
        arguments = self.arguments()
        arguments.include_reviewed_memory_nodes = True
        recovered = self.module.execute(arguments)
        self.assertEqual(recovered["status"], "published")
        self.assertEqual(self.remote_head(), candidate)

    def test_candidate_sha_mismatch_and_non_direct_child_are_blocked(self):
        staging, candidate = self.seed_candidate(explicit=True)
        state_path = self.state / "transaction.json"
        state = json.loads(state_path.read_text())
        state["candidate_sha"] = self.base
        state_path.write_text(json.dumps(state))
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "remote_race")
        self.assert_preserved(staging, candidate)
        (staging / "INDEX.md").write_text("second commit\n")
        self.assertEqual(git(staging, "commit", "-am", "Unexpected second candidate").returncode, 0)
        candidate = git(staging, "rev-parse", "HEAD").stdout.strip()
        del state["candidate_sha"]
        state_path.write_text(json.dumps(state))
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "sync_live_candidate_mismatch")
        self.assert_preserved(staging, candidate)

    def test_unexpected_path_candidate_uses_deployed_sync_policy_and_is_retained(self):
        staging, candidate = self.seed_candidate(relative="README.md")
        with mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            with self.assertRaises(self.module.TransactionBlocked) as blocked:
                self.module.execute(self.arguments())
        self.assertEqual(blocked.exception.reason, "sync_dry_run_failed")
        self.assertEqual(blocked.exception.diagnostics["primary_failure"]["error_category"], "policy")
        self.assertTrue(any(call.args[1] == "sync_memory_archive.py" and "--dry-run" in call.args
                            for call in tools.call_args_list))
        self.assert_preserved(staging, candidate)
        self.assertEqual(self.remote_head(), self.base)
        self.assertEqual(json.loads((self.state / "transaction.json").read_text())["candidate_sha"], candidate)

    def test_new_commit_is_pinned_before_post_commit_policy_can_fail(self):
        original = self.module.run_python_tool

        def commit_hook(staging, name, *arguments, **kwargs):
            if name == "sync_memory_archive.py" and "--dry-run" not in arguments:
                hook = staging / ".git" / "hooks" / "pre-commit"
                hook.write_text("#!/bin/sh\nprintf 'outside scope\\n' > README.md\ngit add README.md\n")
                hook.chmod(0o700)
            return original(staging, name, *arguments, **kwargs)

        with mock.patch.object(self.module, "run_python_tool", side_effect=commit_hook):
            with self.assertRaisesRegex(self.module.TransactionBlocked, "sync_dry_run_failed"):
                self.module.execute(self.arguments())
        staging = self.state / "staging"
        candidate = git(staging, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(candidate, self.base)
        state = json.loads((self.state / "transaction.json").read_text())
        self.assertEqual(state["candidate_sha"], candidate)
        self.assert_preserved(staging, candidate)
        self.assertEqual(self.remote_head(), self.base)

    def test_secret_candidate_is_refused_by_deployed_scanner_without_rendering_secret(self):
        secret = "sk-" + "SyntheticSecretValue" * 3
        staging, candidate = self.seed_candidate(content=secret + "\n")
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(report["reason"], "sync_dry_run_failed")
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assert_preserved(staging, candidate)

    def test_candidate_cannot_replace_the_tools_that_validate_it(self):
        staging, candidate = self.seed_candidate(relative="tools/audit_memory_archive.py", content="raise AssertionError('must not execute')\n")
        with mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
            with self.assertRaisesRegex(self.module.TransactionBlocked, "sync_live_candidate_tools_changed"):
                self.module.execute(self.arguments())
        tools.assert_not_called()
        self.assert_preserved(staging, candidate)

    def test_hidden_worktree_tool_edits_cannot_bypass_candidate_validation(self):
        staging, candidate = self.seed_candidate(explicit=True)
        for flag in ("skip-worktree", "assume-unchanged"):
            with self.subTest(flag=flag):
                relative = "tools/sync_memory_archive.py"
                original = (staging / relative).read_bytes()
                self.assertEqual(git(staging, "update-index", f"--{flag}", relative).returncode, 0)
                (staging / relative).write_text("raise AssertionError('must not execute hidden edit')\n")
                self.assertEqual(git(staging, "status", "--porcelain=v1").stdout, "")
                index = (staging / ".git" / "index").read_bytes()
                with mock.patch.object(self.module, "run_python_tool", wraps=self.module.run_python_tool) as tools:
                    with self.assertRaisesRegex(self.module.TransactionBlocked, "sync_live_candidate_dirty"):
                        self.module.execute(self.arguments())
                tools.assert_not_called()
                self.assertEqual((staging / ".git" / "index").read_bytes(), index)
                self.assert_preserved(staging, candidate)
                (staging / relative).write_bytes(original)
                self.assertEqual(git(staging, "update-index", f"--no-{flag}", relative).returncode, 0)

    def test_candidate_origin_and_push_destination_mismatches_fail_closed(self):
        staging, candidate = self.seed_candidate(explicit=True)
        self.assertEqual(git(staging, "remote", "set-url", "origin", str(self.root / "other.git")).returncode, 0)
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertEqual(report["reason"], "unexpected_remote")
        self.assertNotEqual(result.returncode, 0)
        self.assert_preserved(staging, candidate)
        self.assertEqual(git(staging, "remote", "set-url", "origin", str(self.remote)).returncode, 0)
        self.assertEqual(git(staging, "remote", "set-url", "--push", "origin", str(self.root / "other.git")).returncode, 0)
        result, report = invoke(self.canonical, self.source, self.state)
        self.assertEqual(report["reason"], "unexpected_remote")
        self.assertNotEqual(result.returncode, 0)
        self.assert_preserved(staging, candidate)

    def test_remote_race_at_push_is_rejected_by_exact_base_lease_and_retains_candidate(self):
        staging, candidate = self.seed_candidate(explicit=True)
        racer = self.root / "racer"
        self.assertEqual(git(self.root, "clone", str(self.remote), str(racer)).returncode, 0)
        self.assertEqual(git(racer, "config", "user.email", "racer@example.invalid").returncode, 0)
        self.assertEqual(git(racer, "config", "user.name", "Synthetic Racer").returncode, 0)
        (racer / "INDEX.md").write_text("competing publication\n")
        self.assertEqual(git(racer, "add", "INDEX.md").returncode, 0)
        self.assertEqual(git(racer, "commit", "-m", "Competing synthetic publication").returncode, 0)
        original = self.module.run_git
        pushes = []

        def race_at_push(repo, *arguments, **kwargs):
            if arguments[0] == "push":
                pushes.append(arguments)
                self.assertEqual(git(racer, "push", "origin", "main").returncode, 0)
            return original(repo, *arguments, **kwargs)

        with mock.patch.object(self.module, "run_git", side_effect=race_at_push):
            with self.assertRaises(self.module.TransactionBlocked) as blocked:
                self.module.execute(self.arguments())
        self.assertEqual(blocked.exception.reason, "remote_race")
        self.assertEqual(blocked.exception.diagnostics["primary_failure"]["error_category"], "rejected")
        self.assertEqual(blocked.exception.diagnostics["remote_observation"], "other")
        self.assertEqual(len(pushes), 1)
        self.assert_preserved(staging, candidate)

    def test_candidate_readiness_and_search_are_checked_again_without_repair(self):
        staging, candidate = self.seed_candidate()
        original = self.module.run_python_tool
        for failing_tool, reason in (("audit_memory_archive.py", "archive_audit_failed"),
                                     ("audit_publish_readiness.py", "publish_readiness_failed"),
                                     ("search_memory.py", "search_health_failed")):
            with self.subTest(tool=failing_tool):
                def reject_tool(repo, name, *arguments, **kwargs):
                    if name == failing_tool:
                        return subprocess.CompletedProcess([name], 1, "", "synthetic failure")
                    return original(repo, name, *arguments, **kwargs)

                with mock.patch.object(self.module, "run_python_tool", side_effect=reject_tool) as tools:
                    with self.assertRaises(self.module.TransactionBlocked) as blocked:
                        self.module.execute(self.arguments())
                self.assertEqual(blocked.exception.reason, reason)
                self.assertFalse(any(call.args[1] == "repair_publish_surfaces.py" for call in tools.call_args_list))
                self.assert_preserved(staging, candidate)


class ScheduledPowerAssertionTests(unittest.TestCase):
    def test_darwin_assertion_uses_parent_pid_without_lock_inheritance_and_releases(self):
        module = load_module()
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(module.sys, "platform", "darwin"), \
                mock.patch.object(module.os, "access", return_value=True), \
                mock.patch.object(module, "_ACTIVE_TRANSACTION_LOCK_FD", 123), \
                mock.patch.object(module.subprocess, "Popen", return_value=process) as popen:
            with module.ScopedPowerAssertion():
                process.terminate.assert_not_called()
        self.assertEqual(popen.call_args.args[0], ["/usr/bin/caffeinate", "-i", "-s", "-w", str(os.getpid())])
        self.assertTrue(popen.call_args.kwargs["close_fds"])
        self.assertNotIn("pass_fds", popen.call_args.kwargs)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_assertion_releases_on_exception_or_interruption(self):
        for error in (RuntimeError, KeyboardInterrupt):
            with self.subTest(error=error.__name__):
                module = load_module()
                process = mock.Mock()
                process.poll.return_value = None
                with mock.patch.object(module.sys, "platform", "darwin"), \
                        mock.patch.object(module.os, "access", return_value=True), \
                        mock.patch.object(module.subprocess, "Popen", return_value=process):
                    with self.assertRaises(error):
                        with module.ScopedPowerAssertion():
                            raise error()
                process.terminate.assert_called_once()
                process.wait.assert_called_once()

    def test_other_platform_missing_tool_or_disabled_assertion_does_not_launch(self):
        for platform, available, enabled in (("linux", True, True), ("win32", True, True),
                                              ("darwin", False, True), ("darwin", True, False)):
            with self.subTest(platform=platform, available=available, enabled=enabled):
                module = load_module()
                with mock.patch.object(module.sys, "platform", platform), \
                        mock.patch.object(module.os, "access", return_value=available), \
                        mock.patch.object(module.subprocess, "Popen") as popen:
                    with module.ScopedPowerAssertion(enabled=enabled):
                        pass
                popen.assert_not_called()

    def test_unavailable_assertion_can_never_block_transaction_and_exit_reaps_it(self):
        module = load_module()
        with mock.patch.object(module.sys, "platform", "darwin"), \
                mock.patch.object(module.os, "access", return_value=True), \
                mock.patch.object(module.subprocess, "Popen", side_effect=OSError):
            with module.ScopedPowerAssertion():
                pass
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("caffeinate", 5), 0]
        with mock.patch.object(module.sys, "platform", "darwin"), \
                mock.patch.object(module.os, "access", return_value=True), \
                mock.patch.object(module.subprocess, "Popen", return_value=process):
            with module.ScopedPowerAssertion():
                pass
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)


class ScheduledMemoryTransactionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "transaction interruption test requires POSIX signals")
    def test_interrupted_update_replays_after_receipted_remote_advance_with_overlaps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            marker = root / "update-started"
            release = root / "update-release"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(canonical),
                    "--source-dir",
                    str(source),
                    "--state-dir",
                    str(state),
                    "--push",
                ],
                cwd=canonical,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "change",
                    "SYNTHETIC_UPDATE_STARTED": str(marker),
                    "SYNTHETIC_UPDATE_RELEASE": str(release),
                },
                start_new_session=True,
            )
            deadline = time.monotonic() + 10.0
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)

            transaction = json.loads((state / "transaction.json").read_text(encoding="utf-8"))
            self.assertEqual(transaction["phase"], "updating")
            self.assertNotIn("candidate_sha", transaction)
            staging = state / "staging"
            (staging / "baseline.txt").write_text("stale tracked update\n", encoding="utf-8")
            staging_status = git(staging, "status", "--porcelain=v1", "--untracked-files=all").stdout
            self.assertIn("baseline.txt", staging_status)
            self.assertIn("?? INDEX.md", staging_status)

            racer = root / "racer"
            self.assertEqual(git(root, "clone", str(remote), str(racer)).returncode, 0)
            self.assertEqual(git(racer, "config", "user.email", "racer@example.invalid").returncode, 0)
            self.assertEqual(git(racer, "config", "user.name", "Synthetic Remote Receipt").returncode, 0)
            (racer / "baseline.txt").write_text("receipted tracked update\n", encoding="utf-8")
            (racer / "INDEX.md").write_text("receipted untracked update\n", encoding="utf-8")
            self.assertEqual(git(racer, "add", "baseline.txt", "INDEX.md").returncode, 0)
            self.assertEqual(git(racer, "commit", "-m", "Synthetic receipted remote advance").returncode, 0)
            self.assertEqual(git(racer, "push", "origin", "main").returncode, 0)
            remote_head = git(remote, "rev-parse", "main").stdout.strip()

            self.assertEqual(git(canonical, "fetch", "origin", "main").returncode, 0)
            self.assertEqual(git(canonical, "merge", "--ff-only", "origin/main").returncode, 0)
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), remote_head)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

            replay, replay_report = invoke(
                canonical,
                source,
                state,
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "noop"},
            )

            self.assertEqual(replay_report["reason"], "no_op_current")
            self.assertEqual(replay.returncode, 0)
            self.assertEqual(replay_report["status"], "no_op_current")
            self.assertEqual(replay_report["recovery_action"], "stale_staging_replayed")
            self.assertEqual(replay_report["metrics"]["recovery_count"], 1)
            self.assertEqual(replay_report["metrics"]["remote_publish_count"], 0)
            self.assertEqual(replay_report["metrics"]["canonical_mutation_count"], 0)
            self.assertFalse((state / "transaction.json").exists())
            self.assertEqual(git(staging, "rev-parse", "HEAD").stdout.strip(), remote_head)
            self.assertEqual(git(staging, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")
            self.assertEqual(git(remote, "rev-list", "--count", f"{transaction['base_sha']}..main").stdout.strip(), "1")

    @unittest.skipUnless(os.name == "posix", "parent-only SIGKILL test requires POSIX signals")
    def test_parent_sigkill_leaves_child_holding_transaction_lock_until_replay_is_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            marker = root / "update-started"
            release = root / "update-release"
            command = [
                sys.executable,
                str(SCRIPT),
                "--memory-repo",
                str(canonical),
                "--source-dir",
                str(source),
                "--state-dir",
                str(state),
                "--push",
            ]
            process = subprocess.Popen(
                command,
                cwd=canonical,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "change",
                    "SYNTHETIC_UPDATE_STARTED": str(marker),
                    "SYNTHETIC_UPDATE_RELEASE": str(release),
                },
            )
            deadline = time.monotonic() + 10.0
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            os.kill(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)

            try:
                blocked, blocked_report = invoke(canonical, source, state)

                self.assertNotEqual(blocked.returncode, 0)
                self.assertEqual(blocked_report["reason"], "concurrent_transaction")
                self.assertEqual(git(canonical, "status", "--porcelain=v1").stdout, "")
            finally:
                release.write_text("release\n", encoding="utf-8")

            deadline = time.monotonic() + 10.0
            while True:
                replay, replay_report = invoke(canonical, source, state)
                if replay_report["reason"] != "concurrent_transaction":
                    break
                if time.monotonic() >= deadline:
                    self.fail("orphan child did not release inherited transaction lock")
                time.sleep(0.05)
            self.assertEqual(replay.returncode, 0)
            self.assertEqual(replay_report["status"], "published")
            self.assertEqual(replay_report["recovery_action"], "stale_staging_replayed")

    def test_same_canonical_with_different_state_directories_still_has_one_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            first_state = root / "first-state"
            second_state = root / "second-state"
            marker = root / "update-started"
            release = root / "update-release"
            command = [
                sys.executable,
                str(SCRIPT),
                "--memory-repo",
                str(canonical),
                "--source-dir",
                str(source),
                "--state-dir",
                str(first_state),
                "--push",
            ]
            first = subprocess.Popen(
                command,
                cwd=canonical,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "change",
                    "SYNTHETIC_UPDATE_STARTED": str(marker),
                    "SYNTHETIC_UPDATE_RELEASE": str(release),
                },
            )
            deadline = time.monotonic() + 10.0
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            try:
                second, second_report = invoke(canonical, source, second_state)
            finally:
                release.write_text("release\n", encoding="utf-8")
            first_stdout, first_stderr = first.communicate(timeout=10)
            self.assertEqual(first.returncode, 0, first_stderr)
            first_report = json.loads(first_stdout)

            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(second_report["reason"], "concurrent_transaction")
            self.assertEqual(first_report["status"], "published")
            self.assertEqual(git(canonical, "status", "--porcelain=v1").stdout, "")

    def test_state_directory_cannot_overlap_canonical_or_source(self):
        for location in ("canonical", "source"):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                canonical, source, _remote = setup_archive(root)
                parent = canonical if location == "canonical" else source
                state = parent / "transaction-runtime"

                result, report = invoke(canonical, source, state)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["reason"], "unsafe_state_dir")
                self.assertFalse(state.exists())
                self.assertEqual(
                    git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout,
                    "",
                )

    def test_dirty_canonical_fails_closed_without_creating_staging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            state = root / "state"
            (canonical / "baseline.txt").write_text("dirty\n", encoding="utf-8")

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["report_kind"], "scheduled_memory_transaction")
            self.assertEqual(report["report_version"], 1)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "dirty_canonical")
            self.assertFalse((state / "staging").exists())

    def test_malformed_state_fails_closed_and_state_directory_is_private(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            state = root / "state"
            state.mkdir(mode=0o755)
            (state / "transaction.json").write_text("{malformed", encoding="utf-8")

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "malformed_state")
            self.assertEqual(os.stat(state).st_mode & 0o777, 0o700)
            self.assertFalse((state / "staging").exists())

    def test_symlinked_staging_fails_closed_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            state = root / "state"
            outside = root / "outside"
            state.mkdir(mode=0o700)
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("preserve\n", encoding="utf-8")
            (state / "staging").symlink_to(outside, target_is_directory=True)

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "unsafe_staging")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")

    def test_owned_staging_clone_is_created_and_stale_output_is_replayed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, _source, _remote = setup_archive(root)
            state = module.prepare_state_dir(root / "state")
            remote_url = module.canonical_remote_url(canonical)
            repo_fingerprint = module.path_fingerprint(canonical)
            remote_fingerprint = module.remote_fingerprint(remote_url, canonical)

            staging, recovered = module.prepare_staging(
                canonical,
                state,
                remote_url,
                repo_fingerprint,
                remote_fingerprint,
            )

            self.assertFalse(recovered)
            self.assertEqual(git(staging, "status", "--porcelain=v1").stdout, "")
            (staging / "baseline.txt").write_text("partial\n", encoding="utf-8")
            (staging / "partial.txt").write_text("partial\n", encoding="utf-8")

            replayed, recovered = module.prepare_staging(
                canonical,
                state,
                remote_url,
                repo_fingerprint,
                remote_fingerprint,
            )

            self.assertTrue(recovered)
            self.assertEqual(replayed, staging)
            self.assertEqual((staging / "baseline.txt").read_text(encoding="utf-8"), "baseline\n")
            self.assertFalse((staging / "partial.txt").exists())
            self.assertEqual(git(staging, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")
            owner = json.loads((state / "staging-owner.json").read_text(encoding="utf-8"))
            self.assertEqual(owner["repository_fingerprint"], repo_fingerprint)
            self.assertEqual(owner["remote_fingerprint"], remote_fingerprint)
            self.assertNotIn(str(canonical), json.dumps(owner))

    def test_relative_remote_url_is_resolved_from_canonical_before_staging_clone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            self.assertEqual(git(canonical, "remote", "set-url", "origin", "../remote.git").returncode, 0)

            result, report = invoke(
                canonical,
                source,
                root / "runtime" / "state",
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "change"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "published")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout, git(canonical, "rev-parse", "origin/main").stdout)

    def test_scp_style_remote_url_with_custom_user_is_not_resolved_as_local_path(self):
        module = load_module()
        remote = "deploy@example.invalid:org/archive.git"

        self.assertEqual(module.normalized_remote_url(remote, Path("/tmp/canonical")), remote)

    def test_staging_owner_or_remote_mismatch_fails_without_cleaning(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, _source, _remote = setup_archive(root)
            state = module.prepare_state_dir(root / "state")
            remote_url = module.canonical_remote_url(canonical)
            repo_fingerprint = module.path_fingerprint(canonical)
            remote_fingerprint = module.remote_fingerprint(remote_url, canonical)
            staging, _recovered = module.prepare_staging(
                canonical,
                state,
                remote_url,
                repo_fingerprint,
                remote_fingerprint,
            )
            sentinel = staging / "do-not-clean.txt"
            sentinel.write_text("preserve\n", encoding="utf-8")
            owner_path = state / "staging-owner.json"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["remote_fingerprint"] = "0" * 64
            owner_path.write_text(json.dumps(owner), encoding="utf-8")

            with self.assertRaisesRegex(module.TransactionBlocked, "unsafe_staging"):
                module.prepare_staging(
                    canonical,
                    state,
                    remote_url,
                    repo_fingerprint,
                    remote_fingerprint,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")

            owner["remote_fingerprint"] = remote_fingerprint
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            assert git(staging, "remote", "set-url", "origin", str(root / "other.git")).returncode == 0
            with self.assertRaisesRegex(module.TransactionBlocked, "unexpected_remote"):
                module.prepare_staging(
                    canonical,
                    state,
                    remote_url,
                    repo_fingerprint,
                    remote_fingerprint,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")

    def test_clean_publish_updates_remote_then_fast_forwards_canonical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()

            result, report = invoke(canonical, source, state, env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "change"})

            self.assertEqual(result.returncode, 0)
            self.assertEqual(report["status"], "published")
            self.assertEqual(report["reason"], "published")
            self.assertNotEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(
                git(canonical, "rev-parse", "HEAD").stdout.strip(),
                git(canonical, "rev-parse", "origin/main").stdout.strip(),
            )
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    def test_no_op_current_does_not_create_commit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()

            result, report = invoke(canonical, source, state, env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "noop"})

            self.assertEqual(result.returncode, 0)
            self.assertEqual(report["status"], "no_op_current")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(report["metrics"]["remote_publish_count"], 0)

    def test_deferred_without_archive_change_is_successful_but_not_no_op_current(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)

            result, report = invoke(
                canonical,
                source,
                root / "state",
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "deferred_noop"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "deferred")
            self.assertEqual(report["reason"], "source_records_deferred")
            self.assertFalse(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["source_record_deferred_count"], 1)
            self.assertEqual(report["metrics"]["remote_publish_count"], 0)

    @unittest.skipUnless(os.name == "posix", "completed no-publish recovery test requires POSIX signals")
    def test_completed_deferred_no_publish_state_recovers_after_sigkill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()
            payload = interrupt_at_completed_deferred_no_publish(canonical, source, state, root)
            state_file = state / "transaction.json"
            self.assertEqual(payload["candidate_sha"], payload["base_sha"])
            self.assertEqual(payload["source_record_deferred_count"], 1)
            self.assertFalse(payload["source_batch_complete"])

            result, report = invoke(
                canonical,
                source,
                state,
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "noop"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "deferred")
            self.assertEqual(report["reason"], "source_records_deferred")
            self.assertEqual(report["recovery_action"], "completed_no_publish_reconciled")
            self.assertFalse(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["recovery_count"], 1)
            self.assertEqual(report["metrics"]["source_record_deferred_count"], 1)
            self.assertEqual(report["metrics"]["remote_publish_count"], 0)
            self.assertFalse(state_file.exists())
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(git(remote, "rev-parse", "main").stdout.strip(), starting)

    @unittest.skipUnless(os.name == "posix", "completed no-publish recovery test requires POSIX signals")
    def test_completed_no_publish_recovery_refuses_dirty_canonical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            interrupt_at_completed_deferred_no_publish(canonical, source, state, root)
            (canonical / "PRIVATE_USER_EDIT.txt").write_text("unrelated user edit\n", encoding="utf-8")

            result, report = invoke(
                canonical,
                source,
                state,
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "noop"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "dirty_canonical")
            self.assertTrue((state / "transaction.json").is_file())
            self.assertTrue((canonical / "PRIVATE_USER_EDIT.txt").is_file())

    def test_publish_can_report_incomplete_source_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)

            result, report = invoke(
                canonical,
                source,
                root / "state",
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "deferred_change"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "published")
            self.assertFalse(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["source_record_deferred_count"], 1)
            self.assertEqual(report["metrics"]["remote_publish_count"], 1)

    @unittest.skipUnless(os.name == "posix", "post-push interruption test requires POSIX signals")
    def test_post_push_reconciliation_preserves_deferred_source_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            release = root / "receipt-release"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(canonical),
                    "--source-dir",
                    str(source),
                    "--state-dir",
                    str(state),
                    "--push",
                ],
                cwd=canonical,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "deferred_change",
                    "MY_PRECIOUS_TRANSACTION_TEST_PAUSE_PHASE": "remote_receipt",
                    "MY_PRECIOUS_TRANSACTION_TEST_RELEASE_FILE": str(release),
                },
                start_new_session=True,
            )
            state_file = state / "transaction.json"
            deadline = time.monotonic() + 10.0
            payload: dict[str, object] = {}
            while time.monotonic() < deadline:
                try:
                    payload = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.02)
                    continue
                if payload.get("phase") == "remote_receipt":
                    break
                time.sleep(0.02)
            if payload.get("phase") != "remote_receipt":
                process.kill()
                process.communicate()
                self.fail("transaction did not reach remote_receipt")
            self.assertEqual(payload["source_record_deferred_count"], 1)
            self.assertEqual(payload["source_target_deferred_count"], 1)
            self.assertFalse(payload["source_batch_complete"])
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)

            result, report = invoke(canonical, source, state)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "published")
            self.assertEqual(report["recovery_action"], "post_push_reconciled")
            self.assertFalse(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["source_record_deferred_count"], 1)
            self.assertEqual(report["metrics"]["source_target_deferred_count"], 1)

    def test_live_sync_without_a_new_commit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"

            result, report = invoke(
                canonical,
                source,
                state,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "change",
                    "SYNTHETIC_SYNC_MODE": "live_noop",
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "sync_live_no_commit")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), git(canonical, "rev-parse", "origin/main").stdout.strip())
            self.assertEqual(git(canonical, "status", "--porcelain=v1").stdout, "")

    def test_updater_failure_never_mutates_canonical_or_remote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()

            result, report = invoke(
                canonical,
                source,
                state,
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "update_fail"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "child_failure_unclassified")
            self.assertEqual(report["failure_stage"], "update")
            self.assertEqual(report["metrics"]["update_child_failure_count"], 0)
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(git(canonical, "rev-parse", "origin/main").stdout.strip(), starting)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    def test_update_batch_parser_accepts_structured_finalization_review_failure(self):
        module = load_module()
        payload = {
            "report_kind": "memory_update_batch_report",
            "report_version": 1,
            "status": "blocked",
            "reason": "memory_review_decision_invalid",
            "failure_stage": "archive_finalization",
            "source_batch_complete": False,
            "metrics": {
                "inventory_worker_count": 1,
                "projects_updated_count": 123,
                "source_streams_updated_count": 0,
                "archive_finalization_count": 0,
                "records_deferred_count": 1,
                "targets_deferred_count": 1,
                "child_failure_count": 1,
            },
            "privacy": {
                "aggregate_only": True,
                "paths_rendered": False,
                "source_content_rendered": False,
                "child_output_rendered": False,
            },
        }
        result = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            stderr="",
        )

        parsed = module.parse_update_batch_report(result)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["reason"], "memory_review_decision_invalid")
        self.assertEqual(parsed["failure_stage"], "archive_finalization")

    def test_structured_update_failure_preserves_aggregate_stage_and_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()

            result, report = invoke(
                canonical,
                source,
                root / "state",
                env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "structured_update_fail"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "child_failure_unclassified")
            self.assertEqual(report["failure_stage"], "project_update")
            self.assertEqual(report["metrics"]["update_inventory_worker_count"], 1)
            self.assertEqual(report["metrics"]["update_child_failure_count"], 1)
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    def test_post_update_gate_failure_preserves_update_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()

            result, report = invoke(
                canonical,
                source,
                root / "state",
                env={**os.environ, "SYNTHETIC_AUDIT_FAIL": "1"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "archive_audit_failed")
            self.assertEqual(report["failure_stage"], "archive_audit")
            self.assertTrue(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["update_inventory_worker_count"], 1)
            self.assertEqual(report["metrics"]["update_project_processed_count"], 1)
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(git(canonical, "rev-parse", "origin/main").stdout.strip(), starting)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    def test_unreceipted_remote_advancement_never_mutates_canonical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            starting = git(canonical, "rev-parse", "HEAD").stdout.strip()
            starting_tracking = git(canonical, "rev-parse", "origin/main").stdout.strip()
            racer = root / "racer"
            self.assertEqual(git(root, "clone", str(remote), str(racer)).returncode, 0)
            self.assertEqual(git(racer, "config", "user.email", "racer@example.invalid").returncode, 0)
            self.assertEqual(git(racer, "config", "user.name", "Synthetic Racer").returncode, 0)
            (racer / "remote-only.txt").write_text("unreceipted\n", encoding="utf-8")
            self.assertEqual(git(racer, "add", "remote-only.txt").returncode, 0)
            self.assertEqual(git(racer, "commit", "-m", "Synthetic unreceipted remote advance").returncode, 0)
            self.assertEqual(git(racer, "push", "origin", "main").returncode, 0)

            result, report = invoke(canonical, source, root / "state")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["reason"], "canonical_remote_mismatch")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(git(canonical, "rev-parse", "origin/main").stdout.strip(), starting_tracking)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    @unittest.skipUnless(os.name == "posix", "canonical SIGKILL recovery test requires POSIX signals")
    def test_verified_canonical_fast_forward_interruption_is_repaired_on_replay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            payload = interrupt_at_canonical_fast_forward(canonical, source, state, root)

            candidate = str(payload["candidate_sha"])
            candidate_index = git(state / "staging", "show", f"{candidate}:INDEX.md")
            self.assertEqual(candidate_index.returncode, 0)
            (canonical / "INDEX.md").write_text(candidate_index.stdout, encoding="utf-8")
            self.assertNotEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

            result, report = invoke(canonical, source, state)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["status"], "published")
            self.assertEqual(report["recovery_action"], "post_push_reconciled")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), candidate)
            self.assertEqual(git(canonical, "rev-parse", "origin/main").stdout.strip(), candidate)
            self.assertEqual(git(canonical, "status", "--porcelain=v1", "--untracked-files=all").stdout, "")

    @unittest.skipUnless(os.name == "posix", "canonical SIGKILL recovery test requires POSIX signals")
    def test_canonical_recovery_refuses_dirty_paths_outside_verified_receipt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            payload = interrupt_at_canonical_fast_forward(canonical, source, state, root)
            starting = str(payload["base_sha"])
            unexpected = canonical / "unexpected-user-file.txt"
            unexpected.write_text("preserve\n", encoding="utf-8")

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["reason"], "dirty_canonical")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(unexpected.read_text(encoding="utf-8"), "preserve\n")

    @unittest.skipUnless(os.name == "posix", "canonical SIGKILL recovery test requires POSIX signals")
    def test_canonical_recovery_refuses_user_edit_on_candidate_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            payload = interrupt_at_canonical_fast_forward(canonical, source, state, root)
            starting = str(payload["base_sha"])
            edited = canonical / "INDEX.md"
            edited.write_text("same path, unrelated user edit\n", encoding="utf-8")

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["reason"], "dirty_canonical")
            self.assertEqual(git(canonical, "rev-parse", "HEAD").stdout.strip(), starting)
            self.assertEqual(edited.read_text(encoding="utf-8"), "same path, unrelated user edit\n")

    @unittest.skipUnless(os.name == "posix", "canonical SIGKILL recovery test requires POSIX signals")
    def test_canonical_recovery_refuses_staged_user_edit_on_candidate_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"
            interrupt_at_canonical_fast_forward(canonical, source, state, root)
            edited = canonical / "INDEX.md"
            edited.write_text("staged unrelated user edit\n", encoding="utf-8")
            self.assertEqual(git(canonical, "add", "INDEX.md").returncode, 0)

            result, report = invoke(canonical, source, state)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["reason"], "dirty_canonical")
            self.assertEqual(edited.read_text(encoding="utf-8"), "staged unrelated user edit\n")
            self.assertEqual(git(canonical, "show", ":INDEX.md").stdout, "staged unrelated user edit\n")

    def test_readiness_failure_runs_one_bounded_repair_then_publishes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"

            result, report = invoke(canonical, source, state, env={**os.environ, "SYNTHETIC_TRANSACTION_MODE": "repair"})

            self.assertEqual(result.returncode, 0)
            self.assertEqual(report["status"], "published")
            self.assertEqual(report["metrics"]["repair_attempt_count"], 1)
            self.assertEqual((canonical / "INDEX.md").read_text(encoding="utf-8"), "repaired\n")

    def test_archive_audit_failure_runs_one_bounded_repair_then_publishes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            canonical, source, _remote = setup_archive(root)
            install_synthetic_runtime(canonical)
            state = root / "state"

            result, report = invoke(
                canonical,
                source,
                state,
                env={
                    **os.environ,
                    "SYNTHETIC_TRANSACTION_MODE": "repair",
                    "SYNTHETIC_AUDIT_REPAIRABLE": "1",
                },
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(report["status"], "published")
            self.assertEqual(report["metrics"]["repair_attempt_count"], 1)
            self.assertEqual((canonical / "INDEX.md").read_text(encoding="utf-8"), "repaired\n")


if __name__ == "__main__":
    unittest.main()
