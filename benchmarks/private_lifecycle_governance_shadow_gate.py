#!/usr/bin/env python3
"""Aggregate-only private lifecycle governance shadow gate.

This runner audits lifecycle governance from structured archive surfaces and
context packages. It may read private archive text internally as search queries,
but it never renders queries, memory text, memory IDs, source paths, raw refs, or
source content in its report.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import lifecycle_governance_gate as lifecycle  # noqa: E402


REPORT_KIND = "private_lifecycle_governance_shadow_gate"
VALIDATION_REPORT_KIND = "private_lifecycle_governance_shadow_gate_validation"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
MEMORY_ID_RE = re.compile(r"^mem_[A-Za-z0-9_.:-]+$")
PRIVATE_PATH_RE = re.compile(r"/Users/[A-Za-z0-9_.@-]+/[^\s\"']+")
RAW_REF_KEYS = {"raw_ref", "raw_refs", "source_ref", "source_refs"}
SYNTHETIC_FORBIDDEN_MARKERS = (
    "V220 refresh routing keeps legacy",
    "V220 deleted lifecycle policy",
    "SYNTHETIC_V220_PRIVATE_TOKEN",
    "/Users/soku/private/lifecycle-source.jsonl",
)
ACTIVE_SUPPORT_FAILURE_COUNTERS = (
    "active_support_expected_node_missing_count",
    "active_support_package_unsupported_count",
    "active_support_query_support_missing_count",
    "active_support_summary_drill_missing_count",
    "active_support_evidence_drill_missing_count",
    "active_support_wrong_active_hit_count",
    "archive_search_tool_context_package_failure_count",
    "template_search_tool_fallback_success_count",
    "unknown_privacy_preserved_failure_count",
)


def ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def empty_active_support_failure_counts() -> dict[str, int]:
    return {key: 0 for key in ACTIVE_SUPPORT_FAILURE_COUNTERS}


def add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def safe_memory_id(value: object) -> str:
    if isinstance(value, str) and MEMORY_ID_RE.fullmatch(value):
        return value
    return ""


def safe_id(value: object) -> str:
    if isinstance(value, str) and SAFE_ID_RE.fullmatch(value):
        return value
    return ""


def text_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(iter_jsonl(path))


def node_id_map(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        memory_id = safe_memory_id(node.get("memory_id"))
        if memory_id:
            by_id[memory_id] = node
    return by_id


def relation_integrity(nodes: list[dict[str, Any]]) -> tuple[float, int, int]:
    by_id = node_id_map(nodes)
    checked = 0
    valid = 0

    def check_forward(node_id: str, field: str, reverse_field: str) -> None:
        nonlocal checked, valid
        for target_id in text_list(by_id[node_id].get(field)):
            if not safe_memory_id(target_id):
                continue
            checked += 1
            target = by_id.get(target_id)
            reverse_value = target.get(reverse_field) if target is not None else None
            if reverse_field == "contradicted_by":
                if isinstance(reverse_value, list) and node_id in reverse_value:
                    valid += 1
            elif reverse_value == node_id:
                valid += 1

    def check_reverse(node_id: str, field: str, forward_field: str) -> None:
        nonlocal checked, valid
        value = by_id[node_id].get(field)
        values = text_list(value)
        for source_id in values:
            if not safe_memory_id(source_id):
                continue
            checked += 1
            source = by_id.get(source_id)
            if source is not None and node_id in text_list(source.get(forward_field)):
                valid += 1

    for node_id in by_id:
        check_forward(node_id, "supersedes", "superseded_by")
        check_forward(node_id, "deprecates", "deprecated_by")
        check_forward(node_id, "contradicts", "contradicted_by")
        check_reverse(node_id, "superseded_by", "supersedes")
        check_reverse(node_id, "deprecated_by", "deprecates")
        check_reverse(node_id, "contradicted_by", "contradicts")
    return ratio(valid, checked), checked, checked - valid


def inactive_memory_ids(nodes: list[dict[str, Any]]) -> set[str]:
    inactive: set[str] = set()
    by_id = node_id_map(nodes)
    for node_id, node in by_id.items():
        for target_id in text_list(node.get("supersedes")):
            if target_id in by_id:
                inactive.add(target_id)
        for target_id in text_list(node.get("deprecates")):
            if target_id in by_id:
                inactive.add(target_id)
        for target_id in text_list(node.get("contradicts")):
            if target_id in by_id:
                inactive.add(target_id)
        if text_list(node.get("superseded_by")) or text_list(node.get("deprecated_by")):
            inactive.add(node_id)
        if text_list(node.get("contradicted_by")):
            inactive.add(node_id)
        if text_list(node.get("deprecates")):
            inactive.add(node_id)
    return inactive


def repo_relative_path(repo: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    rel = Path(value)
    if rel.is_absolute():
        return None
    candidate = (repo / rel).resolve(strict=False)
    try:
        candidate.relative_to(repo.resolve(strict=False))
    except ValueError:
        return None
    return candidate


def evidence_quote_exists(path: Path, quote_id: object) -> bool:
    if not isinstance(quote_id, str) or not safe_id(quote_id) or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return quote_id in text


def derived_ref_reachable(repo: Path, by_id: dict[str, dict[str, Any]], value: object) -> bool:
    memory_id = safe_memory_id(value)
    if memory_id:
        return memory_id in by_id
    path = repo_relative_path(repo, value)
    return bool(path and path.is_file())


def evidence_ref_reachable(repo: Path, value: object) -> bool:
    if not isinstance(value, dict):
        return False
    path = repo_relative_path(repo, value.get("path"))
    return bool(path and evidence_quote_exists(path, value.get("quote_id")))


def node_support_refs_reachable(repo: Path, by_id: dict[str, dict[str, Any]], node: dict[str, Any]) -> bool:
    checks: list[bool] = []
    derived_from = node.get("derived_from")
    if isinstance(derived_from, list):
        checks.extend(derived_ref_reachable(repo, by_id, item) for item in derived_from)
    evidence_refs = node.get("evidence_refs")
    if isinstance(evidence_refs, list):
        checks.extend(evidence_ref_reachable(repo, item) for item in evidence_refs)
    if not checks:
        return False
    return all(checks)


def support_ref_reachability_rate(
    repo: Path,
    nodes: list[dict[str, Any]],
    sample_limit: int,
) -> tuple[float, int, int]:
    by_id = node_id_map(nodes)
    sampled = [
        node
        for node in nodes
        if safe_memory_id(node.get("memory_id")) and (node.get("derived_from") or node.get("evidence_refs"))
    ][:sample_limit]
    reachable = sum(int(node_support_refs_reachable(repo, by_id, node)) for node in sampled)
    return ratio(reachable, len(sampled)), len(sampled), len(sampled) - reachable


def sorted_sample_nodes(
    nodes: list[dict[str, Any]],
    inactive_ids: set[str],
    *,
    active: bool,
    sample_limit: int,
) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for node in nodes:
        memory_id = safe_memory_id(node.get("memory_id"))
        text = node.get("text")
        if not memory_id or not isinstance(text, str) or not text.strip():
            continue
        is_inactive = memory_id in inactive_ids
        if active and is_inactive:
            continue
        if not active and not is_inactive:
            continue
        sampled.append(node)
    sampled.sort(
        key=lambda item: (
            int(item.get("support_count") or 0),
            str(item.get("last_seen") or ""),
        ),
        reverse=True,
    )
    return sampled[:sample_limit]


def run_context_search(repo: Path, query: str, python: str, search_tool: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            python,
            str(search_tool),
            query,
            "--repo",
            str(repo),
            "--limit",
            "5",
            "--depth",
            "evidence",
            "--context-json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def parse_context_search_result(result: subprocess.CompletedProcess[str]) -> tuple[dict[str, Any] | None, str]:
    if result.returncode != 0:
        return None, "command_failed"
    try:
        package = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(package, dict) or package.get("report_kind") != CONTEXT_REPORT_KIND:
        return None, "wrong_report_kind"
    return package, "parsed"


def load_context_package(repo: Path, query: str, python: str) -> tuple[dict[str, Any] | None, str]:
    primary_tool = repo / "tools/search_memory.py"
    fallback_tool = REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py"
    package, outcome = parse_context_search_result(run_context_search(repo, query, python, primary_tool))
    if outcome == "parsed":
        return package, outcome
    if fallback_tool.resolve(strict=False) == primary_tool.resolve(strict=False):
        return package, outcome
    fallback_package, fallback_outcome = parse_context_search_result(
        run_context_search(repo, query, python, fallback_tool)
    )
    if fallback_outcome == "parsed":
        return fallback_package, "parsed_fallback"
    return fallback_package, fallback_outcome


def package_supports_memory(package: dict[str, Any] | None, node: dict[str, Any]) -> bool:
    return active_support_diagnosis(package, node)[0]


def active_support_diagnosis(
    package: dict[str, Any] | None,
    node: dict[str, Any],
) -> tuple[bool, dict[str, int]]:
    counts = empty_active_support_failure_counts()
    if package is None:
        counts["unknown_privacy_preserved_failure_count"] += 1
        return False, counts
    memory_id = safe_memory_id(node.get("memory_id"))
    if not memory_id:
        counts["active_support_expected_node_missing_count"] += 1
        return False, counts
    hits = package.get("hits")
    if not isinstance(hits, list):
        counts["active_support_expected_node_missing_count"] += 1
        return False, counts

    answerability = package.get("answerability")
    package_supported = isinstance(answerability, dict) and answerability.get("status") == "supported"

    active_supported_hit_count = 0
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_answerability = hit.get("answerability")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
        ):
            active_supported_hit_count += 1
        if hit.get("memory_id") != memory_id:
            continue
        query_support = hit.get("query_support")
        supported = bool(
            package_supported
            and hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and isinstance(hit.get("summary_drill_paths"), list)
            and hit["summary_drill_paths"]
            and isinstance(hit.get("evidence_drill_paths"), list)
            and hit["evidence_drill_paths"]
        )
        if supported:
            return True, counts
        if not package_supported or not isinstance(hit_answerability, dict) or hit_answerability.get("status") != "supported":
            counts["active_support_package_unsupported_count"] += 1
        if hit.get("active_current") is not True:
            counts["active_support_wrong_active_hit_count"] += 1
        if not isinstance(query_support, dict) or query_support.get("status") != "supported":
            counts["active_support_query_support_missing_count"] += 1
        if not isinstance(hit.get("summary_drill_paths"), list) or not hit["summary_drill_paths"]:
            counts["active_support_summary_drill_missing_count"] += 1
        if not isinstance(hit.get("evidence_drill_paths"), list) or not hit["evidence_drill_paths"]:
            counts["active_support_evidence_drill_missing_count"] += 1
        if not any(counts.values()):
            counts["unknown_privacy_preserved_failure_count"] += 1
        return False, counts

    if active_supported_hit_count:
        counts["active_support_wrong_active_hit_count"] += 1
    else:
        counts["active_support_expected_node_missing_count"] += 1
    if not package_supported:
        counts["active_support_package_unsupported_count"] += 1
    return False, counts


def context_sample_metrics(
    repo: Path,
    nodes: list[dict[str, Any]],
    inactive_ids: set[str],
    sample_limit: int,
    python: str,
) -> dict[str, Any]:
    active_samples = sorted_sample_nodes(nodes, inactive_ids, active=True, sample_limit=sample_limit)
    inactive_samples = sorted_sample_nodes(nodes, inactive_ids, active=False, sample_limit=sample_limit)
    parse_success = 0
    query_count = 0
    active_supported = 0
    inactive_suppressed = 0
    failure_counts = empty_active_support_failure_counts()
    outcome_counts = {
        "parsed": 0,
        "parsed_fallback": 0,
        "command_failed": 0,
        "invalid_json": 0,
        "wrong_report_kind": 0,
    }

    for node in active_samples:
        text = str(node.get("text") or "")
        package, outcome = load_context_package(repo, text, python)
        query_count += 1
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        parse_success += int(outcome in {"parsed", "parsed_fallback"})
        supported, support_counts = active_support_diagnosis(package, node)
        add_counts(failure_counts, support_counts)
        active_supported += int(supported)

    for node in inactive_samples:
        text = str(node.get("text") or "")
        package, outcome = load_context_package(repo, text, python)
        query_count += 1
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        parse_success += int(outcome in {"parsed", "parsed_fallback"})
        inactive_suppressed += int(not package_supports_memory(package, node))

    failure_counts["archive_search_tool_context_package_failure_count"] = query_count - outcome_counts["parsed"]
    failure_counts["template_search_tool_fallback_success_count"] = outcome_counts["parsed_fallback"]
    return {
        "parse_success_rate": ratio(parse_success, query_count),
        "active_support_rate": ratio(active_supported, len(active_samples)),
        "inactive_suppression_rate": ratio(inactive_suppressed, len(inactive_samples)),
        "active_support_failure_counts": failure_counts,
        "query_count": query_count,
        "parse_failure_count": query_count - parse_success,
        "fallback_parse_success_count": outcome_counts["parsed_fallback"],
        "command_failure_count": outcome_counts["command_failed"],
        "invalid_json_count": outcome_counts["invalid_json"],
        "wrong_report_kind_count": outcome_counts["wrong_report_kind"],
        "active_sample_count": len(active_samples),
        "inactive_sample_count": len(inactive_samples),
    }


def candidate_actionable(
    candidate: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    repo: Path,
) -> bool:
    if candidate.get("recommended_action") != "manual_review":
        return False
    memory_ids = [
        safe_memory_id(candidate.get("current_memory_id")),
        safe_memory_id(candidate.get("older_memory_id")),
        safe_memory_id(candidate.get("review_subject_memory_id")),
    ]
    memory_ids = [memory_id for memory_id in memory_ids if memory_id]
    if memory_ids:
        return all(memory_id in by_id for memory_id in memory_ids)

    candidate_id = safe_id(candidate.get("candidate_id"))
    candidate_hash = safe_id(candidate.get("candidate_text_sha256"))
    related_hash = safe_id(candidate.get("related_candidate_text_sha256"))
    if not candidate_id and not candidate_hash and not related_hash:
        return False
    return node_support_refs_reachable(repo, by_id, candidate)


def review_queue_actionability_rate(
    repo: Path,
    nodes: list[dict[str, Any]],
    review_candidates: list[dict[str, Any]],
) -> tuple[float, int, int]:
    by_id = node_id_map(nodes)
    actionable = sum(int(candidate_actionable(candidate, by_id, repo)) for candidate in review_candidates)
    return ratio(actionable, len(review_candidates)), len(review_candidates), len(review_candidates) - actionable


def tombstone_marker_count(nodes: list[dict[str, Any]]) -> int:
    return sum(1 for node in nodes if str(node.get("text") or "").startswith("Deleted fact:"))


def stale_review_candidate_count(candidates: list[dict[str, Any]]) -> int:
    return sum(1 for candidate in candidates if candidate.get("reason") == "stale_low_support_memory_requires_review")


def privacy_block() -> dict[str, bool]:
    return {
        "aggregate_only": True,
        "queries_rendered": False,
        "memory_text_rendered": False,
        "memory_ids_rendered": False,
        "source_paths_rendered": False,
        "raw_refs_rendered": False,
        "source_content_rendered": False,
    }


def aggregate_report_text(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True)


def rendered_private_query_count(report: dict[str, Any]) -> int:
    privacy = report.get("privacy")
    return int(isinstance(privacy, dict) and privacy.get("queries_rendered") is True)


def rendered_memory_text_count(report: dict[str, Any]) -> int:
    privacy = report.get("privacy")
    return int(isinstance(privacy, dict) and privacy.get("memory_text_rendered") is True)


def rendered_source_path_count(report: dict[str, Any]) -> int:
    privacy = report.get("privacy")
    text = aggregate_report_text(report)
    return int(isinstance(privacy, dict) and privacy.get("source_paths_rendered") is True) + len(
        PRIVATE_PATH_RE.findall(text)
    )


def rendered_raw_ref_count(report: dict[str, Any]) -> int:
    privacy = report.get("privacy")
    raw_flag = int(isinstance(privacy, dict) and privacy.get("raw_refs_rendered") is True)
    raw_keys = 0
    stack: list[object] = [report]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if key in RAW_REF_KEYS:
                    raw_keys += 1
                stack.append(item)
        elif isinstance(value, list):
            stack.extend(value)
    return raw_flag + raw_keys


def rendered_memory_id_count(report: dict[str, Any]) -> int:
    privacy = report.get("privacy")
    memory_id_flag = int(isinstance(privacy, dict) and privacy.get("memory_ids_rendered") is True)
    return memory_id_flag + len(re.findall(r"\bmem_[A-Za-z0-9_.:-]+", aggregate_report_text(report)))


def privacy_leak_count_for_report(report: dict[str, Any]) -> int:
    text = aggregate_report_text(report)
    marker_count = sum(1 for marker in SYNTHETIC_FORBIDDEN_MARKERS if marker in text)
    return (
        marker_count
        + rendered_private_query_count(report)
        + rendered_memory_text_count(report)
        + rendered_memory_id_count(report)
        + rendered_source_path_count(report)
        + rendered_raw_ref_count(report)
    )


def update_privacy_metrics(report: dict[str, Any]) -> None:
    metrics = report.setdefault("metrics", {})
    metrics["rendered_private_query_count"] = rendered_private_query_count(report)
    metrics["rendered_memory_text_count"] = rendered_memory_text_count(report)
    metrics["rendered_source_path_count"] = rendered_source_path_count(report)
    metrics["rendered_raw_ref_count"] = rendered_raw_ref_count(report)
    metrics["privacy_leak_count"] = privacy_leak_count_for_report(report)


def build_gate_report(
    *,
    repo: Path,
    mode: str,
    update_failures: int,
    sample_limit: int,
    python: str,
) -> dict[str, Any]:
    nodes = load_jsonl(repo / "index/memories.jsonl")
    memory_review_candidates = load_jsonl(repo / "index/memory_review_candidates.jsonl")
    induction_review_candidates = load_jsonl(repo / "index/induction_review_candidates.jsonl")
    review_candidates = [*memory_review_candidates, *induction_review_candidates]
    inactive_ids = inactive_memory_ids(nodes)

    relation_score, relation_checked, relation_broken = relation_integrity(nodes)
    context_metrics = context_sample_metrics(repo, nodes, inactive_ids, sample_limit, python)
    support_rate, support_checked, support_broken = support_ref_reachability_rate(repo, nodes, sample_limit)
    review_rate, review_checked, review_broken = review_queue_actionability_rate(repo, nodes, review_candidates)

    metrics: dict[str, Any] = {
        "private_lifecycle_relation_integrity_score": relation_score,
        "private_inactive_search_suppression_sample_rate": context_metrics["inactive_suppression_rate"],
        "private_active_current_support_sample_rate": context_metrics["active_support_rate"],
        "private_context_package_parse_success_rate": context_metrics["parse_success_rate"],
        "private_tombstone_marker_count": tombstone_marker_count(nodes),
        "private_stale_review_candidate_count": stale_review_candidate_count(memory_review_candidates),
        "private_support_ref_reachability_sample_rate": support_rate,
        "private_review_queue_actionability_rate": review_rate,
        "privacy_leak_count": 0,
        "rendered_private_query_count": 0,
        "rendered_memory_text_count": 0,
        "rendered_source_path_count": 0,
        "rendered_raw_ref_count": 0,
    }
    metrics.update(context_metrics["active_support_failure_counts"])
    failed = (
        update_failures > 0
        or relation_score < 1.0
        or context_metrics["parse_success_rate"] < 1.0
        or context_metrics["active_support_rate"] < 1.0
        or context_metrics["inactive_suppression_rate"] < 1.0
        or support_rate < 1.0
        or review_rate < 1.0
        or (mode == "synthetic_fixture" and metrics["private_tombstone_marker_count"] < 1)
        or (mode == "synthetic_fixture" and metrics["private_stale_review_candidate_count"] < 1)
    )
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "failed" if failed else "passed",
        "mode": mode,
        "claim_boundary": (
            "aggregate-only lifecycle observability; no private text, path, query, memory ID, "
            "raw ref, live LLM answer quality, vector search, ranking, ontology, or archive-correctness claim"
        ),
        "metrics": metrics,
        "diagnostics": {
            "memory_node_count": len(nodes),
            "inactive_memory_count": len(inactive_ids),
            "memory_review_candidate_count": len(memory_review_candidates),
            "induction_review_candidate_count": len(induction_review_candidates),
            "lifecycle_relation_checked_count": relation_checked,
            "lifecycle_relation_broken_count": relation_broken,
            "support_ref_checked_count": support_checked,
            "support_ref_broken_count": support_broken,
            "review_candidate_checked_count": review_checked,
            "review_candidate_broken_count": review_broken,
            "context_package_query_count": context_metrics["query_count"],
            "context_package_parse_failure_count": context_metrics["parse_failure_count"],
            "context_package_fallback_success_count": context_metrics["fallback_parse_success_count"],
            "context_package_command_failure_count": context_metrics["command_failure_count"],
            "context_package_invalid_json_count": context_metrics["invalid_json_count"],
            "context_package_wrong_report_kind_count": context_metrics["wrong_report_kind_count"],
            "active_context_sample_count": context_metrics["active_sample_count"],
            "inactive_context_sample_count": context_metrics["inactive_sample_count"],
            "update_failures": update_failures,
        },
        "privacy": privacy_block(),
    }
    update_privacy_metrics(report)
    if report["metrics"]["privacy_leak_count"]:
        report["status"] = "failed"
    return report


def skipped_private_report(reason: str) -> dict[str, Any]:
    report = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "skipped",
        "mode": "private_archive",
        "claim_boundary": "aggregate-only lifecycle observability was not run",
        "metrics": {
            "private_lifecycle_relation_integrity_score": 1.0,
            "private_inactive_search_suppression_sample_rate": 1.0,
            "private_active_current_support_sample_rate": 1.0,
            "private_context_package_parse_success_rate": 1.0,
            "private_tombstone_marker_count": 0,
            "private_stale_review_candidate_count": 0,
            "private_support_ref_reachability_sample_rate": 1.0,
            "private_review_queue_actionability_rate": 1.0,
            "privacy_leak_count": 0,
            "rendered_private_query_count": 0,
            "rendered_memory_text_count": 0,
            "rendered_source_path_count": 0,
            "rendered_raw_ref_count": 0,
        },
        "diagnostics": {
            "blocker_count": 1,
            "blocker_categories": [reason],
        },
        "privacy": privacy_block(),
    }
    update_privacy_metrics(report)
    return report


def prepare_work_dir(path_text: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path_text:
        root = Path(path_text).expanduser().resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return root, None
    temp_handle = tempfile.TemporaryDirectory(prefix="my-precious-v221-")
    return Path(temp_handle.name), temp_handle


def is_allowed_output_path(path: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    allowed_root = Path("/tmp").resolve(strict=False)
    return resolved == allowed_root or resolved.is_relative_to(allowed_root)


def emit_report(report: dict[str, Any], output: str | None) -> int:
    if output:
        output_path = Path(output).expanduser()
        if not output_path.is_absolute() or not is_allowed_output_path(output_path):
            failed = skipped_private_report("unsafe_output_path")
            failed["status"] = "failed"
            print(json.dumps(failed, sort_keys=True))
            return 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"passed", "skipped"} else 1


def validation_failure_report(
    *,
    privacy_leak_count: int,
    rendered_queries: int,
    rendered_memory_text: int,
    rendered_source_paths: int,
    rendered_raw_refs: int,
    invalid_shape: bool,
) -> dict[str, Any]:
    status = "failed" if invalid_shape or privacy_leak_count else "passed"
    return {
        "report_kind": VALIDATION_REPORT_KIND,
        "report_version": 1,
        "status": status,
        "metrics": {
            "privacy_leak_count": privacy_leak_count,
            "rendered_private_query_count": rendered_queries,
            "rendered_memory_text_count": rendered_memory_text,
            "rendered_source_path_count": rendered_source_paths,
            "rendered_raw_ref_count": rendered_raw_refs,
            "invalid_report_shape_count": int(invalid_shape),
        },
        "privacy": privacy_block(),
    }


def validate_report_file(path: Path) -> tuple[dict[str, Any], int]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = validation_failure_report(
            privacy_leak_count=1,
            rendered_queries=0,
            rendered_memory_text=0,
            rendered_source_paths=0,
            rendered_raw_refs=0,
            invalid_shape=True,
        )
        return report, 1
    invalid_shape = not isinstance(value, dict)
    if not isinstance(value, dict):
        value = {}
    rendered_queries = rendered_private_query_count(value)
    rendered_memory_text = rendered_memory_text_count(value)
    rendered_source_paths = rendered_source_path_count(value)
    rendered_raw_refs = rendered_raw_ref_count(value)
    privacy_leaks = privacy_leak_count_for_report(value)
    if value.get("report_kind") != REPORT_KIND:
        invalid_shape = True
    report = validation_failure_report(
        privacy_leak_count=privacy_leaks,
        rendered_queries=rendered_queries,
        rendered_memory_text=rendered_memory_text,
        rendered_source_paths=rendered_source_paths,
        rendered_raw_refs=rendered_raw_refs,
        invalid_shape=invalid_shape,
    )
    return report, 0 if report["status"] == "passed" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-fixture", action="store_true", help="Run against the public synthetic fixture")
    parser.add_argument("--memory-repo", help="Optional private memory archive to audit read-only")
    parser.add_argument("--require-private", action="store_true", help="Fail if the requested private repo is missing")
    parser.add_argument("--work-dir", help="Optional synthetic fixture work directory")
    parser.add_argument("--output", help="Optional aggregate report output path under /tmp")
    parser.add_argument("--validate-report", help="Validate an aggregate report without rendering its content")
    parser.add_argument("--sample-limit", type=int, default=6, help="Maximum active/inactive/support samples")
    parser.add_argument("--python", default=sys.executable, help="Python executable for child search tool invocations")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.sample_limit <= 0:
        raise SystemExit("--sample-limit must be greater than 0")

    if args.validate_report:
        report, exit_code = validate_report_file(Path(args.validate_report).expanduser())
        print(json.dumps(report, sort_keys=True))
        return exit_code

    if args.require_private and not args.memory_repo:
        report = skipped_private_report("missing_memory_repo_argument")
        report["status"] = "failed"
        return emit_report(report, args.output)

    if args.memory_repo:
        repo = Path(args.memory_repo).expanduser().resolve()
        if not (repo / "index/memories.jsonl").is_file() or not (repo / "tools/search_memory.py").is_file():
            report = skipped_private_report("missing_or_invalid_private_archive")
            if args.require_private:
                report["status"] = "failed"
            return emit_report(report, args.output)
        report = build_gate_report(
            repo=repo,
            mode="private_archive",
            update_failures=0,
            sample_limit=args.sample_limit,
            python=args.python,
        )
        return emit_report(report, args.output)

    work_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        gate_run = lifecycle.run_packaged_update(work_root)
        report = build_gate_report(
            repo=gate_run.memory_repo,
            mode="synthetic_fixture",
            update_failures=gate_run.update_failures,
            sample_limit=args.sample_limit,
            python=args.python,
        )
        return emit_report(report, args.output)
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
