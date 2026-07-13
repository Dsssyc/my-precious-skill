#!/usr/bin/env python3
"""Attribute session-support event loss without exposing scorer labels to runtime code."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
FIRST_LOSS_GATE_PATH = REPO_ROOT / "benchmarks/public_induction_first_loss_gate.py"
REPORT_KIND = "session_support_preservation_gate"
REPORT_VERSION = 1
SUPPORT_EVENT_TAXONOMY = (
    "source_event_missing_after_extraction",
    "durability_filter_rejected",
    "no_summary_channel_candidate",
    "evidence_budget_evicted",
    "evidence_bound_to_wrong_ordinal",
    "evidence_source_entry_missing",
    "source_anchor_materialization_failed",
    "preserved",
)
ALLOWED_REPAIR_SURFACES = frozenset(
    {
        "durability_filter_rejected",
        "no_summary_channel_candidate",
        "evidence_budget_evicted",
        "evidence_bound_to_wrong_ordinal",
        "evidence_source_entry_missing",
        "source_anchor_materialization_failed",
    }
)
MINIMUM_DOMINANT_CASE_COUNT = 5
MINIMUM_DOMINANT_CASE_SHARE = 0.40
MINIMUM_CALIBRATION_RECOVERY = 3
MINIMUM_CALIBRATION_EVENT_GAIN = 3
MINIMUM_HOLDOUT_RECOVERY = 4
MINIMUM_HOLDOUT_REDUCTION = 0.25
MINIMUM_HOLDOUT_EVENT_GAIN = 4
SAFETY_NONINCREASING_COUNT_METRICS = (
    "source_rejected_count",
    "update_failed_count",
    "archive_audit_failed_count",
)
SAFETY_NONDECREASING_RATE_METRICS = (
    "packaged_setup_success_rate",
    "updater_success_rate",
    "archive_audit_success_rate",
)
SAFETY_ONE_RATE_METRICS = (
    "positive_first_loss_attribution_coverage_rate",
    "support_event_attribution_coverage_rate",
    "hard_negative_rejection_rate",
    "abstention_accuracy",
)
SAFETY_ZERO_COUNT_METRICS = (
    "first_loss_partition_invariant_violation_count",
    "support_event_partition_invariant_violation_count",
    "false_promotion_count",
    "gold_label_ingestion_count",
    "answer_ingestion_count",
    "direct_memory_injection_count",
    "privacy_leak_count",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


first_loss_gate = _load_module("v245_public_induction_first_loss_gate", FIRST_LOSS_GATE_PATH)
OFFICIAL_DATASET_SHA256 = first_loss_gate.OFFICIAL_DATASET_SHA256
OFFICIAL_DATASET_SOURCE = first_loss_gate.OFFICIAL_DATASET_SOURCE
CALIBRATION_FINGERPRINT = first_loss_gate.CALIBRATION_FINGERPRINT
HOLDOUT_FINGERPRINT = first_loss_gate.HOLDOUT_FINGERPRINT
V244_BASELINE_RUNTIME_FINGERPRINT = (
    "d6c2b27f44432590a96bc21ec76dd11ee2906e68bbc2eebf30b4cfa2517dd1c0"
)
V244_BASELINE_COUNTS = {
    "calibration": {
        "session_support_omitted_count": 15,
        "preserved_support_event_count": 19,
        "expected_support_event_count": 56,
    },
    "holdout": {
        "session_support_omitted_count": 15,
        "preserved_support_event_count": 19,
        "expected_support_event_count": 46,
    },
}


@dataclass(frozen=True)
class EventProbe:
    kind: str
    text: str
    line_number: int
    event_ordinal: int


def classify_support_event_trace(trace: dict[str, Any]) -> str:
    """Return the first terminal event-loss stage in pipeline order."""
    if not trace.get("source_event_present"):
        return "source_event_missing_after_extraction"
    if not trace.get("durability_candidate_present"):
        return "durability_filter_rejected"
    if not trace.get("summary_channel_candidate_present"):
        return "no_summary_channel_candidate"
    if not trace.get("evidence_candidate_present"):
        return "evidence_budget_evicted"
    if trace.get("evidence_source_entry_present") and not trace.get(
        "evidence_bound_to_expected_locator"
    ):
        return "evidence_bound_to_wrong_ordinal"
    if not trace.get("evidence_source_entry_present"):
        return "evidence_source_entry_missing"
    if not trace.get("source_anchor_present"):
        return "source_anchor_materialization_failed"
    return "preserved"


def scorer_support_source_locators(row: dict[str, Any]) -> set[tuple[str, int, int]]:
    """Map scorer turn positions to the JSONL locator used by the packaged updater."""
    return {
        (session_id, turn_ordinal, 1)
        for session_id, turn_ordinal in first_loss_gate.scorer_support_event_ordinals(row)
    }


def _summary_channel_texts(summary_data: dict[str, Any]) -> Iterable[str]:
    for key in ("user_intent", "final_state"):
        value = summary_data.get(key)
        if isinstance(value, str) and value:
            yield value
    for key in ("context", "facts", "decisions", "problems", "unresolved"):
        values = summary_data.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value:
                    yield value


def _source_locator(value: object) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    line_number = value.get("line_number")
    event_ordinal = value.get("event_ordinal")
    if not isinstance(line_number, int) or not isinstance(event_ordinal, int):
        return None
    return line_number, event_ordinal


def trace_support_event(
    *,
    expected_locator: tuple[int, int],
    events: list[Any],
    summary_data: dict[str, Any],
    source_anchors: list[dict[str, Any]],
    text_key: Callable[[str], str],
    durable_keys: Callable[[Any], set[str]],
) -> dict[str, int | str]:
    """Trace one scorer event through extraction, selection, binding, and anchoring."""
    source_events = [
        event
        for event in events
        if (int(event.line_number), int(event.event_ordinal)) == expected_locator
    ]
    candidate_keys = {
        key
        for event in source_events
        for key in durable_keys(event)
        if isinstance(key, str) and key
    }
    summary_match = any(
        text_key(text) in candidate_keys for text in _summary_channel_texts(summary_data)
    )
    evidence = summary_data.get("evidence")
    evidence_values = evidence if isinstance(evidence, list) else []
    quote_id = ""
    for index, value in enumerate(evidence_values, 1):
        if isinstance(value, str) and text_key(value) in candidate_keys:
            quote_id = f"ev_{index:03d}"
            break

    evidence_source = next(
        (
            value
            for value in summary_data.get("evidence_sources") or []
            if isinstance(value, dict) and value.get("quote_id") == quote_id
        ),
        None,
    )
    bound_locator = _source_locator(evidence_source)
    source_anchor = next(
        (
            value
            for value in source_anchors
            if isinstance(value, dict) and value.get("quote_id") == quote_id
        ),
        None,
    )
    anchor_locator = _source_locator(source_anchor)
    trace: dict[str, int | str] = {
        "source_event_present": int(bool(source_events)),
        "durability_candidate_present": int(bool(candidate_keys)),
        "summary_channel_candidate_present": int(summary_match),
        "evidence_candidate_present": int(bool(quote_id)),
        "evidence_source_entry_present": int(evidence_source is not None),
        "evidence_bound_to_expected_locator": int(bound_locator == expected_locator),
        "source_anchor_present": int(
            source_anchor is not None and anchor_locator == expected_locator
        ),
        "evidence_quote_id": quote_id,
    }
    trace["category"] = classify_support_event_trace(trace)
    return trace


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _archive_source_payloads(memory_repo: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        meta = _load_json_object(meta_path)
        source_record = meta.get("source_record")
        source_map_path = meta.get("source_map_path")
        evidence_path = meta.get("evidence_path")
        if not all(isinstance(value, str) and value for value in (source_record, source_map_path, evidence_path)):
            continue
        payloads[str(Path(source_record).resolve())] = {
            "source_map": _load_json_object(memory_repo / str(source_map_path)),
            "evidence_path": str(evidence_path),
        }
    return payloads


def _durable_event_keys(updater: Any, event: Any) -> set[str]:
    candidates = [
        updater.durable_memory_text(event.text),
        updater.durable_user_memory_text(event.text)
        if event.kind == "user"
        else "",
        updater.natural_user_memory_fact(event.text)
        if event.kind == "user"
        else "",
    ]
    return {
        key
        for candidate in candidates
        if candidate and (key := updater.source_text_key(candidate))
    }


def trace_packaged_support_events(
    row: dict[str, Any],
    *,
    case: dict[str, Any],
    case_root: Path,
) -> dict[str, Any]:
    expected = scorer_support_source_locators(row)
    updater_path = case_root / "archive/tools/update_memory_archive.py"
    if not updater_path.is_file():
        traces = [
            {
                "category": "source_event_missing_after_extraction",
                "source_event_present": 0,
                "durability_candidate_present": 0,
                "summary_channel_candidate_present": 0,
                "evidence_candidate_present": 0,
                "evidence_source_entry_present": 0,
                "evidence_bound_to_expected_locator": 0,
                "source_anchor_present": 0,
            }
            for _ in sorted(expected)
        ]
        return {
            "expected_support_event_count": len(expected),
            "preserved_support_event_count": 0,
            "support_event_traces": traces,
            "support_refs": set(),
        }

    module_name = "v245_updater_" + hashlib.sha256(
        str(updater_path).encode("utf-8")
    ).hexdigest()[:16]
    updater = _load_module(module_name, updater_path)
    memory_repo = case_root / "archive"
    archive_payloads = _archive_source_payloads(memory_repo)
    source_by_session = {
        str(record["scorer_session_id"]): (
            case_root
            / "source-records"
            / str(record["record_id"])
            / "record.jsonl"
        )
        for record in case.get("source_records") or []
    }
    traces: list[dict[str, Any]] = []
    support_refs: set[tuple[str, str]] = set()
    project_name = f"public-case-{int(case['case_ordinal']):03d}"
    for session_id, line_number, event_ordinal in sorted(expected):
        source_path = source_by_session.get(session_id)
        if source_path is None or not source_path.is_file():
            trace = {
                "source_event_present": 0,
                "durability_candidate_present": 0,
                "summary_channel_candidate_present": 0,
                "evidence_candidate_present": 0,
                "evidence_source_entry_present": 0,
                "evidence_bound_to_expected_locator": 0,
                "source_anchor_present": 0,
            }
            trace["category"] = classify_support_event_trace(trace)
            traces.append(trace)
            continue
        source_text = source_path.read_text(encoding="utf-8")
        redacted_text, _ = updater.redact_text(source_text)
        events = updater.extract_source_events(source_path, redacted_text, source_text)
        summary_data = updater.summarize_events(events, project_name)
        payload = archive_payloads.get(str(source_path.resolve()), {})
        source_map = payload.get("source_map")
        source_anchors = (
            source_map.get("evidence_source_anchors") or []
            if isinstance(source_map, dict)
            else []
        )
        trace = trace_support_event(
            expected_locator=(line_number, event_ordinal),
            events=events,
            summary_data=summary_data,
            source_anchors=source_anchors,
            text_key=updater.source_text_key,
            durable_keys=lambda event: _durable_event_keys(updater, event),
        )
        evidence_path = payload.get("evidence_path")
        quote_id = trace.get("evidence_quote_id")
        if (
            trace["category"] == "preserved"
            and isinstance(evidence_path, str)
            and isinstance(quote_id, str)
            and quote_id
        ):
            support_refs.add((evidence_path, quote_id))
        traces.append(trace)
    return {
        "expected_support_event_count": len(expected),
        "preserved_support_event_count": sum(
            int(trace.get("category") == "preserved") for trace in traces
        ),
        "support_event_traces": traces,
        "support_refs": support_refs,
    }


def observe_packaged_case(
    row: dict[str, Any],
    *,
    case_ordinal: int,
    case_root: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    """Run V2.44 unchanged, then score complete event locators in a sidecar."""
    observation = first_loss_gate.observe_packaged_case(
        row,
        case_ordinal=case_ordinal,
        case_root=case_root,
        runtime_root=runtime_root,
    )
    case = first_loss_gate.public_gate.convert_longmemeval_case(
        row, case_ordinal=case_ordinal
    )
    observation["v244_preserved_support_event_count"] = int(
        observation.get("preserved_support_event_count") or 0
    )
    observation["v244_first_loss"] = observation.get("first_loss")
    traced = trace_packaged_support_events(row, case=case, case_root=case_root)
    observation.update(
        {
            key: traced[key]
            for key in (
                "expected_support_event_count",
                "preserved_support_event_count",
                "support_event_traces",
            )
        }
    )

    if observation.get("packaged_setup_success") and observation.get("updater_success"):
        memory_repo = case_root / "archive"
        records = first_loss_gate.public_gate._load_jsonl(
            memory_repo / "index/memories.jsonl"
        )
        search_module = first_loss_gate.public_gate._load_search_module(
            memory_repo / "tools/search_memory.py"
        )
        memory_state = first_loss_gate.support_memory_state(
            records,
            traced["support_refs"],
            inactive_ids=first_loss_gate._inactive_memory_ids(search_module, records),
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
        package = first_loss_gate.public_gate._context_search(
            memory_repo, str(case["question"]), "evidence"
        )
        observation.update(
            first_loss_gate.package_support_state(
                package, memory_state["active_support_memory_ids"]
            )
        )
        observation["supported_decision"] = int(
            first_loss_gate.public_gate.context_package_decision(package) == "answer"
        )
        observation["abstention_correct"] = int(
            bool(case["is_abstention"]) and not observation["supported_decision"]
        )
        observation["hard_negative_rejected"] = observation["abstention_correct"]
        observation["false_promotion_count"] = int(
            bool(case["is_abstention"]) and bool(observation["supported_decision"])
        )
    if not observation.get("is_abstention"):
        observation["first_loss"] = first_loss_gate.classify_first_loss(observation)
    return observation


def _rate(
    metrics: dict[str, int | float],
    counts: dict[str, dict[str, int]],
    name: str,
    numerator: int,
    denominator: int,
) -> None:
    metrics[name] = numerator / denominator if denominator else 0.0
    counts[name] = {"numerator": numerator, "denominator": denominator}


def aggregate_support_metrics(
    observations: list[dict[str, Any]],
) -> tuple[dict[str, int | float], dict[str, dict[str, int]]]:
    base_metrics, base_counts = first_loss_gate.aggregate_metrics(observations)
    metrics: dict[str, int | float] = dict(base_metrics)
    counts = dict(base_counts)
    positives = [row for row in observations if not row.get("is_abstention")]
    traces = [
        trace
        for row in positives
        for trace in row.get("support_event_traces") or []
        if isinstance(trace, dict)
    ]
    expected_count = sum(
        int(row.get("expected_support_event_count") or 0) for row in positives
    )
    valid_traces = [
        trace for trace in traces if trace.get("category") in SUPPORT_EVENT_TAXONOMY
    ]
    invalid_count = len(traces) - len(valid_traces)
    partition_violation_count = invalid_count + abs(expected_count - len(traces))
    metrics["expected_support_event_count"] = expected_count
    metrics["preserved_support_event_count"] = sum(
        int(trace.get("category") == "preserved") for trace in valid_traces
    )
    metrics["support_event_partition_invariant_violation_count"] = (
        partition_violation_count
    )
    v244_preserved_count = sum(
        int(row.get("v244_preserved_support_event_count") or 0) for row in positives
    )
    v244_omitted_count = sum(
        int(row.get("v244_first_loss") == "session_support_omitted")
        for row in positives
    )
    locator_disagreement_count = sum(
        int(
            bool(row.get("v244_preserved_support_event_count"))
            != bool(row.get("preserved_support_event_count"))
        )
        for row in positives
        if "v244_preserved_support_event_count" in row
    )
    metrics["v244_preserved_support_event_count"] = v244_preserved_count
    metrics["v244_session_support_omitted_count"] = v244_omitted_count
    metrics["v244_locator_support_status_disagreement_count"] = (
        locator_disagreement_count
    )
    _rate(
        metrics,
        counts,
        "v244_session_support_event_preservation_rate",
        v244_preserved_count,
        expected_count,
    )
    _rate(
        metrics,
        counts,
        "support_event_attribution_coverage_rate",
        len(valid_traces),
        expected_count,
    )
    _rate(
        metrics,
        counts,
        "session_support_event_preservation_rate",
        int(metrics["preserved_support_event_count"]),
        expected_count,
    )
    for category in SUPPORT_EVENT_TAXONOMY:
        count = sum(int(trace.get("category") == category) for trace in valid_traces)
        metrics[f"{category}_count"] = count
        _rate(metrics, counts, f"{category}_rate", count, expected_count)
    return metrics, counts


def select_session_repair_target(
    observations: list[dict[str, Any]], metrics: dict[str, int | float]
) -> dict[str, Any]:
    omitted = [
        row
        for row in observations
        if not row.get("is_abstention")
        and row.get("first_loss") == "session_support_omitted"
    ]
    case_counts = {
        category: sum(
            int(
                any(
                    isinstance(trace, dict) and trace.get("category") == category
                    for trace in row.get("support_event_traces") or []
                )
            )
            for row in omitted
        )
        for category in SUPPORT_EVENT_TAXONOMY
        if category != "preserved"
    }
    target = (
        max(case_counts, key=case_counts.get)
        if omitted and any(case_counts.values())
        else None
    )
    target_count = case_counts.get(target, 0) if target else 0
    target_share = target_count / len(omitted) if omitted else 0.0
    dominant = (
        target_count >= MINIMUM_DOMINANT_CASE_COUNT
        and target_share >= MINIMUM_DOMINANT_CASE_SHARE
    )
    if not dominant:
        reason = "no_dominant_session_loss"
        eligible = False
    elif target not in ALLOWED_REPAIR_SURFACES:
        reason = "dominant_loss_outside_allowed_surface"
        eligible = False
    else:
        reason = "repair_eligible"
        eligible = True
    return {
        "repair_eligible": int(eligible),
        "targeted_defect": target,
        "targeted_defect_case_count": target_count,
        "targeted_defect_case_share": target_share,
        "session_support_omitted_case_count": len(omitted),
        "minimum_case_count": MINIMUM_DOMINANT_CASE_COUNT,
        "minimum_case_share": MINIMUM_DOMINANT_CASE_SHARE,
        "decision_reason": reason,
        "case_counts": case_counts,
    }


def safe_metric_fixture(**overrides: int | float) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        "source_rejected_count": 0,
        "update_failed_count": 0,
        "archive_audit_failed_count": 0,
        "memory_induction_omitted_or_overcompressed_count": 0,
        "packaged_setup_success_rate": 1.0,
        "updater_success_rate": 1.0,
        "archive_audit_success_rate": 1.0,
        "positive_first_loss_attribution_coverage_rate": 1.0,
        "first_loss_partition_invariant_violation_count": 0,
        "support_event_attribution_coverage_rate": 1.0,
        "support_event_partition_invariant_violation_count": 0,
        "hard_negative_rejection_rate": 1.0,
        "abstention_accuracy": 1.0,
        "false_promotion_count": 0,
        "gold_label_ingestion_count": 0,
        "answer_ingestion_count": 0,
        "direct_memory_injection_count": 0,
        "privacy_leak_count": 0,
        "session_support_omitted_count": 0,
        "pre_retrieval_induction_loss_count": 0,
        "preserved_support_event_count": 0,
        "expected_support_event_count": 0,
    }
    metrics.update(overrides)
    denominator = int(metrics["expected_support_event_count"])
    numerator = int(metrics["preserved_support_event_count"])
    metrics["session_support_event_preservation_rate"] = (
        numerator / denominator if denominator else 0.0
    )
    return metrics


def _candidate_safety_passed(
    baseline: dict[str, int | float], candidate: dict[str, int | float]
) -> bool:
    no_new_early_failures = all(
        int(candidate.get(name, 0)) <= int(baseline.get(name, 0))
        for name in SAFETY_NONINCREASING_COUNT_METRICS
    )
    no_rate_regression = all(
        float(candidate.get(name, 0.0)) >= float(baseline.get(name, 0.0))
        for name in SAFETY_NONDECREASING_RATE_METRICS
    )
    return (
        no_new_early_failures
        and no_rate_regression
        and all(
            float(candidate.get(name, 0.0)) == 1.0
            for name in SAFETY_ONE_RATE_METRICS
        )
        and all(
            int(candidate.get(name, 1)) == 0
            for name in SAFETY_ZERO_COUNT_METRICS
        )
    )


def _candidate_gains(
    baseline: dict[str, int | float], candidate: dict[str, int | float]
) -> dict[str, int | float]:
    baseline_omitted = int(baseline.get("session_support_omitted_count", 0))
    candidate_omitted = int(candidate.get("session_support_omitted_count", 0))
    recovered = max(0, baseline_omitted - candidate_omitted)
    baseline_pre = int(baseline.get("pre_retrieval_induction_loss_count", 0))
    candidate_pre = int(candidate.get("pre_retrieval_induction_loss_count", 0))
    recovered_pre = max(0, baseline_pre - candidate_pre)
    event_gain = max(
        0,
        int(candidate.get("preserved_support_event_count", 0))
        - int(baseline.get("preserved_support_event_count", 0)),
    )
    return {
        "recovered_session_support_case_count": recovered,
        "session_support_omission_reduction_rate": (
            recovered / baseline_omitted if baseline_omitted else 0.0
        ),
        "recovered_pre_retrieval_positive_count": recovered_pre,
        "pre_retrieval_induction_loss_reduction_rate": (
            recovered_pre / baseline_pre if baseline_pre else 0.0
        ),
        "support_event_preservation_gain_count": event_gain,
        "memory_induction_stage_shift_count": max(
            0,
            int(candidate.get("memory_induction_omitted_or_overcompressed_count", 0))
            - int(baseline.get("memory_induction_omitted_or_overcompressed_count", 0)),
        ),
    }


def evaluate_calibration_candidate(
    baseline: dict[str, int | float], candidate: dict[str, int | float]
) -> dict[str, int | float | str]:
    gains = _candidate_gains(baseline, candidate)
    safety = _candidate_safety_passed(baseline, candidate)
    gain_passed = (
        int(gains["recovered_session_support_case_count"])
        >= MINIMUM_CALIBRATION_RECOVERY
        and int(gains["recovered_pre_retrieval_positive_count"])
        >= MINIMUM_CALIBRATION_RECOVERY
        and int(gains["support_event_preservation_gain_count"])
        >= MINIMUM_CALIBRATION_EVENT_GAIN
        and int(gains["memory_induction_stage_shift_count"]) == 0
    )
    if not safety:
        status, reason = "session_support_no_go", "safety_regression"
    elif not gain_passed:
        status, reason = "session_support_no_go", "calibration_gain_insufficient"
    else:
        status, reason = "candidate_frozen", "calibration_gain_sufficient"
    return {
        "readiness_status": status,
        "decision_reason": reason,
        "safety_passed": int(safety),
        "gain_passed": int(gain_passed),
        "minimum_recovered_calibration_case_count": MINIMUM_CALIBRATION_RECOVERY,
        "minimum_calibration_support_event_gain_count": MINIMUM_CALIBRATION_EVENT_GAIN,
        **gains,
    }


def evaluate_holdout_candidate(
    baseline: dict[str, int | float], candidate: dict[str, int | float]
) -> dict[str, int | float | str]:
    gains = _candidate_gains(baseline, candidate)
    safety = _candidate_safety_passed(baseline, candidate)
    gain_passed = (
        int(gains["recovered_session_support_case_count"]) >= MINIMUM_HOLDOUT_RECOVERY
        and float(gains["session_support_omission_reduction_rate"])
        >= MINIMUM_HOLDOUT_REDUCTION
        and int(gains["recovered_pre_retrieval_positive_count"])
        >= MINIMUM_HOLDOUT_RECOVERY
        and float(gains["pre_retrieval_induction_loss_reduction_rate"])
        >= MINIMUM_HOLDOUT_REDUCTION
        and int(gains["support_event_preservation_gain_count"])
        >= MINIMUM_HOLDOUT_EVENT_GAIN
        and int(gains["memory_induction_stage_shift_count"]) == 0
    )
    if not safety:
        status, reason = "session_support_no_go", "safety_regression"
    elif not gain_passed:
        status, reason = "session_support_no_go", "insufficient_holdout_gain"
    else:
        status, reason = (
            "session_support_repair_go",
            "holdout_gain_and_safety_passed",
        )
    return {
        "readiness_status": status,
        "decision_reason": reason,
        "safety_passed": int(safety),
        "gain_passed": int(gain_passed),
        "minimum_recovered_holdout_case_count": MINIMUM_HOLDOUT_RECOVERY,
        "minimum_holdout_reduction_rate": MINIMUM_HOLDOUT_REDUCTION,
        "minimum_support_event_preservation_gain_count": MINIMUM_HOLDOUT_EVENT_GAIN,
        **gains,
    }


def _json_fingerprint(value: object) -> str:
    rendered = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def candidate_configuration_payload(
    candidate_strategy: str | None,
) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "taxonomy": SUPPORT_EVENT_TAXONOMY,
        "allowed_repair_surfaces": tuple(
            category
            for category in SUPPORT_EVENT_TAXONOMY
            if category in ALLOWED_REPAIR_SURFACES
        ),
        "minimum_case_count": MINIMUM_DOMINANT_CASE_COUNT,
        "minimum_case_share": MINIMUM_DOMINANT_CASE_SHARE,
        "minimum_calibration_recovery": MINIMUM_CALIBRATION_RECOVERY,
        "minimum_calibration_event_gain": MINIMUM_CALIBRATION_EVENT_GAIN,
        "minimum_holdout_recovery": MINIMUM_HOLDOUT_RECOVERY,
        "minimum_holdout_reduction": MINIMUM_HOLDOUT_REDUCTION,
        "minimum_holdout_event_gain": MINIMUM_HOLDOUT_EVENT_GAIN,
        "memory_induction_stage_shift_allowed": 0,
        "safety_nonincreasing_count_metrics": SAFETY_NONINCREASING_COUNT_METRICS,
        "safety_nondecreasing_rate_metrics": SAFETY_NONDECREASING_RATE_METRICS,
        "safety_one_rate_metrics": SAFETY_ONE_RATE_METRICS,
        "safety_zero_count_metrics": SAFETY_ZERO_COUNT_METRICS,
        "candidate_strategy_fingerprint_sha256": (
            sha256_text(candidate_strategy) if candidate_strategy else None
        ),
    }


def candidate_configuration_fingerprint(candidate_strategy: str | None) -> str:
    return _json_fingerprint(candidate_configuration_payload(candidate_strategy))


def _metric_count(report: dict[str, Any], name: str) -> tuple[int, int]:
    value = (report.get("metric_counts") or {}).get(name) or {}
    return int(value.get("numerator") or 0), int(value.get("denominator") or 0)


def validate_v244_baseline_report(
    report: dict[str, Any], *, cohort: str
) -> dict[str, Any]:
    if cohort not in V244_BASELINE_COUNTS:
        raise ValueError("V2.44 baseline cohort must be calibration or holdout")
    expected = V244_BASELINE_COUNTS[cohort]
    selection_fingerprint = (
        CALIBRATION_FINGERPRINT if cohort == "calibration" else HOLDOUT_FINGERPRINT
    )
    metrics = report.get("metrics") or {}
    preserved, support_events = _metric_count(
        report, "session_support_event_preservation_rate"
    )
    if "preserved_support_event_count" in metrics:
        preserved = int(metrics["preserved_support_event_count"])
    if "expected_support_event_count" in metrics:
        support_events = int(metrics["expected_support_event_count"])
    valid = (
        report.get("report_kind") == "public_induction_first_loss_gate"
        and report.get("cohort") == cohort
        and report.get("status") == "passed"
        and (report.get("dataset") or {}).get("sha256") == OFFICIAL_DATASET_SHA256
        and (report.get("selection") or {}).get("selected_fingerprint_sha256")
        == selection_fingerprint
        and (report.get("runtime_bundle") or {}).get("fingerprint_sha256")
        == V244_BASELINE_RUNTIME_FINGERPRINT
        and int(metrics.get("session_support_omitted_count", -1))
        == expected["session_support_omitted_count"]
        and preserved == expected["preserved_support_event_count"]
        and support_events == expected["expected_support_event_count"]
    )
    if not valid:
        raise SystemExit("V2.44 baseline contract mismatch")
    return {
        "status": "reproduced",
        "cohort": cohort,
        **expected,
        "dataset_sha256": OFFICIAL_DATASET_SHA256,
        "selection_fingerprint_sha256": selection_fingerprint,
        "runtime_bundle_fingerprint_sha256": V244_BASELINE_RUNTIME_FINGERPRINT,
    }


def validate_candidate_freeze(
    calibration_report: dict[str, Any],
    *,
    candidate_strategy: str,
    runtime_bundle: dict[str, Any],
) -> None:
    freeze = calibration_report.get("candidate_freeze") or {}
    configuration_fingerprint = candidate_configuration_fingerprint(
        candidate_strategy
    )
    valid = (
        calibration_report.get("report_kind") == REPORT_KIND
        and calibration_report.get("cohort") == "calibration"
        and calibration_report.get("status") == "passed"
        and calibration_report.get("readiness_status") == "candidate_frozen"
        and freeze.get("candidate_strategy") == candidate_strategy
        and freeze.get("candidate_strategy_fingerprint_sha256")
        == sha256_text(candidate_strategy)
        and freeze.get("runtime_bundle_fingerprint_sha256")
        == runtime_bundle.get("fingerprint_sha256")
        and freeze.get("configuration_fingerprint_sha256")
        == configuration_fingerprint
        and (calibration_report.get("configuration") or {}).get(
            "fingerprint_sha256"
        )
        == configuration_fingerprint
    )
    if not valid:
        raise SystemExit("candidate freeze mismatch")


def build_report(
    *,
    cohort: str,
    mode: str,
    observations: list[dict[str, Any]],
    dataset: dict[str, Any],
    selection: dict[str, Any],
    runtime_bundle: dict[str, Any],
    baseline_report: dict[str, Any] | None = None,
    calibration_report: dict[str, Any] | None = None,
    candidate_strategy: str | None = None,
    v244_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics, counts = aggregate_support_metrics(observations)
    repair = select_session_repair_target(observations, metrics)
    structural_valid = (
        metrics.get("support_event_attribution_coverage_rate") == 1.0
        and metrics.get("support_event_partition_invariant_violation_count") == 0
        and metrics.get("positive_first_loss_attribution_coverage_rate") == 1.0
        and metrics.get("first_loss_partition_invariant_violation_count") == 0
        and int(metrics.get("scorer_support_label_missing_count", 0)) == 0
        and int(metrics.get("gold_label_ingestion_count", 0)) == 0
        and int(metrics.get("answer_ingestion_count", 0)) == 0
        and int(metrics.get("direct_memory_injection_count", 0)) == 0
        and int(metrics.get("privacy_leak_count", 0)) == 0
        and int(selection.get("cohort_overlap_count", 0)) == 0
    )
    comparison: dict[str, Any] = {}
    if not structural_valid:
        readiness_status, decision_reason = "session_support_no_go", "safety_regression"
    elif candidate_strategy and baseline_report:
        baseline_metrics = baseline_report.get("metrics") or {}
        if cohort == "calibration":
            comparison = evaluate_calibration_candidate(baseline_metrics, metrics)
        else:
            comparison = evaluate_holdout_candidate(baseline_metrics, metrics)
        readiness_status = str(comparison["readiness_status"])
        decision_reason = str(comparison["decision_reason"])
    elif cohort == "holdout":
        readiness_status, decision_reason = (
            "holdout_baseline_completed",
            "candidate_not_evaluated",
        )
    elif repair["repair_eligible"]:
        readiness_status, decision_reason = "repair_eligible", "repair_eligible"
    else:
        readiness_status = "session_support_no_go"
        decision_reason = str(repair["decision_reason"])

    strategy_fingerprint = (
        hashlib.sha256(candidate_strategy.encode("utf-8")).hexdigest()
        if candidate_strategy
        else None
    )
    configuration_fingerprint = candidate_configuration_fingerprint(
        candidate_strategy
    )
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
            "fingerprint_sha256": configuration_fingerprint,
            "candidate_strategy_count": int(candidate_strategy is not None),
            "candidate_strategy_fingerprint_sha256": strategy_fingerprint,
        },
        "taxonomy": list(SUPPORT_EVENT_TAXONOMY),
        "metrics": metrics,
        "metric_counts": counts,
        "repair_decision": repair,
        "candidate_comparison": comparison,
        "v244_baseline_contract": v244_baseline or {},
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "support_event_traces_rendered": False,
            "support_event_locators_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "deterministic session-support event attribution and bounded repair only; "
            "not LLM answer quality, ranking quality, vector search, ontology discovery, "
            "public leaderboard parity, private deployment readiness, or scheduler reliability"
        ),
    }
    if (
        cohort == "calibration"
        and candidate_strategy
        and readiness_status == "candidate_frozen"
    ):
        report["candidate_freeze"] = {
            "candidate_strategy": candidate_strategy,
            "candidate_strategy_fingerprint_sha256": strategy_fingerprint,
            "runtime_bundle_fingerprint_sha256": runtime_bundle.get(
                "fingerprint_sha256"
            ),
            "configuration_fingerprint_sha256": configuration_fingerprint,
            "calibration_selection_fingerprint_sha256": selection.get(
                "selected_fingerprint_sha256"
            ),
        }
    else:
        report["candidate_freeze"] = {}
    return report


def _offline_observation(category: str) -> dict[str, Any]:
    preserved = int(category == "preserved")
    return {
        "question_type": "synthetic",
        "is_abstention": 0,
        "source_rejected": 0,
        "packaged_setup_success": 1,
        "updater_success": 1,
        "archive_audit_success": 1,
        "context_package_parse_success": 1,
        "expected_support_event_count": 1,
        "preserved_support_event_count": preserved,
        "active_support_memory_count": preserved,
        "support_candidate_at_5_count": preserved,
        "supported_gold_package": preserved,
        "first_loss": "supported" if preserved else "session_support_omitted",
        "support_event_traces": [{"category": category}],
        "scorer_support_label_missing_count": 0,
        "gold_label_ingestion_count": 0,
        "answer_ingestion_count": 0,
        "direct_memory_injection_count": 0,
        "false_promotion_count": 0,
        "privacy_leak_count": 0,
    }


def run_offline_fixture() -> dict[str, Any]:
    packaged_rows = [
        {
            "question_id": "offline_complete_locator",
            "question_type": "single-session-assistant",
            "question": "Which source-anchor rule was verified?",
            "answer": "Use stable source anchors for durable evidence.",
            "haystack_session_ids": ["offline-support"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "State the source-anchor rule."},
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors for durable evidence.",
                        "has_answer": True,
                    },
                ]
            ],
            "answer_session_ids": ["offline-support"],
        },
        {
            "question_id": "offline_duplicate_locator",
            "question_type": "single-session-assistant",
            "question": "Which rule was repeated?",
            "answer": "Use stable source anchors.",
            "haystack_session_ids": ["offline-duplicate"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors.",
                    },
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors.",
                        "has_answer": True,
                    },
                ]
            ],
            "answer_session_ids": ["offline-duplicate"],
        },
        {
            "question_id": "offline_abs",
            "question_type": "single-session-user",
            "question": "Which unsupported preference was stated?",
            "answer": "No supported answer.",
            "haystack_session_ids": ["offline-abstention"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [{"role": "user", "content": "This session contains neutral filler."}]
            ],
            "answer_session_ids": [],
        },
    ]
    with tempfile.TemporaryDirectory(prefix="my-precious-v245-offline-") as tmpdir:
        root = Path(tmpdir)
        packaged = [
            observe_packaged_case(
                row,
                case_ordinal=ordinal,
                case_root=root / f"case-{ordinal:03d}",
                runtime_root=REPO_ROOT,
            )
            for ordinal, row in enumerate(packaged_rows, 1)
        ]
    synthetic_categories = tuple(
        category
        for category in SUPPORT_EVENT_TAXONOMY
        if category not in {"evidence_bound_to_wrong_ordinal", "preserved"}
    )
    observations = [
        *packaged,
        *[_offline_observation(category) for category in synthetic_categories],
    ]
    return build_report(
        cohort="offline",
        mode="offline_fixture",
        observations=observations,
        dataset={
            "source": "synthetic public-data-free fixture",
            "source_url": "offline",
            "sha256": _json_fingerprint(list(SUPPORT_EVENT_TAXONOMY)),
            "input_record_count": len(observations),
        },
        selection={
            "cohort": "offline",
            "selected_case_count": len(observations),
            "cohort_overlap_count": 0,
        },
        runtime_bundle=first_loss_gate.runtime_bundle_fingerprint(REPO_ROOT),
    )


def _load_external_json(path_text: str, label: str) -> dict[str, Any]:
    path = first_loss_gate.public_gate.require_external_artifact_path(
        Path(path_text), label
    )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"unable to load {label}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object")
    return value


def _load_v245_report(path_text: str, *, cohort: str, label: str) -> dict[str, Any]:
    report = _load_external_json(path_text, label)
    selection_fingerprint = (
        CALIBRATION_FINGERPRINT if cohort == "calibration" else HOLDOUT_FINGERPRINT
    )
    if (
        report.get("report_kind") != REPORT_KIND
        or report.get("cohort") != cohort
        or report.get("status") != "passed"
        or (report.get("dataset") or {}).get("sha256") != OFFICIAL_DATASET_SHA256
        or (report.get("selection") or {}).get("selected_fingerprint_sha256")
        != selection_fingerprint
    ):
        raise SystemExit(f"{label} contract mismatch")
    return report


def _validate_candidate_baseline(report: dict[str, Any], *, cohort: str) -> None:
    configuration = report.get("configuration") or {}
    expected_status = (
        "repair_eligible" if cohort == "calibration" else "holdout_baseline_completed"
    )
    if (
        report.get("readiness_status") != expected_status
        or int(configuration.get("candidate_strategy_count", -1)) != 0
    ):
        raise SystemExit("candidate baseline report contract mismatch")
    if cohort == "calibration":
        repair = report.get("repair_decision") or {}
        if (
            int(repair.get("repair_eligible", 0)) != 1
            or repair.get("targeted_defect") not in ALLOWED_REPAIR_SURFACES
        ):
            raise SystemExit("candidate baseline repair target mismatch")


def _validate_holdout_calibration(
    report: dict[str, Any],
    *,
    candidate_strategy: str | None,
    runtime_bundle: dict[str, Any],
) -> None:
    if candidate_strategy:
        validate_candidate_freeze(
            report,
            candidate_strategy=candidate_strategy,
            runtime_bundle=runtime_bundle,
        )
        return
    if (
        report.get("readiness_status") != "repair_eligible"
        or int((report.get("configuration") or {}).get("candidate_strategy_count", -1))
        != 0
        or int((report.get("repair_decision") or {}).get("repair_eligible", 0)) != 1
    ):
        raise SystemExit("holdout calibration report contract mismatch")


def _failed_public_report(*, failure_reason: str, dataset_sha256: str) -> dict[str, Any]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "mode": "public_unscored",
        "cohort": "unscored",
        "status": "failed",
        "readiness_status": "session_support_no_go",
        "decision_reason": "baseline_not_reproducible",
        "failure_reason": failure_reason,
        "dataset": {
            "source": OFFICIAL_DATASET_SOURCE,
            "sha256": dataset_sha256,
        },
        "metrics": {"privacy_leak_count": 0},
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "support_event_traces_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
        },
        "claim_boundary": "baseline contract failed; no session-support repair claim",
    }


def _selection_payload(
    *,
    cohort: str,
    holdout: list[dict[str, Any]],
    calibration: list[dict[str, Any]],
) -> dict[str, Any]:
    query_gate = first_loss_gate.query_calibration_gate
    selected = calibration if cohort == "calibration" else holdout
    holdout_fingerprint = first_loss_gate.public_gate._selection_fingerprint(holdout)
    calibration_fingerprint = first_loss_gate.public_gate._selection_fingerprint(
        calibration
    )
    return {
        "cohort": cohort,
        "holdout_seed": query_gate.HOLDOUT_SEED,
        "calibration_seed": query_gate.CALIBRATION_SEED,
        "positive_per_type": 5,
        "abstention_count": 10,
        "selected_case_count": len(selected),
        "holdout_case_count": len(holdout),
        "calibration_case_count": len(calibration),
        "cohort_overlap_count": len(
            {str(row["question_id"]) for row in holdout}.intersection(
                {str(row["question_id"]) for row in calibration}
            )
        ),
        "holdout_fingerprint_sha256": holdout_fingerprint,
        "calibration_fingerprint_sha256": calibration_fingerprint,
        "selected_fingerprint_sha256": first_loss_gate.public_gate._selection_fingerprint(
            selected
        ),
        "holdout_selection_fingerprint_match": int(
            holdout_fingerprint == HOLDOUT_FINGERPRINT
        ),
        "calibration_selection_fingerprint_match": int(
            calibration_fingerprint == CALIBRATION_FINGERPRINT
        ),
    }


def _current_run_matches_v244_contract(
    metrics: dict[str, Any], contract: dict[str, Any]
) -> bool:
    return (
        int(metrics.get("v244_session_support_omitted_count", -1))
        == int(contract["session_support_omitted_count"])
        and int(metrics.get("v244_preserved_support_event_count", -1))
        == int(contract["preserved_support_event_count"])
        and int(metrics.get("expected_support_event_count", -1))
        == int(contract["expected_support_event_count"])
    )


def run_public_dataset(args: argparse.Namespace) -> dict[str, Any]:
    input_path = first_loss_gate.public_gate.require_external_artifact_path(
        Path(args.public_input), "public benchmark input"
    )
    try:
        dataset_sha256 = first_loss_gate.public_gate._file_sha256(input_path)
    except OSError:
        return _failed_public_report(
            failure_reason="dataset_unreadable", dataset_sha256="unavailable"
        )
    if dataset_sha256 != OFFICIAL_DATASET_SHA256:
        return _failed_public_report(
            failure_reason="dataset_sha_mismatch", dataset_sha256=dataset_sha256
        )
    try:
        rows = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _failed_public_report(
            failure_reason="dataset_schema_incompatible", dataset_sha256=dataset_sha256
        )
    if not isinstance(rows, list):
        return _failed_public_report(
            failure_reason="dataset_schema_incompatible", dataset_sha256=dataset_sha256
        )
    query_gate = first_loss_gate.query_calibration_gate
    try:
        holdout, calibration = query_gate.select_disjoint_cohorts(
            rows,
            holdout_seed=query_gate.HOLDOUT_SEED,
            calibration_seed=query_gate.CALIBRATION_SEED,
            positive_per_type=5,
            abstention_count=10,
        )
    except SystemExit:
        return _failed_public_report(
            failure_reason="dataset_schema_incompatible", dataset_sha256=dataset_sha256
        )
    selection = _selection_payload(
        cohort=args.cohort, holdout=holdout, calibration=calibration
    )
    if (
        selection["holdout_selection_fingerprint_match"] != 1
        or selection["calibration_selection_fingerprint_match"] != 1
        or selection["cohort_overlap_count"] != 0
    ):
        return _failed_public_report(
            failure_reason="selection_fingerprint_mismatch",
            dataset_sha256=dataset_sha256,
        )

    v244_report = _load_external_json(args.v244_report, "V2.44 aggregate report")
    try:
        v244_contract = validate_v244_baseline_report(
            v244_report, cohort=args.cohort
        )
    except SystemExit:
        return _failed_public_report(
            failure_reason="v244_baseline_contract_mismatch",
            dataset_sha256=dataset_sha256,
        )
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    runtime_bundle = first_loss_gate.runtime_bundle_fingerprint(runtime_root)
    baseline_report = (
        _load_v245_report(
            args.baseline_report,
            cohort=args.cohort,
            label="V2.45 candidate baseline report",
        )
        if args.baseline_report
        else None
    )
    if baseline_report is not None:
        _validate_candidate_baseline(baseline_report, cohort=args.cohort)
    calibration_report = (
        _load_v245_report(
            args.calibration_report,
            cohort="calibration",
            label="V2.45 calibration report",
        )
        if args.calibration_report
        else None
    )
    if args.cohort == "holdout" and calibration_report is not None:
        _validate_holdout_calibration(
            calibration_report,
            candidate_strategy=args.candidate_strategy,
            runtime_bundle=runtime_bundle,
        )

    work_dir = first_loss_gate.public_gate.require_external_artifact_path(
        Path(args.work_dir), "public benchmark work directory"
    )
    if work_dir.exists() and any(work_dir.iterdir()):
        raise SystemExit("--work-dir must be empty")
    work_dir.mkdir(parents=True, exist_ok=True)
    selected = calibration if args.cohort == "calibration" else holdout
    observations = [
        observe_packaged_case(
            row,
            case_ordinal=ordinal,
            case_root=work_dir / f"case-{ordinal:03d}",
            runtime_root=runtime_root,
        )
        for ordinal, row in enumerate(selected, 1)
    ]
    report = build_report(
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
        runtime_bundle=runtime_bundle,
        baseline_report=baseline_report,
        calibration_report=calibration_report,
        candidate_strategy=args.candidate_strategy,
        v244_baseline=v244_contract,
    )
    if not args.candidate_strategy and not _current_run_matches_v244_contract(
        report["metrics"], v244_contract
    ):
        report["status"] = "failed"
        report["readiness_status"] = "session_support_no_go"
        report["decision_reason"] = "baseline_not_reproducible"

    report_path = first_loss_gate.public_gate.require_external_artifact_path(
        Path(args.report_file), "public benchmark report"
    )
    local_paths = [
        input_path,
        work_dir,
        report_path,
        Path(args.v244_report).expanduser().resolve(),
        *(
            [Path(args.baseline_report).expanduser().resolve()]
            if args.baseline_report
            else []
        ),
        *(
            [Path(args.calibration_report).expanduser().resolve()]
            if args.calibration_report
            else []
        ),
    ]
    leak_count = first_loss_gate.public_gate.aggregate_privacy_leak_count(
        report, selected, local_paths
    )
    report["metrics"]["privacy_leak_count"] = int(
        report["metrics"].get("privacy_leak_count", 0)
    ) + int(leak_count)
    if report["metrics"]["privacy_leak_count"]:
        report["status"] = "failed"
        report["readiness_status"] = "session_support_no_go"
        report["decision_reason"] = "safety_regression"
    return report


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
    parser.add_argument("--v244-report")
    parser.add_argument("--calibration-report")
    parser.add_argument("--baseline-report")
    parser.add_argument("--candidate-strategy")
    args = parser.parse_args(argv)
    if args.public_input and not all(
        (
            args.dataset_source_url,
            args.cohort,
            args.work_dir,
            args.report_file,
            args.v244_report,
        )
    ):
        parser.error(
            "public mode requires --dataset-source-url, --cohort, --work-dir, "
            "--report-file, and --v244-report"
        )
    if args.cohort == "holdout" and not args.calibration_report:
        parser.error("holdout mode requires --calibration-report")
    if bool(args.baseline_report) != bool(args.candidate_strategy):
        parser.error("--baseline-report and --candidate-strategy must be used together")
    if args.cohort == "calibration" and args.calibration_report:
        parser.error("calibration mode does not accept --calibration-report")
    if args.candidate_strategy and not all(
        character.islower() or character.isdigit() or character in "_-"
        for character in args.candidate_strategy
    ):
        parser.error("--candidate-strategy must be a lowercase slug")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_offline_fixture() if args.offline_fixture else run_public_dataset(args)
    rendered = json.dumps(report, sort_keys=True)
    if args.report_file:
        report_path = first_loss_gate.public_gate.require_external_artifact_path(
            Path(args.report_file), "public benchmark report"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
