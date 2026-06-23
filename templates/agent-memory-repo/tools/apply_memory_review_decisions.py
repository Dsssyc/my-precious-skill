#!/usr/bin/env python3
"""Apply or preview memory lifecycle review decisions."""

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


def dry_run_report(repo: Path) -> dict[str, Any]:
    nodes = load_index_rows(repo, "index/memories.jsonl")
    candidates = load_index_rows(repo, "index/memory_review_candidates.jsonl")
    decisions = update_memory_archive.load_memory_review_decisions(repo)
    persisted_report = persisted_results_report(repo, nodes, candidates, decisions)
    if persisted_report is not None:
        return persisted_report
    before = relation_record_counts(nodes)
    results = update_memory_archive.apply_memory_review_decisions(nodes, candidates, decisions)
    after = relation_record_counts(nodes)
    return {
        "decision_count": len(decisions),
        "review_candidate_count": len(candidates),
        "result_status_counts": count_by(results, "status"),
        "result_action_counts": count_by(results, "action"),
        "relation_record_counts_before": before,
        "relation_record_counts_after": after,
        "write_enabled": False,
    }


def write_report(repo: Path) -> dict[str, Any]:
    before_nodes = load_index_rows(repo, "index/memories.jsonl")
    before = relation_record_counts(before_nodes)
    update_memory_archive.rebuild_indexes(repo)
    after_nodes = load_index_rows(repo, "index/memories.jsonl")
    results = load_index_rows(repo, "index/memory_review_decision_results.jsonl")
    return {
        "decision_count": len(update_memory_archive.load_memory_review_decisions(repo)),
        "review_candidate_count": len(load_index_rows(repo, "index/memory_review_candidates.jsonl")),
        "result_status_counts": count_by(results, "status"),
        "result_action_counts": count_by(results, "action"),
        "relation_record_counts_before": before,
        "relation_record_counts_after": relation_record_counts(after_nodes),
        "write_enabled": True,
    }


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
