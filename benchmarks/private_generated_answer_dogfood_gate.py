#!/usr/bin/env python3
"""Run the private generated-answer dogfood readiness gate.

This runner orchestrates existing aggregate-only tools. It must not render
private queries, reference answers, generated answers, memory IDs, source paths,
or raw refs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PUBLIC_REPO = Path(__file__).resolve().parents[1]
DEFAULT_CASE_OUTPUT = Path(".tmp/generated-answer-dogfood/cases.jsonl")
DEFAULT_WORK_DIR = Path("/tmp/my_precious_generated_answer_dogfood")
DEFAULT_SHADOW_CASES = Path("eval/redacted_real_history_probe_v3.jsonl")
DEFAULT_SHADOW_FAIL_UNDER = Path("eval/shadow_eval_real_history_v2.fail-under.json")
DEFAULT_SHADOW_FAIL_OVER = Path("eval/shadow_eval_real_history_v2.fail-over.json")
SOURCE_BENCHMARK = "MyPreciousPrivateDogfood"
CASE_ORIGIN = "private_dogfood"
SAFE_EXTERNAL_WORK_DIR_MARKERS = ("generated_answer_dogfood", "generated-answer-dogfood")


def privacy_block() -> dict[str, bool]:
    return {
        "aggregate_only": True,
        "private_paths_rendered": False,
        "queries_rendered": False,
        "reference_answers_rendered": False,
        "generated_answers_rendered": False,
        "memory_text_rendered": False,
        "memory_ids_rendered": False,
        "source_paths_rendered": False,
        "raw_refs_rendered": False,
    }


def resolve_inside_repo(repo: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else repo / path
    try:
        candidate.resolve(strict=False).relative_to(repo.resolve())
    except ValueError as exc:
        raise SystemExit("Refusing to use an output path outside the memory repository") from exc
    return candidate


def relative_posix(repo: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo.resolve()).as_posix()
    except ValueError:
        return ""


def unsafe_work_dir(repo: Path, work_dir: Path) -> bool:
    work_dir_resolved = work_dir.resolve(strict=False)
    repo_resolved = repo.resolve()
    public_resolved = PUBLIC_REPO.resolve()
    repo_tmp = repo_resolved / ".tmp"

    if work_dir_resolved == repo_resolved or repo_resolved.is_relative_to(work_dir_resolved):
        return True
    if work_dir_resolved.is_relative_to(repo_resolved):
        return work_dir_resolved == repo_tmp or not work_dir_resolved.is_relative_to(repo_tmp)
    if work_dir_resolved == public_resolved or public_resolved.is_relative_to(work_dir_resolved):
        return True
    if work_dir_resolved.is_relative_to(public_resolved):
        return True
    if not any(marker in work_dir_resolved.name for marker in SAFE_EXTERNAL_WORK_DIR_MARKERS):
        return True
    return False


def git_status_paths(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit("Unable to inspect memory repository git status")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def preflight_report(repo: Path, case_output: Path | None = None) -> dict[str, Any]:
    status_paths = git_status_paths(repo)
    status_path_set = set(status_paths)
    eval_count = sum(1 for path in status_paths if path.startswith("eval/"))
    tmp_count = sum(1 for path in status_paths if path.startswith(".tmp/"))
    if case_output is not None and case_output.exists():
        case_output_rel = relative_posix(repo, case_output)
        if case_output_rel and case_output_rel not in status_path_set:
            if case_output_rel.startswith("eval/"):
                eval_count += 1
            elif case_output_rel.startswith(".tmp/"):
                tmp_count += 1
    dirty_private_artifacts = eval_count + tmp_count
    failures = []
    status = "preflight_passed"
    if dirty_private_artifacts:
        failures.append({"reason": "dirty_private_dogfood_artifacts"})
        status = "failed"
    return {
        "report_kind": "private_generated_answer_dogfood_gate",
        "report_version": 1,
        "claim_boundary": "private dogfood orchestration only; aggregate reports only",
        "status": status,
        "memory_repo_dirty": bool(status_paths),
        "dirty_status_count": len(status_paths),
        "dirty_eval_artifact_count": eval_count,
        "dirty_tmp_artifact_count": tmp_count,
        "dirty_private_artifact_count": dirty_private_artifacts,
        "failures": failures,
        "privacy": privacy_block(),
    }


def safe_subset(report: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: report[key] for key in keys if key in report}


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("unable to read aggregate JSON report") from exc
    if not isinstance(value, dict):
        raise RuntimeError("aggregate JSON report must be an object")
    return value


def run_json_capture(name: str, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} did not produce JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} report must be an object")
    return value


def run_json_to_file(name: str, command: list[str], output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=handle,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        raise RuntimeError(f"{name} failed")
    return read_json_file(output)


def cleanup_success_artifacts(repo: Path, case_output: Path, work_dir: Path) -> bool:
    try:
        if case_output.exists():
            case_output.unlink()
        tmp_root = repo.resolve() / ".tmp"
        parent = case_output.parent
        while parent.resolve(strict=False).is_relative_to(tmp_root) and parent != tmp_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        if tmp_root.exists():
            try:
                tmp_root.rmdir()
            except OSError:
                pass
        shutil.rmtree(work_dir, ignore_errors=True)
    except OSError:
        return False
    return not case_output.exists() and not work_dir.exists()


def readiness_dimension_statuses(report: dict[str, Any]) -> dict[str, str]:
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, dict):
        return {}
    statuses: dict[str, str] = {}
    for key, value in dimensions.items():
        if isinstance(value, dict) and isinstance(value.get("status"), str):
            statuses[str(key)] = str(value["status"])
    return dict(sorted(statuses.items()))


def run_gate(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    repo = Path(args.memory_repo).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()
    case_output = resolve_inside_repo(repo, Path(args.case_output))
    shadow_cases = Path(args.shadow_cases)
    shadow_fail_under = Path(args.shadow_fail_under_file)
    shadow_fail_over = Path(args.shadow_fail_over_file)
    if not shadow_cases.is_absolute():
        shadow_cases = repo / shadow_cases
    if not shadow_fail_under.is_absolute():
        shadow_fail_under = repo / shadow_fail_under
    if not shadow_fail_over.is_absolute():
        shadow_fail_over = repo / shadow_fail_over

    report = preflight_report(repo, case_output)
    if unsafe_work_dir(repo, work_dir):
        report["status"] = "failed"
        report["failures"].append({"reason": "unsafe_work_dir"})
    if args.preflight_only or report["status"] == "failed":
        return report, 0 if report["status"] == "preflight_passed" else 1

    work_dir.mkdir(parents=True, exist_ok=True)
    answer_records = work_dir / "answer_records.jsonl"
    answer_report_path = work_dir / "answer_report.json"
    answer_details = work_dir / "details.jsonl"
    shadow_report_path = work_dir / "shadow_report.json"

    python = args.python
    try:
        author_dry_run = run_json_capture(
            "case author dry-run",
            [
                python,
                str(PUBLIC_REPO / "templates/agent-memory-repo/tools/author_generated_answer_cases.py"),
                "--repo",
                str(repo),
                "--output",
                relative_posix(repo, case_output),
                "--limit",
                str(args.limit),
                "--abstain-limit",
                str(args.abstain_limit),
                "--dry-run",
            ],
        )
        author_write = run_json_capture(
            "case author write",
            [
                python,
                str(PUBLIC_REPO / "templates/agent-memory-repo/tools/author_generated_answer_cases.py"),
                "--repo",
                str(repo),
                "--output",
                relative_posix(repo, case_output),
                "--limit",
                str(args.limit),
                "--abstain-limit",
                str(args.abstain_limit),
                "--write",
            ],
        )
        case_audit = run_json_capture(
            "case audit",
            [
                python,
                str(PUBLIC_REPO / "benchmarks/generated_answer_case_audit.py"),
                "--cases",
                str(case_output),
                "--require-source-benchmark",
                SOURCE_BENCHMARK,
                "--require-case-origin",
                CASE_ORIGIN,
                "--fail-under",
                "answer_scorable_case_rate=1.0",
                "--fail-over",
                "positive_without_reference_answer=0",
                "--fail-over",
                "privacy_leak_count=0",
                "--fail-over",
                "unsafe_aggregate_identifier_count=0",
            ],
        )
        answer_adapter = run_json_capture(
            "answer record adapter",
            [
                python,
                str(PUBLIC_REPO / "templates/agent-memory-repo/tools/generate_answer_records.py"),
                "--repo",
                str(repo),
                "--cases",
                str(case_output),
                "--output",
                str(answer_records),
                "--limit",
                str(args.answer_search_limit),
            ],
        )
        answer_report = run_json_to_file(
            "generated-answer benchmark",
            [
                python,
                str(PUBLIC_REPO / "benchmarks/generated_answer_benchmark.py"),
                "--cases",
                str(case_output),
                "--answers",
                str(answer_records),
                "--details-jsonl",
                str(answer_details),
                "--fail-under",
                "case_pass_rate=1.0",
                "--fail-under",
                "answer_scorable_case_rate=1.0",
                "--fail-under",
                "abstention_accuracy=1.0",
                "--fail-under",
                "answer_handoff_present_rate=1.0",
                "--fail-under",
                "answer_handoff_support_coverage_rate=1.0",
                "--fail-under",
                "answer_handoff_supported_case_count=1",
                "--fail-under",
                "answer_handoff_abstain_case_count=1",
                "--fail-over",
                "privacy_leak_count=0",
                "--fail-over",
                "failed_case_count=0",
                "--fail-over",
                "missing_answer_count=0",
                "--fail-over",
                "duplicate_answer_count=0",
                "--fail-over",
                "unknown_answer_count=0",
                "--fail-over",
                "positive_without_reference_answer=0",
                "--fail-over",
                "unsupported_claim_count=0",
                "--fail-over",
                "inactive_memory_answer_count=0",
            ],
            answer_report_path,
        )
        shadow_report = run_json_to_file(
            "shadow evaluation",
            [
                python,
                str(PUBLIC_REPO / "templates/agent-memory-repo/tools/shadow_eval_memory_archive.py"),
                "--repo",
                str(repo),
                "--cases",
                str(shadow_cases),
                "--audit-script",
                str(repo / "tools/audit_memory_archive.py"),
                "--fail-under-file",
                str(shadow_fail_under),
                "--fail-over-file",
                str(shadow_fail_over),
            ],
            shadow_report_path,
        )
        readiness_report = run_json_capture(
            "v1 readiness gate",
            [
                python,
                str(PUBLIC_REPO / "benchmarks/v1_readiness_gate.py"),
                "--run-packaged",
                "--require-shadow",
                "--require-answer",
                "--require-answer-source-benchmark",
                SOURCE_BENCHMARK,
                "--require-answer-case-origin",
                CASE_ORIGIN,
                "--shadow-report",
                str(shadow_report_path),
                "--answer-report",
                str(answer_report_path),
            ],
        )
    except RuntimeError as exc:
        report.update(
            {
                "status": "failed",
                "failures": [{"reason": "gate_step_failed", "step": str(exc)}],
                "cleanup_on_failure": bool(args.cleanup_on_failure),
            }
        )
        if args.cleanup_on_failure:
            report["cleanup_success"] = cleanup_success_artifacts(repo, case_output, work_dir)
        return report, 1

    cleanup_success = cleanup_success_artifacts(repo, case_output, work_dir)
    final_preflight = preflight_report(repo, case_output)
    report.update(
        {
            "status": "passed" if cleanup_success and final_preflight["dirty_private_artifact_count"] == 0 else "failed",
            "case_authoring": safe_subset(
                author_write,
                (
                    "candidate_memory_count",
                    "selected_case_count",
                    "positive_case_count",
                    "abstain_case_count",
                    "written_count",
                    "skip_counts",
                    "source_benchmarks",
                    "case_origins",
                ),
            ),
            "case_authoring_dry_run": safe_subset(
                author_dry_run,
                ("selected_case_count", "positive_case_count", "abstain_case_count", "would_write_count"),
            ),
            "case_audit": safe_subset(
                case_audit,
                (
                    "cases",
                    "positive_cases",
                    "abstain_cases",
                    "answer_scorable_case_rate",
                    "positive_without_reference_answer",
                    "privacy_leak_count",
                    "unsafe_aggregate_identifier_count",
                    "source_benchmarks",
                    "case_origins",
                ),
            ),
            "answer_adapter": safe_subset(
                answer_adapter,
                (
                    "cases",
                    "answers_written",
                    "memory_answer_count",
                    "abstention_answer_count",
                    "answer_handoff_supported_case_count",
                    "answer_handoff_abstain_case_count",
                    "answer_handoff_support_coverage_rate",
                    "unsupported_claim_count",
                    "inactive_memory_answer_count",
                    "privacy_leak_count",
                    "no_hit_count",
                    "unsupported_hit_count",
                    "source_benchmarks",
                    "case_origins",
                ),
            ),
            "answer_benchmark": safe_subset(
                answer_report,
                (
                    "cases",
                    "positive_cases",
                    "abstain_cases",
                    "case_pass_rate",
                    "answer_scorable_case_rate",
                    "abstention_accuracy",
                    "answer_normalized_match_rate",
                    "answer_handoff_present_rate",
                    "answer_handoff_support_coverage_rate",
                    "answer_handoff_supported_case_count",
                    "answer_handoff_abstain_case_count",
                    "unsupported_claim_count",
                    "inactive_memory_answer_count",
                    "privacy_leak_count",
                    "failed_case_count",
                    "missing_answer_count",
                    "duplicate_answer_count",
                    "unknown_answer_count",
                    "positive_without_reference_answer",
                    "source_benchmarks",
                    "case_origins",
                ),
            ),
            "shadow_eval": {
                "report_kind": shadow_report.get("report_kind"),
                "metrics": shadow_report.get("metrics", {}),
            },
            "v1_readiness": {
                "overall_status": readiness_report.get("overall_status"),
                "scorecard": readiness_report.get("scorecard", {}),
                "dimension_statuses": readiness_dimension_statuses(readiness_report),
            },
            "cleanup_success": cleanup_success,
            "post_cleanup_private_artifact_count": final_preflight["dirty_private_artifact_count"],
            "privacy": privacy_block(),
        }
    )
    if report["status"] != "passed":
        report["failures"] = [{"reason": "cleanup_or_postflight_failed"}]
    return report, 0 if report["status"] == "passed" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", required=True, help="Private memory repository to evaluate")
    parser.add_argument("--preflight-only", action="store_true", help="Only check dirty private eval/.tmp artifacts")
    parser.add_argument("--case-output", default=str(DEFAULT_CASE_OUTPUT), help="Private case JSONL path inside memory repo")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR), help="Temporary directory for aggregate reports")
    parser.add_argument("--limit", type=int, default=25, help="Positive cases to author")
    parser.add_argument("--abstain-limit", type=int, default=5, help="Expected-abstain cases to author")
    parser.add_argument("--answer-search-limit", type=int, default=5, help="Search result limit for answer extraction")
    parser.add_argument("--shadow-cases", default=str(DEFAULT_SHADOW_CASES), help="Redacted shadow-eval cases")
    parser.add_argument("--shadow-fail-under-file", default=str(DEFAULT_SHADOW_FAIL_UNDER), help="Shadow fail-under JSON")
    parser.add_argument("--shadow-fail-over-file", default=str(DEFAULT_SHADOW_FAIL_OVER), help="Shadow fail-over JSON")
    parser.add_argument("--cleanup-on-failure", action="store_true", help="Remove generated temp files after a failed step")
    parser.add_argument("--python", default=sys.executable, help="Python executable for child tools")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report, exit_code = run_gate(args)
    print(json.dumps(report, sort_keys=True))
    if exit_code:
        print("private generated-answer dogfood gate failed", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
