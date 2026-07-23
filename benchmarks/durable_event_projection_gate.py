#!/usr/bin/env python3
"""Attribute selected-record preparation before allowing durable-event projection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_SOURCE = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
REPORT_KIND = "durable_event_projection_gate"
DURABLE_EVENT_KINDS = {"user", "assistant", "record"}
NOISE_SENTINEL = "NON_DURABLE_SYNTHETIC_PAYLOAD"
DURABLE_SENTINEL = "DURABLE_PROJECTION_DECISION"
PHASE_NAMES = (
    "read_hash",
    "redaction",
    "json_decoding",
    "durable_event_extraction",
    "nondurable_event_materialization",
    "durable_event_normalization",
    "nondurable_event_normalization",
    "analysis_other",
    "validation_scans",
    "summary_source_anchor",
    "artifact_rendering",
    "artifact_apply",
    "orchestration",
)


@dataclass
class ProfileResult:
    total_seconds: float
    phase_seconds: dict[str, float]
    counts: dict[str, int]
    prepared: object


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("updater module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def projected_max_speedup(avoidable_share: float) -> float:
    if avoidable_share >= 1.0:
        return float("inf")
    if avoidable_share <= 0.0:
        return 1.0
    return 1.0 / (1.0 - avoidable_share)


def profile_decision(avoidable_share: float, dependency_rate: float) -> str:
    if (
        avoidable_share >= 0.55
        and projected_max_speedup(avoidable_share) >= 2.2
        and dependency_rate == 0.0
    ):
        return "implement"
    return "profile_no_go"


def event_processing_class(value: object) -> str:
    if isinstance(value, list):
        classes = {event_processing_class(item) for item in value}
        return classes.pop() if len(classes) == 1 else "mixed"
    if not isinstance(value, dict):
        return "durable"
    event_type = str(value.get("type") or "")
    if event_type in {"session_meta", "turn_context", "event_msg"}:
        return "skipped"
    payload = value.get("payload")
    body = payload if isinstance(payload, dict) else value
    body_type = str(body.get("type") or event_type)
    if body_type in {"function_call", "function_call_output"}:
        return "nondurable"
    role = str(body.get("role") or value.get("role") or "").lower()
    if role == "assistant" and str(body.get("phase") or body.get("channel") or "").lower() == "commentary":
        return "nondurable"
    return "durable"


def normalize_nested_phases(total: float, values: dict[str, float]) -> tuple[dict[str, float], float]:
    nested = sum(values.values())
    if nested > total and nested > 0.0:
        scale = total / nested
        values = {name: value * scale for name, value in values.items()}
        nested = total
    return values, max(0.0, total - nested)


def profiled_analysis(module: ModuleType, source_text: str, redacted_text: str) -> tuple[list[object], list[object], dict[str, float], dict[str, int], float]:
    original_json_loads = module.json.loads
    original_events_from_value = module.events_from_value
    original_clean_source_events = module.clean_source_events
    nested = {
        "json_decoding": 0.0,
        "durable_event_extraction": 0.0,
        "nondurable_event_materialization": 0.0,
        "durable_event_normalization": 0.0,
        "nondurable_event_normalization": 0.0,
    }
    counts = {
        "nondurable_event_text_materialization_count": 0,
        "nondurable_event_normalization_count": 0,
    }
    event_depth = 0

    def counted_json_loads(value, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_json_loads(value, *args, **kwargs)
        finally:
            nested["json_decoding"] += time.perf_counter() - started

    def counted_events_from_value(value):
        nonlocal event_depth
        top_level = event_depth == 0
        event_depth += 1
        json_before = nested["json_decoding"]
        started = time.perf_counter()
        try:
            result = original_events_from_value(value)
        finally:
            elapsed = time.perf_counter() - started
            event_depth -= 1
        if top_level:
            exclusive = max(0.0, elapsed - (nested["json_decoding"] - json_before))
            classification = event_processing_class(value)
            if classification == "nondurable":
                nested["nondurable_event_materialization"] += exclusive
                counts["nondurable_event_text_materialization_count"] += 1
            elif classification == "durable":
                nested["durable_event_extraction"] += exclusive
        return result

    def counted_clean_source_events(events):
        cleaned = []
        for event in events:
            started = time.perf_counter()
            event_text = module.strip_memory_citation_blocks(event.text)
            if not module.is_injected_context_text(event_text):
                for piece in module.split_memory_text(event_text):
                    text = module.strip_process_clauses(piece)
                    if text and not module.is_noisy_text(text) and not module.is_process_update(text):
                        cleaned.append(
                            module.MemoryEvent(
                                event.kind,
                                text,
                                event.line_number,
                                event.event_ordinal,
                                event.event_sha256,
                            )
                        )
            elapsed = time.perf_counter() - started
            if event.kind in DURABLE_EVENT_KINDS:
                nested["durable_event_normalization"] += elapsed
            else:
                nested["nondurable_event_normalization"] += elapsed
                counts["nondurable_event_normalization_count"] += 1
        return cleaned

    module.json.loads = counted_json_loads
    module.events_from_value = counted_events_from_value
    module.clean_source_events = counted_clean_source_events
    started = time.perf_counter()
    try:
        events, values = module.analyze_selected_jsonl(source_text, redacted_text)
    finally:
        elapsed = time.perf_counter() - started
        module.json.loads = original_json_loads
        module.events_from_value = original_events_from_value
        module.clean_source_events = original_clean_source_events
    nested, residual = normalize_nested_phases(elapsed, nested)
    nested["analysis_other"] = residual
    return events, values, nested, counts, elapsed


def timed(function: Callable, *args, **kwargs):
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, time.perf_counter() - started


def profile_inventory_record(
    module: ModuleType,
    memory_repo: Path,
    project_path: Path,
    archive_scope: str,
    source_partition: str,
    project_name: str,
    source_agent: str,
    record: object,
    require_project_metadata: bool,
    *,
    apply: bool = True,
) -> ProfileResult:
    phases = {name: 0.0 for name in PHASE_NAMES}
    total_started = time.perf_counter()

    (source_text, source_mtime), phases["read_hash"] = timed(module.read_validated_inventory_record, record)
    (redacted_text, redaction_counts), phases["redaction"] = timed(module.redact_text, source_text)
    events, source_values, analysis_phases, counts, analysis_elapsed = profiled_analysis(
        module, source_text, redacted_text
    )
    phases.update(analysis_phases)

    validation_started = time.perf_counter()
    if module.source_values_are_automation(source_values):
        raise module.SourceInventoryError("source inventory contains an automation record")
    if not module.record_matches_project_values(source_values, project_path, require_project_metadata):
        raise module.SourceInventoryError("source inventory target mismatch")
    if module.source_timestamp_from_values(record.path, source_values, fallback_mtime=source_mtime) != record.updated_at:
        raise module.SourceInventoryError("source inventory timestamp mismatch")
    phases["validation_scans"] = time.perf_counter() - validation_started
    del source_values, source_text, redacted_text

    wrapped_names = (
        "summarize_events",
        "extract_explicit_memory_texts",
        "explicit_source_entries",
        "memory_candidate_source_entries",
        "materialize_source_anchors",
    )
    originals = {name: getattr(module, name) for name in wrapped_names}
    nested_prepare = 0.0

    def timed_wrapper(function):
        def wrapper(*args, **kwargs):
            nonlocal nested_prepare
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                nested_prepare += time.perf_counter() - started

        return wrapper

    for name, function in originals.items():
        setattr(module, name, timed_wrapper(function))
    prepare_started = time.perf_counter()
    try:
        prepared = module.prepare_record(
            memory_repo,
            project_path,
            archive_scope,
            source_partition,
            project_name,
            source_agent,
            record,
            events,
            redaction_counts,
        )
    finally:
        prepare_elapsed = time.perf_counter() - prepare_started
        for name, function in originals.items():
            setattr(module, name, function)
    prepare_split, artifact_residual = normalize_nested_phases(
        prepare_elapsed, {"summary_source_anchor": nested_prepare}
    )
    phases.update(prepare_split)
    phases["artifact_rendering"] = artifact_residual

    if apply:
        _, phases["artifact_apply"] = timed(module.apply_prepared_record, memory_repo, prepared)
    total_seconds = time.perf_counter() - total_started
    outer_accounted = (
        phases["read_hash"]
        + phases["redaction"]
        + analysis_elapsed
        + phases["validation_scans"]
        + prepare_elapsed
        + phases["artifact_apply"]
    )
    phases["orchestration"] = max(0.0, total_seconds - outer_accounted)
    return ProfileResult(total_seconds, phases, counts, prepared)


def synthetic_case(root: Path, module: ModuleType) -> tuple[Path, Path, Path, object]:
    memory_repo = root / "agent-memory"
    source_dir = root / "source-records"
    project_path = root / "project"
    memory_repo.mkdir()
    source_dir.mkdir()
    project_path.mkdir()
    noise = (NOISE_SENTINEL + " ") * 8192
    rows = [
        {"type": "session_meta", "timestamp": "2026-07-13T06:00:00Z", "payload": {"cwd": str(project_path), "thread_source": "cli"}},
        {"timestamp": "2026-07-13T06:30:00Z", "cwd": str(project_path), "role": "user", "content": f"Remember that {DURABLE_SENTINEL} preserves output parity."},
        {"type": "event_msg", "timestamp": "2026-07-13T06:45:00Z", "payload": {"message": noise}},
        {"type": "response_item", "timestamp": "2026-07-13T07:00:00Z", "payload": {"type": "message", "role": "assistant", "phase": "commentary", "content": noise}},
        {"type": "response_item", "timestamp": "2026-07-13T07:15:00Z", "payload": {"type": "function_call", "name": "synthetic_tool", "arguments": json.dumps({"content": noise})}},
        {"type": "response_item", "timestamp": "2026-07-13T07:30:00Z", "payload": {"type": "function_call_output", "output": noise}},
        {"type": "response_item", "timestamp": "2026-07-13T08:00:00Z", "payload": {"type": "message", "role": "assistant", "phase": "final", "content": f"Decision: {DURABLE_SENTINEL} is the durable outcome."}},
    ]
    source_path = source_dir / "record.jsonl"
    source_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    raw = source_path.read_bytes()
    stat = source_path.stat()
    record = module.SourceRecord(
        source_path.resolve(),
        datetime(2026, 7, 13, 8, 0, tzinfo=UTC),
        hashlib.sha256(raw).hexdigest(),
        expected_size=len(raw),
        expected_mtime_ns=stat.st_mtime_ns,
    )
    return memory_repo, source_dir, project_path.resolve(), record


def artifact_map(prepared: object) -> dict[str, str]:
    return {name: text for name, text in prepared.artifacts}


def counterfactual_projection_metrics(
    module: ModuleType,
    root: Path,
    project_path: Path,
    record: object,
    archive_scope: str,
    source_partition: str,
) -> dict[str, float]:
    source_text, _ = module.read_validated_inventory_record(record)
    redacted_text, redaction_counts = module.redact_source_text(record.path, source_text)
    events, _ = module.analyze_selected_jsonl(source_text, redacted_text)
    projected = [event for event in events if event.kind in DURABLE_EVENT_KINDS]
    original_now = module.utc_now
    module.utc_now = lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    try:
        complete = module.prepare_record(
            root / "complete",
            project_path,
            archive_scope,
            source_partition,
            "project",
            "synthetic",
            record,
            events,
            redaction_counts,
        )
        durable = module.prepare_record(
            root / "durable",
            project_path,
            archive_scope,
            source_partition,
            "project",
            "synthetic",
            record,
            projected,
            redaction_counts,
        )
    finally:
        module.utc_now = original_now
    complete_durable = [event for event in events if event.kind in DURABLE_EVENT_KINDS]
    order_fields = lambda event: (event.kind, event.text, event.line_number, event.event_ordinal)
    hash_fields = lambda event: (event.line_number, event.event_ordinal, event.event_sha256)
    artifacts_equal = artifact_map(complete) == artifact_map(durable)
    return {
        "nondurable_output_dependency_rate": 0.0 if artifacts_equal else 1.0,
        "durable_event_projection_parity_rate": 1.0 if artifacts_equal else 0.0,
        "durable_event_order_parity_rate": 1.0
        if [order_fields(event) for event in complete_durable] == [order_fields(event) for event in projected]
        else 0.0,
        "durable_event_hash_parity_rate": 1.0
        if [hash_fields(event) for event in complete_durable] == [hash_fields(event) for event in projected]
        else 0.0,
    }


def build_report(root: Path) -> dict[str, object]:
    module = load_module(UPDATER_SOURCE, "durable_event_projection_updater")
    memory_repo, _, project_path, record = synthetic_case(root, module)
    archive_scope = module.normalize_archive_scope(None, project_path)
    source_partition = module.normalize_source_partition(None, project_path)
    original_now = module.utc_now
    module.utc_now = lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    try:
        normal = module.prepare_inventory_record(
            root / "normal",
            project_path,
            archive_scope,
            source_partition,
            "project",
            "synthetic",
            record,
            True,
        )
        profile = profile_inventory_record(
            module,
            memory_repo,
            project_path,
            archive_scope,
            source_partition,
            "project",
            "synthetic",
            record,
            True,
        )
    finally:
        module.utc_now = original_now
    phase_sum = sum(profile.phase_seconds.values())
    coverage = phase_sum / profile.total_seconds if profile.total_seconds > 0.0 else 0.0
    avoidable = (
        profile.phase_seconds["nondurable_event_materialization"]
        + profile.phase_seconds["nondurable_event_normalization"]
    )
    avoidable_share = avoidable / profile.total_seconds if profile.total_seconds > 0.0 else 0.0
    dependency_metrics = counterfactual_projection_metrics(
        module, root / "projection", project_path, record, archive_scope, source_partition
    )
    decision_cases = (
        profile_decision(0.55, 0.0) == "implement",
        profile_decision(0.549999, 0.0) == "profile_no_go",
        profile_decision(0.75, 0.01) == "profile_no_go",
    )
    metrics: dict[str, int | float] = {
        "phase_attribution_coverage_rate": coverage,
        "implementation_decision_accuracy": 1.0 if all(decision_cases) else 0.0,
        "profile_harness_output_parity_rate": 1.0
        if artifact_map(normal) == artifact_map(profile.prepared)
        else 0.0,
        "nondurable_event_text_materialization_count": profile.counts[
            "nondurable_event_text_materialization_count"
        ],
        "nondurable_event_normalization_count": profile.counts[
            "nondurable_event_normalization_count"
        ],
        "synthetic_avoidable_nondurable_processing_share": avoidable_share,
        "synthetic_projected_max_speedup": projected_max_speedup(avoidable_share),
        **dependency_metrics,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "mode": "attribution_only",
        "metrics": metrics,
        "phase_seconds": {name: round(value, 6) for name, value in profile.phase_seconds.items()},
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "source_content_rendered": False,
            "project_names_rendered": False,
            "child_output_rendered": False,
        },
        "claim_boundary": (
            "synthetic selected-record phase attribution, decision-boundary accuracy, and "
            "counterfactual durable-event dependency only; not private hotspot attribution, "
            "projection implementation, deployment approval, memory quality, or ranking"
        ),
    }
    rendered = json.dumps(report, sort_keys=True)
    metrics["privacy_leak_count"] = sum(
        marker in rendered for marker in (str(root), NOISE_SENTINEL, DURABLE_SENTINEL)
    )
    passed = (
        metrics["phase_attribution_coverage_rate"] >= 0.95
        and metrics["implementation_decision_accuracy"] == 1.0
        and metrics["profile_harness_output_parity_rate"] == 1.0
        and metrics["nondurable_output_dependency_rate"] == 0.0
        and metrics["nondurable_event_text_materialization_count"] > 0
        and metrics["nondurable_event_normalization_count"] > 0
        and metrics["durable_event_projection_parity_rate"] == 1.0
        and metrics["durable_event_order_parity_rate"] == 1.0
        and metrics["durable_event_hash_parity_rate"] == 1.0
        and metrics["privacy_leak_count"] == 0
    )
    report["status"] = "passed" if passed else "failed"
    return report


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_report(Path(tmpdir))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
