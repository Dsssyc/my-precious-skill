#!/usr/bin/env python3
"""Gate explicit three-layer distribution and fail-closed scheduled preflight."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = ("setup-my-precious", "update-my-precious", "using-my-precious")
SETUP_SCRIPT_RELATIVE = Path("setup-my-precious/scripts/setup_memory_archive.py")
REPORT_KIND = "three_layer_distribution_preflight_gate"
PARITY_REPORT_KIND = "runtime_tool_bundle_parity"
PRIVATE_SENTINEL = "PRIVATE_DISTRIBUTION_SENTINEL"
UPDATER_SENTINEL = "FAKE_UPDATER_SENTINEL"
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


def skipped(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return "__pycache__" in relative.parts or path.suffix == ".pyc"


def tree_entries(root: Path) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if skipped(path, root):
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, b"symlink\0" + os.readlink(path).encode("utf-8")))
        elif path.is_file():
            entries.append((relative, b"file\0" + path.read_bytes()))
    return entries


def bundle_sha256(entries: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def skill_bundle_sha256(root: Path) -> str:
    entries: list[tuple[str, bytes]] = []
    for skill_name in SKILL_NAMES:
        skill_root = root / skill_name
        if not skill_root.is_dir():
            entries.append((skill_name, b"missing"))
            continue
        entries.extend(
            (f"{skill_name}/{relative}", content)
            for relative, content in tree_entries(skill_root)
        )
    return bundle_sha256(entries)


def copy_installed_skills(installed_root: Path) -> None:
    for skill_name in SKILL_NAMES:
        shutil.copytree(
            REPO_ROOT / "skills" / skill_name,
            installed_root / skill_name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def setup_archive(installed_root: Path, target: Path) -> None:
    result = run(
        [
            sys.executable,
            str(installed_root / SETUP_SCRIPT_RELATIVE),
            "--path",
            str(target),
            "--skip-config",
        ]
    )
    if result.returncode:
        raise GateFailure("setup_failed")


def parity_command(
    installed_root: Path,
    target: Path,
    action: str,
    *,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(installed_root / SETUP_SCRIPT_RELATIVE),
        "--path",
        str(target),
        action,
        "--report-json",
        "--skip-config",
    ]
    if dry_run:
        command.append("--dry-run")
    return run(command)


def parse_object(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def accepted_preflight(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if result.returncode != 0:
        return None
    report = parse_object(result)
    if report is None:
        return None
    expected = report.get("expected_tool_count")
    privacy = report.get("privacy")
    valid = (
        report.get("report_kind") == PARITY_REPORT_KIND
        and report.get("report_version") == 1
        and report.get("action") == "check"
        and report.get("status") == "current"
        and isinstance(expected, int)
        and expected > 0
        and report.get("matching_tool_count") == expected
        and report.get("missing_tool_count") == 0
        and report.get("stale_tool_count") == 0
        and report.get("unsafe_target_count") == 0
        and report.get("changed_tool_count") == 0
        and valid_sha256(report.get("source_bundle_sha256"))
        and report.get("source_bundle_sha256") == report.get("target_bundle_sha256")
        and report.get("privacy_leak_count") == 0
        and isinstance(privacy, dict)
        and privacy.get("aggregate_only") is True
        and privacy.get("absolute_paths_rendered") is False
        and privacy.get("file_contents_rendered") is False
        and privacy.get("archive_text_rendered") is False
    )
    return report if valid else None


def run_update_if_ready(
    *,
    installed_current: bool,
    preflight: subprocess.CompletedProcess[str],
    marker: Path,
) -> bool:
    if not installed_current or accepted_preflight(preflight) is None:
        return False
    marker.write_text(UPDATER_SENTINEL + "\n", encoding="utf-8")
    return True


def snapshot(root: Path, relative_roots: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in relative_roots:
        path = root / relative
        if path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir():
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                result[child.relative_to(root).as_posix()] = hashlib.sha256(
                    child.read_bytes()
                ).hexdigest()
    return result


def seed_archive_side_data(repo: Path) -> None:
    paths = (
        "records/synthetic.txt",
        "sources/synthetic.txt",
        "reviews/synthetic.txt",
    )
    for relative in paths:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PRIVATE_SENTINEL + "\n", encoding="utf-8")


def synthetic_result(
    payload: object,
    *,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
    return subprocess.CompletedProcess(["synthetic-preflight"], returncode, stdout=stdout, stderr="")


def rejected_shape_results(current_report: dict[str, Any]) -> list[subprocess.CompletedProcess[str]]:
    wrong_kind = dict(current_report, report_kind="wrong_kind")
    wrong_version = dict(current_report, report_version=999)
    non_current = dict(current_report, status="drifted")
    return [
        synthetic_result("{"),
        synthetic_result(""),
        synthetic_result(wrong_kind),
        synthetic_result(wrong_version),
        synthetic_result(non_current),
        synthetic_result(current_report, returncode=1),
    ]


def report_status(result: subprocess.CompletedProcess[str], expected: str) -> bool:
    report = parse_object(result)
    return report is not None and report.get("status") == expected


def evaluate_once(root: Path) -> dict[str, object]:
    installed_root = root / "installed"
    copy_installed_skills(installed_root)
    source_hash = skill_bundle_sha256(REPO_ROOT / "skills")
    installed_hash = skill_bundle_sha256(installed_root)
    initial_install_current = source_hash == installed_hash

    deployment = root / "deployment"
    setup_archive(installed_root, deployment)
    seed_archive_side_data(deployment)
    extra_tool = deployment / "tools/user_owned_adapter.py"
    extra_tool.write_text("print('synthetic extra tool')\n", encoding="utf-8")
    clean_result = parity_command(installed_root, deployment, "--check-tools")
    clean_report = accepted_preflight(clean_result)

    marker = root / "updater.marker"
    stale_installed_file = installed_root / "using-my-precious/SKILL.md"
    stale_installed_file.write_text("synthetic stale installed skill\n", encoding="utf-8")
    stale_install_detected = source_hash != skill_bundle_sha256(installed_root)
    stale_install_blocked = not run_update_if_ready(
        installed_current=False,
        preflight=clean_result,
        marker=marker,
    )
    shutil.copy2(REPO_ROOT / "skills/using-my-precious/SKILL.md", stale_installed_file)
    restored_install_current = source_hash == skill_bundle_sha256(installed_root)

    archive_before = snapshot(deployment, PROTECTED_ARCHIVE_ROOTS)
    extra_before = extra_tool.read_bytes()
    stale_tool = deployment / "tools/search_memory.py"
    missing_tool = deployment / "tools/resolve_memory_source.py"
    stale_tool.write_text("print('synthetic stale deployment tool')\n", encoding="utf-8")
    missing_tool.unlink()
    drift_result = parity_command(installed_root, deployment, "--check-tools")
    drift_report = parse_object(drift_result)
    drift_blocked = not run_update_if_ready(
        installed_current=True,
        preflight=drift_result,
        marker=marker,
    )

    refresh_result = parity_command(installed_root, deployment, "--refresh-tools")
    first_current = parity_command(installed_root, deployment, "--check-tools")
    second_current = parity_command(installed_root, deployment, "--check-tools")
    first_report = accepted_preflight(first_current)
    second_report = accepted_preflight(second_current)

    malformed_results = rejected_shape_results(first_report or {})
    malformed_blocked = all(
        not run_update_if_ready(
            installed_current=True,
            preflight=result,
            marker=marker,
        )
        for result in malformed_results
    )

    unsafe_deployment = root / "unsafe-deployment"
    setup_archive(installed_root, unsafe_deployment)
    seed_archive_side_data(unsafe_deployment)
    unsafe_archive_before = snapshot(unsafe_deployment, PROTECTED_ARCHIVE_ROOTS)
    outside = root / "outside-search.py"
    outside.write_text("outside remains unchanged\n", encoding="utf-8")
    unsafe_search = unsafe_deployment / "tools/search_memory.py"
    unsafe_search.unlink()
    unsafe_search.symlink_to(outside)
    unsafe_result = parity_command(installed_root, unsafe_deployment, "--check-tools")
    unsafe_blocked = not run_update_if_ready(
        installed_current=True,
        preflight=unsafe_result,
        marker=marker,
    )

    marker_absent_after_rejections = not marker.exists()
    current_allowed = run_update_if_ready(
        installed_current=restored_install_current,
        preflight=second_current,
        marker=marker,
    )
    marker_count = marker.read_text(encoding="utf-8").count(UPDATER_SENTINEL) if marker.exists() else 0

    archive_after = snapshot(deployment, PROTECTED_ARCHIVE_ROOTS)
    unsafe_archive_after = snapshot(unsafe_deployment, PROTECTED_ARCHIVE_ROOTS)
    rendered = "\n".join(
        result.stdout
        for result in (clean_result, drift_result, refresh_result, first_current, second_current, unsafe_result)
    )
    privacy_markers = (
        PRIVATE_SENTINEL,
        UPDATER_SENTINEL,
        "synthetic stale installed skill",
        "synthetic stale deployment tool",
        str(root),
        str(REPO_ROOT),
    )
    privacy_leak_count = sum(marker_value in rendered for marker_value in privacy_markers)

    clean_parity_detected = clean_report is not None
    refresh_succeeded = refresh_result.returncode == 0 and report_status(
        refresh_result, "refreshed"
    )
    post_refresh_parity_detected = (
        refresh_succeeded and first_report is not None and second_report is not None
    )
    drift_detected = (
        drift_result.returncode != 0
        and drift_report is not None
        and drift_report.get("status") == "drifted"
        and drift_report.get("missing_tool_count") == 1
        and drift_report.get("stale_tool_count") == 1
    )
    unsafe_detected = unsafe_result.returncode != 0 and report_status(unsafe_result, "blocked")
    archive_preserved = (
        archive_before == archive_after
        and unsafe_archive_before == unsafe_archive_after
        and outside.read_text(encoding="utf-8") == "outside remains unchanged\n"
    )
    metrics: dict[str, object] = {
        "source_installed_parity_detection_accuracy": 1.0
        if initial_install_current and stale_install_detected and restored_install_current
        else 0.0,
        "installed_deployment_parity_detection_accuracy": 1.0
        if clean_parity_detected and post_refresh_parity_detected
        else 0.0,
        "stale_installed_rejection_accuracy": 1.0 if stale_install_blocked else 0.0,
        "drifted_deployment_rejection_accuracy": 1.0 if drift_detected and drift_blocked else 0.0,
        "unsafe_deployment_rejection_accuracy": 1.0 if unsafe_detected and unsafe_blocked else 0.0,
        "malformed_preflight_rejection_accuracy": 1.0 if malformed_blocked else 0.0,
        "preflight_blocks_update_accuracy": 1.0
        if marker_absent_after_rejections and stale_install_blocked and drift_blocked and unsafe_blocked
        else 0.0,
        "current_preflight_allows_update_accuracy": 1.0
        if current_allowed and marker_count == 1
        else 0.0,
        "preflight_idempotence_rate": 1.0
        if first_report == second_report and first_report is not None
        else 0.0,
        "archive_preservation_rate": 1.0 if archive_preserved else 0.0,
        "extra_tool_preservation_rate": 1.0 if extra_tool.read_bytes() == extra_before else 0.0,
        "privacy_leak_count": privacy_leak_count,
    }
    return {
        "source_bundle_sha256": source_hash,
        "metrics": metrics,
        "case_counts": {
            "rejected_preflight_cases": 3 + len(malformed_results),
            "allowed_preflight_cases": 1,
        },
    }


def expected_metrics() -> dict[str, object]:
    return {
        "source_installed_parity_detection_accuracy": 1.0,
        "installed_deployment_parity_detection_accuracy": 1.0,
        "stale_installed_rejection_accuracy": 1.0,
        "drifted_deployment_rejection_accuracy": 1.0,
        "unsafe_deployment_rejection_accuracy": 1.0,
        "malformed_preflight_rejection_accuracy": 1.0,
        "preflight_blocks_update_accuracy": 1.0,
        "current_preflight_allows_update_accuracy": 1.0,
        "preflight_idempotence_rate": 1.0,
        "archive_preservation_rate": 1.0,
        "extra_tool_preservation_rate": 1.0,
        "privacy_leak_count": 0,
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-three-layer-") as tmpdir:
            root = Path(tmpdir)
            first = evaluate_once(root / "run-a")
            second = evaluate_once(root / "run-b")
        reports_match = first == second
        bundle_hash_valid = valid_sha256(first.get("source_bundle_sha256"))
        metrics = first["metrics"]
        passed = reports_match and bundle_hash_valid and metrics == expected_metrics()
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "passed" if passed else "failed",
            "metrics": metrics,
            "case_counts": first["case_counts"],
            "determinism": {
                "runs": 2,
                "reports_match": reports_match,
                "bundle_hash_valid": bundle_hash_valid,
            },
            "privacy": {
                "aggregate_only": True,
                "tool_contents_rendered": False,
                "archive_text_rendered": False,
                "absolute_paths_rendered": False,
                "prompt_text_rendered": False,
            },
            "claim_boundary": (
                "synthetic explicit source-to-installed-to-deployment distribution and scheduled "
                "preflight decisions only; not automatic installation, automatic repair, scheduler "
                "or network reliability, private deployment correctness, or archive update quality"
            ),
        }
    except (GateFailure, OSError, ValueError) as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": {"reason": type(exc).__name__},
            "privacy": {"aggregate_only": True, "archive_text_rendered": False},
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
