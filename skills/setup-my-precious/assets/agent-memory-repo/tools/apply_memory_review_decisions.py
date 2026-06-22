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


def dry_run_report(repo: Path) -> dict[str, Any]:
    nodes = load_index_rows(repo, "index/memories.jsonl")
    candidates = load_index_rows(repo, "index/memory_review_candidates.jsonl")
    decisions = update_memory_archive.load_memory_review_decisions(repo)
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
