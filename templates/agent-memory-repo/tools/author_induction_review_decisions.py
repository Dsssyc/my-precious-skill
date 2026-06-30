#!/usr/bin/env python3
"""Author aggregate-safe induction review decision skeletons."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import update_memory_archive  # noqa: E402


DECISION_REL_PATH = Path("reviews/induction_review_decisions.jsonl")


def load_index_rows(repo: Path, relative: str) -> list[dict]:
    return list(update_memory_archive.iter_jsonl(repo / relative))


def induction_decision_result_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("decision_id") or ""),
        str(row.get("action") or ""),
        str(row.get("candidate_id") or ""),
        str(row.get("candidate_text_sha256") or ""),
        str(row.get("candidate_fingerprint") or ""),
    )


def split_reflected_and_pending_decisions(repo: Path, decisions: list[dict]) -> tuple[list[dict], list[dict]]:
    results = load_index_rows(repo, "index/induction_review_decision_results.jsonl")
    if not decisions or not results:
        return [], decisions
    results_by_key = {induction_decision_result_key(result): result for result in results}
    reflected: list[dict] = []
    pending: list[dict] = []
    for decision in decisions:
        if induction_decision_result_key(decision) in results_by_key:
            reflected.append(decision)
        else:
            pending.append(decision)
    return reflected, pending


def decision_candidate_keys(decisions: list[dict]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for decision in decisions:
        candidate_id = decision.get("candidate_id")
        candidate_fingerprint = decision.get("candidate_fingerprint")
        if isinstance(candidate_id, str) and candidate_id:
            keys.add(("candidate_id", candidate_id))
        if isinstance(candidate_fingerprint, str) and candidate_fingerprint:
            keys.add(("candidate_fingerprint", candidate_fingerprint))
    return keys


def pending_candidates(candidates: list[dict], pending_decisions: list[dict]) -> list[dict]:
    existing_keys = decision_candidate_keys(pending_decisions)
    pending: list[dict] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        candidate_fingerprint = update_memory_archive.induction_review_candidate_fingerprint(candidate)
        if ("candidate_id", candidate_id) in existing_keys:
            continue
        if ("candidate_fingerprint", candidate_fingerprint) in existing_keys:
            continue
        pending.append(candidate)
    return pending


def skeleton_decision(candidate: dict, default_action: str) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "")
    candidate_text_sha256 = str(candidate.get("candidate_text_sha256") or "")
    candidate_fingerprint = update_memory_archive.induction_review_candidate_fingerprint(candidate)
    return {
        "decision_id": f"induction_review_{candidate_id}",
        "action": default_action,
        "candidate_id": candidate_id,
        "candidate_text_sha256": candidate_text_sha256,
        "candidate_fingerprint": candidate_fingerprint,
    }


def build_skeletons(candidates: list[dict], default_action: str) -> list[dict]:
    return [skeleton_decision(candidate, default_action) for candidate in candidates]


def increment_error(counts: dict[str, int], key: str) -> None:
    if key in update_memory_archive.INDUCTION_REVIEW_DECISION_SET_ERROR_KEYS:
        counts[key] = counts.get(key, 0) + 1


def merge_error_counts(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    merged = dict(first)
    for key, value in second.items():
        merged[key] = merged.get(key, 0) + value
    return dict(sorted(merged.items()))


def merge_decision_set_error_counts(decisions: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen_decision_ids: set[str] = set()
    seen_exact_rows: set[str] = set()
    for decision in decisions:
        row_fingerprint = json.dumps(decision, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if row_fingerprint in seen_exact_rows:
            increment_error(counts, "exact_duplicate")
        else:
            seen_exact_rows.add(row_fingerprint)

        action = decision.get("action")
        decision_id = decision.get("decision_id")
        candidate_id = decision.get("candidate_id")
        candidate_text_sha256 = decision.get("candidate_text_sha256")
        candidate_fingerprint = decision.get("candidate_fingerprint")
        if (
            not isinstance(action, str)
            or action not in update_memory_archive.INDUCTION_REVIEW_ACTIONS
            or not update_memory_archive.is_safe_memory_review_id(decision_id)
            or not update_memory_archive.is_safe_induction_review_candidate_id(candidate_id)
            or not update_memory_archive.is_safe_sha256_hex(candidate_text_sha256)
            or not isinstance(candidate_fingerprint, str)
        ):
            increment_error(counts, "unsafe")
            continue

        safe_decision_id = str(decision_id)
        if safe_decision_id in seen_decision_ids:
            increment_error(counts, "duplicate_decision_id")
        else:
            seen_decision_ids.add(safe_decision_id)
    return dict(sorted(counts.items()))


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        existing_text = path.read_text(encoding="utf-8")
        if existing_text and not existing_text.endswith("\n"):
            prefix = "\n"
    text = prefix + "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def author_report(repo: Path, default_action: str, write_enabled: bool) -> tuple[dict[str, Any], list[dict]]:
    candidates = load_index_rows(repo, "index/induction_review_candidates.jsonl")
    decisions = update_memory_archive.load_induction_review_decisions(repo)
    reflected_decisions, pending_decisions = split_reflected_and_pending_decisions(repo, decisions)
    candidate_rows = pending_candidates(candidates, pending_decisions)
    skeletons = build_skeletons(candidate_rows, default_action)
    validation_rows = [*pending_decisions, *skeletons]
    candidate_error_counts = update_memory_archive.induction_review_decision_error_counts(candidates, validation_rows)
    candidate_scope_error_counts = {
        key: value
        for key, value in candidate_error_counts.items()
        if key in {"conflicting_candidate_action", "conflicting_fingerprint_action", "stale", "unknown"}
    }
    merge_scope_error_counts = merge_decision_set_error_counts([*decisions, *skeletons])
    error_counts = merge_error_counts(merge_scope_error_counts, candidate_scope_error_counts)
    report = {
        "report_kind": "induction_review_decision_authoring",
        "write_enabled": write_enabled,
        "default_action": default_action,
        "candidate_count": len(candidates),
        "existing_decision_count": len(decisions),
        "reflected_decision_count": len(reflected_decisions),
        "pending_decision_count": len(pending_decisions),
        "pending_candidate_count": len(candidate_rows),
        "skeleton_count": len(skeletons),
        "would_append_count": len(skeletons),
        "appended_count": 0,
        "preflight_passed": not error_counts,
        "decision_error_counts": error_counts,
    }
    return report, skeletons


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", required=True, help="Path to the private memory repository")
    parser.add_argument("--dry-run", action="store_true", help="Preview skeleton authoring without writing")
    parser.add_argument("--write", action="store_true", help="Append safe skeleton decisions to the private reviews file")
    parser.add_argument(
        "--default-action",
        default="noop",
        choices=["noop"],
        help="Non-mutating action to place in generated skeleton rows",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        raise SystemExit("--dry-run and --write are mutually exclusive")
    repo = Path(args.memory_repo).expanduser().resolve()
    write_enabled = bool(args.write)
    report, skeletons = author_report(repo, args.default_action, write_enabled)
    if write_enabled and not report["preflight_passed"]:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    if write_enabled:
        target = repo / DECISION_REL_PATH
        if not update_memory_archive.is_safe_repo_path(repo, target):
            raise SystemExit("Refusing to write unsafe induction review decision path")
        append_jsonl(target, skeletons)
        report["appended_count"] = len(skeletons)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
