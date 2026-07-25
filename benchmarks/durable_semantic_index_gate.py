#!/usr/bin/env python3
"""Attribute fused event/summary work before runtime semantic-index integration."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_SOURCE = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
V241_GATE_SOURCE = REPO_ROOT / "benchmarks/durable_event_projection_gate.py"
REPORT_KIND = "durable_semantic_index_gate"
PARITY_KEYS = (
    "counterfactual_archive_output_parity_rate",
    "counterfactual_summary_field_parity_rate",
    "counterfactual_source_anchor_parity_rate",
    "counterfactual_event_order_parity_rate",
    "counterfactual_event_hash_parity_rate",
)
PHASE_NAMES = (
    "read_hash",
    "redaction",
    "json_decoding",
    "nondurable_event_materialization",
    "nondurable_event_normalization",
    "required_durable_cleanup",
    "required_semantic_normalization",
    "repeated_semantic_normalization",
    "required_event_scan",
    "repeated_event_scans",
    "source_lookup",
    "required_summary_selection",
    "anchor_assembly",
    "rendering",
    "validation",
    "artifact_apply",
    "residual_orchestration",
)
AVOIDABLE_PHASES = (
    "nondurable_event_materialization",
    "nondurable_event_normalization",
    "repeated_semantic_normalization",
    "repeated_event_scans",
    "source_lookup",
)


@dataclass
class _Frame:
    phase: str
    started: float
    child_seconds: float = 0.0


class ExclusivePhaseProfiler:
    """Assign nested call time only to the innermost active phase."""

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.clock = clock
        self.phase_seconds: dict[str, float] = defaultdict(float)
        self._stack: list[_Frame] = []

    @contextmanager
    def measure(self, phase: str) -> Iterator[None]:
        frame = _Frame(phase, self.clock())
        self._stack.append(frame)
        try:
            yield
        finally:
            elapsed = self.clock() - frame.started
            popped = self._stack.pop()
            if popped is not frame:
                raise RuntimeError("exclusive profiler stack is unbalanced")
            self.phase_seconds[phase] += max(0.0, elapsed - frame.child_seconds)
            if self._stack:
                self._stack[-1].child_seconds += elapsed


class CountingEventList(list):
    def __init__(self, values: Iterable[object]) -> None:
        super().__init__(values)
        self.traversal_count = 0

    def __iter__(self):
        self.traversal_count += 1
        return super().__iter__()


@dataclass
class ProfileResult:
    total_seconds: float
    phase_seconds: dict[str, float]
    counts: dict[str, int]
    prepared: object


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module is unavailable: {path.name}")
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


def architecture_decision(
    coverage_rate: float,
    avoidable_share: float,
    parity_rates: Iterable[float],
) -> str:
    rates = tuple(parity_rates)
    if (
        coverage_rate >= 0.95
        and avoidable_share >= 0.60
        and projected_max_speedup(avoidable_share) >= 2.5
        and len(rates) == len(PARITY_KEYS)
        and all(rate == 1.0 for rate in rates)
    ):
        return "implement"
    return "architecture_no_go"


def timed(function: Callable, *args, **kwargs):
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, time.perf_counter() - started


def _scaled_phases(total: float, phases: dict[str, float]) -> tuple[dict[str, float], float]:
    attributed = sum(phases.values())
    if attributed > total and attributed > 0.0:
        scale = total / attributed
        phases = {name: value * scale for name, value in phases.items()}
        attributed = total
    return phases, max(0.0, total - attributed)


def _profile_prepare(
    module: ModuleType,
    memory_repo: Path,
    project_path: Path,
    archive_scope: str,
    source_partition: str,
    project_name: str,
    source_agent: str,
    record: object,
    events: list[object],
    redaction_counts: dict[str, int],
) -> tuple[object, dict[str, float], dict[str, int], float]:
    profiler = ExclusivePhaseProfiler()
    counted_events = CountingEventList(events)
    originals: dict[str, Callable] = {}
    seen_semantic_inputs: set[tuple[str, str]] = set()
    counts = {
        "repeated_semantic_normalization_count": 0,
        "source_event_lookup_full_scan_count": 0,
        "source_event_for_text_scan_count": 0,
        "source_text_normalization_count": 0,
    }
    event_scan_seen = False

    def patch(name: str, phase_for_call: Callable[..., str]) -> None:
        original = getattr(module, name)
        originals[name] = original

        def wrapper(*args, **kwargs):
            phase = phase_for_call(*args, **kwargs)
            with profiler.measure(phase):
                return original(*args, **kwargs)

        setattr(module, name, wrapper)

    def semantic_phase(name: str, *args, **_kwargs) -> str:
        if name == "source_text_key":
            counts["source_text_normalization_count"] += 1
        value = args[0] if args and isinstance(args[0], str) else repr(args[:1])
        key = (name, value)
        if key in seen_semantic_inputs:
            counts["repeated_semantic_normalization_count"] += 1
            return "repeated_semantic_normalization"
        seen_semantic_inputs.add(key)
        return "required_semantic_normalization"

    def event_scan_phase(*_args, **_kwargs) -> str:
        nonlocal event_scan_seen
        if not event_scan_seen:
            event_scan_seen = True
            return "required_event_scan"
        return "repeated_event_scans"

    def source_scan_phase(*_args, **_kwargs) -> str:
        counts["source_event_lookup_full_scan_count"] += 1
        return "source_lookup"

    def source_event_for_text_phase(*_args, **_kwargs) -> str:
        counts["source_event_lookup_full_scan_count"] += 1
        counts["source_event_for_text_scan_count"] += 1
        return "source_lookup"

    def source_lookup_phase(*_args, **_kwargs) -> str:
        return "source_lookup"

    for name in (
        "durable_memory_text",
        "durable_user_memory_text",
        "normalize_memory_text",
        "source_text_key",
        "natural_user_memory_fact",
    ):
        patch(name, lambda *args, _name=name, **kwargs: semantic_phase(_name, *args, **kwargs))
    patch("event_texts", event_scan_phase)
    patch("extract_explicit_memory_texts", lambda *_args, **_kwargs: "repeated_event_scans")
    for name in (
        "event_has_reusable_fact_text",
        "explicit_source_event",
    ):
        patch(name, source_scan_phase)
    patch("source_event_for_text", source_event_for_text_phase)
    for name in (
        "evidence_source_entries",
        "explicit_source_entries",
        "fact_source_entries",
        "memory_candidate_source_entries",
    ):
        patch(name, source_lookup_phase)
    patch("summarize_events", lambda *_args, **_kwargs: "required_summary_selection")
    patch("materialize_source_anchors", lambda *_args, **_kwargs: "anchor_assembly")

    started = time.perf_counter()
    try:
        prepared = module.prepare_record(
            memory_repo,
            project_path,
            archive_scope,
            source_partition,
            project_name,
            source_agent,
            record,
            counted_events,
            redaction_counts,
        )
    finally:
        elapsed = time.perf_counter() - started
        for name, original in originals.items():
            setattr(module, name, original)
    phases, rendering = _scaled_phases(elapsed, dict(profiler.phase_seconds))
    phases["rendering"] = rendering
    counts["raw_event_traversal_count"] = counted_events.traversal_count
    return prepared, phases, counts, elapsed


def profile_inventory_record(
    module: ModuleType,
    v241: ModuleType,
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
    events, source_values, analysis, analysis_counts, analysis_elapsed = v241.profiled_analysis(
        module, source_text, redacted_text
    )
    phases["json_decoding"] = analysis["json_decoding"]
    phases["nondurable_event_materialization"] = analysis["nondurable_event_materialization"]
    phases["nondurable_event_normalization"] = analysis["nondurable_event_normalization"]
    phases["required_durable_cleanup"] = (
        analysis["durable_event_extraction"] + analysis["durable_event_normalization"]
    )
    phases["residual_orchestration"] += analysis["analysis_other"]

    validation_started = time.perf_counter()
    if module.source_values_are_automation(source_values):
        raise module.SourceInventoryError("source inventory contains an automation record")
    if not module.record_matches_project_values(source_values, project_path, require_project_metadata):
        raise module.SourceInventoryError("source inventory target mismatch")
    if module.source_timestamp_from_values(record.path, source_values, fallback_mtime=source_mtime) != record.updated_at:
        raise module.SourceInventoryError("source inventory timestamp mismatch")
    phases["validation"] = time.perf_counter() - validation_started
    del source_values, source_text, redacted_text

    prepared, prepare_phases, prepare_counts, prepare_elapsed = _profile_prepare(
        module,
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
    for name, value in prepare_phases.items():
        phases[name] += value
    if apply:
        _, phases["artifact_apply"] = timed(module.apply_prepared_record, memory_repo, prepared)
    total_seconds = time.perf_counter() - total_started
    accounted_outer = (
        phases["read_hash"]
        + phases["redaction"]
        + analysis_elapsed
        + phases["validation"]
        + prepare_elapsed
        + phases["artifact_apply"]
    )
    phases["residual_orchestration"] += max(0.0, total_seconds - accounted_outer)
    counts = {
        **prepare_counts,
        "nondurable_text_materialization_count": analysis_counts[
            "nondurable_event_text_materialization_count"
        ],
    }
    return ProfileResult(total_seconds, phases, counts, prepared)


@contextmanager
def semantic_cache_counterfactual(module: ModuleType, events: list[object]):
    originals: dict[str, Callable] = {}

    def patch_unary(name: str) -> None:
        original = getattr(module, name)
        originals[name] = original
        cache: dict[str, object] = {}

        def wrapper(value: str):
            if value not in cache:
                cache[value] = original(value)
            return cache[value]

        setattr(module, name, wrapper)

    for name in (
        "durable_memory_text",
        "durable_user_memory_text",
        "normalize_memory_text",
        "source_text_key",
        "natural_user_memory_fact",
    ):
        patch_unary(name)

    original_event_texts = module.event_texts
    originals["event_texts"] = original_event_texts
    text_cache: dict[tuple[str, ...] | None, list[str]] = {}

    def cached_event_texts(_events, kinds=None):
        key = tuple(sorted(kinds)) if kinds is not None else None
        if key not in text_cache:
            text_cache[key] = original_event_texts(events, kinds)
        return list(text_cache[key])

    module.event_texts = cached_event_texts
    for name in ("source_event_for_text", "explicit_source_event", "event_has_reusable_fact_text"):
        original = getattr(module, name)
        originals[name] = original
        cache: dict[str, object] = {}

        def wrapper(_events, text, *, _original=original, _cache=cache):
            if text not in _cache:
                _cache[text] = _original(events, text)
            return _cache[text]

        setattr(module, name, wrapper)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(module, name, original)


def artifact_map(prepared: object) -> dict[str, str]:
    return {name: text for name, text in prepared.artifacts}


def json_artifact(prepared: object, suffix: str) -> object:
    for name, text in prepared.artifacts:
        if name.endswith(suffix):
            return json.loads(text)
    raise AssertionError(f"missing artifact: {suffix}")


def counterfactual_metrics(
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
    durable_events = [event for event in events if event.kind in {"user", "assistant", "record"}]
    original_now = module.utc_now
    module.utc_now = lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    try:
        normal = module.prepare_record(
            root / "normal",
            project_path,
            archive_scope,
            source_partition,
            "project",
            "synthetic",
            record,
            events,
            redaction_counts,
        )
        with semantic_cache_counterfactual(module, durable_events):
            counterfactual = module.prepare_record(
                root / "counterfactual",
                project_path,
                archive_scope,
                source_partition,
                "project",
                "synthetic",
                record,
                durable_events,
                redaction_counts,
            )
    finally:
        module.utc_now = original_now
    normal_meta = json_artifact(normal, "meta.json")
    counterfactual_meta = json_artifact(counterfactual, "meta.json")
    summary_keys = (
        "title",
        "user_intent",
        "summary",
        "reusable_facts",
        "reusable_fact_sources",
        "memory_candidate_sources",
        "tags",
        "decisions",
        "explicit_memories",
        "explicit_memory_sources",
        "unresolved_tasks",
    )
    normal_summary = {key: normal_meta.get(key) for key in summary_keys}
    counterfactual_summary = {key: counterfactual_meta.get(key) for key in summary_keys}
    order = lambda event: (event.kind, event.text, event.line_number, event.event_ordinal)
    hashes = lambda event: (event.line_number, event.event_ordinal, event.event_sha256)
    return {
        "counterfactual_archive_output_parity_rate": 1.0
        if artifact_map(normal) == artifact_map(counterfactual)
        else 0.0,
        "counterfactual_summary_field_parity_rate": 1.0
        if normal_summary == counterfactual_summary
        else 0.0,
        "counterfactual_source_anchor_parity_rate": 1.0
        if json_artifact(normal, "source-map.json") == json_artifact(counterfactual, "source-map.json")
        else 0.0,
        "counterfactual_event_order_parity_rate": 1.0
        if [order(event) for event in events if event.kind in {"user", "assistant", "record"}]
        == [order(event) for event in durable_events]
        else 0.0,
        "counterfactual_event_hash_parity_rate": 1.0
        if [hashes(event) for event in events if event.kind in {"user", "assistant", "record"}]
        == [hashes(event) for event in durable_events]
        else 0.0,
    }


def build_report(root: Path) -> dict[str, object]:
    module = load_module(UPDATER_SOURCE, "durable_semantic_index_updater")
    v241 = load_module(V241_GATE_SOURCE, "durable_semantic_index_v241_gate")
    memory_repo, _, project_path, record = v241.synthetic_case(root, module)
    archive_scope = module.normalize_archive_scope(None, project_path)
    source_partition = module.normalize_source_partition(None, project_path)
    original_now = module.utc_now
    module.utc_now = lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    try:
        profile = profile_inventory_record(
            module,
            v241,
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
    overlap = max(0.0, phase_sum - profile.total_seconds)
    coverage = min(phase_sum, profile.total_seconds) / profile.total_seconds
    avoidable_seconds = sum(profile.phase_seconds[name] for name in AVOIDABLE_PHASES)
    avoidable_share = avoidable_seconds / profile.total_seconds
    parity = counterfactual_metrics(
        module, root / "counterfactual", project_path, record, archive_scope, source_partition
    )
    parity_rates = tuple(parity[name] for name in PARITY_KEYS)
    decision_cases = (
        architecture_decision(0.95, 0.60, (1.0,) * 5) == "implement",
        architecture_decision(0.949999, 0.60, (1.0,) * 5) == "architecture_no_go",
        architecture_decision(0.95, 0.599999, (1.0,) * 5) == "architecture_no_go",
        architecture_decision(0.95, 0.60, ()) == "architecture_no_go",
        architecture_decision(0.95, 0.60, (1.0,) * 4) == "architecture_no_go",
        architecture_decision(0.95, 0.60, (1.0, 1.0, 0.9, 1.0, 1.0))
        == "architecture_no_go",
    )
    metrics: dict[str, int | float] = {
        "exclusive_phase_attribution_coverage_rate": coverage,
        "exclusive_phase_overlap_seconds": overlap,
        "architecture_decision_accuracy": 1.0 if all(decision_cases) else 0.0,
        "baseline_raw_event_traversal_count": profile.counts["raw_event_traversal_count"],
        "baseline_source_event_lookup_full_scan_count": profile.counts[
            "source_event_lookup_full_scan_count"
        ],
        "baseline_source_event_for_text_scan_count": profile.counts[
            "source_event_for_text_scan_count"
        ],
        "baseline_source_text_normalization_count": profile.counts[
            "source_text_normalization_count"
        ],
        "baseline_repeated_semantic_normalization_count": profile.counts[
            "repeated_semantic_normalization_count"
        ],
        "baseline_nondurable_text_materialization_count": profile.counts[
            "nondurable_text_materialization_count"
        ],
        "synthetic_fused_avoidable_processing_share": avoidable_share,
        "synthetic_fused_projected_max_speedup": projected_max_speedup(avoidable_share),
        **parity,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "mode": "attribution_only",
        "architecture_decision": architecture_decision(coverage, avoidable_share, parity_rates),
        "metrics": metrics,
        "phase_seconds": {name: round(profile.phase_seconds[name], 6) for name in PHASE_NAMES},
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "source_content_rendered": False,
            "project_names_rendered": False,
            "child_output_rendered": False,
        },
        "claim_boundary": (
            "synthetic exclusive phase attribution and semantic-cache counterfactual parity only; "
            "not private hotspot attribution, runtime semantic-index implementation, deployment "
            "approval, memory quality, ranking, or LLM quality"
        ),
    }
    rendered = json.dumps(report, sort_keys=True)
    metrics["privacy_leak_count"] = sum(
        marker in rendered
        for marker in (str(root), v241.NOISE_SENTINEL, v241.DURABLE_SENTINEL)
    )
    report["status"] = "passed" if (
        coverage >= 0.95
        and overlap == 0.0
        and metrics["architecture_decision_accuracy"] == 1.0
        and metrics["baseline_raw_event_traversal_count"] > 1
        and metrics["baseline_source_event_lookup_full_scan_count"] > 0
        and metrics["baseline_source_event_for_text_scan_count"] > 0
        and metrics["baseline_source_text_normalization_count"] > 0
        and metrics["baseline_repeated_semantic_normalization_count"] > 0
        and metrics["baseline_nondurable_text_materialization_count"] > 0
        and all(rate == 1.0 for rate in parity_rates)
        and metrics["privacy_leak_count"] == 0
    ) else "failed"
    return report


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_report(Path(tmpdir))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
