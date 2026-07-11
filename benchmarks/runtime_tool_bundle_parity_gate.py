#!/usr/bin/env python3
"""Gate full runtime tool-bundle parity and archive-preserving repair."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "runtime_tool_bundle_parity_gate"
PARITY_REPORT_KIND = "runtime_tool_bundle_parity"
FACT = "Runtime bundle parity keeps packaged archive tools complete and reviewable."
PROTECTED_ARCHIVE_ROOTS = (
    "INDEX.md",
    "config",
    "daily",
    "index",
    "memories",
    "records",
    "reviews",
    "sessions",
    "sources",
)


class GateFailure(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = run(command, cwd=cwd)
    if result.returncode:
        raise GateFailure(f"{stage}:command_failed:{result.returncode}")
    return result


def setup_archive(root: Path) -> Path:
    repo = root / "agent-memory"
    require(
        [sys.executable, str(SETUP_SCRIPT), "--path", str(repo), "--skip-config"],
        "setup_archive",
    )
    return repo


def parse_report(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("report_kind") != PARITY_REPORT_KIND:
        return None
    return payload


def parity_command(repo: Path, action: str, *, dry_run: bool = False) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SETUP_SCRIPT),
        "--path",
        str(repo),
        action,
        "--report-json",
        "--skip-config",
    ]
    if dry_run:
        command.append("--dry-run")
    return run(command)


def file_snapshot(repo: Path, roots: tuple[str, ...]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative in roots:
        root = repo / relative
        if root.is_file():
            snapshot[relative] = hashlib.sha256(root.read_bytes()).hexdigest()
        elif root.is_dir():
            for path in sorted(child for child in root.rglob("*") if child.is_file()):
                snapshot[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def changed_snapshot_count(before: dict[str, str], after: dict[str, str]) -> int:
    keys = set(before) | set(after)
    return sum(before.get(key) != after.get(key) for key in keys)


def add_preserved_archive_data(repo: Path) -> None:
    for relative in ("records/user-owned.txt", "sources/user-owned.txt", "reviews/user-owned.txt"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic preserved archive-side data\n", encoding="utf-8")


def init_git(repo: Path) -> None:
    require(["git", "init", "--initial-branch=main"], "git_init", cwd=repo)
    require(["git", "config", "user.email", "synthetic@example.invalid"], "git_email", cwd=repo)
    require(["git", "config", "user.name", "Synthetic Gate"], "git_name", cwd=repo)
    require(["git", "add", "."], "git_add", cwd=repo)
    require(["git", "commit", "-m", "Initialize synthetic runtime bundle"], "git_commit", cwd=repo)


def set_mtime(path: Path, stamp: str) -> None:
    timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    os.utime(path, (timestamp, timestamp))


def run_post_refresh_lifecycle(repo: Path, root: Path) -> dict[str, bool]:
    source_dir = root / "source-records"
    project_path = root / "project"
    source_dir.mkdir()
    project_path.mkdir()
    source = source_dir / "runtime-bundle.jsonl"
    source.write_text(
        json.dumps({"role": "user", "content": f"Please remember: {FACT}"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    set_mtime(source, "2026-07-11T10:00:00Z")
    update = run(
        [
            sys.executable,
            str(repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--source-dir",
            str(source_dir),
            "--project-path",
            str(project_path),
            "--project",
            "synthetic-runtime-bundle",
        ],
        cwd=repo,
    )
    audit = run(
        [sys.executable, str(repo / "tools/audit_memory_archive.py"), "--memory-repo", str(repo)],
        cwd=repo,
    )
    search = run(
        [sys.executable, str(repo / "tools/search_memory.py"), "--repo", str(repo), "--health-check"],
        cwd=repo,
    )
    sync = run(
        [
            sys.executable,
            str(repo / "tools/sync_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--include-reviewed-memory-nodes",
            "--dry-run",
        ],
        cwd=repo,
    )
    return {
        "update": update.returncode == 0,
        "audit": audit.returncode == 0,
        "search": search.returncode == 0,
        "sync": sync.returncode == 0,
    }


def run_repair_case(root: Path) -> tuple[int, str | None, dict[str, object], list[str]]:
    repo = setup_archive(root)
    add_preserved_archive_data(repo)
    extra = repo / "tools/user_adapter.py"
    extra.write_text("print('synthetic user-owned tool')\n", encoding="utf-8")

    clean_result = parity_command(repo, "--check-tools")
    clean_report = parse_report(clean_result)
    init_git(repo)
    archive_before = file_snapshot(repo, PROTECTED_ARCHIVE_ROOTS)
    extra_before = extra.read_bytes()

    stale_paths = (repo / "tools/search_memory.py", repo / "tools/audit_memory_archive.py")
    missing_paths = (repo / "tools/resolve_memory_source.py", repo / "tools/upgrade_source_anchors.py")
    for path in stale_paths:
        path.write_text("print('stale synthetic tool')\n", encoding="utf-8")
    for path in missing_paths:
        path.unlink()

    drift_result = parity_command(repo, "--check-tools")
    drift_report = parse_report(drift_result)
    dry_result = parity_command(repo, "--refresh-tools", dry_run=True)
    dry_report = parse_report(dry_result)
    dry_archive = file_snapshot(repo, PROTECTED_ARCHIVE_ROOTS)
    dry_still_drifted = all(path.exists() for path in stale_paths) and all(not path.exists() for path in missing_paths)

    refresh_result = parity_command(repo, "--refresh-tools")
    refresh_report = parse_report(refresh_result)
    post_result = parity_command(repo, "--check-tools")
    post_report = parse_report(post_result)
    tools_before_replay = file_snapshot(repo, ("tools",))
    replay_result = parity_command(repo, "--refresh-tools")
    replay_report = parse_report(replay_result)
    tools_after_replay = file_snapshot(repo, ("tools",))
    archive_after = file_snapshot(repo, PROTECTED_ARCHIVE_ROOTS)
    post_lifecycle = run_post_refresh_lifecycle(repo, root)

    reports = [clean_report, drift_report, dry_report, refresh_report, post_report, replay_report]
    parse_success = all(isinstance(report, dict) for report in reports)
    expected_count = int(clean_report.get("expected_tool_count", 0)) if clean_report else 0
    metrics: dict[str, object] = {
        "runtime_bundle_report_parse_success_rate": 1.0 if parse_success else 0.0,
        "runtime_bundle_clean_detection_accuracy": 1.0
        if clean_result.returncode == 0 and clean_report and clean_report.get("status") == "current"
        else 0.0,
        "runtime_bundle_drift_detection_accuracy": 1.0
        if drift_result.returncode != 0 and drift_report and drift_report.get("status") == "drifted"
        else 0.0,
        "runtime_bundle_missing_detection_accuracy": 1.0
        if drift_report and drift_report.get("missing_tool_count") == 2
        else 0.0,
        "runtime_bundle_stale_detection_accuracy": 1.0
        if drift_report and drift_report.get("stale_tool_count") == 2
        else 0.0,
        "runtime_bundle_refresh_success_rate": 1.0
        if refresh_result.returncode == 0 and refresh_report and refresh_report.get("status") == "refreshed"
        else 0.0,
        "runtime_bundle_post_refresh_parity_rate": 1.0
        if post_result.returncode == 0
        and post_report
        and post_report.get("status") == "current"
        and post_report.get("matching_tool_count") == expected_count
        else 0.0,
        "runtime_bundle_archive_preservation_rate": 1.0
        if changed_snapshot_count(archive_before, archive_after) == 0
        and changed_snapshot_count(archive_before, dry_archive) == 0
        and dry_still_drifted
        else 0.0,
        "runtime_bundle_extra_tool_preservation_rate": 1.0 if extra.read_bytes() == extra_before else 0.0,
        "runtime_bundle_idempotent_refresh_rate": 1.0
        if replay_result.returncode == 0
        and replay_report
        and replay_report.get("status") == "current"
        and replay_report.get("changed_tool_count") == 0
        and tools_before_replay == tools_after_replay
        else 0.0,
        "post_refresh_packaged_update_success_rate": 1.0 if post_lifecycle["update"] else 0.0,
        "post_refresh_archive_audit_pass_rate": 1.0 if post_lifecycle["audit"] else 0.0,
        "post_refresh_search_health_pass_rate": 1.0 if post_lifecycle["search"] else 0.0,
        "post_refresh_reviewed_sync_dry_run_pass_rate": 1.0 if post_lifecycle["sync"] else 0.0,
    }
    rendered_reports = [result.stdout for result in (clean_result, drift_result, dry_result, refresh_result, post_result, replay_result)]
    source_bundle_sha256 = clean_report.get("source_bundle_sha256") if clean_report else None
    return expected_count, source_bundle_sha256, metrics, rendered_reports


def run_unsafe_case(root: Path) -> tuple[float, list[str]]:
    repo = setup_archive(root)
    add_preserved_archive_data(repo)
    archive_before = file_snapshot(repo, PROTECTED_ARCHIVE_ROOTS)
    outside = root / "outside-search.py"
    outside.write_text("outside stays unchanged\n", encoding="utf-8")
    search = repo / "tools/search_memory.py"
    search.unlink()
    search.symlink_to(outside)

    check_result = parity_command(repo, "--check-tools")
    refresh_result = parity_command(repo, "--refresh-tools")
    check_report = parse_report(check_result)
    refresh_report = parse_report(refresh_result)
    passed = (
        check_result.returncode != 0
        and refresh_result.returncode != 0
        and check_report is not None
        and refresh_report is not None
        and check_report.get("status") == "blocked"
        and refresh_report.get("status") == "blocked"
        and check_report.get("unsafe_target_count") == 1
        and refresh_report.get("unsafe_target_count") == 1
        and refresh_report.get("changed_tool_count") == 0
        and outside.read_text(encoding="utf-8") == "outside stays unchanged\n"
        and changed_snapshot_count(archive_before, file_snapshot(repo, PROTECTED_ARCHIVE_ROOTS)) == 0
    )
    return (1.0 if passed else 0.0), [check_result.stdout, refresh_result.stdout]


def evaluate_once(root: Path) -> dict[str, object]:
    expected_count, source_bundle_sha256, metrics, rendered = run_repair_case(root / "repair")
    unsafe_rate, unsafe_rendered = run_unsafe_case(root / "unsafe")
    metrics["runtime_bundle_unsafe_target_rejection_rate"] = unsafe_rate
    all_rendered = "\n".join([*rendered, *unsafe_rendered])
    absolute_markers = (str(root), str(REPO_ROOT), "/Users/", "/private/var/", "/tmp/")
    metrics["absolute_path_leak_count"] = sum(marker in all_rendered for marker in absolute_markers)
    privacy_markers = (FACT, "stale synthetic tool", "synthetic user-owned tool", "outside stays unchanged")
    metrics["privacy_leak_count"] = sum(marker in all_rendered for marker in privacy_markers)
    return {
        "expected_tool_count": expected_count,
        "source_bundle_sha256": source_bundle_sha256,
        "metrics": metrics,
    }


def expected_metrics() -> dict[str, object]:
    return {
        "runtime_bundle_report_parse_success_rate": 1.0,
        "runtime_bundle_clean_detection_accuracy": 1.0,
        "runtime_bundle_drift_detection_accuracy": 1.0,
        "runtime_bundle_missing_detection_accuracy": 1.0,
        "runtime_bundle_stale_detection_accuracy": 1.0,
        "runtime_bundle_refresh_success_rate": 1.0,
        "runtime_bundle_post_refresh_parity_rate": 1.0,
        "runtime_bundle_archive_preservation_rate": 1.0,
        "runtime_bundle_extra_tool_preservation_rate": 1.0,
        "runtime_bundle_unsafe_target_rejection_rate": 1.0,
        "runtime_bundle_idempotent_refresh_rate": 1.0,
        "post_refresh_packaged_update_success_rate": 1.0,
        "post_refresh_archive_audit_pass_rate": 1.0,
        "post_refresh_search_health_pass_rate": 1.0,
        "post_refresh_reviewed_sync_dry_run_pass_rate": 1.0,
        "absolute_path_leak_count": 0,
        "privacy_leak_count": 0,
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-runtime-bundle-") as tmpdir:
            root = Path(tmpdir)
            first = evaluate_once(root / "run-a")
            second = evaluate_once(root / "run-b")
        reports_match = first == second
        expected_count = int(first["expected_tool_count"])
        metrics = first["metrics"]
        source_bundle_sha256 = first.get("source_bundle_sha256")
        valid_bundle_hash = (
            isinstance(source_bundle_sha256, str)
            and len(source_bundle_sha256) == 64
            and all(character in "0123456789abcdef" for character in source_bundle_sha256)
        )
        passed = (
            reports_match
            and valid_bundle_hash
            and expected_count == 19
            and metrics == expected_metrics()
        )
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "passed" if passed else "failed",
            "expected_tool_count": expected_count,
            "metrics": metrics,
            "determinism": {
                "runs": 2,
                "reports_match": reports_match,
                "bundle_hash_valid": valid_bundle_hash,
            },
            "privacy": {
                "aggregate_only": True,
                "archive_text_rendered": False,
                "absolute_paths_rendered": False,
                "tool_contents_rendered": False,
            },
            "claim_boundary": (
                "deterministic packaged parity and archive-preserving repair against the setup bundle; "
                "not latest-release discovery, live deployment correctness, scheduler reliability, "
                "LLM quality, ranking, vector search, ontology discovery, or public leaderboard parity"
            ),
        }
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": {"reason": str(exc)},
            "privacy": {"aggregate_only": True, "archive_text_rendered": False},
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
