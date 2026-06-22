#!/usr/bin/env python3
"""Report privacy-safe induction and consolidation metrics for a memory archive."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import update_memory_archive  # noqa: E402


CANDIDATE_FIELDS = ("reusable_facts", "decisions", "unresolved_tasks")
SAFE_DETAIL_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
SAFE_LAYERS = {"global", "domain", "project"}
RATIO_BUCKETS = (
    ("0.00-0.24", 0.0, 0.25),
    ("0.25-0.44", 0.25, 0.45),
    ("0.45-0.59", 0.45, 0.60),
    ("0.60-0.74", 0.60, 0.75),
    ("0.75-1.00", 0.75, 1.01),
)


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def iter_candidate_field_values(rows: Iterable[dict]) -> Iterable[str]:
    for row in rows:
        for field in CANDIDATE_FIELDS:
            value = row.get(field)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, (str, int, float)):
                    text = update_memory_archive.normalize_memory_text(
                        update_memory_archive.strip_reusable_fact_prefix(str(item))
                    )
                    if text:
                        yield text


def candidate_rejection_reason(text: str) -> str:
    if update_memory_archive.is_noisy_text(text) or update_memory_archive.is_raw_prompt_text(text):
        return "noise"
    if update_memory_archive.is_process_update(text):
        return "process_update"
    if update_memory_archive.is_low_signal_memory_text(text):
        return "low_signal"
    return ""


def count_candidates(rows: list[dict]) -> dict[str, int]:
    total = 0
    accepted = 0
    process_noise_rejected = 0
    low_signal_rejected = 0
    for text in iter_candidate_field_values(rows):
        total += 1
        reason = candidate_rejection_reason(text)
        if reason in {"noise", "process_update"}:
            process_noise_rejected += 1
        elif reason == "low_signal":
            low_signal_rejected += 1
        else:
            accepted += 1
    return {
        "induction_candidate_count": total,
        "accepted_induction_candidate_count": accepted,
        "process_noise_rejected_count": process_noise_rejected,
        "low_signal_rejected_count": low_signal_rejected,
    }


def text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str) and value:
        return [value]
    return []


def safe_memory_id(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value):
        return value
    return ""


def node_id_map(nodes: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for node in nodes:
        memory_id = safe_memory_id(node.get("memory_id"))
        if memory_id:
            out[memory_id] = node
    return out


def supersession_reciprocity(nodes: list[dict]) -> float | None:
    by_id = node_id_map(nodes)
    checked = 0
    reciprocal = 0
    for node in nodes:
        memory_id = safe_memory_id(node.get("memory_id"))
        if not memory_id:
            continue
        for target_id in text_list(node.get("supersedes")):
            if not safe_memory_id(target_id):
                continue
            checked += 1
            target = by_id.get(target_id)
            if target is not None and target.get("superseded_by") == memory_id:
                reciprocal += 1
        superseded_by = safe_memory_id(node.get("superseded_by"))
        if superseded_by:
            checked += 1
            target = by_id.get(superseded_by)
            if target is not None and memory_id in text_list(target.get("supersedes")):
                reciprocal += 1
    if checked == 0:
        return 1.0
    return ratio(reciprocal, checked)


def count_contradiction_links(nodes: list[dict]) -> int:
    count = 0
    for node in nodes:
        for target_id in text_list(node.get("contradicts")):
            if safe_memory_id(target_id):
                count += 1
    return count


def count_by_reason(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason") or "")
        if not safe_detail_value(reason):
            reason = "unsafe_reason"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def ratio_bucket(value: object) -> str:
    try:
        ratio_value = float(value)
    except (TypeError, ValueError):
        ratio_value = 0.0
    if ratio_value < 0:
        ratio_value = 0.0
    for label, lower, upper in RATIO_BUCKETS:
        if lower <= ratio_value < upper:
            return label
    return "0.75-1.00"


def token_bucket(value: object) -> str:
    try:
        token_count = int(value)
    except (TypeError, ValueError):
        token_count = 0
    if token_count <= 3:
        return "0-3"
    if token_count <= 5:
        return "4-5"
    if token_count <= 8:
        return "6-8"
    return "9+"


def bucket_counts(rows: list[dict], field: str, bucket_fn) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        bucket = bucket_fn(row.get(field))
        counts[bucket] = counts.get(bucket, 0) + 1
    return dict(sorted(counts.items()))


def safe_layer(value: object) -> str:
    layer = str(value or "")
    return layer if layer in SAFE_LAYERS else "unknown"


def review_pair_distributions(review_candidates: list[dict], nodes: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    by_id = node_id_map(nodes)
    layer_counts: dict[str, int] = {}
    scope_counts: dict[str, int] = {}
    for candidate in review_candidates:
        current = by_id.get(safe_memory_id(candidate.get("current_memory_id")))
        old = by_id.get(safe_memory_id(candidate.get("older_memory_id")))
        if current is None or old is None:
            layer_pair = "unknown->unknown"
            scope_pair = "unknown"
        else:
            current_layer = safe_layer(current.get("layer"))
            old_layer = safe_layer(old.get("layer"))
            layer_pair = f"{current_layer}->{old_layer}"
            current_scope = str(current.get("scope") or "")
            old_scope = str(old.get("scope") or "")
            if not current_scope or not old_scope:
                scope_pair = "unknown"
            elif current_layer != old_layer:
                scope_pair = "different_layer"
            elif current_scope == old_scope:
                scope_pair = "same_scope"
            else:
                scope_pair = "same_layer_different_scope"
        layer_counts[layer_pair] = layer_counts.get(layer_pair, 0) + 1
        scope_counts[scope_pair] = scope_counts.get(scope_pair, 0) + 1
    return dict(sorted(layer_counts.items())), dict(sorted(scope_counts.items()))


def review_queue_metrics(review_candidates: list[dict], nodes: list[dict]) -> dict[str, Any]:
    reason_distribution = count_by_reason(review_candidates)
    layer_pair_distribution, scope_pair_distribution = review_pair_distributions(review_candidates, nodes)
    represented_review_count = sum(
        int(candidate.get("compressed_candidate_count") or 1)
        for candidate in review_candidates
    )
    return {
        "review_candidate_count": len(review_candidates),
        "represented_review_candidate_count": represented_review_count,
        "compressed_review_candidate_count": max(0, represented_review_count - len(review_candidates)),
        "ambiguous_scope_review_count": reason_distribution.get(
            "ambiguous_scope_narrowing_requires_review",
            0,
        ),
        "low_confidence_semantic_overlap_review_count": reason_distribution.get(
            "low_confidence_semantic_overlap_requires_review",
            0,
        ),
        "review_reason_distribution": reason_distribution,
        "overlap_ratio_buckets": bucket_counts(review_candidates, "overlap_ratio", ratio_bucket),
        "overlap_token_buckets": bucket_counts(review_candidates, "overlap_token_count", token_bucket),
        "layer_pair_distribution": layer_pair_distribution,
        "scope_pair_distribution_safe": scope_pair_distribution,
    }


def trace_metrics(traces: list[dict]) -> dict[str, int]:
    return {
        "auto_merge_count": sum(1 for trace in traces if trace.get("decision") == "merge"),
        "skipped_lifecycle_count": sum(
            int(trace.get("compressed_candidate_count") or 1)
            for trace in traces
            if trace.get("decision") == "skip"
        ),
    }


def evidence_ref_reachability(repo: Path, nodes: list[dict]) -> float | None:
    checked = 0
    reachable = 0
    for node in nodes:
        evidence_refs = node.get("evidence_refs", [])
        if not isinstance(evidence_refs, list):
            continue
        for ref in evidence_refs:
            if not isinstance(ref, dict):
                continue
            path = ref.get("path")
            quote_id = ref.get("quote_id")
            if not isinstance(path, str) or not isinstance(quote_id, str):
                continue
            checked += 1
            evidence_path = update_memory_archive.archive_ref_path(repo, path)
            if evidence_path is not None and update_memory_archive.evidence_quote_id_exists(evidence_path, quote_id):
                reachable += 1
    if checked == 0:
        return 1.0
    return ratio(reachable, checked)


def safe_detail_value(value: object) -> bool:
    return isinstance(value, str) and bool(SAFE_DETAIL_RE.fullmatch(value))


def case_detail(case_id: str, category: str, decision: str, failure_reason: str = "") -> dict[str, str]:
    row = {
        "case_id": case_id,
        "category": category,
        "decision": decision,
        "failure_reason": failure_reason,
    }
    if not all(safe_detail_value(value) or (key == "failure_reason" and value == "") for key, value in row.items()):
        raise SystemExit("unsafe audit case detail")
    return row


def privacy_pass_rate(details: list[dict[str, str]]) -> float:
    if not details:
        return 1.0
    safe = 0
    for detail in details:
        values_safe = all(
            safe_detail_value(value) or (key == "failure_reason" and value == "")
            for key, value in detail.items()
        )
        safe += int(values_safe)
    return ratio(safe, len(details)) or 0.0


def build_case_details(metrics: dict[str, Any]) -> list[dict[str, str]]:
    details = [
        case_detail("induction-candidates", "induction", "count"),
        case_detail("promotion-count", "induction", "promote"),
    ]
    if metrics["process_noise_rejected_count"]:
        details.append(case_detail("process-noise-rejection", "induction", "reject"))
    if metrics["ambiguous_scope_review_count"]:
        details.append(case_detail("ambiguous-scope-review", "consolidation", "review"))
    if metrics["low_confidence_semantic_overlap_review_count"]:
        details.append(case_detail("semantic-overlap-review", "consolidation", "review"))
    if metrics["contradiction_preserved_count"]:
        details.append(case_detail("contradiction-preserved", "consolidation", "preserve"))
    details.append(
        case_detail(
            "supersession-reciprocity",
            "lifecycle",
            "pass" if metrics["supersession_reciprocity"] == 1.0 else "fail",
            "" if metrics["supersession_reciprocity"] == 1.0 else "broken-ref",
        )
    )
    details.append(
        case_detail(
            "evidence-ref-reachability",
            "provenance",
            "pass" if metrics["evidence_ref_reachability"] == 1.0 else "fail",
            "" if metrics["evidence_ref_reachability"] == 1.0 else "missing-ref",
        )
    )
    return details


def build_report(repo: Path) -> dict[str, Any]:
    rows = update_memory_archive.collect_meta(repo)
    candidate_counts = count_candidates(rows)
    nodes = update_memory_archive.build_memory_nodes(rows, repo)
    automatic_nodes = [node for node in nodes if node.get("source") == "automatic"]
    review_candidates = update_memory_archive.build_memory_review_candidates(nodes)
    consolidation_traces = update_memory_archive.build_memory_consolidation_traces(nodes, review_candidates)
    metrics: dict[str, Any] = {
        **candidate_counts,
        "promoted_memory_count": len(automatic_nodes),
        **review_queue_metrics(review_candidates, nodes),
        **trace_metrics(consolidation_traces),
        "contradiction_preserved_count": count_contradiction_links(automatic_nodes),
        "supersession_reciprocity": supersession_reciprocity(automatic_nodes),
        "evidence_ref_reachability": evidence_ref_reachability(repo, automatic_nodes),
    }
    details = build_case_details(metrics)
    metrics["real_history_privacy_pass_rate"] = privacy_pass_rate(details)
    return {
        "report_version": 1,
        "report_kind": "induction_consolidation_audit",
        "privacy": {
            "aggregate_only": True,
            "case_details_safe": metrics["real_history_privacy_pass_rate"] == 1.0,
            "source_content_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "archive": {
            "session_meta_records": len(rows),
            "memory_review_index_present": (repo / "index" / "memory_review_candidates.jsonl").is_file(),
            "memory_consolidation_trace_index_present": (repo / "index" / "memory_consolidation_trace.jsonl").is_file(),
            "dry_run_only": True,
        },
        "metrics": metrics,
        "case_details": details,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "sessions").is_dir():
        raise SystemExit("--repo must point to a memory archive with a sessions directory")
    report = build_report(repo)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
