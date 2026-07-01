#!/usr/bin/env python3
"""Run a privacy-safe shadow evaluation against an agent memory archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import search_memory  # noqa: E402


DEFAULT_LIMIT = 5
MEMORY_LAYERS = {"global", "domain", "project"}


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def safe_diagnostic_text(value: object, limit: int = 240) -> str:
    return search_memory.safe_display_text(str(value), limit)


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSONL at {path.name}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"invalid JSONL at {path.name}:{line_no}: expected object")
            yield value


def text_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def safe_memory_id(value: object) -> str:
    if not search_memory.is_safe_memory_identifier(value):
        return ""
    return str(value)


def case_label_hash(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def expected_memory_ids(case: dict) -> list[str]:
    ids: list[str] = []
    for memory_id in text_list(case.get("expected_memory_ids")):
        safe_id = safe_memory_id(memory_id)
        if safe_id and safe_id not in ids:
            ids.append(safe_id)
    singular_id = safe_memory_id(case.get("expected_memory_id"))
    if singular_id and singular_id not in ids:
        ids.append(singular_id)
    return ids


def expected_layer(case: dict) -> str:
    layer = str(case.get("expected_layer") or "").strip()
    return layer if layer in MEMORY_LAYERS else ""


def forbidden_patterns(case: dict) -> list[str]:
    patterns: list[str] = []
    for idx, pattern in enumerate(text_list(case.get("forbidden_output_patterns"))):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SystemExit(f"invalid forbidden_output_patterns[{idx}]: {exc}") from exc
        patterns.append(pattern)
    return patterns


def forbidden_output_violation_count(outputs: list[str], patterns: list[str]) -> int:
    if not patterns:
        return 0
    combined = "\n".join(outputs)
    return sum(1 for pattern in patterns if re.search(pattern, combined))


def load_memory_records(repo: Path) -> list[dict]:
    path = repo / "index" / "memories.jsonl"
    if not path.is_file():
        return []
    return list(iter_jsonl(path))


def count_legacy_session_records(repo: Path) -> int:
    path = repo / "index" / "sessions.jsonl"
    if not path.is_file():
        return 0
    return sum(1 for _ in iter_jsonl(path))


def load_cases(path: Path | None) -> list[dict]:
    if path is None:
        return []
    if not path.is_file():
        raise SystemExit("case file does not exist")
    return list(iter_jsonl(path))


def top_memory_hits(repo: Path, query: str, limit: int, preferred_scope: str = "") -> list[search_memory.Hit]:
    query_tokens = search_memory.unique_query_tokens(query)
    if not query_tokens:
        return []
    return search_memory.merge_hits(
        repo,
        search_memory.collect_memory_hits(repo, query_tokens, [], "all", preferred_scope),
    )[:limit]


def top_memory_ids(repo: Path, query: str, limit: int) -> list[str]:
    out: list[str] = []
    for hit in top_memory_hits(repo, query, limit):
        memory_id = safe_memory_id(hit.memory_id)
        if memory_id:
            out.append(memory_id)
    return out


def inactive_memory_ids(records: list[dict]) -> set[str]:
    supersedes_by_memory_id = search_memory.collect_supersedes_by_memory_id(records)
    contradicts_by_memory_id = search_memory.collect_contradicts_by_memory_id(records)
    deprecates_by_memory_id = search_memory.collect_deprecates_by_memory_id(records)
    inactive = set(search_memory.collect_forward_superseded_ids(supersedes_by_memory_id))
    inactive.update(search_memory.collect_forward_contradicted_ids(contradicts_by_memory_id))
    inactive.update(search_memory.collect_forward_deprecated_ids(deprecates_by_memory_id))
    for record in records:
        memory_id = safe_memory_id(record.get("memory_id"))
        if not memory_id:
            continue
        if search_memory.has_confirmed_superseded_by(record, supersedes_by_memory_id):
            inactive.add(memory_id)
        if search_memory.has_confirmed_contradicted_by(record, contradicts_by_memory_id):
            inactive.add(memory_id)
        if search_memory.has_confirmed_deprecated_by(record, deprecates_by_memory_id):
            inactive.add(memory_id)
        if search_memory.has_deprecation_marker(record):
            inactive.add(memory_id)
    return inactive


def classify_noise_source(hit: search_memory.Hit, case: dict, inactive_ids: set[str]) -> str:
    memory_id = safe_memory_id(hit.memory_id)
    if memory_id in inactive_ids:
        return "inactive_lifecycle"
    if "low-signal-only" in hit.why or "broad-field-only" in hit.why:
        return "low_signal_memory_node"
    expected_layer = str(case.get("expected_layer") or "").strip()
    if expected_layer and hit.layer and hit.layer != expected_layer:
        return "scope_mixed"
    return "broad_lexical_match"


def relation_value(value: object, limit: int = 120) -> str:
    return search_memory.safe_display_scalar(value or "", limit)


def record_relation(record: dict) -> tuple[str, str, str]:
    return (
        relation_value(record.get("layer"), 60),
        relation_value(record.get("scope"), 120),
        relation_value(record.get("topic"), 120),
    )


def hit_relation(hit: search_memory.Hit) -> tuple[str, str, str]:
    return (
        relation_value(hit.layer, 60),
        relation_value(hit.scope, 120),
        relation_value(hit.topic, 120),
    )


def new_noise_sources() -> dict[str, int]:
    return {
        "broad_lexical_match": 0,
        "scope_mixed": 0,
        "inactive_lifecycle": 0,
        "low_signal_memory_node": 0,
    }


def new_noise_relation_to_expected() -> dict[str, int]:
    return {
        "same_layer_scope_topic": 0,
        "same_layer_scope_diff_topic": 0,
        "same_layer_diff_scope_same_topic": 0,
        "same_layer_diff_scope_topic": 0,
        "diff_layer_same_scope_topic": 0,
        "diff_layer": 0,
        "expected_record_missing": 0,
    }


def classify_noise_relation_to_expected(hit: search_memory.Hit, expected_records: list[dict]) -> str:
    expected_relations = [record_relation(record) for record in expected_records]
    expected_relations = [relation for relation in expected_relations if any(relation)]
    if not expected_relations:
        return "expected_record_missing"

    hit_layer, hit_scope, hit_topic = hit_relation(hit)

    def same_layer(relation: tuple[str, str, str]) -> bool:
        return bool(hit_layer and relation[0] and hit_layer == relation[0])

    def same_scope(relation: tuple[str, str, str]) -> bool:
        return bool(hit_scope and relation[1] and hit_scope == relation[1])

    def same_topic(relation: tuple[str, str, str]) -> bool:
        return bool(hit_topic and relation[2] and hit_topic == relation[2])

    if any(same_layer(relation) and same_scope(relation) and same_topic(relation) for relation in expected_relations):
        return "same_layer_scope_topic"
    if any(same_layer(relation) and same_scope(relation) for relation in expected_relations):
        return "same_layer_scope_diff_topic"
    if any(same_layer(relation) and same_topic(relation) for relation in expected_relations):
        return "same_layer_diff_scope_same_topic"
    if any(same_layer(relation) for relation in expected_relations):
        return "same_layer_diff_scope_topic"
    if any(same_scope(relation) and same_topic(relation) for relation in expected_relations):
        return "diff_layer_same_scope_topic"
    return "diff_layer"


def evaluate_cases(
    repo: Path,
    cases: list[dict],
    records: list[dict],
    limit: int,
    output_texts: list[str] | None = None,
) -> dict[str, Any]:
    totals: dict[str, int] = {
        "cases": 0,
        "positive_cases": 0,
        "abstain_cases": 0,
        "abstain_hits": 0,
        "abstain_false_positive_results": 0,
        "recall_hits": 0,
        "relevant_results": 0,
        "total_results": 0,
        "suppression_cases": 0,
        "suppression_hits": 0,
        "privacy_cases": 0,
        "privacy_hits": 0,
        "forbidden_output_violations": 0,
    }
    noise_sources = new_noise_sources()
    noise_relation_to_expected = new_noise_relation_to_expected()
    details: list[dict[str, Any]] = []
    inactive_ids = inactive_memory_ids(records)
    records_by_id = record_id_map(records)
    for case in cases:
        query = str(case.get("query") or "").strip()
        if not query:
            continue
        totals["cases"] += 1
        hits = top_memory_hits(repo, query, limit, expected_layer(case))
        result_ids = [memory_id for hit in hits if (memory_id := safe_memory_id(hit.memory_id))]
        expected_ids = expected_memory_ids(case)
        expected_id_set = set(expected_ids)
        expected_not_memory_ids = [
            memory_id for memory_id in text_list(case.get("expected_not_memory_id")) if safe_memory_id(memory_id)
        ]
        patterns = forbidden_patterns(case)
        violation_count = forbidden_output_violation_count(output_texts or [], patterns)
        if patterns:
            totals["privacy_cases"] += 1
            if violation_count == 0:
                totals["privacy_hits"] += 1
            else:
                totals["forbidden_output_violations"] += 1
        case_noise_sources = new_noise_sources()
        case_noise_relation_to_expected = new_noise_relation_to_expected()
        relevant_count = 0
        abstention_hit = None
        if case.get("expected_abstain") is True:
            totals["abstain_cases"] += 1
            abstention_hit = len(result_ids) == 0
            if abstention_hit:
                totals["abstain_hits"] += 1
            else:
                totals["abstain_false_positive_results"] += len(result_ids)
        elif expected_ids:
            totals["positive_cases"] += 1
            totals["total_results"] += len(result_ids)
            relevant_count = sum(1 for memory_id in result_ids if memory_id in expected_id_set)
            totals["relevant_results"] += relevant_count
            if relevant_count:
                totals["recall_hits"] += 1
            expected_records = [records_by_id[memory_id] for memory_id in expected_ids if memory_id in records_by_id]
            for hit in hits:
                hit_id = safe_memory_id(hit.memory_id)
                if hit_id and hit_id not in expected_id_set:
                    source = classify_noise_source(hit, case, inactive_ids)
                    noise_sources[source] += 1
                    case_noise_sources[source] += 1
                    relation = classify_noise_relation_to_expected(hit, expected_records)
                    noise_relation_to_expected[relation] += 1
                    case_noise_relation_to_expected[relation] += 1
        if expected_not_memory_ids:
            totals["suppression_cases"] += 1
            if all(memory_id not in result_ids for memory_id in expected_not_memory_ids):
                totals["suppression_hits"] += 1
        details.append(
            {
                "case_index": totals["cases"],
                "case_label_hash": case_label_hash(case.get("case_id")),
                "positive_case": bool(expected_ids),
                "expected_memory_count": len(expected_ids),
                "result_count": len(result_ids),
                "relevant_result_count": relevant_count,
                "noise_result_count": max(0, len(result_ids) - relevant_count) if expected_ids else 0,
                "recall_hit": bool(relevant_count),
                "abstention_hit": abstention_hit,
                "abstain_false_positive_result_count": (
                    len(result_ids) if case.get("expected_abstain") is True and result_ids else 0
                ),
                "suppression_hit": (
                    None
                    if not expected_not_memory_ids
                    else all(memory_id not in result_ids for memory_id in expected_not_memory_ids)
                ),
                "noise_sources_at_5": case_noise_sources,
                "noise_relation_to_expected_at_5": case_noise_relation_to_expected,
                "forbidden_output_patterns_count": len(patterns),
                "forbidden_output_violation_count": violation_count,
                "privacy_boundary_pass": violation_count == 0,
            }
        )
    precision = ratio(totals["relevant_results"], totals["total_results"])
    return {
        **totals,
        "memory_recall_at_5": ratio(totals["recall_hits"], totals["positive_cases"]),
        "memory_precision_at_5": precision,
        "top_k_noise_at_5": None if precision is None else 1.0 - precision,
        "noise_sources_at_5": noise_sources,
        "noise_relation_to_expected_at_5": noise_relation_to_expected,
        "abstain_pass_rate": ratio(totals["abstain_hits"], totals["abstain_cases"]),
        "abstain_false_positive_results": totals["abstain_false_positive_results"],
        "active_memory_suppression": ratio(totals["suppression_hits"], totals["suppression_cases"]),
        "privacy_boundary_pass_rate": ratio(totals["privacy_hits"], totals["privacy_cases"]),
        "case_details": details,
    }


def diagnostic_case_summary(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_ordinal": detail["case_index"],
        "case_label_hash": detail.get("case_label_hash", ""),
        "expected_memory_count": detail["expected_memory_count"],
        "result_count": detail["result_count"],
        "relevant_result_count": detail["relevant_result_count"],
        "noise_result_count": detail["noise_result_count"],
        "abstain_false_positive_result_count": detail["abstain_false_positive_result_count"],
        "forbidden_output_patterns_count": detail["forbidden_output_patterns_count"],
        "forbidden_output_violation_count": detail["forbidden_output_violation_count"],
        "noise_sources_at_5": detail["noise_sources_at_5"],
        "noise_relation_to_expected_at_5": detail["noise_relation_to_expected_at_5"],
    }


def diagnostic_failure_types(details: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "recall_miss": [],
        "abstain_false_positive": [],
        "suppression_failure": [],
        "privacy_failure": [],
        "top_k_noise": [],
    }
    for detail in details:
        summary = diagnostic_case_summary(detail)
        if detail["positive_case"] and not detail["recall_hit"]:
            groups["recall_miss"].append(summary)
        if detail["abstention_hit"] is False:
            groups["abstain_false_positive"].append(summary)
        if detail["suppression_hit"] is False:
            groups["suppression_failure"].append(summary)
        if not detail["privacy_boundary_pass"]:
            groups["privacy_failure"].append(summary)
        if detail["noise_result_count"] > 0:
            groups["top_k_noise"].append(summary)
    return {
        failure_type: {"count": len(cases), "cases": cases}
        for failure_type, cases in groups.items()
    }


def diagnostic_summary(case_metrics: dict[str, Any]) -> dict[str, Any]:
    failure_types = diagnostic_failure_types(case_metrics["case_details"])
    failure_ordinals = {
        case["case_ordinal"]
        for summary in failure_types.values()
        for case in summary["cases"]
    }
    return {
        "privacy": {
            "aggregate_only": True,
            "case_labels_hashed": True,
            "queries_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_refs_rendered": False,
            "raw_refs_rendered": False,
            "forbidden_patterns_rendered": False,
        },
        "totals": {
            "failure_case_count": len(failure_ordinals),
            "failure_observation_count": sum(summary["count"] for summary in failure_types.values()),
        },
        "failure_types": failure_types,
    }


def record_id_map(records: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for record in records:
        memory_id = safe_memory_id(record.get("memory_id"))
        if memory_id:
            out[memory_id] = record
    return out


def list_field(record: dict, field: str) -> list[str]:
    return [item for item in text_list(record.get(field)) if safe_memory_id(item)]


def lifecycle_integrity(records: list[dict]) -> dict[str, Any]:
    by_id = record_id_map(records)
    checked_refs = 0
    broken_refs = 0
    illegal_state_records = 0
    relation_counts = {
        "supersedes": 0,
        "contradicts": 0,
        "deprecates": 0,
        "superseded_by": 0,
        "contradicted_by": 0,
        "deprecated_by": 0,
    }
    for record in records:
        memory_id = safe_memory_id(record.get("memory_id"))
        if not memory_id:
            continue
        supersedes = list_field(record, "supersedes")
        contradicts = list_field(record, "contradicts")
        deprecates = list_field(record, "deprecates")
        superseded_by = safe_memory_id(record.get("superseded_by"))
        deprecated_by = safe_memory_id(record.get("deprecated_by"))
        contradicted_by = list_field(record, "contradicted_by")
        if superseded_by and deprecated_by:
            illegal_state_records += 1
        if supersedes and deprecates:
            illegal_state_records += 1
        for target_id in supersedes:
            checked_refs += 1
            relation_counts["supersedes"] += 1
            if target_id not in by_id or by_id[target_id].get("superseded_by") != memory_id:
                broken_refs += 1
        for target_id in contradicts:
            checked_refs += 1
            relation_counts["contradicts"] += 1
            target = by_id.get(target_id)
            if target is None or memory_id not in list_field(target, "contradicted_by"):
                broken_refs += 1
        for target_id in deprecates:
            checked_refs += 1
            relation_counts["deprecates"] += 1
            if target_id not in by_id or by_id[target_id].get("deprecated_by") != memory_id:
                broken_refs += 1
        if superseded_by:
            checked_refs += 1
            relation_counts["superseded_by"] += 1
            target = by_id.get(superseded_by)
            if target is None or memory_id not in list_field(target, "supersedes"):
                broken_refs += 1
        for target_id in contradicted_by:
            checked_refs += 1
            relation_counts["contradicted_by"] += 1
            target = by_id.get(target_id)
            if target is None or memory_id not in list_field(target, "contradicts"):
                broken_refs += 1
        if deprecated_by:
            checked_refs += 1
            relation_counts["deprecated_by"] += 1
            target = by_id.get(deprecated_by)
            if target is None or memory_id not in list_field(target, "deprecates"):
                broken_refs += 1
    failures = broken_refs + illegal_state_records
    return {
        "checked_refs": checked_refs,
        "broken_refs": broken_refs,
        "illegal_state_records": illegal_state_records,
        "relation_counts": relation_counts,
        "score": 1.0 if failures == 0 else 0.0,
    }


def provenance_coverage(records: list[dict]) -> dict[str, Any]:
    total = len(records)
    with_derived_from = 0
    with_evidence_refs = 0
    with_any_provenance = 0
    for record in records:
        derived_from = text_list(record.get("derived_from"))
        evidence_refs = record.get("evidence_refs", [])
        has_derived_from = bool(derived_from)
        has_evidence_refs = isinstance(evidence_refs, list) and bool(evidence_refs)
        with_derived_from += int(has_derived_from)
        with_evidence_refs += int(has_evidence_refs)
        with_any_provenance += int(has_derived_from or has_evidence_refs)
    return {
        "records": total,
        "with_derived_from": with_derived_from,
        "with_evidence_refs": with_evidence_refs,
        "score": ratio(with_any_provenance, total),
        "evidence_ref_coverage": ratio(with_evidence_refs, total),
    }


def run_audit(repo: Path, audit_script: Path | None) -> tuple[dict[str, Any], list[str]]:
    if audit_script is None:
        return {"status": "skipped"}, []
    result = subprocess.run(
        [
            sys.executable,
            str(audit_script),
            "--memory-repo",
            str(repo),
            "--skip-process-update-check",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return (
        {
            "status": "passed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
        },
        [result.stdout, result.stderr],
    )


def nested_metric_value(payload: dict[str, Any], metric: str) -> object:
    value: object = payload
    for part in metric.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            raise KeyError(metric)
        value = value[part]
    return value


def threshold_metric_value(payload: dict[str, Any], metric: str, option: str) -> float:
    metric = metric.strip()
    display_metric = safe_diagnostic_text(metric)
    candidate_metrics = [metric]
    if not metric.startswith("metrics."):
        candidate_metrics.append(f"metrics.{metric}")
    value: object = None
    found = False
    for candidate in candidate_metrics:
        try:
            value = nested_metric_value(payload, candidate)
        except KeyError:
            continue
        found = True
        break
    if not found or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"{option} metric is not numeric in shadow eval output: {display_metric}")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise SystemExit(f"{option} metric is not finite in shadow eval output: {display_metric}")
    return numeric_value


def parse_thresholds(values: list[str], payload: dict[str, Any], option: str) -> list[tuple[str, float]]:
    thresholds: list[tuple[str, float]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{option} must use metric=threshold, got: {safe_diagnostic_text(value)}")
        metric, raw_threshold = value.split("=", 1)
        metric = metric.strip()
        raw_threshold = raw_threshold.strip()
        threshold_metric_value(payload, metric, option)
        display_metric = safe_diagnostic_text(metric)
        display_threshold = safe_diagnostic_text(raw_threshold)
        try:
            threshold = float(raw_threshold)
        except ValueError as exc:
            raise SystemExit(f"{option} threshold must be numeric for {display_metric}: {display_threshold}") from exc
        if not math.isfinite(threshold):
            raise SystemExit(f"{option} threshold must be finite for {display_metric}: {display_threshold}")
        thresholds.append((metric, threshold))
    return thresholds


def load_threshold_file(path: Path, payload: dict[str, Any], option: str) -> list[tuple[str, float]]:
    display_path = safe_diagnostic_text(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"unable to read {option} {display_path}: {safe_diagnostic_text(exc)}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON at {display_path}: {safe_diagnostic_text(exc)}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{option} must contain a JSON object: {display_path}")
    thresholds: list[tuple[str, float]] = []
    for metric, raw_threshold in data.items():
        if not isinstance(metric, str) or not metric.strip():
            raise SystemExit(f"{option} metric keys must be non-empty strings: {display_path}")
        metric = metric.strip()
        threshold_metric_value(payload, metric, option)
        display_metric = safe_diagnostic_text(metric)
        if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
            raise SystemExit(f"{option} threshold must be numeric for {display_metric}")
        threshold = float(raw_threshold)
        if not math.isfinite(threshold):
            raise SystemExit(f"{option} threshold must be finite for {display_metric}")
        thresholds.append((metric, threshold))
    return thresholds


def merge_thresholds(*groups: list[tuple[str, float]]) -> list[tuple[str, float]]:
    merged: dict[str, float] = {}
    for group in groups:
        for metric, threshold in group:
            merged[metric] = threshold
    return list(merged.items())


def threshold_failure_details(
    payload: dict[str, Any],
    thresholds: list[tuple[str, float]],
    comparison: str,
    option: str,
) -> list[dict[str, float | str]]:
    failures: list[dict[str, float | str]] = []
    for metric, threshold in thresholds:
        value = threshold_metric_value(payload, metric, option)
        if (comparison == "below" and value < threshold) or (comparison == "above" and value > threshold):
            failures.append({"comparison": comparison, "metric": metric, "value": value, "threshold": threshold})
    return failures


def format_threshold_failures(failures: list[dict[str, float | str]]) -> str:
    parts: list[str] = []
    for failure in failures:
        metric = safe_diagnostic_text(failure["metric"])
        value = failure["value"]
        threshold = failure["threshold"]
        direction = "below" if failure["comparison"] == "below" else "above"
        parts.append(f"{metric}={value} {direction} threshold {threshold}")
    return "shadow eval threshold failed: " + "; ".join(parts)


def build_report(repo: Path, cases: list[dict], audit_script: Path | None, limit: int) -> dict[str, Any]:
    records = load_memory_records(repo)
    audit, audit_outputs = run_audit(repo, audit_script)
    case_metrics = evaluate_cases(repo, cases, records, limit, audit_outputs)
    memory_index_present = (repo / "index" / "memories.jsonl").is_file()
    return {
        "report_version": 1,
        "report_kind": "real_archive_shadow_evaluation",
        "privacy": {
            "aggregate_only": True,
            "private_probe_cases_rendered": False,
            "queries_rendered": False,
            "memory_ids_rendered": False,
            "source_content_rendered": False,
            "memory_text_rendered": False,
            "source_refs_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "archive": {
            "format": "layered" if memory_index_present else "legacy",
            "memory_index_present": memory_index_present,
            "memory_records": len(records),
            "legacy_session_records": count_legacy_session_records(repo),
        },
        "probe_cases": {
            "cases": case_metrics["cases"],
            "positive_cases": case_metrics["positive_cases"],
            "abstain_cases": case_metrics["abstain_cases"],
        },
        "metrics": {
            "memory_recall_at_5": case_metrics["memory_recall_at_5"],
            "memory_precision_at_5": case_metrics["memory_precision_at_5"],
            "top_k_noise_at_5": case_metrics["top_k_noise_at_5"],
            "noise_sources_at_5": case_metrics["noise_sources_at_5"],
            "noise_relation_to_expected_at_5": case_metrics["noise_relation_to_expected_at_5"],
            "abstain_pass_rate": case_metrics["abstain_pass_rate"],
            "abstain_false_positive_results": case_metrics["abstain_false_positive_results"],
            "active_memory_suppression": case_metrics["active_memory_suppression"],
            "privacy_boundary_pass_rate": case_metrics["privacy_boundary_pass_rate"],
            "forbidden_output_violations": case_metrics["forbidden_output_violations"],
            "provenance_coverage": provenance_coverage(records),
            "lifecycle_integrity": lifecycle_integrity(records),
        },
        "case_details": case_metrics["case_details"],
        "diagnostics": diagnostic_summary(case_metrics),
        "audit": audit,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    parser.add_argument("--cases", help="Optional redacted probe cases JSONL")
    parser.add_argument("--audit-script", help="Optional audit_memory_archive.py path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Top-k memory hits to score")
    parser.add_argument(
        "--fail-under",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Exit non-zero when a numeric aggregate metric is below a threshold",
    )
    parser.add_argument(
        "--fail-under-file",
        action="append",
        default=[],
        metavar="PATH",
        help="JSON object of lower-bound aggregate metric thresholds",
    )
    parser.add_argument(
        "--fail-over",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Exit non-zero when a numeric aggregate metric is above a threshold",
    )
    parser.add_argument(
        "--fail-over-file",
        action="append",
        default=[],
        metavar="PATH",
        help="JSON object of upper-bound aggregate metric thresholds",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")
    repo = Path(args.repo)
    cases = load_cases(Path(args.cases) if args.cases else None)
    audit_script = Path(args.audit_script) if args.audit_script else None
    report = build_report(repo, cases, audit_script, args.limit)
    file_under_thresholds: list[tuple[str, float]] = []
    for threshold_file in args.fail_under_file:
        file_under_thresholds.extend(load_threshold_file(Path(threshold_file), report, "--fail-under-file"))
    file_over_thresholds: list[tuple[str, float]] = []
    for threshold_file in args.fail_over_file:
        file_over_thresholds.extend(load_threshold_file(Path(threshold_file), report, "--fail-over-file"))
    under_thresholds = merge_thresholds(file_under_thresholds, parse_thresholds(args.fail_under, report, "--fail-under"))
    over_thresholds = merge_thresholds(file_over_thresholds, parse_thresholds(args.fail_over, report, "--fail-over"))
    failures = threshold_failure_details(report, under_thresholds, "below", "--fail-under")
    failures.extend(threshold_failure_details(report, over_thresholds, "above", "--fail-over"))
    if failures:
        print(format_threshold_failures(failures), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
