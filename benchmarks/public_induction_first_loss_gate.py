#!/usr/bin/env python3
"""Attribute the first deterministic loss in public conversation induction."""

from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GATE_SCRIPT = REPO_ROOT / "benchmarks/public_induction_recall_gate.py"
QUERY_CALIBRATION_GATE_SCRIPT = (
    REPO_ROOT / "benchmarks/public_query_support_calibration_gate.py"
)
REPORT_KIND = "public_induction_first_loss_gate"
REPORT_VERSION = 1
OFFICIAL_DATASET_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
OFFICIAL_DATASET_SOURCE = "LongMemEval cleaned S"
HOLDOUT_FINGERPRINT = (
    "4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7"
)
CALIBRATION_FINGERPRINT = (
    "c8ac66423f41b968ca60c9af18ae3f2c949f534a8f875d8997ec83cd8fbb5e19"
)
RUNTIME_COMPONENTS = (
    "skills/setup-my-precious/scripts/setup_memory_archive.py",
    "skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py",
    "skills/setup-my-precious/assets/agent-memory-repo/tools/memory_consolidation.py",
    "skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py",
    "skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py",
)
FIRST_LOSS_TAXONOMY = (
    "source_rejected",
    "update_failed",
    "archive_audit_failed",
    "session_support_omitted",
    "memory_induction_omitted_or_overcompressed",
    "memory_present_not_top5",
    "top1_not_query_supported",
    "supported",
)


def classify_first_loss(observation: dict[str, Any]) -> str:
    """Return the earliest failed stage for one positive scorer observation."""
    if observation.get("source_rejected"):
        return "source_rejected"
    if not observation.get("packaged_setup_success") or not observation.get(
        "updater_success"
    ):
        return "update_failed"
    if not observation.get("archive_audit_success"):
        return "archive_audit_failed"
    if not observation.get("preserved_support_event_count"):
        return "session_support_omitted"
    if not observation.get("active_support_memory_count"):
        return "memory_induction_omitted_or_overcompressed"
    if not observation.get("support_candidate_at_5_count"):
        return "memory_present_not_top5"
    if not observation.get("supported_gold_package"):
        return "top1_not_query_supported"
    return "supported"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


public_gate = _load_module("v244_public_induction_recall_gate", PUBLIC_GATE_SCRIPT)
query_calibration_gate = _load_module(
    "v244_public_query_support_calibration_gate",
    QUERY_CALIBRATION_GATE_SCRIPT,
)


def scorer_support_event_ordinals(row: dict[str, Any]) -> set[tuple[str, int]]:
    """Return answer-bearing event positions without exposing their content downstream."""
    session_ids = row.get("haystack_session_ids")
    sessions = row.get("haystack_sessions")
    answer_session_ids = row.get("answer_session_ids")
    if not all(isinstance(value, list) for value in (session_ids, sessions, answer_session_ids)):
        raise SystemExit("LongMemEval row has malformed scorer support arrays")
    if len(session_ids) != len(sessions):
        raise SystemExit("LongMemEval scorer support arrays must be aligned")
    answer_ids = {str(value) for value in answer_session_ids}
    expected: set[tuple[str, int]] = set()
    for session_id, turns in zip(session_ids, sessions):
        if not isinstance(session_id, str) or not isinstance(turns, list):
            raise SystemExit("LongMemEval scorer support session is malformed")
        if session_id not in answer_ids:
            continue
        for event_ordinal, turn in enumerate(turns, 1):
            if isinstance(turn, dict) and turn.get("has_answer") is True:
                expected.add((session_id, event_ordinal))
    return expected


def _case_source_path_to_session_id(
    case: dict[str, Any], case_root: Path
) -> dict[str, str]:
    source_root = case_root / "source-records"
    return {
        str((source_root / str(record["record_id"]) / "record.jsonl").resolve()): str(
            record["scorer_session_id"]
        )
        for record in case.get("source_records") or []
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def archived_support_refs(
    case: dict[str, Any],
    case_root: Path,
    expected_events: set[tuple[str, int]],
) -> dict[str, Any]:
    """Resolve scorer event positions to archive evidence refs through source maps."""
    memory_repo = case_root / "archive"
    source_sessions = _case_source_path_to_session_id(case, case_root)
    preserved_events: set[tuple[str, int]] = set()
    support_refs: set[tuple[str, str]] = set()
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        meta = _load_json_object(meta_path)
        source_record = meta.get("source_record")
        if not isinstance(source_record, str):
            continue
        session_id = source_sessions.get(str(Path(source_record).resolve()))
        evidence_path = meta.get("evidence_path")
        source_map_path = meta.get("source_map_path")
        if not session_id or not isinstance(evidence_path, str) or not isinstance(
            source_map_path, str
        ):
            continue
        source_map = _load_json_object(memory_repo / source_map_path)
        for anchor in source_map.get("evidence_source_anchors") or []:
            if not isinstance(anchor, dict):
                continue
            quote_id = anchor.get("quote_id")
            event_ordinal = anchor.get("event_ordinal")
            event = (session_id, event_ordinal)
            if (
                event in expected_events
                and isinstance(quote_id, str)
                and quote_id
                and isinstance(event_ordinal, int)
            ):
                preserved_events.add((session_id, event_ordinal))
                support_refs.add((evidence_path, quote_id))
    return {
        "expected_support_event_count": len(expected_events),
        "preserved_support_event_count": len(preserved_events),
        "support_refs": support_refs,
    }


def _evidence_refs(record: dict[str, Any]) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for value in record.get("evidence_refs") or []:
        if isinstance(value, dict):
            path = value.get("path")
            quote_id = value.get("quote_id")
        elif isinstance(value, str) and "#" in value:
            path, quote_id = value.split("#", 1)
        else:
            continue
        if isinstance(path, str) and path and isinstance(quote_id, str) and quote_id:
            refs.add((path, quote_id))
    return refs


def support_memory_state(
    records: list[dict[str, Any]],
    support_refs: set[tuple[str, str]],
    *,
    inactive_ids: set[str],
) -> dict[str, Any]:
    support_ids: set[str] = set()
    for record in records:
        memory_id = record.get("memory_id")
        if (
            record.get("source") == "automatic"
            and isinstance(memory_id, str)
            and memory_id
            and _evidence_refs(record).intersection(support_refs)
        ):
            support_ids.add(memory_id)
    active_ids = support_ids.difference(inactive_ids)
    return {
        "support_memory_count": len(support_ids),
        "active_support_memory_count": len(active_ids),
        "inactive_support_memory_count": len(support_ids.intersection(inactive_ids)),
        "active_support_memory_ids": active_ids,
    }


def package_support_state(
    package: object,
    active_support_memory_ids: set[str],
) -> dict[str, int]:
    if (
        not isinstance(package, dict)
        or package.get("report_kind") != public_gate.CONTEXT_REPORT_KIND
    ):
        return {
            "context_package_parse_success": 0,
            "support_candidate_at_1_count": 0,
            "support_candidate_at_5_count": 0,
            "supported_gold_package": 0,
        }
    hits = [value for value in package.get("hits") or [] if isinstance(value, dict)][:5]
    support_hits = [
        hit
        for hit in hits
        if isinstance(hit.get("memory_id"), str)
        and hit["memory_id"] in active_support_memory_ids
    ]
    at_1 = sum(
        int((hit.get("rank") or index) == 1)
        for index, hit in enumerate(support_hits, 1)
    )
    supported = bool(
        public_gate.context_package_decision(package) == "answer"
        and any(public_gate._supported_active_hit(hit) for hit in support_hits)
    )
    return {
        "context_package_parse_success": 1,
        "support_candidate_at_1_count": at_1,
        "support_candidate_at_5_count": len(support_hits),
        "supported_gold_package": int(supported),
    }


def _inactive_memory_ids(search_module: Any, records: list[dict[str, Any]]) -> set[str]:
    supersedes = search_module.collect_supersedes_by_memory_id(records)
    contradicts = search_module.collect_contradicts_by_memory_id(records)
    deprecates = search_module.collect_deprecates_by_memory_id(records)
    return search_module.collect_inactive_memory_ids(
        records,
        supersedes,
        search_module.collect_forward_superseded_ids(supersedes),
        contradicts,
        search_module.collect_forward_contradicted_ids(contradicts),
        deprecates,
        search_module.collect_forward_deprecated_ids(deprecates),
    )


def _sensitive_source_record_count(case_root: Path) -> int:
    updater_path = case_root / "archive/tools/update_memory_archive.py"
    if not updater_path.is_file():
        return 0
    module_name = "v244_updater_" + hashlib.sha256(
        str(updater_path).encode("utf-8")
    ).hexdigest()[:16]
    updater = _load_module(module_name, updater_path)
    sensitive = 0
    for source_path in sorted((case_root / "source-records").glob("**/*.jsonl")):
        try:
            _, counts = updater.redact_text(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        sensitive += int(bool(counts))
    return sensitive


def observe_packaged_case(
    row: dict[str, Any],
    *,
    case_ordinal: int,
    case_root: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    """Run one packaged case and derive aggregate-safe scorer stage facts."""
    case = public_gate.convert_longmemeval_case(row, case_ordinal=case_ordinal)
    expected_events = scorer_support_event_ordinals(row)
    setup_script = (
        runtime_root.resolve()
        / "skills/setup-my-precious/scripts/setup_memory_archive.py"
    )
    if not setup_script.is_file():
        raise SystemExit("runtime root is missing setup_memory_archive.py")
    original_setup_script = public_gate.SETUP_SCRIPT
    public_gate.SETUP_SCRIPT = setup_script
    try:
        packaged = public_gate.run_packaged_case(case, case_root)
    finally:
        public_gate.SETUP_SCRIPT = original_setup_script

    is_abstention = int(bool(case["is_abstention"]))
    observation: dict[str, Any] = {
        "question_type": str(case["question_type"]),
        "is_abstention": is_abstention,
        "source_rejected": 0,
        "packaged_setup_success": int(packaged.get("packaged_setup_success") or 0),
        "updater_success": int(packaged.get("updater_success") or 0),
        "archive_audit_success": int(packaged.get("archive_audit_success") or 0),
        "baseline_retrievable": int(packaged.get("baseline_retrievable") or 0),
        "expected_support_event_count": len(expected_events),
        "preserved_support_event_count": 0,
        "support_memory_count": 0,
        "active_support_memory_count": 0,
        "inactive_support_memory_count": 0,
        "context_package_parse_success": 0,
        "support_candidate_at_1_count": 0,
        "support_candidate_at_5_count": 0,
        "supported_gold_package": 0,
        "supported_decision": int(packaged.get("supported_decision") or 0),
        "abstention_correct": int(packaged.get("abstention_correct") or 0),
        "hard_negative_rejected": int(
            bool(is_abstention) and not packaged.get("supported_decision")
        ),
        "scorer_support_label_missing_count": int(
            not is_abstention and not expected_events
        ),
        "gold_label_ingestion_count": int(
            packaged.get("public_gold_label_ingestion_count") or 0
        ),
        "answer_ingestion_count": int(packaged.get("public_answer_ingestion_count") or 0),
        "direct_memory_injection_count": int(
            packaged.get("synthetic_memory_marker_injection_count") or 0
        )
        + int(packaged.get("direct_synthetic_archive_injection_count") or 0),
        "false_promotion_count": int(
            bool(is_abstention) and bool(packaged.get("supported_decision"))
        ),
        "privacy_leak_count": int(packaged.get("privacy_leak_count") or 0),
    }
    if not observation["updater_success"]:
        observation["source_rejected"] = int(
            _sensitive_source_record_count(case_root) > 0
        )
    if observation["packaged_setup_success"] and observation["updater_success"]:
        support = archived_support_refs(case, case_root, expected_events)
        observation.update(
            {
                "expected_support_event_count": support[
                    "expected_support_event_count"
                ],
                "preserved_support_event_count": support[
                    "preserved_support_event_count"
                ],
            }
        )
        memory_repo = case_root / "archive"
        records = public_gate._load_jsonl(memory_repo / "index/memories.jsonl")
        search_module = public_gate._load_search_module(
            memory_repo / "tools/search_memory.py"
        )
        memory_state = support_memory_state(
            records,
            support["support_refs"],
            inactive_ids=_inactive_memory_ids(search_module, records),
        )
        observation.update(
            {
                key: memory_state[key]
                for key in (
                    "support_memory_count",
                    "active_support_memory_count",
                    "inactive_support_memory_count",
                )
            }
        )
        package = public_gate._context_search(
            memory_repo,
            str(case["question"]),
            "evidence",
        )
        package_state = package_support_state(
            package,
            memory_state["active_support_memory_ids"],
        )
        observation.update(package_state)
        observation["supported_decision"] = int(
            public_gate.context_package_decision(package) == "answer"
        )
        observation["abstention_correct"] = int(
            bool(is_abstention) and not observation["supported_decision"]
        )
        observation["hard_negative_rejected"] = observation["abstention_correct"]
        observation["false_promotion_count"] = int(
            bool(is_abstention) and bool(observation["supported_decision"])
        )
    if not is_abstention:
        observation["first_loss"] = classify_first_loss(observation)
    return observation


def _rate_metric(
    metrics: dict[str, int | float],
    counts: dict[str, dict[str, int]],
    name: str,
    numerator: int,
    denominator: int,
    *,
    empty_value: float = 0.0,
) -> None:
    metrics[name] = numerator / denominator if denominator else empty_value
    counts[name] = {"numerator": numerator, "denominator": denominator}


def aggregate_metrics(
    observations: list[dict[str, Any]],
) -> tuple[dict[str, int | float], dict[str, dict[str, int]]]:
    positives = [row for row in observations if not row.get("is_abstention")]
    abstentions = [row for row in observations if row.get("is_abstention")]
    previously_unexplained = [
        row for row in positives if not row.get("baseline_retrievable")
    ]
    first_losses = [str(row.get("first_loss") or "") for row in positives]
    previously_unexplained_losses = [
        str(row.get("first_loss") or "") for row in previously_unexplained
    ]
    valid_attributions = sum(loss in FIRST_LOSS_TAXONOMY for loss in first_losses)
    valid_previously_unexplained_attributions = sum(
        loss in FIRST_LOSS_TAXONOMY for loss in previously_unexplained_losses
    )
    metrics: dict[str, int | float] = {
        "positive_case_count": len(positives),
        "abstention_case_count": len(abstentions),
        "baseline_retrievable_positive_count": len(positives)
        - len(previously_unexplained),
        "previously_unexplained_positive_count": len(previously_unexplained),
    }
    counts: dict[str, dict[str, int]] = {}
    _rate_metric(
        metrics,
        counts,
        "positive_first_loss_attribution_coverage_rate",
        valid_attributions,
        len(positives),
    )
    _rate_metric(
        metrics,
        counts,
        "previously_unexplained_first_loss_attribution_coverage_rate",
        valid_previously_unexplained_attributions,
        len(previously_unexplained),
        empty_value=1.0,
    )
    for category in FIRST_LOSS_TAXONOMY:
        count = first_losses.count(category)
        metrics[f"{category}_count"] = count
        _rate_metric(
            metrics,
            counts,
            f"{category}_rate",
            count,
            len(positives),
        )
        previously_unexplained_count = previously_unexplained_losses.count(category)
        metrics[f"previously_unexplained_{category}_count"] = (
            previously_unexplained_count
        )
        _rate_metric(
            metrics,
            counts,
            f"previously_unexplained_{category}_rate",
            previously_unexplained_count,
            len(previously_unexplained),
        )
    metrics.update(
        {
            "pre_retrieval_induction_loss_count": int(
                metrics["session_support_omitted_count"]
            )
            + int(metrics["memory_induction_omitted_or_overcompressed_count"]),
            "retrieval_first_loss_count": int(metrics["memory_present_not_top5_count"]),
            "query_support_first_loss_count": int(
                metrics["top1_not_query_supported_count"]
            ),
            "supported_case_count": int(metrics["supported_count"]),
            "first_loss_partition_invariant_violation_count": int(
                valid_attributions != len(positives)
            )
            + int(
                sum(int(metrics[f"{category}_count"]) for category in FIRST_LOSS_TAXONOMY)
                != len(positives)
            ),
            "previously_unexplained_first_loss_partition_invariant_violation_count": int(
                valid_previously_unexplained_attributions
                != len(previously_unexplained)
            )
            + int(
                sum(
                    int(metrics[f"previously_unexplained_{category}_count"])
                    for category in FIRST_LOSS_TAXONOMY
                )
                != len(previously_unexplained)
            ),
            "scorer_support_label_missing_count": sum(
                int(row.get("scorer_support_label_missing_count") or 0)
                for row in positives
            ),
            "gold_label_ingestion_count": sum(
                int(row.get("gold_label_ingestion_count") or 0)
                for row in observations
            ),
            "answer_ingestion_count": sum(
                int(row.get("answer_ingestion_count") or 0) for row in observations
            ),
            "direct_memory_injection_count": sum(
                int(row.get("direct_memory_injection_count") or 0)
                for row in observations
            ),
            "false_promotion_count": sum(
                int(row.get("false_promotion_count") or 0) for row in observations
            ),
            "privacy_leak_count": sum(
                int(row.get("privacy_leak_count") or 0) for row in observations
            ),
            "inactive_support_memory_count": sum(
                int(row.get("inactive_support_memory_count") or 0)
                for row in positives
            ),
        }
    )
    for name, key in (
        ("packaged_setup_success_rate", "packaged_setup_success"),
        ("updater_success_rate", "updater_success"),
        ("archive_audit_success_rate", "archive_audit_success"),
        ("context_package_parse_success_rate", "context_package_parse_success"),
    ):
        _rate_metric(
            metrics,
            counts,
            name,
            sum(int(bool(row.get(key))) for row in observations),
            len(observations),
        )
    expected_support_events = sum(
        int(row.get("expected_support_event_count") or 0) for row in positives
    )
    _rate_metric(
        metrics,
        counts,
        "session_support_event_preservation_rate",
        sum(int(row.get("preserved_support_event_count") or 0) for row in positives),
        expected_support_events,
    )
    _rate_metric(
        metrics,
        counts,
        "hard_negative_rejection_rate",
        sum(int(row.get("hard_negative_rejected") or 0) for row in abstentions),
        len(abstentions),
    )
    _rate_metric(
        metrics,
        counts,
        "abstention_accuracy",
        sum(int(row.get("abstention_correct") or 0) for row in abstentions),
        len(abstentions),
    )
    return metrics, counts


def select_repair_target(metrics: dict[str, int | float]) -> dict[str, Any]:
    induction_categories = (
        "session_support_omitted",
        "memory_induction_omitted_or_overcompressed",
    )
    counts = {
        category: int(metrics.get(f"{category}_count", 0))
        for category in induction_categories
    }
    pre_retrieval_count = sum(counts.values())
    target = max(induction_categories, key=lambda category: counts[category])
    target_count = counts[target]
    target_share = target_count / pre_retrieval_count if pre_retrieval_count else 0.0
    eligible = target_count >= 5 and target_share >= 0.40
    if eligible:
        reason = "repair_eligible"
    else:
        outside_categories = (
            "source_rejected",
            "update_failed",
            "archive_audit_failed",
            "memory_present_not_top5",
            "top1_not_query_supported",
        )
        outside_max = max(
            (int(metrics.get(f"{category}_count", 0)) for category in outside_categories),
            default=0,
        )
        reason = (
            "dominant_loss_outside_induction"
            if outside_max > target_count
            else "no_dominant_induction_defect"
        )
    return {
        "repair_eligible": int(eligible),
        "targeted_defect": target if eligible else None,
        "targeted_defect_count": target_count,
        "targeted_defect_share": target_share,
        "minimum_case_count": 5,
        "minimum_pre_retrieval_share": 0.40,
        "decision_reason": reason,
    }


def _json_fingerprint(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def runtime_bundle_fingerprint(runtime_root: Path) -> dict[str, Any]:
    root = runtime_root.resolve()
    digest = hashlib.sha256()
    for relative in RUNTIME_COMPONENTS:
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"runtime root is missing required component: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "fingerprint_sha256": digest.hexdigest(),
        "component_count": len(RUNTIME_COMPONENTS),
        "components": list(RUNTIME_COMPONENTS),
    }


def evaluate_holdout_decision(
    targeted_defect: str,
    baseline_metrics: dict[str, int | float],
    candidate_metrics: dict[str, int | float],
) -> dict[str, int | float | str]:
    if targeted_defect not in {
        "session_support_omitted",
        "memory_induction_omitted_or_overcompressed",
    }:
        raise ValueError("holdout target must be an automatic-induction defect")
    metric_name = f"{targeted_defect}_count"
    baseline_count = int(baseline_metrics.get(metric_name, 0))
    candidate_count = int(candidate_metrics.get(metric_name, 0))
    recovered = max(0, baseline_count - candidate_count)
    reduction_rate = recovered / baseline_count if baseline_count else 0.0
    baseline_pre_retrieval = int(
        baseline_metrics.get("pre_retrieval_induction_loss_count", 0)
    )
    candidate_pre_retrieval = int(
        candidate_metrics.get("pre_retrieval_induction_loss_count", 0)
    )
    recovered_pre_retrieval = max(
        0,
        baseline_pre_retrieval - candidate_pre_retrieval,
    )
    pre_retrieval_reduction_rate = (
        recovered_pre_retrieval / baseline_pre_retrieval
        if baseline_pre_retrieval
        else 0.0
    )
    no_new_pipeline_failures = (
        int(candidate_metrics.get("source_rejected_count", 0))
        <= int(baseline_metrics.get("source_rejected_count", 0))
        and all(
            float(candidate_metrics.get(name, -1.0))
            >= float(baseline_metrics.get(name, 2.0))
            for name in (
                "packaged_setup_success_rate",
                "updater_success_rate",
                "archive_audit_success_rate",
            )
        )
    )
    safety_passed = (
        float(candidate_metrics.get("positive_first_loss_attribution_coverage_rate", 0.0))
        == 1.0
        and int(
            candidate_metrics.get("first_loss_partition_invariant_violation_count", 1)
        )
        == 0
        and float(candidate_metrics.get("hard_negative_rejection_rate", 0.0)) == 1.0
        and float(candidate_metrics.get("abstention_accuracy", 0.0)) == 1.0
        and int(candidate_metrics.get("false_promotion_count", 1)) == 0
        and int(candidate_metrics.get("gold_label_ingestion_count", 1)) == 0
        and int(candidate_metrics.get("direct_memory_injection_count", 1)) == 0
        and int(candidate_metrics.get("privacy_leak_count", 1)) == 0
        and no_new_pipeline_failures
    )
    gain_passed = (
        recovered >= 2
        and reduction_rate >= 0.25
        and recovered_pre_retrieval >= 2
        and pre_retrieval_reduction_rate >= 0.25
    )
    if not safety_passed:
        readiness_status = "induction_no_go"
        reason = "safety_regression"
    elif not gain_passed:
        readiness_status = "induction_no_go"
        reason = "insufficient_holdout_gain"
    else:
        readiness_status = "induction_repair_go"
        reason = "holdout_gain_and_safety_passed"
    return {
        "readiness_status": readiness_status,
        "decision_reason": reason,
        "targeted_defect": targeted_defect,
        "baseline_targeted_loss_count": baseline_count,
        "candidate_targeted_loss_count": candidate_count,
        "recovered_holdout_positive_count": recovered,
        "targeted_holdout_loss_reduction_rate": reduction_rate,
        "recovered_pre_retrieval_positive_count": recovered_pre_retrieval,
        "pre_retrieval_induction_loss_reduction_rate": pre_retrieval_reduction_rate,
        "minimum_recovered_holdout_positive_count": 2,
        "minimum_targeted_holdout_loss_reduction_rate": 0.25,
        "safety_passed": int(safety_passed),
        "gain_passed": int(gain_passed),
    }


def build_report(
    *,
    cohort: str,
    mode: str,
    observations: list[dict[str, Any]],
    dataset: dict[str, Any],
    selection: dict[str, Any],
    runtime_bundle: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    local_paths: list[Path],
    calibration_report: dict[str, Any] | None = None,
    baseline_report: dict[str, Any] | None = None,
    candidate_strategy: str | None = None,
) -> dict[str, Any]:
    if cohort not in {"offline", "calibration", "holdout"}:
        raise ValueError("cohort must be offline, calibration, or holdout")
    metrics, counts = aggregate_metrics(observations)
    repair_decision = select_repair_target(metrics)
    structural_valid = (
        metrics["positive_first_loss_attribution_coverage_rate"] == 1.0
        and metrics["first_loss_partition_invariant_violation_count"] == 0
        and metrics[
            "previously_unexplained_first_loss_attribution_coverage_rate"
        ]
        == 1.0
        and metrics[
            "previously_unexplained_first_loss_partition_invariant_violation_count"
        ]
        == 0
        and metrics["scorer_support_label_missing_count"] == 0
        and metrics["gold_label_ingestion_count"] == 0
        and metrics["answer_ingestion_count"] == 0
        and metrics["direct_memory_injection_count"] == 0
        and int(selection.get("cohort_overlap_count") or 0) == 0
        and int(selection.get("holdout_selection_fingerprint_match", 1)) == 1
        and int(selection.get("calibration_selection_fingerprint_match", 1)) == 1
    )

    comparison: dict[str, Any] = {}
    if not structural_valid:
        readiness_status = "induction_no_go"
        decision_reason = "safety_regression"
    elif cohort in {"offline", "calibration"}:
        readiness_status = (
            "repair_eligible" if repair_decision["repair_eligible"] else "induction_no_go"
        )
        decision_reason = str(repair_decision["decision_reason"])
    else:
        calibration_decision = (
            calibration_report.get("repair_decision", {})
            if isinstance(calibration_report, dict)
            else {}
        )
        targeted_defect = calibration_decision.get("targeted_defect")
        if not isinstance(targeted_defect, str):
            readiness_status = "induction_no_go"
            decision_reason = str(
                calibration_decision.get(
                    "decision_reason", "no_dominant_induction_defect"
                )
            )
        elif baseline_report is None:
            readiness_status = "holdout_baseline_completed"
            decision_reason = "candidate_not_evaluated"
        else:
            baseline_metrics = baseline_report.get("metrics", {})
            if not isinstance(baseline_metrics, dict) or not candidate_strategy:
                readiness_status = "induction_no_go"
                decision_reason = "safety_regression"
            else:
                comparison = evaluate_holdout_decision(
                    targeted_defect,
                    baseline_metrics,
                    metrics,
                )
                readiness_status = str(comparison["readiness_status"])
                decision_reason = str(comparison["decision_reason"])

    first_loss_by_question_type: dict[str, dict[str, int]] = {}
    for row in observations:
        if row.get("is_abstention"):
            continue
        question_type = str(row.get("question_type") or "unknown")
        bucket = first_loss_by_question_type.setdefault(
            question_type,
            {category: 0 for category in FIRST_LOSS_TAXONOMY},
        )
        first_loss = str(row.get("first_loss") or "")
        if first_loss in bucket:
            bucket[first_loss] += 1

    strategy_fingerprint = (
        hashlib.sha256(candidate_strategy.encode("utf-8")).hexdigest()
        if candidate_strategy
        else None
    )
    configuration_payload = {
        "report_version": REPORT_VERSION,
        "taxonomy": FIRST_LOSS_TAXONOMY,
        "minimum_repair_case_count": 5,
        "minimum_repair_pre_retrieval_share": 0.40,
        "minimum_holdout_recovery_count": 2,
        "minimum_holdout_reduction_rate": 0.25,
        "candidate_strategy_count": int(candidate_strategy is not None),
        "candidate_strategy_fingerprint_sha256": strategy_fingerprint,
    }
    report = {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "mode": mode,
        "cohort": cohort,
        "status": "passed" if structural_valid else "failed",
        "readiness_status": readiness_status,
        "decision_reason": decision_reason,
        "dataset": dataset,
        "selection": selection,
        "runtime_bundle": runtime_bundle,
        "configuration": {
            "fingerprint_sha256": _json_fingerprint(configuration_payload),
            "candidate_strategy_count": int(candidate_strategy is not None),
            "candidate_strategy_fingerprint_sha256": strategy_fingerprint,
        },
        "taxonomy": list(FIRST_LOSS_TAXONOMY),
        "metrics": metrics,
        "metric_counts": counts,
        "repair_decision": repair_decision,
        "holdout_comparison": comparison,
        "first_loss_by_question_type": dict(sorted(first_loss_by_question_type.items())),
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "support_events_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "deterministic source-to-session-to-memory first-loss attribution only; not LLM "
            "answer quality, semantic ranking quality, vector search, ontology discovery, or "
            "public leaderboard parity"
        ),
    }
    metrics["privacy_leak_count"] = int(metrics["privacy_leak_count"]) + int(
        public_gate.aggregate_privacy_leak_count(report, selected_rows, local_paths)
    )
    if metrics["privacy_leak_count"]:
        report["status"] = "failed"
        report["readiness_status"] = "induction_no_go"
        report["decision_reason"] = "safety_regression"
    return report


def run_offline_fixture() -> dict[str, Any]:
    rows = json.loads(public_gate.OFFLINE_FIXTURE.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SystemExit("offline first-loss fixture must contain object rows")
    selected = [dict(row) for row in rows]
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        observations = [
            observe_packaged_case(
                row,
                case_ordinal=ordinal,
                case_root=work_dir / f"case-{ordinal:03d}",
                runtime_root=REPO_ROOT,
            )
            for ordinal, row in enumerate(selected, 1)
        ]
    selection = {
        "cohort": "offline",
        "selected_case_count": len(selected),
        "selected_fingerprint_sha256": public_gate._selection_fingerprint(selected),
        "cohort_overlap_count": 0,
        "holdout_selection_fingerprint_match": 1,
        "calibration_selection_fingerprint_match": 1,
    }
    return build_report(
        cohort="offline",
        mode="offline_fixture",
        observations=observations,
        dataset={
            "source": "synthetic public-data-free fixture",
            "source_url": "offline",
            "sha256": public_gate._file_sha256(public_gate.OFFLINE_FIXTURE),
            "input_record_count": len(rows),
        },
        selection=selection,
        runtime_bundle=runtime_bundle_fingerprint(REPO_ROOT),
        selected_rows=selected,
        local_paths=[public_gate.OFFLINE_FIXTURE],
    )


def _failed_public_report(
    *,
    source_url: str,
    dataset_sha256: str,
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "mode": "public_unscored",
        "cohort": "unscored",
        "status": "failed",
        "readiness_status": "induction_no_go",
        "decision_reason": "safety_regression",
        "failure_reason": failure_reason,
        "dataset": {
            "source": OFFICIAL_DATASET_SOURCE,
            "source_url": source_url,
            "sha256": dataset_sha256,
        },
        "metrics": {"privacy_leak_count": 0},
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
        },
        "claim_boundary": "dataset contract failed; no induction-readiness claim",
    }


def _load_aggregate_report(path_text: str, *, cohort: str) -> dict[str, Any]:
    path = public_gate.require_external_artifact_path(
        Path(path_text), f"{cohort} aggregate report"
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"unable to load {cohort} aggregate report") from exc
    if (
        not isinstance(value, dict)
        or value.get("report_kind") != REPORT_KIND
        or value.get("cohort") != cohort
        or value.get("status") != "passed"
        or (value.get("dataset") or {}).get("sha256") != OFFICIAL_DATASET_SHA256
    ):
        raise SystemExit(f"{cohort} aggregate report contract mismatch")
    expected_fingerprint = (
        CALIBRATION_FINGERPRINT if cohort == "calibration" else HOLDOUT_FINGERPRINT
    )
    if (
        (value.get("selection") or {}).get("selected_fingerprint_sha256")
        != expected_fingerprint
    ):
        raise SystemExit(f"{cohort} aggregate report selection mismatch")
    configuration = value.get("configuration") or {}
    if cohort == "calibration":
        repair_decision = value.get("repair_decision") or {}
        if (
            value.get("readiness_status") != "repair_eligible"
            or repair_decision.get("repair_eligible") != 1
            or configuration.get("candidate_strategy_count") != 0
        ):
            raise SystemExit("frozen calibration contract mismatch")
    elif (
        value.get("readiness_status") != "holdout_baseline_completed"
        or configuration.get("candidate_strategy_count") != 0
        or value.get("holdout_comparison") not in ({}, None)
    ):
        raise SystemExit("frozen baseline contract mismatch")
    return value


def run_public_dataset(args: argparse.Namespace) -> dict[str, Any]:
    input_path = public_gate.require_external_artifact_path(
        Path(args.public_input), "public benchmark input"
    )
    try:
        dataset_sha256 = public_gate._file_sha256(input_path)
    except OSError:
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256="unavailable",
            failure_reason="dataset_unreadable",
        )
    if dataset_sha256 != OFFICIAL_DATASET_SHA256:
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256=dataset_sha256,
            failure_reason="dataset_sha_mismatch",
        )
    try:
        rows = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256=dataset_sha256,
            failure_reason="dataset_schema_incompatible",
        )
    if not isinstance(rows, list):
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256=dataset_sha256,
            failure_reason="dataset_schema_incompatible",
        )
    try:
        holdout, calibration = query_calibration_gate.select_disjoint_cohorts(
            rows,
            holdout_seed=query_calibration_gate.HOLDOUT_SEED,
            calibration_seed=query_calibration_gate.CALIBRATION_SEED,
            positive_per_type=5,
            abstention_count=10,
        )
    except SystemExit:
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256=dataset_sha256,
            failure_reason="dataset_schema_incompatible",
        )

    holdout_fingerprint = public_gate._selection_fingerprint(holdout)
    calibration_fingerprint = public_gate._selection_fingerprint(calibration)
    if (
        holdout_fingerprint != HOLDOUT_FINGERPRINT
        or calibration_fingerprint != CALIBRATION_FINGERPRINT
    ):
        return _failed_public_report(
            source_url=args.dataset_source_url,
            dataset_sha256=dataset_sha256,
            failure_reason="selection_fingerprint_mismatch",
        )
    selected = calibration if args.cohort == "calibration" else holdout
    holdout_ids = {str(row["question_id"]) for row in holdout}
    calibration_ids = {str(row["question_id"]) for row in calibration}
    work_dir = public_gate.require_external_artifact_path(
        Path(args.work_dir), "public benchmark work directory"
    )
    if work_dir.exists() and any(work_dir.iterdir()):
        raise SystemExit("--work-dir must be empty")
    work_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    observations = [
        observe_packaged_case(
            row,
            case_ordinal=ordinal,
            case_root=work_dir / f"case-{ordinal:03d}",
            runtime_root=runtime_root,
        )
        for ordinal, row in enumerate(selected, 1)
    ]
    calibration_report = (
        _load_aggregate_report(args.calibration_report, cohort="calibration")
        if args.calibration_report
        else None
    )
    baseline_report = (
        _load_aggregate_report(args.baseline_report, cohort="holdout")
        if args.baseline_report
        else None
    )
    report_path = public_gate.require_external_artifact_path(
        Path(args.report_file), "public benchmark report"
    )
    selection = {
        "cohort": args.cohort,
        "holdout_seed": query_calibration_gate.HOLDOUT_SEED,
        "calibration_seed": query_calibration_gate.CALIBRATION_SEED,
        "positive_per_type": 5,
        "abstention_count": 10,
        "selected_case_count": len(selected),
        "holdout_case_count": len(holdout),
        "calibration_case_count": len(calibration),
        "cohort_overlap_count": len(holdout_ids.intersection(calibration_ids)),
        "holdout_fingerprint_sha256": holdout_fingerprint,
        "calibration_fingerprint_sha256": calibration_fingerprint,
        "selected_fingerprint_sha256": public_gate._selection_fingerprint(selected),
        "holdout_selection_fingerprint_match": int(
            holdout_fingerprint == HOLDOUT_FINGERPRINT
        ),
        "calibration_selection_fingerprint_match": int(
            calibration_fingerprint == CALIBRATION_FINGERPRINT
        ),
    }
    return build_report(
        cohort=args.cohort,
        mode=f"public_{args.cohort}",
        observations=observations,
        dataset={
            "source": OFFICIAL_DATASET_SOURCE,
            "source_url": args.dataset_source_url,
            "sha256": dataset_sha256,
            "input_record_count": len(rows),
        },
        selection=selection,
        runtime_bundle=runtime_bundle_fingerprint(runtime_root),
        selected_rows=selected,
        local_paths=[
            input_path,
            work_dir,
            report_path,
            *(
                [Path(args.calibration_report).expanduser().resolve()]
                if args.calibration_report
                else []
            ),
            *(
                [Path(args.baseline_report).expanduser().resolve()]
                if args.baseline_report
                else []
            ),
        ],
        calibration_report=calibration_report,
        baseline_report=baseline_report,
        candidate_strategy=args.candidate_strategy,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline-fixture", action="store_true")
    mode.add_argument("--public-input")
    parser.add_argument("--dataset-source-url")
    parser.add_argument("--cohort", choices=("calibration", "holdout"))
    parser.add_argument("--work-dir")
    parser.add_argument("--report-file")
    parser.add_argument("--runtime-root", default=str(REPO_ROOT))
    parser.add_argument("--calibration-report")
    parser.add_argument("--baseline-report")
    parser.add_argument("--candidate-strategy")
    args = parser.parse_args(argv)
    if args.public_input and not all(
        (args.dataset_source_url, args.cohort, args.work_dir, args.report_file)
    ):
        parser.error(
            "public mode requires --dataset-source-url, --cohort, --work-dir, and --report-file"
        )
    if args.cohort == "holdout" and not args.calibration_report:
        parser.error("holdout mode requires --calibration-report")
    if bool(args.baseline_report) != bool(args.candidate_strategy):
        parser.error("--baseline-report and --candidate-strategy must be used together")
    if args.candidate_strategy and not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,63}", args.candidate_strategy
    ):
        parser.error("--candidate-strategy must be a short lowercase slug")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_offline_fixture() if args.offline_fixture else run_public_dataset(args)
    rendered = json.dumps(report, sort_keys=True)
    if args.report_file:
        report_path = public_gate.require_external_artifact_path(
            Path(args.report_file), "public benchmark report"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
