#!/usr/bin/env python3
"""Gate approved-source release identity across installed and deployed layers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from live_automation_prompt_alignment_gate import synthetic_transaction_prompt


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "tools" / "audit_release_convergence.py"
SEARCH_RELEASE_GATE = REPO_ROOT / "benchmarks" / "search_memory_release_truth_gate.py"
REPORT_KIND = "release_convergence_gate"
PRIVATE_SENTINEL = "PRIVATE_RELEASE_CONVERGENCE_SENTINEL"
FIXED_GIT_DATE = "2026-07-28T00:00:00+00:00"


class GateFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Fixture:
    root: Path
    source: Path
    installed: Path
    deployment: Path
    automation: Path


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_DATE": FIXED_GIT_DATE,
            "GIT_COMMITTER_DATE": FIXED_GIT_DATE,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require_success(
    command: list[str],
    *,
    cwd: Path | None = None,
    reason: str,
) -> subprocess.CompletedProcess[str]:
    result = run(command, cwd=cwd)
    if result.returncode != 0:
        raise GateFailure(reason)
    return result


def copy_fixture_source(target: Path) -> None:
    target.mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "skills",
        target / "skills",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    benchmarks = target / "benchmarks"
    benchmarks.mkdir()
    shutil.copy2(
        REPO_ROOT / "benchmarks" / "live_automation_prompt_alignment_gate.py",
        benchmarks / "live_automation_prompt_alignment_gate.py",
    )


def commit_all(source: Path, message: str) -> None:
    require_success(["git", "add", "-A"], cwd=source, reason="source_stage_failed")
    require_success(
        ["git", "commit", "-m", message],
        cwd=source,
        reason="source_commit_failed",
    )


def initialize_source(source: Path) -> None:
    require_success(
        ["git", "init", "--initial-branch=main"],
        cwd=source,
        reason="source_init_failed",
    )
    require_success(
        ["git", "config", "user.name", "Synthetic Release Gate"],
        cwd=source,
        reason="source_config_failed",
    )
    require_success(
        ["git", "config", "user.email", "synthetic-release@example.invalid"],
        cwd=source,
        reason="source_config_failed",
    )
    commit_all(source, "synthetic approved release")
    require_success(
        ["git", "branch", "dev-feature"],
        cwd=source,
        reason="integration_branch_failed",
    )


def valid_automation_prompt(installed: Path) -> str:
    return (
        synthetic_transaction_prompt()
        .replace("/installed", str(installed.resolve()))
        + f"\nPrivate marker for non-rendering verification: {PRIVATE_SENTINEL}"
    )


def write_automation(path: Path, prompt: str) -> None:
    path.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "synthetic-release-automation"',
                'kind = "cron"',
                f"prompt = {json.dumps(prompt)}",
                'status = "ACTIVE"',
                'execution_environment = "local"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def create_fixture(root: Path) -> Fixture:
    source = root / "source"
    installed = root / "installed"
    deployment = root / "deployment"
    automation = root / "automation.toml"
    copy_fixture_source(source)
    initialize_source(source)
    shutil.copytree(
        source / "skills",
        installed,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    setup = source / "skills/setup-my-precious/scripts/setup_memory_archive.py"
    require_success(
        [
            sys.executable,
            str(setup),
            "--path",
            str(deployment),
            "--skip-config",
        ],
        cwd=source,
        reason="deployment_setup_failed",
    )
    write_automation(automation, valid_automation_prompt(installed))
    return Fixture(root, source, installed, deployment, automation)


def file_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.name if root.is_file() else path.relative_to(root).as_posix()
        if ".git" in path.parts or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def fixture_snapshot(fixture: Fixture) -> dict[str, dict[str, str]]:
    return {
        "source": file_snapshot(fixture.source),
        "installed": file_snapshot(fixture.installed),
        "deployment": file_snapshot(fixture.deployment),
        "automation": file_snapshot(fixture.automation),
    }


def run_audit(fixture: Fixture) -> tuple[dict[str, object], str, int]:
    before = fixture_snapshot(fixture)
    result = run(
        [
            sys.executable,
            str(AUDIT),
            "--source-repo",
            str(fixture.source),
            "--approved-ref",
            "refs/heads/main",
            "--integration-ref",
            "refs/heads/dev-feature",
            "--installed-root",
            str(fixture.installed),
            "--deployment-repo",
            str(fixture.deployment),
            "--automation-config",
            str(fixture.automation),
            "--report-json",
        ],
        cwd=fixture.source,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("malformed_audit_output") from exc
    if not isinstance(report, dict):
        raise GateFailure("malformed_audit_output")
    after = fixture_snapshot(fixture)
    mutation_count = int(before != after)
    return report, result.stdout, mutation_count


def append_text(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def advance_source_release(fixture: Fixture, *, converge_integration: bool = True) -> None:
    runtime = (
        fixture.source
        / "skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py"
    )
    append_text(runtime, "\n# synthetic approved release advance\n")
    commit_all(fixture.source, "advance synthetic approved release")
    if converge_integration:
        require_success(
            ["git", "branch", "-f", "dev-feature", "HEAD"],
            cwd=fixture.source,
            reason="integration_branch_update_failed",
        )


def current_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    report, rendered, mutations = run_audit(fixture)
    return report.get("status") == "current", rendered, mutations


def old_both_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    advance_source_release(fixture)
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("source_installed_skills_match") is False
        and checks.get("source_deployed_tools_match") is False,
        rendered,
        mutations,
    )


def stale_installed_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    append_text(
        fixture.installed / "using-my-precious/SKILL.md",
        "\nsynthetic stale installed skill\n",
    )
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("source_installed_skills_match") is False
        and checks.get("source_deployed_tools_match") is True,
        rendered,
        mutations,
    )


def stale_private_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    append_text(
        fixture.deployment / "tools/search_memory.py",
        "\n# synthetic stale deployed tool\n",
    )
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("source_installed_skills_match") is True
        and checks.get("source_deployed_tools_match") is False,
        rendered,
        mutations,
    )


def source_head_mismatch_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    require_success(
        ["git", "checkout", "-b", "candidate"],
        cwd=fixture.source,
        reason="candidate_checkout_failed",
    )
    append_text(
        fixture.source / "skills/using-my-precious/SKILL.md",
        "\nsynthetic unreleased candidate\n",
    )
    commit_all(fixture.source, "synthetic unreleased candidate")
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("source_head_matches_approved_ref") is False,
        rendered,
        mutations,
    )


def unmerged_integration_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    require_success(
        ["git", "checkout", "dev-feature"],
        cwd=fixture.source,
        reason="integration_checkout_failed",
    )
    append_text(
        fixture.source / "skills/using-my-precious/SKILL.md",
        "\nsynthetic unmerged integration candidate\n",
    )
    commit_all(fixture.source, "synthetic unmerged integration candidate")
    require_success(
        ["git", "checkout", "main"],
        cwd=fixture.source,
        reason="main_checkout_failed",
    )
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("approved_integration_refs_converged") is False,
        rendered,
        mutations,
    )


def wrong_automation_path_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    write_automation(
        fixture.automation,
        valid_automation_prompt(fixture.installed).replace(
            str(fixture.installed.resolve()),
            "/synthetic-wrong-installed-root",
        ),
    )
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    return (
        report.get("status") == "drifted"
        and checks.get("automation_contract_aligned") is False,
        rendered,
        mutations,
    )


def automation_self_update_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    write_automation(
        fixture.automation,
        valid_automation_prompt(fixture.installed) + "\n$ git pull origin main",
    )
    report, rendered, mutations = run_audit(fixture)
    checks = report.get("checks", {})
    mismatch_counts = report.get("mismatch_counts", {})
    return (
        report.get("status") == "drifted"
        and checks.get("automation_contract_aligned") is False
        and mismatch_counts.get("automation_self_update_command_count") == 1,
        rendered,
        mutations,
    )


def malformed_evidence_case(root: Path) -> tuple[bool, str, int]:
    fixture = create_fixture(root)
    setup = (
        fixture.source
        / "skills/setup-my-precious/scripts/setup_memory_archive.py"
    )
    setup.write_text("print('{')\n", encoding="utf-8")
    commit_all(fixture.source, "synthetic malformed parity evidence")
    require_success(
        ["git", "branch", "-f", "dev-feature", "HEAD"],
        cwd=fixture.source,
        reason="integration_branch_update_failed",
    )
    report, rendered, mutations = run_audit(fixture)
    failure = report.get("failure", {})
    return (
        report.get("status") == "blocked"
        and failure.get("reason") == "malformed_tool_parity_report",
        rendered,
        mutations,
    )


def search_release_metrics() -> tuple[float, float, str]:
    result = run([sys.executable, str(SEARCH_RELEASE_GATE)], cwd=REPO_ROOT)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("malformed_search_release_report") from exc
    metrics = report.get("metrics", {}) if isinstance(report, dict) else {}
    if result.returncode != 0 or report.get("status") != "passed":
        raise GateFailure("search_release_gate_failed")
    return (
        float(metrics.get("approved_runtime_match_rate", 0.0)),
        float(metrics.get("rejected_runtime_absence_rate", 0.0)),
        result.stdout,
    )


def evaluate_once(root: Path) -> dict[str, object]:
    cases: tuple[
        tuple[str, Callable[[Path], tuple[bool, str, int]]],
        ...,
    ] = (
        ("current", current_case),
        ("old_both", old_both_case),
        ("stale_installed", stale_installed_case),
        ("stale_private", stale_private_case),
        ("source_head_mismatch", source_head_mismatch_case),
        ("unmerged_integration", unmerged_integration_case),
        ("wrong_automation_path", wrong_automation_path_case),
        ("automation_self_update", automation_self_update_case),
        ("malformed_evidence", malformed_evidence_case),
    )
    results: dict[str, bool] = {}
    rendered: list[str] = []
    mutation_count = 0
    for name, case in cases:
        passed, output, mutations = case(root / name)
        results[name] = passed
        rendered.append(output)
        mutation_count += mutations

    approved_rate, rejected_rate, search_rendered = search_release_metrics()
    rendered.append(search_rendered)
    combined = "\n".join(rendered)
    privacy_markers = (
        PRIVATE_SENTINEL,
        str(root),
        str(REPO_ROOT),
        "synthetic stale installed skill",
        "synthetic stale deployed tool",
        "synthetic unreleased candidate",
    )
    privacy_leak_count = sum(marker in combined for marker in privacy_markers)
    metrics: dict[str, object] = {
        "current_release_acceptance_accuracy": 1.0 if results["current"] else 0.0,
        "old_but_mutually_consistent_rejection_accuracy": 1.0
        if results["old_both"]
        else 0.0,
        "stale_installed_rejection_accuracy": 1.0
        if results["stale_installed"]
        else 0.0,
        "stale_private_runtime_rejection_accuracy": 1.0
        if results["stale_private"]
        else 0.0,
        "unreleased_source_ref_rejection_accuracy": 1.0
        if results["source_head_mismatch"] and results["unmerged_integration"]
        else 0.0,
        "automation_path_mismatch_rejection_accuracy": 1.0
        if results["wrong_automation_path"]
        else 0.0,
        "automation_self_update_rejection_accuracy": 1.0
        if results["automation_self_update"]
        else 0.0,
        "malformed_release_evidence_rejection_accuracy": 1.0
        if results["malformed_evidence"]
        else 0.0,
        "approved_search_runtime_acceptance_accuracy": approved_rate,
        "historical_no_go_runtime_rejection_accuracy": rejected_rate,
        "audit_mutation_count": mutation_count,
        "privacy_leak_count": privacy_leak_count,
    }
    return {
        "metrics": metrics,
        "case_counts": {
            "accepted_case_count": 1,
            "rejected_case_count": len(cases) - 1,
        },
    }


def expected_metrics() -> dict[str, object]:
    return {
        "current_release_acceptance_accuracy": 1.0,
        "old_but_mutually_consistent_rejection_accuracy": 1.0,
        "stale_installed_rejection_accuracy": 1.0,
        "stale_private_runtime_rejection_accuracy": 1.0,
        "unreleased_source_ref_rejection_accuracy": 1.0,
        "automation_path_mismatch_rejection_accuracy": 1.0,
        "automation_self_update_rejection_accuracy": 1.0,
        "malformed_release_evidence_rejection_accuracy": 1.0,
        "approved_search_runtime_acceptance_accuracy": 1.0,
        "historical_no_go_runtime_rejection_accuracy": 1.0,
        "audit_mutation_count": 0,
        "privacy_leak_count": 0,
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-release-convergence-") as tmpdir:
            root = Path(tmpdir)
            first = evaluate_once(root / "run-a")
            second = evaluate_once(root / "run-b")
        reports_match = first == second
        passed = reports_match and first["metrics"] == expected_metrics()
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "passed" if passed else "failed",
            "metrics": first["metrics"],
            "case_counts": first["case_counts"],
            "determinism": {
                "runs": 2,
                "reports_match": reports_match,
            },
            "privacy": {
                "aggregate_only": True,
                "absolute_paths_rendered": False,
                "automation_prompt_rendered": False,
                "archive_content_rendered": False,
                "file_contents_rendered": False,
            },
            "claim_boundary": (
                "synthetic and read-only release identity convergence only; not automatic "
                "installation, scheduled self-update, scheduler or network reliability, "
                "archive quality, recall quality, ranking quality, or LLM answer quality"
            ),
        }
    except (GateFailure, OSError, ValueError) as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": {"reason": type(exc).__name__},
            "privacy": {
                "aggregate_only": True,
                "absolute_paths_rendered": False,
                "automation_prompt_rendered": False,
                "archive_content_rendered": False,
                "file_contents_rendered": False,
            },
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
