#!/usr/bin/env python3
"""Prove scheduled update single-writer and interrupted-run closure."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_SOURCE = REPO_ROOT / "templates/agent-memory-repo/tools/run_memory_updates.py"
REPORT_KIND = "scheduled_update_single_writer_gate"
PRIVATE_SENTINEL = "PRIVATE_SINGLE_WRITER_SENTINEL"


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def runner_command(memory_repo: Path, source_dir: Path, *extra: str) -> list[str]:
    return [
        sys.executable,
        str(memory_repo / "tools/run_memory_updates.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        *extra,
    ]


def setup_repo(
    root: Path,
    name: str,
    *,
    project_count: int = 1,
    include_stream: bool = False,
) -> tuple[Path, Path]:
    memory_repo = root / name / "agent-memory"
    source_dir = root / name / "source-records"
    tools_dir = memory_repo / "tools"
    config_dir = memory_repo / "config"
    tools_dir.mkdir(parents=True)
    config_dir.mkdir()
    source_dir.mkdir()
    shutil.copyfile(RUNNER_SOURCE, tools_dir / "run_memory_updates.py")
    projects = []
    for ordinal in range(project_count):
        project_path = root / name / f"project-{chr(ord('a') + ordinal)}"
        project_path.mkdir()
        projects.append(
            {
                "project_path": str(project_path.resolve()),
                "source_dir": str(source_dir.resolve()),
                "enabled": True,
                "source": "synthetic",
            }
        )
    (config_dir / "projects.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in projects),
        encoding="utf-8",
    )
    streams = []
    if include_stream:
        stream_path = root / name / "source-stream"
        stream_path.mkdir()
        streams.append(
            {
                "stream_id": "synthetic-stream",
                "source_dir": str(source_dir.resolve()),
                "project_path": str(stream_path.resolve()),
                "archive_scope": "domain:synthetic",
                "source_partition": "source:synthetic",
                "enabled": True,
            }
        )
    (config_dir / "source_streams.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in streams),
        encoding="utf-8",
    )
    (tools_dir / "update_memory_archive.py").write_text(
        f"""#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
is_finalize = '--finalize-archive' in args
project_path = Path(args[args.index('--project-path') + 1]) if '--project-path' in args else None
launch_log = Path(os.environ['MY_PRECIOUS_GATE_LAUNCH_LOG'])
with launch_log.open('a', encoding='utf-8') as handle:
    handle.write((project_path.name if project_path is not None else 'finalize') + ':' + str(os.getpid()) + '\\n')
mode = os.environ['MY_PRECIOUS_GATE_MODE']
if mode == 'fail' and project_path is not None and project_path.name == 'project-a':
    print('{PRIVATE_SENTINEL}', file=sys.stderr)
    raise SystemExit(9)
if mode == 'block':
    release = Path(os.environ['MY_PRECIOUS_GATE_RELEASE'])
    while not release.exists():
        time.sleep(0.05)
""",
        encoding="utf-8",
    )
    return memory_repo, source_dir


def gate_env(root: Path, mode: str) -> dict[str, str]:
    return {
        **os.environ,
        "MY_PRECIOUS_GATE_MODE": mode,
        "MY_PRECIOUS_GATE_LAUNCH_LOG": str(root / "launches.txt"),
        "MY_PRECIOUS_GATE_RELEASE": str(root / "release"),
    }


def wait_for_launches(path: Path, count: int = 1) -> list[tuple[str, int]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            rows = []
            for line in path.read_text(encoding="utf-8").splitlines():
                name, pid = line.rsplit(":", 1)
                rows.append((name, int(pid)))
            if len(rows) >= count:
                return rows
        time.sleep(0.05)
    raise RuntimeError("synthetic updater did not start")


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for_exit(pid: int, timeout: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.05)
    return not process_alive(pid)


def privacy_hits(outputs: list[str], roots: list[Path]) -> int:
    markers = [PRIVATE_SENTINEL, *(str(root) for root in roots)]
    return sum(marker in output for output in outputs for marker in markers)


def run_concurrent_case(root: Path) -> tuple[dict[str, int | float], list[str]]:
    memory_repo, source_dir = setup_repo(root, "concurrent")
    case_root = root / "concurrent"
    env = gate_env(case_root, "block")
    first = subprocess.Popen(
        runner_command(memory_repo, source_dir),
        cwd=memory_repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    outputs: list[str] = []
    second = None
    try:
        wait_for_launches(case_root / "launches.txt")
        registry_before = (memory_repo / "config/projects.jsonl").read_bytes()
        second = run_command(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
        outputs.append(second.stdout + second.stderr)
        concurrent_rejected = (
            second.returncode != 0
            and "update_status=blocked reason=concurrent_update" in second.stderr
            and (memory_repo / "config/projects.jsonl").read_bytes() == registry_before
        )
    finally:
        (case_root / "release").touch()
        first_out, first_err = first.communicate(timeout=5)
        outputs.append(first_out + first_err)
    third = run_command(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    outputs.append(third.stdout + third.stderr)
    return {
        "single_writer_accepted": int(first.returncode == 0),
        "concurrent_writer_rejected": int(concurrent_rejected),
        "lock_released": int(third.returncode == 0),
    }, outputs


def run_dirty_cases(root: Path) -> tuple[int, list[str]]:
    passed = 0
    outputs: list[str] = []
    for kind in ("tracked", "deleted", "untracked"):
        memory_repo, source_dir = setup_repo(root, f"dirty-{kind}")
        case_root = root / f"dirty-{kind}"
        env = gate_env(case_root, "success")
        tracked = memory_repo / "tracked.txt"
        tracked.write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=memory_repo, check=True)
        subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=memory_repo, check=True)
        subprocess.run(["git", "config", "user.name", "Synthetic Gate"], cwd=memory_repo, check=True)
        subprocess.run(["git", "add", "."], cwd=memory_repo, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=memory_repo, check=True)
        if kind == "tracked":
            tracked.write_text("changed\n", encoding="utf-8")
        elif kind == "deleted":
            tracked.unlink()
        else:
            (memory_repo / "untracked.txt").write_text("new\n", encoding="utf-8")
        result = run_command(
            runner_command(memory_repo, source_dir, "--require-clean-worktree"),
            cwd=memory_repo,
            env=env,
        )
        outputs.append(result.stdout + result.stderr)
        passed += int(
            result.returncode != 0
            and "update_status=blocked reason=dirty_worktree" in result.stderr
            and not (case_root / "launches.txt").exists()
        )
    return passed, outputs


def run_fail_fast_case(root: Path) -> tuple[dict[str, int], list[str]]:
    memory_repo, source_dir = setup_repo(root, "fail-fast", project_count=2, include_stream=True)
    case_root = root / "fail-fast"
    env = gate_env(case_root, "fail")
    result = run_command(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    launches = (case_root / "launches.txt").read_text(encoding="utf-8").splitlines()
    publish_marker = case_root / "publish-attempt"
    if result.returncode == 0:
        publish_marker.touch()
    return {
        "fail_fast": int(result.returncode != 0 and len(launches) == 1),
        "post_failure_launches": max(0, len(launches) - 1),
        "publish_attempts": int(publish_marker.exists()),
    }, [result.stdout + result.stderr]


def run_termination_case(root: Path) -> tuple[dict[str, int], list[str]]:
    memory_repo, source_dir = setup_repo(root, "termination")
    case_root = root / "termination"
    env = gate_env(case_root, "block")
    runner = subprocess.Popen(
        runner_command(memory_repo, source_dir),
        cwd=memory_repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid = wait_for_launches(case_root / "launches.txt")[0][1]
    try:
        runner.send_signal(signal.SIGTERM)
        stdout, stderr = runner.communicate(timeout=5)
        child_cleanup = wait_for_exit(child_pid)
    finally:
        (case_root / "release").touch()
        if process_alive(child_pid):
            os.kill(child_pid, signal.SIGTERM)
            wait_for_exit(child_pid)
        if runner.poll() is None:
            runner.kill()
            runner.communicate(timeout=5)
    return {"child_cleanup": int(child_cleanup)}, [stdout + stderr]


def run_orphan_case(root: Path) -> tuple[dict[str, int], list[str]]:
    memory_repo, source_dir = setup_repo(root, "orphan")
    case_root = root / "orphan"
    env = gate_env(case_root, "block")
    first = subprocess.Popen(
        runner_command(memory_repo, source_dir),
        cwd=memory_repo,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child_pid = wait_for_launches(case_root / "launches.txt")[0][1]
    outputs: list[str] = []
    try:
        os.kill(first.pid, signal.SIGKILL)
        first.communicate(timeout=5)
        child_survived = process_alive(child_pid)
        second = run_command(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
        outputs.append(second.stdout + second.stderr)
        lock_retained = (
            child_survived
            and second.returncode != 0
            and "update_status=blocked reason=concurrent_update" in second.stderr
        )
    finally:
        (case_root / "release").touch()
        if process_alive(child_pid):
            os.kill(child_pid, signal.SIGTERM)
        wait_for_exit(child_pid)
    third = run_command(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    outputs.append(third.stdout + third.stderr)
    return {
        "orphan_lock_retained": int(lock_retained),
        "lock_released": int(third.returncode == 0),
    }, outputs


def build_report(root: Path) -> dict[str, object]:
    concurrent, concurrent_outputs = run_concurrent_case(root)
    dirty_passes, dirty_outputs = run_dirty_cases(root)
    fail_fast, fail_outputs = run_fail_fast_case(root)
    termination, termination_outputs = run_termination_case(root)
    orphan, orphan_outputs = run_orphan_case(root)
    outputs = [
        *concurrent_outputs,
        *dirty_outputs,
        *fail_outputs,
        *termination_outputs,
        *orphan_outputs,
    ]
    metrics: dict[str, int | float] = {
        "single_writer_acceptance_rate": float(concurrent["single_writer_accepted"]),
        "concurrent_writer_rejection_rate": float(concurrent["concurrent_writer_rejected"]),
        "dirty_startup_rejection_rate": dirty_passes / 3,
        "first_failure_fail_fast_rate": float(fail_fast["fail_fast"]),
        "post_failure_child_launch_count": fail_fast["post_failure_launches"],
        "parent_termination_child_cleanup_rate": float(termination["child_cleanup"]),
        "orphan_child_lock_retention_rate": float(orphan["orphan_lock_retained"]),
        "lock_release_after_exit_rate": (
            concurrent["lock_released"] + orphan["lock_released"]
        )
        / 2,
        "publish_attempt_after_failed_update_count": fail_fast["publish_attempts"],
        "privacy_leak_count": privacy_hits(
            outputs,
            [root / name for name in ("concurrent", "dirty-tracked", "dirty-deleted", "dirty-untracked", "fail-fast", "termination", "orphan")],
        ),
    }
    passed = (
        all(
            metrics[name] == 1.0
            for name in (
                "single_writer_acceptance_rate",
                "concurrent_writer_rejection_rate",
                "dirty_startup_rejection_rate",
                "first_failure_fail_fast_rate",
                "parent_termination_child_cleanup_rate",
                "orphan_child_lock_retention_rate",
                "lock_release_after_exit_rate",
            )
        )
        and metrics["post_failure_child_launch_count"] == 0
        and metrics["publish_attempt_after_failed_update_count"] == 0
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "process_ids_rendered": False,
            "source_paths_rendered": False,
            "child_output_rendered": False,
            "memory_text_rendered": False,
        },
        "claim_boundary": (
            "single-host scheduled update ownership, fail-fast, and process cleanup only; "
            "not whole-run rollback, distributed locking, GitHub availability, or memory quality"
        ),
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-single-writer-") as tmpdir:
            report = build_report(Path(tmpdir))
    except Exception as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": {"reason": type(exc).__name__},
            "privacy": {"aggregate_only": True},
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
