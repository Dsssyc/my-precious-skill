import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


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
            "--push",
        ],
        cwd=canonical,
        env=env,
    )
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise AssertionError(f"expected one JSON line, got stdout={result.stdout!r} stderr={result.stderr!r}")
    return result, json.loads(lines[0])


def install_synthetic_runtime(canonical: Path) -> None:
    tools = canonical / "tools"
    tools.mkdir()
    (tools / "run_memory_updates.py").write_text(
        """#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
mode = os.environ.get('SYNTHETIC_TRANSACTION_MODE', 'change')
if mode == 'update_fail':
    raise SystemExit(7)
if mode != 'noop':
    value = 'needs-repair\\n' if mode == 'repair' else 'updated\\n'
    (repo / 'INDEX.md').write_text(value, encoding='utf-8')
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
        "import sys\nraise SystemExit(0)\n",
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
            self.assertEqual(report["reason"], "update_failed")
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


if __name__ == "__main__":
    unittest.main()
