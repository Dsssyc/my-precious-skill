#!/usr/bin/env python3
"""Gate packaged scope-aware generated-answer adapter consumption.

The gate installs a clean packaged archive, writes only synthetic public
memory rows and answer cases, runs the copied deployment
tools/generate_answer_records.py, and verifies answer-or-abstain decisions
from context-package handoff metadata instead of free-form search output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import scope_answer_handoff_gate as handoff_gate


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ANSWER_BENCHMARK = REPO_ROOT / "benchmarks/generated_answer_benchmark.py"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SOURCE_BENCHMARK = "MyPreciousScopeAdapterSynthetic"
CASE_ORIGIN = "packaged_generated_answer_scope_adapter_gate"

VISIBLE_LEAK_MARKERS = (
    handoff_gate.GLOBAL_TEXT,
    handoff_gate.DOMAIN_TEXT,
    handoff_gate.PROJECT_TEXT,
    handoff_gate.WRONG_PROJECT_TEXT,
    handoff_gate.SECOND_PROJECT_TEXT,
    handoff_gate.STALE_BROAD_TEXT,
    handoff_gate.CURRENT_REPLACEMENT_TEXT,
    handoff_gate.RAW_SOURCE_SENTINEL,
    handoff_gate.SECRET_SENTINEL,
)


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def to_report(self) -> dict[str, object]:
        report: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            report["returncode"] = self.returncode
        return report


@dataclass(frozen=True)
class AdapterRun:
    report: dict[str, Any]
    stdout: str
    stderr: str


def run_command(command: list[str], stage: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            yield value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def memory_text_by_id(repo: Path, memory_id: str) -> str:
    for row in iter_jsonl(repo / "index/memories.jsonl"):
        if row.get("memory_id") == memory_id and isinstance(row.get("text"), str):
            return str(row["text"])
    raise GateFailure("build_answer_cases", "expected_memory_missing")


def answer_case(repo: Path, spec: handoff_gate.CaseSpec) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": spec.case_id,
        "query": spec.query,
        "source_benchmark": SOURCE_BENCHMARK,
        "case_origin": CASE_ORIGIN,
        "forbidden_output_patterns": [
            r"RAW V28 TRANSCRIPT SHOULD NOT RENDER",
            r"cookie\s*=\s*V28_SHOULD_NOT_RENDER",
        ],
    }
    if spec.expected_action == "answer":
        row.update(
            {
                "category": "generated_answer_positive",
                "reference_answer": memory_text_by_id(repo, spec.expected_memory_id),
                "expected_memory_id": spec.expected_memory_id,
            }
        )
    else:
        row.update(
            {
                "category": "generated_answer_abstain",
                "reference_answer": "not enough information",
                "expected_abstain": True,
            }
        )
    if spec.preferred_scope:
        row["preferred_scope"] = spec.preferred_scope
    if spec.project_path:
        row["project_path"] = spec.project_path
    return row


def malformed_answer_case() -> dict[str, Any]:
    return {
        "case_id": handoff_gate.MALFORMED_HANDOFF_CASE,
        "query": "v29 malformed context package adapter failure",
        "category": "generated_answer_abstain",
        "source_benchmark": SOURCE_BENCHMARK,
        "case_origin": CASE_ORIGIN,
        "reference_answer": "not enough information",
        "expected_abstain": True,
        "preferred_scope": "global",
        "forbidden_output_patterns": [
            r"RAW V28 TRANSCRIPT SHOULD NOT RENDER",
            r"cookie\s*=\s*V28_SHOULD_NOT_RENDER",
        ],
    }


def run_adapter(
    *,
    repo: Path,
    cases: Path,
    output: Path,
    search_script: Path | None = None,
) -> AdapterRun:
    command = [
        sys.executable,
        str(repo / "tools/generate_answer_records.py"),
        "--repo",
        str(repo),
        "--cases",
        str(cases),
        "--output",
        str(output),
        "--limit",
        "5",
    ]
    if search_script is not None:
        command.extend(["--search-script", str(search_script)])
    result = run_command(command, "generate_answer_records", cwd=repo)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("generate_answer_records", "invalid_json_report") from exc
    if not isinstance(report, dict):
        raise GateFailure("generate_answer_records", "non_object_report")
    return AdapterRun(report=report, stdout=result.stdout, stderr=result.stderr)


def write_malformed_search_script(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "print('{\"report_kind\":\"wrong_package\",\"answerability\":{\"status\":\"supported\"}}')\n",
        encoding="utf-8",
    )


def run_generated_answer_benchmark(cases: Path, answers: Path) -> dict[str, Any]:
    result = run_command(
        [
            sys.executable,
            str(GENERATED_ANSWER_BENCHMARK),
            "--cases",
            str(cases),
            "--answers",
            str(answers),
            "--fail-under",
            "case_pass_rate=1.0",
            "--fail-under",
            "answer_normalized_match_rate=1.0",
            "--fail-under",
            "abstention_accuracy=1.0",
            "--fail-under",
            "answer_handoff_present_rate=1.0",
            "--fail-under",
            "answer_handoff_support_coverage_rate=1.0",
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
            "unsupported_claim_count=0",
            "--fail-over",
            "inactive_memory_answer_count=0",
        ],
        "generated_answer_benchmark",
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("generated_answer_benchmark", "invalid_json_report") from exc
    if not isinstance(payload, dict):
        raise GateFailure("generated_answer_benchmark", "non_object_report")
    return payload


def answer_handoff(row: dict[str, Any]) -> dict[str, Any]:
    handoff = row.get("answer_handoff")
    return handoff if isinstance(handoff, dict) else {}


def support_refs_cover_answer(handoff: dict[str, Any]) -> bool:
    refs = handoff.get("support_refs")
    if not isinstance(refs, list):
        return False
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        memory_id = ref.get("memory_id")
        summary_paths = ref.get("summary_paths")
        evidence_refs = ref.get("evidence_refs")
        if (
            isinstance(memory_id, str)
            and memory_id.strip()
            and isinstance(summary_paths, list)
            and any(isinstance(path, str) and path.strip() for path in summary_paths)
            and isinstance(evidence_refs, list)
            and any(isinstance(evidence_ref, str) and evidence_ref.strip() for evidence_ref in evidence_refs)
        ):
            return True
    return False


def support_memory_id(handoff: dict[str, Any]) -> str:
    refs = handoff.get("support_refs")
    if not isinstance(refs, list) or not refs:
        return ""
    first = refs[0]
    if not isinstance(first, dict):
        return ""
    memory_id = first.get("memory_id")
    return memory_id if isinstance(memory_id, str) else ""


def context_package_meta(handoff: dict[str, Any]) -> dict[str, Any]:
    package = handoff.get("context_package")
    return package if isinstance(package, dict) else {}


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def count_visible_privacy_leaks(rendered: str) -> int:
    return sum(1 for marker in VISIBLE_LEAK_MARKERS if marker in rendered)


def build_report(
    *,
    repo: Path,
    valid_specs: list[handoff_gate.CaseSpec],
    all_cases: list[dict[str, Any]],
    answer_rows: list[dict[str, Any]],
    valid_adapter: AdapterRun,
    malformed_adapter: AdapterRun,
    benchmark_report: dict[str, Any],
) -> dict[str, Any]:
    answers_by_case = {str(row.get("case_id")): row for row in answer_rows}
    positive_specs = [spec for spec in valid_specs if spec.expected_action == "answer"]
    negative_case_ids = {
        spec.case_id for spec in valid_specs if spec.expected_action == "abstain"
    } | {handoff_gate.MALFORMED_HANDOFF_CASE}
    case_outcomes: dict[str, str] = {}
    for case in all_cases:
        case_id = str(case["case_id"])
        handoff = answer_handoff(answers_by_case.get(case_id, {}))
        case_outcomes[case_id] = "abstain" if handoff.get("abstained") is True else "answer"

    positive_hits = 0
    support_ref_hits = 0
    for spec in positive_specs:
        row = answers_by_case.get(spec.case_id, {})
        handoff = answer_handoff(row)
        if support_refs_cover_answer(handoff):
            support_ref_hits += 1
        if (
            handoff.get("abstained") is not True
            and support_refs_cover_answer(handoff)
            and support_memory_id(handoff) == spec.expected_memory_id
            and row.get("generated_answer") == memory_text_by_id(repo, spec.expected_memory_id)
        ):
            positive_hits += 1

    abstention_hits = sum(
        1
        for case_id in negative_case_ids
        if answer_handoff(answers_by_case.get(case_id, {})).get("abstained") is True
    )
    project_handoff = answer_handoff(answers_by_case.get(handoff_gate.PROJECT_HANDOFF_CASE, {}))
    wrong_project_handoff = answer_handoff(answers_by_case.get(handoff_gate.WRONG_PROJECT_HANDOFF_CASE, {}))
    missing_context_handoff = answer_handoff(answers_by_case.get(handoff_gate.MISSING_PROJECT_CONTEXT_CASE, {}))
    stale_handoff = answer_handoff(answers_by_case.get(handoff_gate.STALE_BROAD_HANDOFF_CASE, {}))
    malformed_handoff = answer_handoff(answers_by_case.get(handoff_gate.MALFORMED_HANDOFF_CASE, {}))
    malformed_meta = context_package_meta(malformed_handoff)

    unsupported_claim_count = int(benchmark_report.get("unsupported_claim_count") or 0)
    visible_text = json.dumps(
        {
            "valid_adapter_report": valid_adapter.report,
            "malformed_adapter_report": malformed_adapter.report,
            "benchmark_report": benchmark_report,
            "case_outcomes": case_outcomes,
        },
        sort_keys=True,
    )
    visible_text += valid_adapter.stdout + valid_adapter.stderr + malformed_adapter.stdout + malformed_adapter.stderr
    privacy_leak_count = int(benchmark_report.get("privacy_leak_count") or 0) + count_visible_privacy_leaks(visible_text)

    valid_case_count = len(valid_specs)
    valid_parse_success = int(valid_adapter.report.get("context_package_parse_success_count") or 0)
    scope_field_rate = float(valid_adapter.report.get("context_package_scope_field_pass_through_rate") or 0.0)
    metrics: dict[str, object] = {
        "adapter_context_package_parse_success_rate": safe_rate(valid_parse_success, valid_case_count),
        "adapter_scope_supported_answer_accuracy": safe_rate(positive_hits, len(positive_specs)),
        "adapter_scope_abstention_accuracy": safe_rate(abstention_hits, len(negative_case_ids)),
        "adapter_scope_support_ref_coverage_rate": safe_rate(support_ref_hits, len(positive_specs)),
        "adapter_project_override_accuracy": float(
            project_handoff.get("abstained") is not True
            and support_memory_id(project_handoff) == "mem_v28_project_handoff"
            and support_refs_cover_answer(project_handoff)
        ),
        "adapter_wrong_project_rejection_count": int(
            wrong_project_handoff.get("abstained") is True
            and wrong_project_handoff.get("abstain_reason") == "wrong_project_scope_mismatch"
        ),
        "adapter_missing_project_context_rejection_count": int(
            missing_context_handoff.get("abstained") is True
            and missing_context_handoff.get("abstain_reason")
            == "missing_project_context_for_project_specific_handoff"
        ),
        "adapter_stale_broad_rejection_count": int(
            stale_handoff.get("abstained") is True
            and stale_handoff.get("abstain_reason") == "no_active_current_support"
        ),
        "adapter_malformed_fail_closed_count": int(
            malformed_handoff.get("abstained") is True
            and malformed_handoff.get("abstain_reason") == "context_package_unavailable"
            and malformed_meta.get("parse_success") is False
        ),
        "adapter_scope_field_pass_through_rate": scope_field_rate,
        "unsupported_claim_count": unsupported_claim_count,
        "privacy_leak_count": privacy_leak_count,
    }
    expected_outcomes = {
        handoff_gate.GLOBAL_HANDOFF_CASE: "answer",
        handoff_gate.DOMAIN_HANDOFF_CASE: "answer",
        handoff_gate.PROJECT_HANDOFF_CASE: "answer",
        handoff_gate.WRONG_PROJECT_HANDOFF_CASE: "abstain",
        handoff_gate.MISSING_PROJECT_CONTEXT_CASE: "abstain",
        handoff_gate.STALE_BROAD_HANDOFF_CASE: "abstain",
        handoff_gate.NO_HIT_HANDOFF_CASE: "abstain",
        handoff_gate.MALFORMED_HANDOFF_CASE: "abstain",
    }
    status = "passed"
    if (
        case_outcomes != expected_outcomes
        or metrics["adapter_context_package_parse_success_rate"] != 1.0
        or metrics["adapter_scope_supported_answer_accuracy"] != 1.0
        or metrics["adapter_scope_abstention_accuracy"] != 1.0
        or metrics["adapter_scope_support_ref_coverage_rate"] != 1.0
        or metrics["adapter_project_override_accuracy"] != 1.0
        or metrics["adapter_wrong_project_rejection_count"] != 1
        or metrics["adapter_missing_project_context_rejection_count"] != 1
        or metrics["adapter_stale_broad_rejection_count"] != 1
        or metrics["adapter_malformed_fail_closed_count"] != 1
        or metrics["adapter_scope_field_pass_through_rate"] != 1.0
        or unsupported_claim_count != 0
        or privacy_leak_count != 0
    ):
        status = "failed"
    return {
        "report_kind": "generated_answer_scope_adapter_gate",
        "report_version": 1,
        "status": status,
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "generated_answer_adapter": True,
            "search_tool": "copied_deployment_tools_search_memory",
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "handoff_source": "generated_answer_records_answer_handoff",
            "project_path_cases": True,
            "preferred_scopes": ["global", "domain", "project"],
            "limit": 5,
        },
        "case_outcomes": case_outcomes,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "generated_answers_rendered": False,
            "reference_answers_rendered": False,
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "local_private_paths_rendered": False,
        },
        "claim_boundary": (
            "packaged generated-answer adapter scope contract only; not live LLM "
            "answer quality, ranking overhaul, vector search, ontology discovery, "
            "private archive quality, or public leaderboard parity"
        ),
    }


def run_gate(root: Path) -> dict[str, object]:
    repo = handoff_gate.setup_packaged_archive(root)
    handoff_gate.write_synthetic_archive(repo)
    valid_specs = handoff_gate.case_specs(root)
    valid_cases = [answer_case(repo, spec) for spec in valid_specs]
    malformed_case = malformed_answer_case()

    valid_cases_path = root / "answer_cases_valid.jsonl"
    valid_answers_path = root / "answer_records_valid.jsonl"
    malformed_cases_path = root / "answer_cases_malformed.jsonl"
    malformed_answers_path = root / "answer_records_malformed.jsonl"
    all_cases_path = root / "answer_cases_all.jsonl"
    all_answers_path = root / "answer_records_all.jsonl"
    write_jsonl(valid_cases_path, valid_cases)
    write_jsonl(malformed_cases_path, [malformed_case])
    write_malformed_search_script(root / "malformed_search.py")

    valid_adapter = run_adapter(repo=repo, cases=valid_cases_path, output=valid_answers_path)
    malformed_adapter = run_adapter(
        repo=repo,
        cases=malformed_cases_path,
        output=malformed_answers_path,
        search_script=root / "malformed_search.py",
    )

    all_cases = [*valid_cases, malformed_case]
    write_jsonl(all_cases_path, all_cases)
    all_answers_path.write_text(
        valid_answers_path.read_text(encoding="utf-8")
        + malformed_answers_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    benchmark_report = run_generated_answer_benchmark(all_cases_path, all_answers_path)
    return build_report(
        repo=repo,
        valid_specs=valid_specs,
        all_cases=all_cases,
        answer_rows=list(iter_jsonl(all_answers_path)),
        valid_adapter=valid_adapter,
        malformed_adapter=malformed_adapter,
        benchmark_report=benchmark_report,
    )


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-answer-scope-adapter-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-answer-scope-adapter-", dir=parent))
    return root, None, root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent directory for generated clean-room artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_work_root(args.work_dir)
        report = run_gate(root)
    except (GateFailure, handoff_gate.GateFailure) as failure:
        to_report = failure.to_report() if hasattr(failure, "to_report") else {"reason": str(failure)}
        print(
            json.dumps(
                {
                    "report_kind": "generated_answer_scope_adapter_gate",
                    "status": "failed",
                    "failures": [to_report],
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)
        if temp is not None:
            temp.cleanup()

    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
