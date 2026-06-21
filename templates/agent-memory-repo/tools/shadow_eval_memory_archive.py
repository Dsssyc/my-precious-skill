#!/usr/bin/env python3
"""Run a privacy-safe shadow evaluation against an agent memory archive."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import search_memory  # noqa: E402


DEFAULT_LIMIT = 5


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


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


def top_memory_hits(repo: Path, query: str, limit: int) -> list[search_memory.Hit]:
    query_tokens = search_memory.unique_query_tokens(query)
    if not query_tokens:
        return []
    return search_memory.merge_hits(
        repo,
        search_memory.collect_memory_hits(repo, query_tokens, [], "all"),
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


def evaluate_cases(repo: Path, cases: list[dict], records: list[dict], limit: int) -> dict[str, Any]:
    totals: dict[str, int] = {
        "cases": 0,
        "positive_cases": 0,
        "abstain_cases": 0,
        "recall_hits": 0,
        "relevant_results": 0,
        "total_results": 0,
        "suppression_cases": 0,
        "suppression_hits": 0,
    }
    noise_sources = {
        "broad_lexical_match": 0,
        "scope_mixed": 0,
        "inactive_lifecycle": 0,
        "low_signal_memory_node": 0,
    }
    inactive_ids = inactive_memory_ids(records)
    for case in cases:
        query = str(case.get("query") or "").strip()
        if not query:
            continue
        totals["cases"] += 1
        hits = top_memory_hits(repo, query, limit)
        result_ids = [memory_id for hit in hits if (memory_id := safe_memory_id(hit.memory_id))]
        expected_memory_id = safe_memory_id(case.get("expected_memory_id"))
        expected_not_memory_ids = [
            memory_id for memory_id in text_list(case.get("expected_not_memory_id")) if safe_memory_id(memory_id)
        ]
        if case.get("expected_abstain") is True:
            totals["abstain_cases"] += 1
        elif expected_memory_id:
            totals["positive_cases"] += 1
            totals["total_results"] += len(result_ids)
            if expected_memory_id in result_ids:
                totals["recall_hits"] += 1
                totals["relevant_results"] += 1
            for hit in hits:
                hit_id = safe_memory_id(hit.memory_id)
                if hit_id and hit_id != expected_memory_id:
                    noise_sources[classify_noise_source(hit, case, inactive_ids)] += 1
        if expected_not_memory_ids:
            totals["suppression_cases"] += 1
            if all(memory_id not in result_ids for memory_id in expected_not_memory_ids):
                totals["suppression_hits"] += 1
    precision = ratio(totals["relevant_results"], totals["total_results"])
    return {
        **totals,
        "memory_recall_at_5": ratio(totals["recall_hits"], totals["positive_cases"]),
        "memory_precision_at_5": precision,
        "top_k_noise_at_5": None if precision is None else 1.0 - precision,
        "noise_sources_at_5": noise_sources,
        "active_memory_suppression": ratio(totals["suppression_hits"], totals["suppression_cases"]),
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


def run_audit(repo: Path, audit_script: Path | None) -> dict[str, Any]:
    if audit_script is None:
        return {"status": "skipped"}
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
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
    }


def build_report(repo: Path, cases: list[dict], audit_script: Path | None, limit: int) -> dict[str, Any]:
    records = load_memory_records(repo)
    case_metrics = evaluate_cases(repo, cases, records, limit)
    memory_index_present = (repo / "index" / "memories.jsonl").is_file()
    return {
        "report_version": 1,
        "report_kind": "real_archive_shadow_evaluation",
        "privacy": {
            "aggregate_only": True,
            "source_content_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
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
            "active_memory_suppression": case_metrics["active_memory_suppression"],
            "provenance_coverage": provenance_coverage(records),
            "lifecycle_integrity": lifecycle_integrity(records),
        },
        "audit": run_audit(repo, audit_script),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    parser.add_argument("--cases", help="Optional redacted probe cases JSONL")
    parser.add_argument("--audit-script", help="Optional audit_memory_archive.py path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Top-k memory hits to score")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")
    repo = Path(args.repo)
    cases = load_cases(Path(args.cases) if args.cases else None)
    audit_script = Path(args.audit_script) if args.audit_script else None
    report = build_report(repo, cases, audit_script, args.limit)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
