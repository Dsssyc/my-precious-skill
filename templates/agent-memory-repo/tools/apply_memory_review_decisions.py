#!/usr/bin/env python3
"""Apply or preview memory lifecycle and induction review decisions."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import update_memory_archive  # noqa: E402


RELATION_FIELDS = (
    "supersedes",
    "superseded_by",
    "contradicts",
    "contradicted_by",
    "deprecates",
    "deprecated_by",
)


def load_index_rows(repo: Path, relative: str) -> list[dict]:
    return list(update_memory_archive.iter_jsonl(repo / relative))


def relation_record_counts(nodes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {field: 0 for field in RELATION_FIELDS}
    for node in nodes:
        for field in ("supersedes", "contradicts", "contradicted_by", "deprecates"):
            value = node.get(field)
            if isinstance(value, list) and value:
                counts[field] += 1
        for field in ("superseded_by", "deprecated_by"):
            value = node.get(field)
            if isinstance(value, str) and value:
                counts[field] += 1
    return counts


def count_by(rows: list[dict], field: str) -> dict[str, int]:
    counter = Counter(str(row.get(field) or "") for row in rows)
    counter.pop("", None)
    return dict(sorted(counter.items()))


def decision_result_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("decision_id") or ""),
        str(row.get("action") or ""),
        str(row.get("current_memory_id") or ""),
        str(row.get("older_memory_id") or ""),
        str(row.get("candidate_fingerprint") or ""),
    )


def induction_decision_result_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("decision_id") or ""),
        str(row.get("action") or ""),
        str(row.get("candidate_id") or ""),
        str(row.get("candidate_text_sha256") or ""),
        str(row.get("candidate_fingerprint") or ""),
    )


def induction_promoted_count(results: list[dict]) -> int:
    return sum(
        1
        for result in results
        if result.get("status") == "applied" and result.get("action") == "approve_promote"
    )


def induction_decision_error_counts(candidates: list[dict], decisions: list[dict]) -> dict[str, int]:
    return update_memory_archive.induction_review_decision_error_counts(candidates, decisions)


def split_reflected_induction_results_and_pending_decisions(
    repo: Path,
    decisions: list[dict],
) -> tuple[list[dict], list[dict]]:
    results = load_index_rows(repo, "index/induction_review_decision_results.jsonl")
    if not decisions or not results:
        return [], decisions
    results_by_key = {induction_decision_result_key(result): result for result in results}
    reflected_results: list[dict] = []
    pending_decisions: list[dict] = []
    for decision in decisions:
        result = results_by_key.get(induction_decision_result_key(decision))
        if result is not None:
            reflected_results.append(result)
        else:
            pending_decisions.append(decision)
    return reflected_results, pending_decisions


def induction_dry_run_results(
    repo: Path,
    candidates: list[dict],
    decisions: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    reflected_results, pending_decisions = split_reflected_induction_results_and_pending_decisions(repo, decisions)
    error_counts = induction_decision_error_counts(candidates, pending_decisions)
    if error_counts:
        return [], error_counts
    pending_results = update_memory_archive.apply_induction_review_decisions(candidates, pending_decisions)
    return [*reflected_results, *pending_results], {}


def add_induction_report_fields(
    report: dict[str, Any],
    candidates: list[dict],
    decisions: list[dict],
    results: list[dict],
    error_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    error_counts = error_counts or {}
    report.update(
        {
            "induction_decision_count": len(decisions),
            "induction_review_candidate_count": len(candidates),
            "induction_decision_preflight_passed": not error_counts,
            "induction_decision_error_counts": error_counts,
            "induction_result_status_counts": count_by(results, "status"),
            "induction_result_action_counts": count_by(results, "action"),
            "induction_promoted_count": induction_promoted_count(results),
        }
    )
    return report


def result_reflected_by_nodes(result: dict, nodes_by_id: dict[str, dict]) -> bool:
    status = result.get("status")
    if status == "ignored":
        return True
    if status != "applied":
        return False
    current_id = str(result.get("current_memory_id") or "")
    older_id = str(result.get("older_memory_id") or "")
    current = nodes_by_id.get(current_id)
    old = nodes_by_id.get(older_id)
    if current is None or old is None:
        return False
    action = result.get("action")
    if action == "approve_supersedes":
        return (
            older_id in set(update_memory_archive.string_items(current.get("supersedes")))
            and old.get("superseded_by") == current_id
        )
    if action == "approve_contradicts":
        return (
            older_id in set(update_memory_archive.string_items(current.get("contradicts")))
            and current_id in set(update_memory_archive.string_items(old.get("contradicted_by")))
        )
    if action == "approve_deprecates":
        return (
            older_id in set(update_memory_archive.string_items(current.get("deprecates")))
            and old.get("deprecated_by") == current_id
        )
    return False


def persisted_results_report(
    repo: Path,
    nodes: list[dict],
    candidates: list[dict],
    decisions: list[dict],
) -> dict[str, Any] | None:
    if not decisions:
        return None
    results = load_index_rows(repo, "index/memory_review_decision_results.jsonl")
    if not results:
        return None
    results_by_key = {decision_result_key(result): result for result in results}
    decision_keys = [decision_result_key(decision) for decision in decisions]
    if not decision_keys or any(key not in results_by_key for key in decision_keys):
        return None
    matched_results = [results_by_key[key] for key in decision_keys]
    nodes_by_id = {
        memory_id: node
        for node in nodes
        if (memory_id := update_memory_archive.safe_node_memory_id(node))
    }
    if not all(result_reflected_by_nodes(result, nodes_by_id) for result in matched_results):
        return None
    counts = relation_record_counts(nodes)
    return {
        "decision_count": len(decisions),
        "review_candidate_count": len(candidates),
        "result_status_counts": count_by(matched_results, "status"),
        "result_action_counts": count_by(matched_results, "action"),
        "relation_record_counts_before": counts,
        "relation_record_counts_after": counts,
        "write_enabled": False,
    }


def split_reflected_results_and_pending_decisions(
    repo: Path,
    nodes: list[dict],
    decisions: list[dict],
) -> tuple[list[dict], list[dict]]:
    results = load_index_rows(repo, "index/memory_review_decision_results.jsonl")
    if not decisions or not results:
        return [], decisions
    results_by_key = {decision_result_key(result): result for result in results}
    nodes_by_id = {
        memory_id: node
        for node in nodes
        if (memory_id := update_memory_archive.safe_node_memory_id(node))
    }
    reflected_results: list[dict] = []
    pending_decisions: list[dict] = []
    for decision in decisions:
        result = results_by_key.get(decision_result_key(decision))
        if result is not None and result_reflected_by_nodes(result, nodes_by_id):
            reflected_results.append(result)
        else:
            pending_decisions.append(decision)
    return reflected_results, pending_decisions


def dry_run_report(repo: Path) -> dict[str, Any]:
    nodes = load_index_rows(repo, "index/memories.jsonl")
    candidates = load_index_rows(repo, "index/memory_review_candidates.jsonl")
    decisions = update_memory_archive.load_memory_review_decisions(repo)
    induction_candidates = load_index_rows(repo, "index/induction_review_candidates.jsonl")
    induction_decisions = update_memory_archive.load_induction_review_decisions(repo)
    persisted_report = persisted_results_report(repo, nodes, candidates, decisions)
    if persisted_report is not None:
        induction_results, induction_errors = induction_dry_run_results(repo, induction_candidates, induction_decisions)
        return add_induction_report_fields(
            persisted_report,
            induction_candidates,
            induction_decisions,
            induction_results,
            induction_errors,
        )
    before = relation_record_counts(nodes)
    reflected_results, pending_decisions = split_reflected_results_and_pending_decisions(repo, nodes, decisions)
    pending_results = update_memory_archive.apply_memory_review_decisions(nodes, candidates, pending_decisions)
    results = [*reflected_results, *pending_results]
    induction_results, induction_errors = induction_dry_run_results(repo, induction_candidates, induction_decisions)
    after = relation_record_counts(nodes)
    return add_induction_report_fields(
        {
            "decision_count": len(decisions),
            "review_candidate_count": len(candidates),
            "result_status_counts": count_by(results, "status"),
            "result_action_counts": count_by(results, "action"),
            "relation_record_counts_before": before,
            "relation_record_counts_after": after,
            "write_enabled": False,
        },
        induction_candidates,
        induction_decisions,
        induction_results,
        induction_errors,
    )


def write_report(repo: Path) -> dict[str, Any]:
    before_nodes = load_index_rows(repo, "index/memories.jsonl")
    before = relation_record_counts(before_nodes)
    before_induction_candidates = load_index_rows(repo, "index/induction_review_candidates.jsonl")
    induction_decisions = update_memory_archive.load_induction_review_decisions(repo)
    induction_errors = induction_decision_error_counts(before_induction_candidates, induction_decisions)
    update_memory_archive.raise_induction_review_decision_error(induction_errors)
    update_memory_archive.rebuild_indexes(repo)
    after_nodes = load_index_rows(repo, "index/memories.jsonl")
    results = load_index_rows(repo, "index/memory_review_decision_results.jsonl")
    induction_candidates = load_index_rows(repo, "index/induction_review_candidates.jsonl")
    induction_results = load_index_rows(repo, "index/induction_review_decision_results.jsonl")
    return add_induction_report_fields(
        {
            "decision_count": len(update_memory_archive.load_memory_review_decisions(repo)),
            "review_candidate_count": len(load_index_rows(repo, "index/memory_review_candidates.jsonl")),
            "result_status_counts": count_by(results, "status"),
            "result_action_counts": count_by(results, "action"),
            "relation_record_counts_before": before,
            "relation_record_counts_after": relation_record_counts(after_nodes),
            "write_enabled": True,
        },
        induction_candidates,
        induction_decisions,
        induction_results,
        induction_errors,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", required=True, help="Path to the private memory repository")
    parser.add_argument("--dry-run", action="store_true", help="Preview decisions without writing archive files")
    parser.add_argument("--write", action="store_true", help="Apply decisions by rebuilding archive indexes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        raise SystemExit("--dry-run and --write are mutually exclusive")
    repo = Path(args.memory_repo).expanduser().resolve()
    report = write_report(repo) if args.write else dry_run_report(repo)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
