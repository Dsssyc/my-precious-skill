#!/usr/bin/env python3
"""Run an end-to-end synthetic induction-to-recall benchmark.

The runner creates temporary synthetic source records, runs the real archive
setup and updater, derives recall cases from the generated memory nodes, then
scores those cases through the real layered recall benchmark and search script.
It prints aggregate-only JSON and does not render source content, memory text,
source paths, raw anchors, or per-case details.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import layered_recall_benchmark as recall_benchmark
import updater_induction_benchmark as induction_benchmark


DEFAULT_SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"


@dataclass
class CaseRun:
    case_id: str
    category: str
    source_records: int
    recall_cases: int
    natural_quality: dict[str, int]
    lifecycle_suppression_cases: int
    lifecycle_suppression_hits: int
    memory_id_provenance_cases: int
    memory_id_provenance_hits: int
    recall_details: list[dict[str, Any]]
    failed: bool
    leaked: bool


def ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def validate_e2e_cases(cases: list[dict[str, Any]]) -> None:
    induction_benchmark.validate_cases(cases)
    for case in cases:
        for expected in case.get("expected_memories") or []:
            if not isinstance(expected, dict):
                raise SystemExit("expected_memories entries must be objects")
            query = expected.get("recall_query")
            if not isinstance(query, str) or not query.strip():
                raise SystemExit("expected memory must include non-empty recall_query")
            if expected.get("expect_evidence_drilldown") is not True:
                raise SystemExit("expected memory must include expect_evidence_drilldown=true")
            if expected.get("expect_source_policy") is not True:
                raise SystemExit("expected memory must include expect_source_policy=true")


def prepare_work_dir(work_dir: str | None):
    if work_dir:
        path = Path(work_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise SystemExit("--work-dir must be empty")
        return path, None
    temp = tempfile.TemporaryDirectory(prefix="my-precious-e2e-induction-recall-")
    return Path(temp.name), temp


def node_by_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    for node in nodes:
        if node.get("text") == text:
            return node
    return None


def text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def evidence_paths(node: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for ref in node.get("evidence_refs") or []:
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            path = ref["path"]
            if path not in paths:
                paths.append(path)
    return paths


def first_summary_path(node: dict[str, Any]) -> str:
    paths = text_list(node.get("derived_from"))
    return paths[0] if paths else ""


def first_source_anchor(node: dict[str, Any]) -> str:
    for ref in node.get("raw_refs") or []:
        if not isinstance(ref, dict):
            continue
        path = ref.get("path")
        anchor = ref.get("anchor")
        if isinstance(path, str) and path.strip() and isinstance(anchor, str) and anchor.strip():
            return f"{path}#{anchor}"
    return ""


def relation_targets(case: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    targets: dict[str, dict[str, list[str]]] = {}
    for link in case.get("expected_lifecycle_links") or []:
        if not isinstance(link, dict):
            raise SystemExit("expected_lifecycle_links entries must be objects")
        current_text = str(link.get("current_text") or "")
        target_text = str(link.get("target_text") or "")
        relation = str(link.get("relation") or "")
        target = node_by_text(nodes, target_text)
        target_id = target.get("memory_id") if isinstance(target, dict) else None
        if not isinstance(target_id, str) or not target_id:
            continue
        bucket = targets.setdefault(current_text, {})
        if relation == "supersedes":
            bucket.setdefault("stale_memory_id", []).append(target_id)
        elif relation == "contradicts":
            bucket.setdefault("contradicted_memory_id", []).append(target_id)
        elif relation == "deprecates":
            bucket.setdefault("deprecated_memory_id", []).append(target_id)
        bucket.setdefault("expected_not_memory_id", []).append(target_id)
    return targets


def build_recall_case(
    induction_case: dict[str, Any],
    expected: dict[str, Any],
    node: dict[str, Any],
    target_ids: dict[str, list[str]],
) -> dict[str, Any]:
    memory_id = node.get("memory_id")
    summary_path = first_summary_path(node)
    source_anchor = first_source_anchor(node)
    required_evidence = evidence_paths(node)
    if not isinstance(memory_id, str) or not memory_id:
        raise ValueError("generated memory is missing memory_id")
    if not summary_path:
        raise ValueError("generated memory is missing derived_from")
    if not source_anchor:
        raise ValueError("generated memory is missing raw_refs")
    if not required_evidence:
        raise ValueError("generated memory is missing evidence_refs")

    case_id = induction_benchmark.safe_id(induction_case.get("case_id"), "case_id")
    recall_case: dict[str, Any] = {
        "case_id": f"{case_id}:{memory_id}",
        "query": str(expected["recall_query"]),
        "category": induction_benchmark.safe_category(induction_case.get("category")),
        "source_benchmark": "MyPrecious-e2e-synthetic",
        "expected_layer": str(expected["layer"]),
        "expected_memory_id": memory_id,
        "expected_summary_path": summary_path,
        "expected_source_anchor": source_anchor,
        "required_evidence_paths": required_evidence,
    }
    for key, values in target_ids.items():
        if values:
            recall_case[key] = values if len(values) > 1 else values[0]
    forbidden = induction_case.get("forbidden_output_patterns")
    if isinstance(forbidden, list) and forbidden:
        recall_case["forbidden_output_patterns"] = forbidden
    if expected.get("source") == "explicit":
        recall_case["e2e_forced_memory"] = True
    return recall_case


def score_lifecycle_suppression_probes(
    case: dict[str, Any],
    memory_repo: Path,
    nodes: list[dict[str, Any]],
    search_timeout_s: float,
) -> tuple[int, int, bool]:
    links = case.get("expected_lifecycle_links") or []
    if not links:
        return 0, 0, False
    memory_records = recall_benchmark.load_memory_records(memory_repo)
    cases = 0
    hits = 0
    leaked = False
    forbidden_patterns = text_list(case.get("forbidden_output_patterns"))
    for link in links:
        if not isinstance(link, dict):
            continue
        target_text = str(link.get("target_text") or "")
        target = node_by_text(nodes, target_text)
        target_id = target.get("memory_id") if isinstance(target, dict) else None
        if not isinstance(target_id, str) or not target_id:
            cases += 1
            continue
        query = str(link.get("suppression_query") or target_text)
        search = recall_benchmark.run_search(
            memory_repo / "tools/search_memory.py",
            memory_repo,
            query,
            "memory",
            search_timeout_s,
        )
        combined = search.combined()
        leaked = leaked or not recall_benchmark.sensitive_output_free(combined, forbidden_patterns)
        blocks = recall_benchmark.parse_hit_blocks(combined)
        cases += 1
        hits += int(not recall_benchmark.blocks_contain_memory_ids(blocks, [target_id], memory_records))
    return cases, hits, leaked


def score_memory_id_provenance(
    case: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> tuple[int, int]:
    cases = 0
    hits = 0
    for link in case.get("expected_lifecycle_links") or []:
        if not isinstance(link, dict):
            continue
        cases += 1
        hits += int(
            induction_benchmark.memory_id_provenance_hit(
                nodes,
                str(link.get("current_text") or ""),
                str(link.get("target_text") or ""),
            )
        )
    return cases, hits


def write_recall_cases(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True) + "\n")


def run_updates_for_case(
    case: dict[str, Any],
    case_root: Path,
    setup_script: Path,
) -> tuple[Path, list[induction_benchmark.CommandResult], bool, int]:
    memory_repo = case_root / "synthetic-memory-archive"
    induction_benchmark.setup_archive(memory_repo, setup_script)
    command_outputs: list[induction_benchmark.CommandResult] = []
    failed = False
    source_records = 0
    for record in case["records"]:
        source_records += 1
        source_dir, project_path, _ = induction_benchmark.write_source_record(case_root, record)
        result = induction_benchmark.run_update(memory_repo, source_dir, project_path, record)
        command_outputs.append(result)
        if record.get("expect_refusal") is True:
            failed = failed or not induction_benchmark.refusal_pass(memory_repo, result)
        elif result.returncode != 0:
            failed = True
    if case.get("expected_redaction") is True:
        failed = failed or not induction_benchmark.redaction_pass(induction_benchmark.load_meta_rows(memory_repo))
    return memory_repo, command_outputs, failed, source_records


def score_e2e_case(
    case: dict[str, Any],
    run_root: Path,
    setup_script: Path,
    search_timeout_s: float,
) -> CaseRun:
    case_id = induction_benchmark.safe_id(case.get("case_id"), "case_id")
    category = induction_benchmark.safe_category(case.get("category"))
    case_root = run_root / induction_benchmark.safe_case_slug(case_id)
    case_root.mkdir(parents=True, exist_ok=True)
    memory_repo, command_outputs, failed, source_records = run_updates_for_case(case, case_root, setup_script)
    leaked = induction_benchmark.privacy_leaked(case, command_outputs, memory_repo)
    nodes = induction_benchmark.load_nodes(memory_repo)
    natural_quality = induction_benchmark.score_natural_quality_expectations(case, memory_repo, nodes)
    targets_by_text = relation_targets(case, nodes)
    recall_cases: list[dict[str, Any]] = []
    lifecycle_cases, lifecycle_hits, lifecycle_leaked = score_lifecycle_suppression_probes(
        case,
        memory_repo,
        nodes,
        search_timeout_s,
    )
    memory_id_provenance_cases, memory_id_provenance_hits = score_memory_id_provenance(case, nodes)
    leaked = leaked or lifecycle_leaked

    for expected in case.get("expected_memories") or []:
        expected_text = str(expected.get("text") or "")
        expected_source = str(expected.get("source") or "")
        node = induction_benchmark.node_by_text(nodes, expected_text, expected_source)
        if node is None:
            failed = True
            continue
        try:
            recall_cases.append(
                build_recall_case(
                    case,
                    expected,
                    node,
                    targets_by_text.get(expected_text, {}),
                )
            )
        except ValueError:
            failed = True

    details: list[dict[str, Any]] = []
    if recall_cases:
        recall_cases_path = case_root / "e2e-recall-cases.jsonl"
        write_recall_cases(recall_cases_path, recall_cases)
        loaded_cases = recall_benchmark.load_cases(recall_cases_path)
        _, details = recall_benchmark.score_cases(
            memory_repo,
            loaded_cases,
            memory_repo / "tools/search_memory.py",
            search_timeout_s,
        )
        failed = failed or any(not detail.get("case_pass") for detail in details)
        leaked = leaked or any(not detail.get("privacy_boundary_pass") for detail in details)

    return CaseRun(
        case_id=case_id,
        category=category,
        source_records=source_records,
        recall_cases=len(recall_cases),
        natural_quality=dict(natural_quality),
        lifecycle_suppression_cases=lifecycle_cases,
        lifecycle_suppression_hits=lifecycle_hits,
        memory_id_provenance_cases=memory_id_provenance_cases,
        memory_id_provenance_hits=memory_id_provenance_hits,
        recall_details=details,
        failed=failed
        or leaked
        or lifecycle_hits != lifecycle_cases
        or memory_id_provenance_hits != memory_id_provenance_cases
        or not induction_benchmark.natural_quality_expectations_pass(natural_quality),
        leaked=leaked,
    )


def detail_hit(detail: dict[str, Any], key: str) -> int:
    return int(detail.get(key) is True)


def build_report(cases: list[dict[str, Any]], runs: list[CaseRun], fingerprint: str) -> dict[str, Any]:
    details = [detail for run in runs for detail in run.recall_details]
    forced_details = [
        detail
        for detail in details
        if detail.get("category") == "forced_memory"
    ]

    recall_cases = len(details)
    layer_cases = sum(1 for detail in details if detail.get("expected_layer"))
    evidence_cases = sum(1 for detail in details if detail.get("required_evidence_paths"))
    source_policy_cases = sum(1 for detail in details if detail.get("expected_source_anchor"))
    quality_totals = Counter()
    for run in runs:
        quality_totals.update(run.natural_quality)

    return {
        "report_version": 1,
        "report_kind": "e2e_induction_recall_benchmark",
        "cases_sha256": fingerprint,
        "privacy": {
            "aggregate_only": True,
            "case_details_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "cases": len(cases),
        "source_records": sum(run.source_records for run in runs),
        "recall_cases": recall_cases,
        "category_counts": dict(sorted(Counter(run.category for run in runs).items())),
        "natural_induction_success_rate": ratio(
            quality_totals["natural_hits"],
            quality_totals["natural_cases"],
        ),
        "cross_project_generalization_rate": ratio(
            quality_totals["cross_project_generalization_hits"],
            quality_totals["cross_project_generalization_cases"],
        ),
        "project_scope_precision": ratio(
            quality_totals["project_scope_precision_hits"],
            quality_totals["project_scope_precision_cases"],
        ),
        "ambiguous_candidate_review_rate": ratio(
            quality_totals["review_hits"],
            quality_totals["review_cases"],
        ),
        "process_noise_rejection_rate": ratio(
            quality_totals["noise_hits"],
            quality_totals["noise_cases"],
        ),
        "e2e_memory_recall_at_1": ratio(sum(detail_hit(detail, "memory_recall_at_1") for detail in details), recall_cases),
        "e2e_memory_recall_at_5": ratio(sum(detail_hit(detail, "memory_recall_at_5") for detail in details), recall_cases),
        "e2e_layer_assignment_accuracy": ratio(
            sum(detail_hit(detail, "layer_calibration_hit") for detail in details),
            layer_cases,
        ),
        "e2e_session_drilldown_rate": ratio(
            sum(detail_hit(detail, "session_drilldown_hit") for detail in details),
            recall_cases,
        ),
        "e2e_evidence_reachability_rate": ratio(
            sum(
                int(
                    detail.get("evidence_reachability_hit") is True
                    and detail.get("memory_evidence_ref_reachability_hit") is True
                )
                for detail in details
            ),
            evidence_cases,
        ),
        "e2e_source_policy_pass_rate": ratio(
            sum(detail_hit(detail, "source_depth_policy_pass") for detail in details),
            source_policy_cases,
        ),
        "e2e_lifecycle_active_suppression_rate": ratio(
            sum(run.lifecycle_suppression_hits for run in runs),
            sum(run.lifecycle_suppression_cases for run in runs),
        ),
        "e2e_memory_id_provenance_rate": ratio(
            sum(run.memory_id_provenance_hits for run in runs),
            sum(run.memory_id_provenance_cases for run in runs),
        ),
        "e2e_forced_memory_recall_rate": ratio(
            sum(detail_hit(detail, "memory_recall_at_5") for detail in forced_details),
            len(forced_details),
        ),
        "privacy_leak_count": sum(int(run.leaked) for run in runs),
        "failed_case_count": sum(int(run.failed) for run in runs),
        "case_pass_rate": ratio(sum(int(not run.failed) for run in runs), len(runs)),
    }


def load_threshold_file(path_text: str | None) -> dict[str, float]:
    if not path_text:
        return {}
    path = Path(path_text).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("unable to read threshold file") from exc
    if not isinstance(payload, dict):
        raise SystemExit("threshold file must contain an object")
    thresholds: dict[str, float] = {}
    for key, value in payload.items():
        if not induction_benchmark.SAFE_ID_RE.fullmatch(str(key)):
            raise SystemExit("unsafe threshold metric name")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SystemExit("threshold values must be numeric")
        thresholds[str(key)] = float(value)
    return thresholds


def parse_thresholds(values: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit("thresholds must use metric=value")
        metric, raw_threshold = value.split("=", 1)
        metric = metric.strip()
        if not induction_benchmark.SAFE_ID_RE.fullmatch(metric):
            raise SystemExit("unsafe threshold metric name")
        try:
            thresholds[metric] = float(raw_threshold)
        except ValueError as exc:
            raise SystemExit("threshold value must be numeric") from exc
    return thresholds


def apply_quality_gates(report: dict[str, Any], fail_under: dict[str, float], fail_over: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for metric, threshold in sorted(fail_under.items()):
        value = report.get(metric)
        if not isinstance(value, (int, float)) or float(value) < threshold:
            failures.append(f"{metric} below threshold")
    for metric, threshold in sorted(fail_over.items()):
        value = report.get(metric)
        if not isinstance(value, (int, float)) or float(value) > threshold:
            failures.append(f"{metric} above threshold")
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Synthetic e2e induction-to-recall benchmark JSONL")
    parser.add_argument("--work-dir", help="Empty directory for temporary synthetic archives")
    parser.add_argument("--setup-script", default=str(DEFAULT_SETUP_SCRIPT), help="Archive setup script to run")
    parser.add_argument(
        "--search-timeout-s",
        type=float,
        default=recall_benchmark.DEFAULT_SEARCH_TIMEOUT_S,
        help="Per-depth search subprocess timeout in seconds",
    )
    parser.add_argument("--fail-under", action="append", default=[], help="Require metric >= value")
    parser.add_argument("--fail-over", action="append", default=[], help="Require metric <= value")
    parser.add_argument("--fail-under-file", help="JSON object of lower-bound metric thresholds")
    parser.add_argument("--fail-over-file", help="JSON object of upper-bound metric thresholds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases_path = Path(args.cases).expanduser().resolve()
    setup_script = Path(args.setup_script).expanduser().resolve()
    if not setup_script.is_file():
        raise SystemExit("setup script not found")
    cases = list(induction_benchmark.iter_jsonl(cases_path))
    validate_e2e_cases(cases)
    run_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        runs = [
            score_e2e_case(case, run_root, setup_script, args.search_timeout_s)
            for case in cases
        ]
        report = build_report(cases, runs, induction_benchmark.cases_fingerprint(cases_path))
        fail_under = {
            **load_threshold_file(args.fail_under_file),
            **parse_thresholds(args.fail_under),
        }
        fail_over = {
            **load_threshold_file(args.fail_over_file),
            **parse_thresholds(args.fail_over),
        }
        failures = apply_quality_gates(report, fail_under, fail_over)
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
