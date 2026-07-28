#!/usr/bin/env python3
"""Calibrate query-support policies without exposing public benchmark labels."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_GATE_SCRIPT = REPO_ROOT / "benchmarks/public_induction_recall_gate.py"
QUERY_GATE_SCRIPT = REPO_ROOT / "benchmarks/query_support_recall_gate.py"
POLICY_NAMES = (
    "strict_v1",
    "weighted_partial_060_v1",
    "weighted_partial_050_specific_v1",
)
BASELINE_RUNTIME_POLICY = "strict_meaningful_or_important_query_token_coverage"
OFFICIAL_DATASET_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
OFFICIAL_DATASET_SOURCE = "LongMemEval cleaned S"
HOLDOUT_SEED = "my-precious-v236"
CALIBRATION_SEED = "my-precious-v237-calibration"
HOLDOUT_FINGERPRINT = "4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


public_gate = _load_module("v237_public_induction_recall_gate", PUBLIC_GATE_SCRIPT)
query_gate = _load_module("v237_query_support_recall_gate", QUERY_GATE_SCRIPT)
search_module = public_gate._load_search_module(query_gate.SEARCH_SCRIPT)


def _tokens(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [token for token in value if isinstance(token, str) and token]


def policy_supports(
    query_support: object,
    token_importance: Callable[[str], int],
    policy: str,
) -> bool:
    if policy not in POLICY_NAMES:
        raise ValueError(f"unknown query-support policy: {policy}")
    if not isinstance(query_support, dict):
        return False
    matched = _tokens(query_support.get("matched_tokens"))
    missing = _tokens(query_support.get("missing_tokens"))
    if policy == "strict_v1":
        return bool(
            query_support.get("strict_token_coverage")
            or query_support.get("meaningful_token_coverage")
            or (matched and not missing)
        )

    required = [*matched, *missing]
    total_weight = sum(token_importance(token) for token in required)
    matched_weight = sum(token_importance(token) for token in matched)
    coverage = matched_weight / total_weight if total_weight else 0.0
    if len(matched) < 2 or any(token_importance(token) >= 4 for token in missing):
        return False
    if policy == "weighted_partial_060_v1":
        return coverage >= 0.60
    return coverage >= 0.50 and any(token_importance(token) >= 2 for token in matched)


def select_candidate_policy(policy_metrics: dict[str, dict[str, int | float]]) -> dict[str, Any]:
    rejections: dict[str, list[str]] = {}
    eligible: list[str] = []
    for policy in POLICY_NAMES:
        metrics = policy_metrics.get(policy, {})
        reasons: list[str] = []
        if int(metrics.get("gold_candidate_count", 0)) < 5:
            reasons.append("gold_candidate_count_below_minimum")
        if float(metrics.get("hard_negative_rejection_rate", 0.0)) < 1.0:
            reasons.append("hard_negative_rejection_rate_below_threshold")
        if float(metrics.get("inactive_lifecycle_rejection_rate", 0.0)) < 1.0:
            reasons.append("inactive_lifecycle_rejection_rate_below_threshold")
        if float(metrics.get("malformed_missing_fail_closed_rate", 0.0)) < 1.0:
            reasons.append("malformed_missing_fail_closed_rate_below_threshold")
        if float(metrics.get("abstention_accuracy", 0.0)) < 0.90:
            reasons.append("abstention_accuracy_below_threshold")
        if float(metrics.get("supported_decision_precision", 0.0)) < 0.80:
            reasons.append("supported_decision_precision_below_threshold")
        if float(metrics.get("gold_candidate_support_rate", 0.0)) < 0.80:
            reasons.append("gold_candidate_support_rate_below_threshold")
        rejections[policy] = reasons
        if not reasons:
            eligible.append(policy)

    selected = None
    if eligible:
        selected = max(
            eligible,
            key=lambda policy: (
                float(policy_metrics[policy]["gold_candidate_support_rate"]),
                -POLICY_NAMES.index(policy),
            ),
        )
    return {
        "selected_policy": selected,
        "selected_policy_count": int(selected is not None),
        "decision_reason": "policy_selected" if selected else "no_safe_policy",
        "rejections": rejections,
    }


def select_disjoint_cohorts(
    rows: list[object],
    *,
    holdout_seed: str,
    calibration_seed: str,
    positive_per_type: int,
    abstention_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    holdout = public_gate.select_longmemeval_cases(
        rows,
        seed=holdout_seed,
        positive_per_type=positive_per_type,
        abstention_count=abstention_count,
    )
    holdout_ids = {row["question_id"] for row in holdout}
    remaining = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("question_id") not in holdout_ids
    ]
    calibration = public_gate.select_longmemeval_cases(
        remaining,
        seed=calibration_seed,
        positive_per_type=positive_per_type,
        abstention_count=abstention_count,
    )
    return holdout, calibration


def classify_first_loss(observation: dict[str, Any]) -> str:
    if not observation.get("gold_memory_present") or not observation.get(
        "active_gold_memory_present"
    ):
        return "induction_loss"
    if not observation.get("gold_candidate_at_5"):
        return "retrieval_loss"
    if not observation.get("gold_candidate_query_supported"):
        return "query_support_rejection"
    if not observation.get("gold_candidate_answerable") or not observation.get(
        "supported_gold_package"
    ):
        return "answerability_rejection"
    return "supported"


def policy_package_action(package: object, policy: str) -> str:
    if not isinstance(package, dict) or package.get("report_kind") != query_gate.CONTEXT_REPORT_KIND:
        return "abstain"
    hits = package.get("hits")
    if not isinstance(hits, list):
        return "abstain"
    for hit in hits[:5]:
        if not isinstance(hit, dict) or hit.get("active_current") is not True:
            continue
        if not hit.get("summary_drill_paths") or not hit.get("evidence_drill_paths"):
            continue
        if policy_supports(hit.get("query_support"), search_module.token_importance, policy):
            return "answer"
    return "abstain"


def _hit_policy_supported(hit: object, policy: str) -> bool:
    return bool(
        isinstance(hit, dict)
        and hit.get("active_current") is True
        and hit.get("summary_drill_paths")
        and hit.get("evidence_drill_paths")
        and policy_supports(hit.get("query_support"), search_module.token_importance, policy)
    )


def score_policy_outcome(
    *,
    supported_memory_ids: set[str],
    active_gold_memory_ids: set[str],
    is_abstention: bool,
) -> dict[str, int]:
    supported_decision = bool(supported_memory_ids)
    supported_gold = bool(
        supported_decision
        and not is_abstention
        and supported_memory_ids.intersection(active_gold_memory_ids)
    )
    return {
        "supported_decision": int(supported_decision),
        "supported_gold_decision": int(supported_gold),
        "false_support": int(supported_decision and not supported_gold),
        "abstention_correct": int(is_abstention and not supported_decision),
    }


def _source_path_to_session_id(case: dict[str, Any], case_root: Path) -> dict[str, str]:
    source_root = case_root / "source-records"
    return {
        str((source_root / str(record["record_id"]) / "record.jsonl").resolve()): str(
            record["scorer_session_id"]
        )
        for record in case.get("source_records") or []
    }


def _inactive_memory_ids(module: Any, records: list[dict[str, Any]]) -> set[str]:
    supersedes = module.collect_supersedes_by_memory_id(records)
    contradicts = module.collect_contradicts_by_memory_id(records)
    deprecates = module.collect_deprecates_by_memory_id(records)
    return module.collect_inactive_memory_ids(
        records,
        supersedes,
        module.collect_forward_superseded_ids(supersedes),
        contradicts,
        module.collect_forward_contradicted_ids(contradicts),
        deprecates,
        module.collect_forward_deprecated_ids(deprecates),
    )


def _record_evidence_paths(record: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for ref in record.get("evidence_refs") or []:
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            paths.add(ref["path"])
        elif isinstance(ref, str):
            paths.add(ref.split("#", 1)[0])
    return paths


def observe_packaged_case(row: dict[str, Any], case_ordinal: int, case_root: Path) -> dict[str, Any]:
    case = public_gate.convert_longmemeval_case(row, case_ordinal=case_ordinal)
    packaged = public_gate.run_packaged_case(case, case_root)
    observation: dict[str, Any] = {
        "question_type": str(case["question_type"]),
        "is_abstention": int(case["is_abstention"]),
        "packaged_setup_success": int(packaged.get("packaged_setup_success") or 0),
        "updater_success": int(packaged.get("updater_success") or 0),
        "archive_audit_success": int(packaged.get("archive_audit_success") or 0),
        "context_package_parse_success": 0,
        "baseline_retrievable": 0,
        "gold_memory_present": 0,
        "active_gold_memory_present": 0,
        "gold_candidate_at_1": 0,
        "gold_candidate_at_5": 0,
        "gold_candidate_query_supported": 0,
        "gold_candidate_answerable": 0,
        "supported_gold_package": 0,
        "baseline_runtime_policy_parity_numerator": 0,
        "baseline_runtime_policy_parity_denominator": 0,
        "non_baseline_runtime_policy_hit_count": 0,
        "runtime_policy_parity": {
            policy: {"numerator": 0, "denominator": 0} for policy in POLICY_NAMES
        },
        "policy_outcomes": {
            policy: {
                "supported_decision": 0,
                "supported_gold_decision": 0,
                "false_support": 0,
                "abstention_correct": int(case["is_abstention"]),
            }
            for policy in POLICY_NAMES
        },
        "public_gold_label_ingestion_count": int(
            packaged.get("public_gold_label_ingestion_count") or 0
        ),
        "public_answer_ingestion_count": int(packaged.get("public_answer_ingestion_count") or 0),
        "synthetic_memory_marker_injection_count": int(
            packaged.get("synthetic_memory_marker_injection_count") or 0
        ),
        "direct_synthetic_archive_injection_count": int(
            packaged.get("direct_synthetic_archive_injection_count") or 0
        ),
        "privacy_leak_count": int(packaged.get("privacy_leak_count") or 0),
    }
    if not observation["packaged_setup_success"] or not observation["updater_success"]:
        return observation

    memory_repo = case_root / "archive"
    module = public_gate._load_search_module(memory_repo / "tools/search_memory.py")
    provenance_map = public_gate._archive_provenance_map(
        memory_repo,
        _source_path_to_session_id(case, case_root),
    )
    gold_session_ids = set(case["answer_session_ids"])
    baseline_ranks = public_gate._session_gold_ranks(
        module,
        memory_repo,
        str(case["question"]),
        provenance_map,
        gold_session_ids,
    )
    observation["baseline_retrievable"] = int(bool(baseline_ranks))

    records = public_gate._load_jsonl(memory_repo / "index/memories.jsonl")
    inactive_ids = _inactive_memory_ids(module, records)
    gold_memory_ids = {
        str(record.get("memory_id"))
        for record in records
        if record.get("source") == "automatic"
        and isinstance(record.get("memory_id"), str)
        and any(
            provenance_map.get(path) in gold_session_ids
            for path in _record_evidence_paths(record)
        )
    }
    active_gold_ids = gold_memory_ids.difference(inactive_ids)
    observation["gold_memory_present"] = int(bool(gold_memory_ids))
    observation["active_gold_memory_present"] = int(bool(active_gold_ids))

    package = public_gate._context_search(memory_repo, str(case["question"]), "evidence")
    if not isinstance(package, dict):
        return observation
    observation["context_package_parse_success"] = 1
    hits = [hit for hit in package.get("hits") or [] if isinstance(hit, dict)][:5]
    gold_hits = [hit for hit in hits if str(hit.get("memory_id") or "") in active_gold_ids]
    observation["gold_candidate_at_1"] = int(
        any(int(hit.get("rank") or 0) == 1 for hit in gold_hits)
    )
    observation["gold_candidate_at_5"] = int(bool(gold_hits))
    observation["gold_candidate_query_supported"] = int(
        any(
            isinstance(hit.get("query_support"), dict)
            and hit["query_support"].get("status") == "supported"
            for hit in gold_hits
        )
    )
    observation["gold_candidate_answerable"] = int(
        any(
            isinstance(hit.get("answerability"), dict)
            and hit["answerability"].get("status") == "supported"
            for hit in gold_hits
        )
    )
    observation["supported_gold_package"] = int(
        public_gate.context_package_decision(package) == "answer"
        and bool(observation["gold_candidate_answerable"])
    )

    for hit in hits:
        support = hit.get("query_support")
        if not isinstance(support, dict):
            continue
        if str(support.get("policy") or BASELINE_RUNTIME_POLICY) != BASELINE_RUNTIME_POLICY:
            observation["non_baseline_runtime_policy_hit_count"] += 1
            continue
        observation["baseline_runtime_policy_parity_denominator"] += 1
        runtime_supported = support.get("status") == "supported"
        for policy in POLICY_NAMES:
            policy_supported = policy_supports(support, module.token_importance, policy)
            observation["runtime_policy_parity"][policy]["denominator"] += 1
            observation["runtime_policy_parity"][policy]["numerator"] += int(
                policy_supported == runtime_supported
            )
        observation["baseline_runtime_policy_parity_numerator"] += int(
            policy_supports(support, module.token_importance, "strict_v1")
            == runtime_supported
        )

    for policy in POLICY_NAMES:
        supported_hits = [hit for hit in hits if _hit_policy_supported(hit, policy)]
        observation["policy_outcomes"][policy] = score_policy_outcome(
            supported_memory_ids={
                str(hit.get("memory_id"))
                for hit in supported_hits
                if isinstance(hit.get("memory_id"), str)
            },
            active_gold_memory_ids=active_gold_ids,
            is_abstention=bool(case["is_abstention"]),
        )
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


def _cohort_policy_metrics(
    observations: list[dict[str, Any]],
    policy_boundaries: dict[str, dict[str, int | float]],
) -> dict[str, dict[str, Any]]:
    positives = [row for row in observations if not row.get("is_abstention")]
    abstentions = [row for row in observations if row.get("is_abstention")]
    candidate_positives = [row for row in positives if row.get("gold_candidate_at_5")]
    results: dict[str, dict[str, Any]] = {}
    for policy in POLICY_NAMES:
        supported_gold = sum(
            int(row["policy_outcomes"][policy]["supported_gold_decision"])
            for row in candidate_positives
        )
        supported_decisions = sum(
            int(row["policy_outcomes"][policy]["supported_decision"])
            for row in observations
        )
        false_support = sum(
            int(row["policy_outcomes"][policy]["false_support"])
            for row in observations
        )
        abstention_correct = sum(
            int(row["policy_outcomes"][policy]["abstention_correct"])
            for row in abstentions
        )
        boundary = policy_boundaries.get(policy, {})
        metrics = {
            "gold_candidate_count": len(candidate_positives),
            "gold_candidate_support_count": supported_gold,
            "gold_candidate_support_rate": (
                supported_gold / len(candidate_positives) if candidate_positives else 0.0
            ),
            "supported_decision_precision": (
                supported_gold / supported_decisions if supported_decisions else 0.0
            ),
            "abstention_accuracy": (
                abstention_correct / len(abstentions) if abstentions else 0.0
            ),
            "false_support_count": false_support,
            "hard_negative_rejection_rate": float(
                boundary.get("hard_negative_rejection_rate", 0.0)
            ),
            "inactive_lifecycle_rejection_rate": float(
                boundary.get("inactive_lifecycle_rejection_rate", 0.0)
            ),
            "malformed_missing_fail_closed_rate": float(
                boundary.get("malformed_missing_fail_closed_rate", 0.0)
            ),
        }
        results[policy] = {
            **metrics,
            "metric_counts": {
                "gold_candidate_support_rate": {
                    "numerator": supported_gold,
                    "denominator": len(candidate_positives),
                },
                "supported_decision_precision": {
                    "numerator": supported_gold,
                    "denominator": supported_decisions,
                },
                "abstention_accuracy": {
                    "numerator": abstention_correct,
                    "denominator": len(abstentions),
                },
            },
        }
    return results


def _attribution_invariant_violations(baseline: list[dict[str, Any]]) -> int:
    violations = 0
    for row in baseline:
        stages = (
            int(bool(row.get("gold_memory_present"))),
            int(bool(row.get("active_gold_memory_present"))),
            int(bool(row.get("gold_candidate_at_5"))),
            int(bool(row.get("gold_candidate_query_supported"))),
            int(bool(row.get("gold_candidate_answerable"))),
            int(bool(row.get("supported_gold_package"))),
        )
        violations += sum(int(later > earlier) for earlier, later in zip(stages, stages[1:]))
    return violations


def build_cohort_report(
    *,
    cohort: str,
    observations: list[dict[str, Any]],
    policy_boundaries: dict[str, dict[str, int | float]],
    dataset: dict[str, Any],
    selection: dict[str, Any],
    selected_policy: str | None = None,
    ranking_drift_count: int = 0,
) -> dict[str, Any]:
    if cohort not in {"calibration", "holdout"}:
        raise ValueError("cohort must be calibration or holdout")
    positives = [row for row in observations if not row.get("is_abstention")]
    baseline = [row for row in positives if row.get("baseline_retrievable")]
    abstentions = [row for row in observations if row.get("is_abstention")]
    first_losses = [classify_first_loss(row) for row in baseline]
    first_loss_buckets = {
        name: first_losses.count(name)
        for name in (
            "induction_loss",
            "retrieval_loss",
            "query_support_rejection",
            "answerability_rejection",
            "supported",
        )
    }
    policy_metrics = _cohort_policy_metrics(observations, policy_boundaries)
    selection_decision = (
        select_candidate_policy(policy_metrics)
        if cohort == "calibration"
        else {
            "selected_policy": selected_policy,
            "selected_policy_count": int(selected_policy is not None),
            "decision_reason": "policy_selected" if selected_policy else "no_safe_policy",
            "rejections": {},
        }
    )
    runtime_policy = selection_decision["selected_policy"] or "strict_v1"
    runtime_metrics = policy_metrics[runtime_policy]
    metrics: dict[str, int | float] = {
        "public_positive_case_count": len(positives),
        "public_abstention_case_count": len(abstentions),
        "public_baseline_retrievable_case_count": len(baseline),
        "public_gold_memory_presence_count": sum(
            int(bool(row.get("gold_memory_present"))) for row in baseline
        ),
        "public_active_gold_memory_count": sum(
            int(bool(row.get("active_gold_memory_present"))) for row in baseline
        ),
        "public_gold_memory_candidate_at_1_count": sum(
            int(bool(row.get("gold_candidate_at_1"))) for row in baseline
        ),
        "public_gold_memory_candidate_at_5_count": sum(
            int(bool(row.get("gold_candidate_at_5"))) for row in baseline
        ),
        "public_gold_candidate_query_supported_count": sum(
            int(bool(row.get("gold_candidate_query_supported"))) for row in baseline
        ),
        "public_gold_candidate_answerable_count": sum(
            int(bool(row.get("gold_candidate_answerable"))) for row in baseline
        ),
        "public_supported_gold_package_count": sum(
            int(bool(row.get("supported_gold_package"))) for row in baseline
        ),
        "public_induction_loss_count": first_loss_buckets["induction_loss"],
        "public_retrieval_loss_count": first_loss_buckets["retrieval_loss"],
        "public_query_support_rejection_count": first_loss_buckets[
            "query_support_rejection"
        ],
        "public_answerability_rejection_count": first_loss_buckets[
            "answerability_rejection"
        ],
        "public_attribution_invariant_violation_count": _attribution_invariant_violations(
            baseline
        )
        + int(sum(first_loss_buckets.values()) != len(baseline)),
        "selected_policy_count": int(selection_decision["selected_policy_count"]),
        "ranking_drift_count": ranking_drift_count,
        "inactive_support_acceptance_count": 0,
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": sum(int(row.get("privacy_leak_count") or 0) for row in observations),
        "public_gold_label_ingestion_count": sum(
            int(row.get("public_gold_label_ingestion_count") or 0) for row in observations
        ),
        "public_answer_ingestion_count": sum(
            int(row.get("public_answer_ingestion_count") or 0) for row in observations
        ),
        "synthetic_memory_marker_injection_count": sum(
            int(row.get("synthetic_memory_marker_injection_count") or 0)
            for row in observations
        ),
        "direct_synthetic_archive_injection_count": sum(
            int(row.get("direct_synthetic_archive_injection_count") or 0)
            for row in observations
        ),
        "non_baseline_runtime_policy_hit_count": sum(
            int(row.get("non_baseline_runtime_policy_hit_count") or 0)
            for row in observations
        ),
        "cohort_overlap_count": int(selection.get("cohort_overlap_count") or 0),
        "holdout_selection_fingerprint_match": int(
            selection.get("holdout_selection_fingerprint_match", 1)
        ),
    }
    counts: dict[str, dict[str, int]] = {}
    for name, key in (
        ("public_packaged_setup_success_rate", "packaged_setup_success"),
        ("public_updater_success_rate", "updater_success"),
        ("public_archive_audit_success_rate", "archive_audit_success"),
        ("public_context_package_parse_success_rate", "context_package_parse_success"),
    ):
        _rate_metric(
            metrics,
            counts,
            name,
            sum(int(bool(row.get(key))) for row in observations),
            len(observations),
        )
    parity_numerator = sum(
        int(row.get("baseline_runtime_policy_parity_numerator") or 0)
        for row in observations
    )
    parity_denominator = sum(
        int(row.get("baseline_runtime_policy_parity_denominator") or 0)
        for row in observations
    )
    _rate_metric(
        metrics,
        counts,
        "baseline_runtime_policy_parity_rate",
        parity_numerator,
        parity_denominator,
        empty_value=1.0,
    )
    selected_parity_numerator = sum(
        int((row.get("runtime_policy_parity") or {}).get(runtime_policy, {}).get("numerator", 0))
        for row in observations
    )
    selected_parity_denominator = sum(
        int((row.get("runtime_policy_parity") or {}).get(runtime_policy, {}).get("denominator", 0))
        for row in observations
    )
    _rate_metric(
        metrics,
        counts,
        "selected_runtime_policy_parity_rate",
        selected_parity_numerator,
        selected_parity_denominator,
        empty_value=1.0,
    )
    prefix = "calibration" if cohort == "calibration" else "holdout"
    metrics[f"{prefix}_gold_memory_candidate_count"] = int(
        runtime_metrics["gold_candidate_count"]
    )
    for suffix, source_name in (
        ("gold_candidate_support_rate", "gold_candidate_support_rate"),
        ("supported_decision_precision", "supported_decision_precision"),
        ("abstention_accuracy", "abstention_accuracy"),
    ):
        name = f"{prefix}_{suffix}"
        source_count = runtime_metrics["metric_counts"][source_name]
        _rate_metric(
            metrics,
            counts,
            name,
            int(source_count["numerator"]),
            int(source_count["denominator"]),
        )
    metrics[f"{prefix}_false_support_count"] = int(runtime_metrics["false_support_count"])
    metrics[f"{prefix}_hard_negative_rejection_rate"] = float(
        runtime_metrics["hard_negative_rejection_rate"]
    )
    metrics[f"{prefix}_inactive_lifecycle_rejection_rate"] = float(
        runtime_metrics["inactive_lifecycle_rejection_rate"]
    )
    metrics[f"{prefix}_malformed_missing_fail_closed_rate"] = float(
        runtime_metrics["malformed_missing_fail_closed_rate"]
    )

    baseline_parity_reproduced = (
        parity_denominator > 0 and metrics["baseline_runtime_policy_parity_rate"] == 1.0
    )
    structural_valid = (
        all(row.get("packaged_setup_success") for row in observations)
        and all(row.get("updater_success") for row in observations)
        and all(row.get("context_package_parse_success") for row in observations)
        and baseline_parity_reproduced
        and metrics["public_attribution_invariant_violation_count"] == 0
        and metrics["public_gold_label_ingestion_count"] == 0
        and metrics["public_answer_ingestion_count"] == 0
        and metrics["synthetic_memory_marker_injection_count"] == 0
        and metrics["direct_synthetic_archive_injection_count"] == 0
        and metrics["cohort_overlap_count"] == 0
        and metrics["holdout_selection_fingerprint_match"] == 1
        and metrics["privacy_leak_count"] == 0
    )
    if not baseline_parity_reproduced:
        readiness_status = "inconclusive"
        decision_reason = "baseline_runtime_policy_parity_mismatch"
    elif int(runtime_metrics["gold_candidate_count"]) < 5:
        readiness_status = "inconclusive"
        decision_reason = "insufficient_gold_candidates"
    elif not structural_valid:
        readiness_status = "inconclusive"
        decision_reason = "structural_validation_failed"
    elif selection_decision["selected_policy"] is None:
        readiness_status = "no_go"
        decision_reason = "no_safe_policy"
    elif cohort == "calibration":
        readiness_status = "calibration_passed"
        decision_reason = "policy_selected"
    else:
        policy_passed = (
            float(runtime_metrics["gold_candidate_support_rate"]) >= 0.80
            and float(runtime_metrics["supported_decision_precision"]) >= 0.80
            and float(runtime_metrics["abstention_accuracy"]) >= 0.90
            and float(runtime_metrics["hard_negative_rejection_rate"]) == 1.0
            and float(runtime_metrics["inactive_lifecycle_rejection_rate"]) == 1.0
            and float(runtime_metrics["malformed_missing_fail_closed_rate"]) == 1.0
            and metrics["selected_runtime_policy_parity_rate"] == 1.0
            and metrics["ranking_drift_count"] == 0
        )
        readiness_status = "go" if structural_valid and policy_passed else "no_go"
        decision_reason = "policy_selected" if readiness_status == "go" else "holdout_failed"

    first_loss_by_question_type: dict[str, dict[str, int]] = {}
    for row in baseline:
        bucket = first_loss_by_question_type.setdefault(
            str(row.get("question_type") or "unknown"),
            {name: 0 for name in first_loss_buckets},
        )
        bucket[classify_first_loss(row)] += 1
    pipeline_failure_by_question_type: dict[str, dict[str, int]] = {}
    for row in observations:
        bucket = pipeline_failure_by_question_type.setdefault(
            str(row.get("question_type") or "unknown"),
            {
                "cases": 0,
                "setup_failure": 0,
                "updater_failure": 0,
                "audit_failure": 0,
                "context_package_parse_failure": 0,
            },
        )
        bucket["cases"] += 1
        bucket["setup_failure"] += int(not row.get("packaged_setup_success"))
        bucket["updater_failure"] += int(not row.get("updater_success"))
        bucket["audit_failure"] += int(not row.get("archive_audit_success"))
        bucket["context_package_parse_failure"] += int(
            not row.get("context_package_parse_success")
        )
    return {
        "report_kind": "public_query_support_calibration_gate",
        "report_version": 1,
        "mode": f"public_{cohort}",
        "status": "completed" if structural_valid else "failed",
        "readiness_status": readiness_status,
        "decision_reason": decision_reason,
        "runtime_policy": runtime_policy,
        "selected_policy": selection_decision["selected_policy"],
        "dataset": dataset,
        "selection": selection,
        "metrics": metrics,
        "metric_counts": counts,
        "policy_metrics": policy_metrics,
        "policy_rejections": selection_decision["rejections"],
        "first_loss_buckets": first_loss_buckets,
        "first_loss_by_question_type": dict(sorted(first_loss_by_question_type.items())),
        "pipeline_failure_by_question_type": dict(
            sorted(pipeline_failure_by_question_type.items())
        ),
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "tokens_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "query-support calibration and frozen holdout evidence only; not ranking repair, "
            "audit repair, induction-content quality, LLM answer quality, or leaderboard parity"
        ),
    }


def _synthetic_partial_positive_package() -> dict[str, Any]:
    return {
        "report_kind": query_gate.CONTEXT_REPORT_KIND,
        "hits": [
            {
                "active_current": True,
                "summary_drill_paths": ["sessions/synthetic/summary.md"],
                "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                "query_support": {
                    "matched_tokens": ["durable", "anchor"],
                    "missing_tokens": ["context"],
                    "strict_token_coverage": False,
                    "meaningful_token_coverage": False,
                },
            }
        ],
    }


def evaluate_synthetic_policy_boundaries(root: Path) -> dict[str, dict[str, int | float]]:
    repo = root / "query-support-archive"
    query_gate.write_synthetic_archive(repo)
    packages = {
        spec.case_id: json.loads(query_gate.run_context_package(repo, spec))
        for spec in query_gate.case_specs()
    }
    hard_negative_ids = (
        query_gate.WRONG_SCOPE_CASE,
        query_gate.WEAK_ACTIVE_CASE,
        query_gate.BROAD_LEXICAL_CASE,
    )
    negative_ids = (
        *hard_negative_ids,
        query_gate.INACTIVE_CASE,
        query_gate.NO_HIT_CASE,
    )
    complete_positive = packages[query_gate.SUPPORTED_CASE]
    partial_positive = _synthetic_partial_positive_package()
    missing_support_package = {
        "report_kind": query_gate.CONTEXT_REPORT_KIND,
        "hits": [
            {
                "active_current": True,
                "summary_drill_paths": [],
                "evidence_drill_paths": [],
                "query_support": {
                    "matched_tokens": ["supported", "anchor"],
                    "missing_tokens": [],
                    "strict_token_coverage": True,
                    "meaningful_token_coverage": True,
                },
            }
        ],
    }
    positive_packages = (complete_positive, partial_positive, partial_positive, partial_positive, partial_positive)
    results: dict[str, dict[str, int | float]] = {}
    for policy in POLICY_NAMES:
        hard_rejections = sum(
            policy_package_action(packages[case_id], policy) == "abstain"
            for case_id in hard_negative_ids
        )
        inactive_rejections = int(
            policy_package_action(packages[query_gate.INACTIVE_CASE], policy) == "abstain"
        )
        malformed_missing_rejections = sum(
            policy_package_action(package, policy) == "abstain"
            for package in (None, {"report_kind": "wrong"})
        )
        missing_support_rejection = int(
            policy_package_action(missing_support_package, policy) == "abstain"
        )
        no_hit_rejection = int(
            policy_package_action(packages[query_gate.NO_HIT_CASE], policy) == "abstain"
        )
        supported_gold = sum(
            policy_package_action(package, policy) == "answer" for package in positive_packages
        )
        false_support = sum(
            policy_package_action(packages[case_id], policy) == "answer" for case_id in negative_ids
        )
        abstentions = len(negative_ids) - false_support
        supported_decisions = supported_gold + false_support
        results[policy] = {
            "gold_candidate_count": len(positive_packages),
            "gold_candidate_support_count": supported_gold,
            "gold_candidate_support_rate": supported_gold / len(positive_packages),
            "supported_decision_precision": (
                supported_gold / supported_decisions if supported_decisions else 0.0
            ),
            "abstention_accuracy": abstentions / len(negative_ids),
            "false_support_count": false_support,
            "hard_negative_rejection_rate": hard_rejections / len(hard_negative_ids),
            "inactive_lifecycle_rejection_rate": float(inactive_rejections),
            "malformed_missing_fail_closed_rate": malformed_missing_rejections / 2,
            "missing_support_drilldown_rejection_rate": float(missing_support_rejection),
            "no_hit_rejection_rate": float(no_hit_rejection),
        }
    return results


def _strict_runtime_parity(packages: list[dict[str, Any]]) -> float:
    cases = matches = 0
    for package in packages:
        for hit in package.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            support = hit.get("query_support")
            if not isinstance(support, dict):
                continue
            if str(support.get("policy") or BASELINE_RUNTIME_POLICY) != BASELINE_RUNTIME_POLICY:
                continue
            cases += 1
            expected = policy_supports(support, search_module.token_importance, "strict_v1")
            matches += int(expected == (support.get("status") == "supported"))
    return matches / cases if cases else 1.0


def run_offline_fixture() -> dict[str, Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        policy_metrics = evaluate_synthetic_policy_boundaries(root)
        repo = root / "parity-archive"
        query_gate.write_synthetic_archive(repo)
        packages = [
            json.loads(query_gate.run_context_package(repo, spec))
            for spec in query_gate.case_specs()
        ]
    selection = select_candidate_policy(policy_metrics)
    metrics = {
        "selected_policy_count": selection["selected_policy_count"],
        "baseline_runtime_policy_parity_rate": _strict_runtime_parity(packages),
        "selected_runtime_policy_parity_rate": _strict_runtime_parity(packages),
        "missing_support_drilldown_rejection_rate": min(
            float(values["missing_support_drilldown_rejection_rate"])
            for values in policy_metrics.values()
        ),
        "no_hit_rejection_rate": min(
            float(values["no_hit_rejection_rate"]) for values in policy_metrics.values()
        ),
        "privacy_leak_count": 0,
    }
    report = {
        "report_kind": "public_query_support_calibration_gate",
        "report_version": 1,
        "mode": "offline_fixture",
        "status": "passed",
        "readiness_status": "no_go",
        "decision_reason": selection["decision_reason"],
        "policy_order": list(POLICY_NAMES),
        "policy_metrics": policy_metrics,
        "policy_rejections": selection["rejections"],
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "case_ids_rendered": False,
            "tokens_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "offline policy-selection contract only; not public calibration performance, "
            "ranking quality, induction quality, answer quality, or leaderboard parity"
        ),
    }
    rendered = json.dumps(report, sort_keys=True)
    metrics["privacy_leak_count"] = sum(marker in rendered for marker in query_gate.LEAK_MARKERS)
    expected = (
        selection["selected_policy"] is None
        and metrics["baseline_runtime_policy_parity_rate"] == 1.0
        and metrics["selected_runtime_policy_parity_rate"] == 1.0
        and metrics["missing_support_drilldown_rejection_rate"] == 1.0
        and metrics["no_hit_rejection_rate"] == 1.0
        and metrics["privacy_leak_count"] == 0
        and policy_metrics["strict_v1"]["hard_negative_rejection_rate"] == 1.0
        and policy_metrics["weighted_partial_060_v1"]["hard_negative_rejection_rate"] < 1.0
        and policy_metrics["weighted_partial_050_specific_v1"]["hard_negative_rejection_rate"] < 1.0
    )
    report["status"] = "passed" if expected else "failed"
    return report


def _inconclusive_report(input_path: Path, source_url: str, reason: str) -> dict[str, Any]:
    try:
        dataset_sha256 = public_gate._file_sha256(input_path)
    except OSError:
        dataset_sha256 = "unavailable"
    return {
        "report_kind": "public_query_support_calibration_gate",
        "report_version": 1,
        "mode": "public_unscored",
        "status": "completed",
        "readiness_status": "inconclusive",
        "decision_reason": reason,
        "dataset": {
            "source": OFFICIAL_DATASET_SOURCE,
            "source_url": source_url,
            "sha256": dataset_sha256,
        },
        "metrics": {"privacy_leak_count": 0},
        "metric_counts": {},
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "tokens_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": "dataset could not be evaluated; no query-support readiness claim",
    }


def frozen_holdout_ranking_drift(observations: list[dict[str, Any]]) -> int:
    positives = [row for row in observations if not row.get("is_abstention")]
    baseline_count = sum(int(row.get("baseline_retrievable") or 0) for row in positives)
    candidate_at_1 = sum(
        int(row.get("baseline_retrievable") and row.get("gold_candidate_at_1"))
        for row in positives
    )
    candidate_at_5 = sum(
        int(row.get("baseline_retrievable") and row.get("gold_candidate_at_5"))
        for row in positives
    )
    return (
        abs(baseline_count - 13)
        + abs(candidate_at_1 - 6)
        + abs(candidate_at_5 - 6)
    )


def run_public_dataset(args: argparse.Namespace) -> dict[str, Any]:
    input_path = public_gate.require_external_artifact_path(
        Path(args.public_input), "public benchmark input"
    )
    try:
        rows = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError:
        return _inconclusive_report(input_path, args.dataset_source_url, "dataset_unreadable")
    except json.JSONDecodeError:
        return _inconclusive_report(input_path, args.dataset_source_url, "dataset_schema_incompatible")
    if not isinstance(rows, list):
        return _inconclusive_report(input_path, args.dataset_source_url, "dataset_schema_incompatible")
    if public_gate._file_sha256(input_path) != OFFICIAL_DATASET_SHA256:
        return _inconclusive_report(input_path, args.dataset_source_url, "dataset_sha_mismatch")
    try:
        holdout, calibration = select_disjoint_cohorts(
            rows,
            holdout_seed=HOLDOUT_SEED,
            calibration_seed=CALIBRATION_SEED,
            positive_per_type=args.positive_per_type,
            abstention_count=args.abstention_count,
        )
    except SystemExit:
        return _inconclusive_report(
            input_path,
            args.dataset_source_url,
            "dataset_schema_incompatible",
        )

    work_dir = public_gate.require_external_artifact_path(
        Path(args.work_dir), "public benchmark work directory"
    )
    report_path = public_gate.require_external_artifact_path(
        Path(args.report_file), "public benchmark report"
    )
    if work_dir.exists() and any(work_dir.iterdir()):
        raise SystemExit("--work-dir must be empty")
    work_dir.mkdir(parents=True, exist_ok=True)

    selected = calibration if args.cohort == "calibration" else holdout
    holdout_ids = {str(row["question_id"]) for row in holdout}
    calibration_ids = {str(row["question_id"]) for row in calibration}
    overlap_count = len(holdout_ids.intersection(calibration_ids))
    holdout_fingerprint = public_gate._selection_fingerprint(holdout)
    calibration_fingerprint = public_gate._selection_fingerprint(calibration)
    formal_selection = args.positive_per_type == 5 and args.abstention_count == 10
    holdout_fingerprint_match = int(
        not formal_selection or holdout_fingerprint == HOLDOUT_FINGERPRINT
    )
    observations = [
        observe_packaged_case(row, ordinal, work_dir / f"case-{ordinal:03d}")
        for ordinal, row in enumerate(selected, 1)
    ]
    policy_boundaries = evaluate_synthetic_policy_boundaries(work_dir / "policy-boundaries")
    ranking_drift_count = 0
    if args.cohort == "holdout" and formal_selection:
        ranking_drift_count = frozen_holdout_ranking_drift(observations)
    selection = {
        "cohort": args.cohort,
        "holdout_seed": HOLDOUT_SEED,
        "calibration_seed": CALIBRATION_SEED,
        "positive_per_type": args.positive_per_type,
        "abstention_count": args.abstention_count,
        "selected_case_count": len(selected),
        "holdout_case_count": len(holdout),
        "calibration_case_count": len(calibration),
        "cohort_overlap_count": overlap_count,
        "holdout_fingerprint_sha256": holdout_fingerprint,
        "calibration_fingerprint_sha256": calibration_fingerprint,
        "selected_fingerprint_sha256": public_gate._selection_fingerprint(selected),
        "holdout_selection_fingerprint_match": holdout_fingerprint_match,
    }
    report = build_cohort_report(
        cohort=args.cohort,
        observations=observations,
        policy_boundaries=policy_boundaries,
        dataset={
            "source": OFFICIAL_DATASET_SOURCE,
            "source_url": args.dataset_source_url,
            "sha256": OFFICIAL_DATASET_SHA256,
            "input_record_count": len(rows),
        },
        selection=selection,
        selected_policy=(
            None if args.selected_policy == "none" else str(args.selected_policy)
        ),
        ranking_drift_count=ranking_drift_count,
    )
    report["selected_case_count"] = len(selected)
    report["metrics"]["privacy_leak_count"] = int(
        report["metrics"]["privacy_leak_count"]
    ) + public_gate.aggregate_privacy_leak_count(
        report,
        selected,
        [input_path, work_dir, report_path],
    )
    if report["metrics"]["privacy_leak_count"]:
        report["status"] = "failed"
        report["readiness_status"] = "no_go"
        report["decision_reason"] = "privacy_boundary_failed"
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
    parser.add_argument("--selected-policy", choices=("none", *POLICY_NAMES), default="none")
    parser.add_argument("--positive-per-type", type=int, default=5)
    parser.add_argument("--abstention-count", type=int, default=10)
    args = parser.parse_args(argv)
    if args.public_input and not all(
        (args.dataset_source_url, args.cohort, args.work_dir, args.report_file)
    ):
        parser.error(
            "public mode requires --dataset-source-url, --cohort, --work-dir, and --report-file"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = (
        public_gate.require_external_artifact_path(
            Path(args.report_file), "public benchmark report"
        )
        if args.report_file
        else None
    )
    report = run_offline_fixture() if args.offline_fixture else run_public_dataset(args)
    rendered = json.dumps(report, sort_keys=True)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] in {"passed", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
