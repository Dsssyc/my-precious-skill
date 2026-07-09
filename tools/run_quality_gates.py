#!/usr/bin/env python3
"""Run the repo-local release quality gate without rendering raw evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO


REPO_ROOT = Path(__file__).resolve().parents[1]

PY_COMPILE_TARGETS = (
    "tools/validate_skills.py",
    "tools/run_quality_gates.py",
    "benchmarks/packaged_lifecycle_gate.py",
    "benchmarks/using_my_precious_runtime_gate.py",
    "benchmarks/query_support_recall_gate.py",
    "benchmarks/progressive_source_drilldown_gate.py",
    "benchmarks/scope_arbitration_gate.py",
    "benchmarks/scope_answer_handoff_gate.py",
    "benchmarks/generated_answer_scope_adapter_gate.py",
    "benchmarks/automation_publish_readiness_gate.py",
    "benchmarks/publish_surface_repair_gate.py",
    "benchmarks/scheduled_publish_recovery_gate.py",
    "benchmarks/scheduled_publish_search_gate.py",
    "benchmarks/scheduled_content_noise_repair_closure_gate.py",
    "benchmarks/live_automation_prompt_alignment_gate.py",
    "benchmarks/induction_consolidation_gate.py",
    "benchmarks/lifecycle_governance_gate.py",
    "benchmarks/private_lifecycle_governance_shadow_gate.py",
    "benchmarks/search_tool_drift_repair_gate.py",
    "benchmarks/e2e_induction_recall_benchmark.py",
    "benchmarks/updater_induction_benchmark.py",
    "benchmarks/layered_recall_benchmark.py",
    "benchmarks/build_synthetic_recall_archive.py",
    "benchmarks/convert_public_memory_benchmark.py",
    "benchmarks/generated_answer_case_audit.py",
    "benchmarks/generated_answer_benchmark.py",
    "benchmarks/private_generated_answer_dogfood_gate.py",
    "benchmarks/source_stream_registry_benchmark.py",
    "benchmarks/v1_readiness_gate.py",
    "skills/setup-my-precious/scripts/setup_memory_archive.py",
    "skills/update-my-precious/scripts/update_memory_archive.py",
    "skills/update-my-precious/scripts/memory_consolidation.py",
    "skills/using-my-precious/scripts/search_memory.py",
    "templates/agent-memory-repo/tools/run_memory_updates.py",
    "templates/agent-memory-repo/tools/audit_memory_archive.py",
    "templates/agent-memory-repo/tools/audit_publish_readiness.py",
    "templates/agent-memory-repo/tools/repair_publish_surfaces.py",
    "templates/agent-memory-repo/tools/backfill_memory_archive.py",
    "templates/agent-memory-repo/tools/apply_memory_review_decisions.py",
    "templates/agent-memory-repo/tools/author_generated_answer_cases.py",
    "templates/agent-memory-repo/tools/capture_explicit_memory.py",
    "templates/agent-memory-repo/tools/update_memory_archive.py",
    "templates/agent-memory-repo/tools/memory_consolidation.py",
    "templates/agent-memory-repo/tools/search_memory.py",
    "templates/agent-memory-repo/tools/generate_answer_records.py",
    "templates/agent-memory-repo/tools/induction_consolidation_audit.py",
    "templates/agent-memory-repo/tools/shadow_eval_memory_archive.py",
    "templates/agent-memory-repo/tools/render_scheduler.py",
    "templates/agent-memory-repo/tools/sync_memory_archive.py",
)

GENERATED_CACHE_PATHS = (
    ".uv-cache",
    "tests/__pycache__",
    "benchmarks/__pycache__",
    "templates/agent-memory-repo/tools/__pycache__",
    "skills/setup-my-precious/scripts/__pycache__",
    "skills/setup-my-precious/assets/agent-memory-repo/tools/__pycache__",
    "skills/update-my-precious/scripts/__pycache__",
    "skills/using-my-precious/scripts/__pycache__",
    "tools/__pycache__",
)


@dataclass(frozen=True)
class CheckSpec:
    name: str
    command: tuple[str, ...]
    summary_kind: str = "generic"
    scorecard_key: str | None = None


Runner = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], float]


def build_release_checks() -> list[CheckSpec]:
    return [
        CheckSpec("validate_skills", ("python3", "tools/validate_skills.py")),
        CheckSpec("packaged_lifecycle", ("python3", "benchmarks/packaged_lifecycle_gate.py")),
        CheckSpec("using_my_precious_runtime", ("python3", "benchmarks/using_my_precious_runtime_gate.py")),
        CheckSpec("query_support_recall", ("python3", "benchmarks/query_support_recall_gate.py")),
        CheckSpec("progressive_source_drilldown", ("python3", "benchmarks/progressive_source_drilldown_gate.py")),
        CheckSpec("scope_arbitration", ("python3", "benchmarks/scope_arbitration_gate.py")),
        CheckSpec("scope_answer_handoff", ("python3", "benchmarks/scope_answer_handoff_gate.py")),
        CheckSpec(
            "generated_answer_scope_adapter",
            ("python3", "benchmarks/generated_answer_scope_adapter_gate.py"),
        ),
        CheckSpec(
            "automation_publish_readiness",
            ("python3", "benchmarks/automation_publish_readiness_gate.py"),
        ),
        CheckSpec(
            "publish_surface_repair",
            ("python3", "benchmarks/publish_surface_repair_gate.py"),
        ),
        CheckSpec(
            "scheduled_publish_recovery",
            ("python3", "benchmarks/scheduled_publish_recovery_gate.py"),
        ),
        CheckSpec(
            "scheduled_publish_search",
            ("python3", "benchmarks/scheduled_publish_search_gate.py"),
        ),
        CheckSpec(
            "scheduled_content_noise_repair_closure",
            ("python3", "benchmarks/scheduled_content_noise_repair_closure_gate.py"),
        ),
        CheckSpec(
            "live_automation_prompt_alignment",
            ("python3", "benchmarks/live_automation_prompt_alignment_gate.py"),
        ),
        CheckSpec(
            "induction_consolidation",
            ("python3", "benchmarks/induction_consolidation_gate.py"),
        ),
        CheckSpec(
            "lifecycle_governance",
            ("python3", "benchmarks/lifecycle_governance_gate.py"),
        ),
        CheckSpec(
            "private_lifecycle_shadow_synthetic",
            ("python3", "benchmarks/private_lifecycle_governance_shadow_gate.py", "--synthetic-fixture"),
        ),
        CheckSpec(
            "search_tool_drift_repair",
            ("python3", "benchmarks/search_tool_drift_repair_gate.py"),
        ),
        CheckSpec(
            "v1_readiness_core",
            ("python3", "benchmarks/v1_readiness_gate.py", "--run-packaged"),
            summary_kind="v1_readiness",
            scorecard_key="v1_core",
        ),
        CheckSpec(
            "v1_readiness_with_answer",
            ("python3", "benchmarks/v1_readiness_gate.py", "--run-packaged", "--require-answer"),
            summary_kind="v1_readiness",
            scorecard_key="v1_with_answer",
        ),
        CheckSpec("unit_tests", ("python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py")),
        CheckSpec("py_compile", ("python3", "-m", "py_compile", *PY_COMPILE_TARGETS)),
        CheckSpec(
            "template_sync_tree",
            ("diff", "-qr", "templates/agent-memory-repo", "skills/setup-my-precious/assets/agent-memory-repo"),
        ),
        CheckSpec(
            "template_sync_update_script",
            (
                "cmp",
                "-s",
                "templates/agent-memory-repo/tools/update_memory_archive.py",
                "skills/update-my-precious/scripts/update_memory_archive.py",
            ),
        ),
        CheckSpec(
            "template_sync_consolidation_script",
            (
                "cmp",
                "-s",
                "templates/agent-memory-repo/tools/memory_consolidation.py",
                "skills/update-my-precious/scripts/memory_consolidation.py",
            ),
        ),
        CheckSpec(
            "template_sync_search_script",
            (
                "cmp",
                "-s",
                "templates/agent-memory-repo/tools/search_memory.py",
                "skills/using-my-precious/scripts/search_memory.py",
            ),
        ),
        CheckSpec("git_diff_check", ("git", "diff", "--check")),
    ]


def safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def v1_summary(stdout: str) -> tuple[dict[str, Any], bool]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"reason": "invalid_json"}, False
    if not isinstance(payload, dict):
        return {"reason": "non_object_json"}, False
    scorecard = payload.get("scorecard")
    if not isinstance(scorecard, dict):
        return {"reason": "missing_scorecard"}, False
    summary = {
        "overall_status": payload.get("overall_status") if isinstance(payload.get("overall_status"), str) else None,
        "required_passed": safe_int(scorecard.get("required_passed")),
        "required_dimensions": safe_int(scorecard.get("required_dimensions")),
        "optional_passed": safe_int(scorecard.get("optional_passed")),
        "optional_dimensions": safe_int(scorecard.get("optional_dimensions")),
    }
    if summary["required_passed"] is None or summary["required_dimensions"] is None:
        return {"reason": "invalid_scorecard"}, False
    return summary, True


def summarize_success(check: CheckSpec, stdout: str) -> tuple[dict[str, Any], bool]:
    if check.summary_kind == "v1_readiness":
        return v1_summary(stdout)
    return {"reason": "completed"}, True


def run_check(check: CheckSpec, *, repo_root: Path, runner: Runner, clock: Clock) -> dict[str, Any]:
    started = clock()
    completed = runner(
        check.command,
        cwd=str(repo_root),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = round(clock() - started, 3)
    if completed.returncode != 0:
        return {
            "name": check.name,
            "status": "failed",
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "summary": {"reason": "command_failed"},
        }
    summary, valid = summarize_success(check, completed.stdout)
    return {
        "name": check.name,
        "status": "passed" if valid else "failed",
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "summary": summary,
    }


def remove_generated_caches(repo_root: Path) -> None:
    for rel_path in GENERATED_CACHE_PATHS:
        shutil.rmtree(repo_root / rel_path, ignore_errors=True)


def run_quality_gates(
    *,
    repo_root: Path = REPO_ROOT,
    runner: Runner = subprocess.run,
    clock: Clock = time.monotonic,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    scorecards: dict[str, dict[str, Any]] = {}
    for check in build_release_checks():
        result = run_check(check, repo_root=repo_root, runner=runner, clock=clock)
        checks.append(result)
        if check.name == "py_compile":
            remove_generated_caches(repo_root)
        if check.scorecard_key and result["status"] == "passed":
            summary = result["summary"]
            scorecards[check.scorecard_key] = {
                "overall_status": summary.get("overall_status"),
                "required_passed": summary.get("required_passed"),
                "required_dimensions": summary.get("required_dimensions"),
                "optional_passed": summary.get("optional_passed"),
                "optional_dimensions": summary.get("optional_dimensions"),
            }
        if result["status"] != "passed":
            break

    status = "passed" if checks and all(check["status"] == "passed" for check in checks) else "failed"
    return {
        "report_kind": "my_precious_release_quality_gate",
        "report_version": 1,
        "status": status,
        "privacy": {
            "aggregate_only": True,
            "stdout_rendered": False,
            "stderr_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "scorecards": scorecards,
        "checks": checks,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the aggregate JSON report")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    runner: Runner = subprocess.run,
    clock: Clock = time.monotonic,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = parse_args(argv)
    report = run_quality_gates(repo_root=repo_root, runner=runner, clock=clock)
    indent = 2 if args.pretty else None
    print(json.dumps(report, sort_keys=True, indent=indent), file=stdout)
    if report["status"] != "passed":
        failed = next((check for check in report["checks"] if check["status"] != "passed"), None)
        name = failed["name"] if failed else "unknown"
        print(f"quality gate failed: {name}; rerun the failed command directly for detailed logs", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
