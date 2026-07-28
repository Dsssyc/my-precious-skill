#!/usr/bin/env python3
"""Measure private immutable-source output parity and post-inventory parent RSS."""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_BASELINE_REF = "5de01cb"
REPORT_KIND = "private_live_source_inventory_ab_gate"
PARITY_ROOTS = ("sessions", "memories", "index", "daily", "INDEX.md")
TOOL_PATHS = (
    "tools/run_memory_updates.py",
    "tools/update_memory_archive.py",
    "tools/memory_consolidation.py",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-memory-repo", required=True)
    parser.add_argument("--private-source-dir", required=True)
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--report-file")
    return parser.parse_args(argv)


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 7200,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def git_blob(ref: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:templates/agent-memory-repo/{relative_path}"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("baseline_tool_unavailable")
    return result.stdout


def clone_private_repo(source: Path, target: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(target)],
        cwd=target.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("private_clone_failed")


def install_tool_set(memory_repo: Path, *, baseline_ref: str | None) -> None:
    for relative_path in TOOL_PATHS:
        destination = memory_repo / relative_path
        if baseline_ref is None:
            source = REPO_ROOT / "templates/agent-memory-repo" / relative_path
            shutil.copyfile(source, destination)
        else:
            destination.write_bytes(git_blob(baseline_ref, relative_path))


def rewrite_source_roots(memory_repo: Path, source_dir: Path) -> None:
    for relative_path in (Path("config/projects.jsonl"), Path("config/source_streams.jsonl")):
        path = memory_repo / relative_path
        if not path.is_file():
            continue
        rows: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            payload["source_dir"] = str(source_dir)
            rows.append(json.dumps(payload, sort_keys=True))
        path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")


def source_fingerprint(source_dir: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    candidates = sorted(
        {
            path.resolve()
            for pattern in ("*.jsonl", "*.json")
            for path in source_dir.rglob(pattern)
            if path.is_file()
        },
        key=lambda path: path.as_posix(),
    )
    for path in candidates:
        relative = path.relative_to(source_dir.resolve()).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                total_bytes += len(chunk)
        count += 1
    return count, total_bytes, digest.hexdigest()


def archive_snapshot(memory_repo: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative in PARITY_ROOTS:
        root = memory_repo / relative
        if root.is_file():
            snapshot[relative] = hashlib.sha256(root.read_bytes()).hexdigest()
        elif root.is_dir():
            for path in sorted(child for child in root.rglob("*") if child.is_file()):
                snapshot[path.relative_to(memory_repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def frozen_parity_environment(root: Path) -> dict[str, str]:
    hook_dir = root / "python-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        """import datetime as _datetime

class FrozenDateTime(_datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 13, 12, 0, 0, tzinfo=_datetime.UTC)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)

_datetime.datetime = FrozenDateTime
""",
        encoding="utf-8",
    )
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            part for part in (str(hook_dir), os.environ.get("PYTHONPATH", "")) if part
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def runner_command(memory_repo: Path, source_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(memory_repo / "tools/run_memory_updates.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--allow-redacted-secrets",
    ]


def output_count(output: str, label: str) -> int:
    prefix = f"{label}: "
    for line in output.splitlines():
        if line.startswith(prefix):
            try:
                return int(line.removeprefix(prefix))
            except ValueError:
                return -1
    return -1


def install_blocking_updater(memory_repo: Path) -> None:
    updater = memory_repo / "tools/update_memory_archive.py"
    implementation = memory_repo / "tools/update_memory_archive_impl.py"
    shutil.copyfile(updater, implementation)
    updater.write_text(
        """#!/usr/bin/env python3
import os
import sys
import time
from pathlib import Path

marker = Path(os.environ['MY_PRECIOUS_RSS_MARKER'])
release = Path(os.environ['MY_PRECIOUS_RSS_RELEASE'])
if '--finalize-archive' not in sys.argv[1:]:
    marker.write_text('ready\\n', encoding='utf-8')
    while not release.exists():
        time.sleep(0.02)
implementation = Path(__file__).with_name('update_memory_archive_impl.py')
os.execv(sys.executable, [sys.executable, str(implementation), *sys.argv[1:]])
""",
        encoding="utf-8",
    )


def process_rss_kib(pid: int) -> int:
    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        return 0
    return int(result.stdout.strip())


def measure_parent_post_inventory_rss(memory_repo: Path, source_dir: Path, case_root: Path) -> tuple[int, str]:
    case_root.mkdir(parents=True)
    install_blocking_updater(memory_repo)
    marker = case_root / "rss-ready"
    release = case_root / "rss-release"
    process = subprocess.Popen(
        runner_command(memory_repo, source_dir),
        cwd=memory_repo,
        env={
            **os.environ,
            "MY_PRECIOUS_RSS_MARKER": str(marker),
            "MY_PRECIOUS_RSS_RELEASE": str(release),
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 1800
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    rss = process_rss_kib(process.pid) if marker.exists() and process.poll() is None else 0
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return rss, stdout + stderr


def privacy_leak_count(outputs: list[str], private_repo: Path, source_dir: Path) -> int:
    markers = (str(private_repo), str(source_dir))
    return sum(marker in output for output in outputs for marker in markers)


def build_report(args: argparse.Namespace) -> dict[str, object]:
    private_repo = Path(args.private_memory_repo).expanduser().resolve()
    source_dir = Path(args.private_source_dir).expanduser().resolve()
    if not (private_repo / ".git").exists() or not source_dir.is_dir():
        raise RuntimeError("private_input_unavailable")
    before = source_fingerprint(source_dir)
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="my-precious-private-ab-") as tmpdir:
        root = Path(tmpdir)
        baseline = root / "baseline"
        candidate = root / "candidate"
        clone_private_repo(private_repo, baseline)
        clone_private_repo(private_repo, candidate)
        install_tool_set(baseline, baseline_ref=args.baseline_ref)
        install_tool_set(candidate, baseline_ref=None)
        rewrite_source_roots(baseline, source_dir)
        rewrite_source_roots(candidate, source_dir)

        parity_env = frozen_parity_environment(root)
        baseline_result = run(runner_command(baseline, source_dir), cwd=baseline, env=parity_env)
        candidate_result = run(runner_command(candidate, source_dir), cwd=candidate, env=parity_env)
        outputs.extend(
            (
                baseline_result.stdout + baseline_result.stderr,
                candidate_result.stdout + candidate_result.stderr,
            )
        )
        completion_rate = (
            int(baseline_result.returncode == 0) + int(candidate_result.returncode == 0)
        ) / 2
        baseline_enabled = output_count(baseline_result.stdout, "Enabled projects") + output_count(
            baseline_result.stdout,
            "Enabled source streams",
        )
        candidate_enabled = output_count(candidate_result.stdout, "Enabled projects") + output_count(
            candidate_result.stdout,
            "Enabled source streams",
        )
        baseline_completed = output_count(baseline_result.stdout, "Projects updated") + output_count(
            baseline_result.stdout,
            "Source streams updated",
        )
        candidate_completed = output_count(candidate_result.stdout, "Projects updated") + output_count(
            candidate_result.stdout,
            "Source streams updated",
        )
        enabled_total = baseline_enabled + candidate_enabled
        completed_total = baseline_completed + candidate_completed
        enabled_target_completion_rate = (
            completed_total / enabled_total
            if baseline_enabled > 0 and candidate_enabled > 0 and completed_total >= 0
            else 0.0
        )
        output_parity = 1.0 if archive_snapshot(baseline) == archive_snapshot(candidate) else 0.0

        baseline_probe = root / "baseline-probe"
        candidate_probe = root / "candidate-probe"
        clone_private_repo(private_repo, baseline_probe)
        clone_private_repo(private_repo, candidate_probe)
        install_tool_set(baseline_probe, baseline_ref=args.baseline_ref)
        install_tool_set(candidate_probe, baseline_ref=None)
        rewrite_source_roots(baseline_probe, source_dir)
        rewrite_source_roots(candidate_probe, source_dir)
        baseline_rss, baseline_output = measure_parent_post_inventory_rss(
            baseline_probe,
            source_dir,
            root / "baseline-rss",
        )
        candidate_rss, candidate_output = measure_parent_post_inventory_rss(
            candidate_probe,
            source_dir,
            root / "candidate-rss",
        )
        outputs.extend((baseline_output, candidate_output))

    after = source_fingerprint(source_dir)
    source_immutable = 1.0 if before == after else 0.0
    rss_reduction = (
        (baseline_rss - candidate_rss) / baseline_rss
        if baseline_rss > 0 and candidate_rss > 0
        else 0.0
    )
    metrics: dict[str, int | float] = {
        "private_source_record_count": before[0],
        "private_source_byte_count": before[1],
        "private_full_completion_rate": completion_rate,
        "baseline_enabled_target_count": baseline_enabled,
        "baseline_completed_target_count": baseline_completed,
        "candidate_enabled_target_count": candidate_enabled,
        "candidate_completed_target_count": candidate_completed,
        "private_enabled_target_completion_rate": enabled_target_completion_rate,
        "private_output_parity_rate": output_parity,
        "private_source_immutability_rate": source_immutable,
        "baseline_parent_post_inventory_rss_kib": baseline_rss,
        "candidate_parent_post_inventory_rss_kib": candidate_rss,
        "parent_post_inventory_rss_reduction_rate": rss_reduction,
        "privacy_leak_count": privacy_leak_count(outputs, private_repo, source_dir),
    }
    passed = (
        metrics["private_source_record_count"] > 0
        and metrics["private_full_completion_rate"] == 1.0
        and metrics["baseline_completed_target_count"]
        == metrics["baseline_enabled_target_count"]
        and metrics["candidate_completed_target_count"]
        == metrics["candidate_enabled_target_count"]
        and metrics["private_enabled_target_completion_rate"] == 1.0
        and metrics["private_output_parity_rate"] == 1.0
        and metrics["private_source_immutability_rate"] == 1.0
        and metrics["parent_post_inventory_rss_reduction_rate"] >= 0.50
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "source_content_rendered": False,
            "archive_content_rendered": False,
        },
        "claim_boundary": (
            "one immutable private source cohort, baseline-versus-candidate archive output parity, and "
            "runner-parent post-inventory RSS only; not process-tree peak RSS, arbitrary hardware, "
            "retrieval quality, ranking quality, vector search, or LLM answer quality"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args)
    except Exception:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "blocked",
            "reason": "private_ab_unavailable",
            "metrics": {"privacy_leak_count": 0},
            "privacy": {
                "aggregate_only": True,
                "paths_rendered": False,
                "source_content_rendered": False,
                "archive_content_rendered": False,
            },
        }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report_file:
        Path(args.report_file).expanduser().write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
