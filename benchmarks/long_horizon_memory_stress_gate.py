#!/usr/bin/env python3
"""Gate bounded long-horizon packaged memory behavior.

The gate creates a clean packaged archive, ingests exactly 240 synthetic
session records in six monthly epochs, and scores only aggregate structure and
deployment context packages. It never uses free-form search output as an
answerability source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import updater_induction_benchmark as induction  # noqa: E402
from using_my_precious_runtime_gate import documented_runtime_decision  # noqa: E402


REPORT_KIND = "long_horizon_memory_stress_gate"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
SEED = 228
EPOCH_COUNT = 6
EVENTS_PER_EPOCH = 40
EVENT_COUNT = EPOCH_COUNT * EVENTS_PER_EPOCH

CROSS_PROJECT_TEXT = (
    "V228 cross project recall policy preserves evidence refs across monthly archive updates."
)
PARAPHRASE_ALPHA = "V228 induction summaries preserve evidence refs across archive updates."
PARAPHRASE_BETA = "V228 induction summaries keep evidence references across archive updates."
UPDATE_OLD = (
    "V228 rolling retention legacyquarteronly policy keeps quarterly archive routing enabled."
)
UPDATE_CURRENT_ONE = (
    "V228 rolling retention currentmonthonly policy keeps monthly archive routing enabled."
)
UPDATE_CURRENT_TWO = (
    "V228 rolling retention finalweekonly policy keeps weekly archive routing enabled."
)
CONFLICT_OLD = (
    "The user prefers V228 governed recall summaries to include legacyincludeonly raw source refs before conclusions."
)
CONFLICT_CURRENT = (
    "The user prefers V228 governed recall summaries to exclude currentexcludeonly raw source refs before conclusions."
)
DEPRECATION_OLD = "V228 deprecated export policy keeps unrestricted raw archive previews enabled."
DEPRECATION_MARKER = f"Deprecated fact: {DEPRECATION_OLD}"
EXPLICIT_TEXT = "V228 explicit long horizon memory remains sticky and evidence bound."

NO_HIT_QUERY = "v228absent quasarjunction nonexisting memory"
NOISE_QUERY = "v228process checked failing tests archive routing"
LEAK_MARKERS = (
    CROSS_PROJECT_TEXT,
    PARAPHRASE_ALPHA,
    PARAPHRASE_BETA,
    UPDATE_OLD,
    UPDATE_CURRENT_ONE,
    UPDATE_CURRENT_TWO,
    CONFLICT_OLD,
    CONFLICT_CURRENT,
    DEPRECATION_OLD,
    EXPLICIT_TEXT,
    "v228noise",
    "v228process",
)
LEAK_PATTERNS = (
    re.compile(r'"memory_id"\s*:'),
    re.compile(r'"query"\s*:'),
    re.compile(r'"raw_refs"\s*:'),
    re.compile(r'"source_ref_id"\s*:'),
    re.compile(r"\bmem_[0-9a-f]{8,}\b"),
    re.compile(r"\bv228-e\d{2}-\d{3}\b"),
    re.compile(r"sessions/\d{4}/"),
    re.compile(r"source-records/"),
    re.compile(r"(?:/Users/|/private/var/|/tmp/)"),
)


@dataclass(frozen=True)
class Partition:
    key: str
    project_name: str
    project_path_key: str
    archive_scope: str
    source_partition: str
    non_project_stream: bool = False


@dataclass(frozen=True)
class SpecialEvent:
    partition_key: str
    content: str
    role: str = "assistant"


@dataclass(frozen=True)
class SourceRecord:
    record_id: str
    epoch: int
    partition: Partition
    updated_at: str
    role: str
    content: str
    noise_marker: str = ""


@dataclass(frozen=True)
class CheckpointCase:
    case_id: str
    epoch: int
    query: str
    expected_action: str
    expected_text: str = ""
    stale_text: str = ""
    require_stale_memory_record: bool = True


@dataclass(frozen=True)
class CheckpointResult:
    case_id: str
    expected_action: str
    actual_action: str
    expected_memory_found: bool
    stale_memory_suppressed: bool
    session_drilldown: bool
    evidence_drilldown: bool
    source_ref_reachable: bool
    package_parse_success: bool


@dataclass
class GateState:
    root: Path
    memory_repo: Path
    partitions: list[Partition]
    records: list[SourceRecord]
    update_command_count: int = 0
    update_success_count: int = 0
    consolidation_epoch_count: int = 0
    explicit_capture_seen: bool = False
    conflict_resolution_applied: bool = False
    idempotent_replay_passed: bool = False


def ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def project_partitions() -> list[Partition]:
    return [
        Partition(
            key=f"project-{index:02d}",
            project_name=f"synthetic-v228-project-{index:02d}",
            project_path_key=f"projects/p{index:02d}",
            archive_scope=f"domain:v228:d{index % 3}",
            source_partition=f"project:v228:p{index:02d}",
        )
        for index in range(12)
    ]


def non_project_partitions() -> list[Partition]:
    return [
        Partition(
            key=f"stream-{index:02d}",
            project_name=f"synthetic-v228-source-stream-{index:02d}",
            project_path_key="runtime/non-project-source-streams",
            archive_scope=f"domain:v228:d{index + 1}",
            source_partition=f"stream:v228:s{index:02d}",
            non_project_stream=True,
        )
        for index in range(2)
    ]


def all_partitions() -> list[Partition]:
    return [*project_partitions(), *non_project_partitions()]


def special_events() -> dict[int, list[SpecialEvent]]:
    events = {
        0: [
            SpecialEvent("project-00", f"Reusable fact: {CROSS_PROJECT_TEXT}"),
            SpecialEvent("project-01", PARAPHRASE_ALPHA),
            SpecialEvent("project-02", f"Reusable fact: {UPDATE_OLD}"),
            SpecialEvent("project-03", f"Reusable fact: {DEPRECATION_OLD}"),
            SpecialEvent(
                "project-04",
                "I prefer V228 governed recall summaries to include legacyincludeonly raw source refs before conclusions.",
                role="user",
            ),
            SpecialEvent("project-05", f"Please remember: {EXPLICIT_TEXT}", role="user"),
        ],
        1: [
            SpecialEvent("project-03", f"Reusable fact: {CROSS_PROJECT_TEXT}"),
            SpecialEvent("project-04", PARAPHRASE_BETA),
            SpecialEvent(
                "project-07",
                "I prefer V228 governed recall summaries to exclude currentexcludeonly raw source refs before conclusions.",
                role="user",
            ),
        ],
        2: [
            SpecialEvent(
                "project-05",
                f"Reusable fact: Updated fact: {UPDATE_OLD} => {UPDATE_CURRENT_ONE}",
            ),
            SpecialEvent("project-06", f"Reusable fact: {CROSS_PROJECT_TEXT}"),
        ],
        3: [
            SpecialEvent("project-09", f"Reusable fact: {DEPRECATION_MARKER}"),
            SpecialEvent("project-00", f"Reusable fact: {CROSS_PROJECT_TEXT}"),
        ],
        4: [
            SpecialEvent(
                "project-08",
                f"Reusable fact: Updated fact: {UPDATE_CURRENT_ONE} => {UPDATE_CURRENT_TWO}",
            ),
            SpecialEvent("project-10", PARAPHRASE_BETA),
        ],
        5: [
            SpecialEvent("project-03", f"Reusable fact: {CROSS_PROJECT_TEXT}"),
            SpecialEvent("project-01", PARAPHRASE_ALPHA),
        ],
    }
    extra_cross_project_partitions = {
        0: ("project-03", "project-06", "project-09"),
        1: ("project-00", "project-06", "project-09"),
        2: ("project-00", "project-03", "project-09"),
        3: ("project-03", "project-06", "project-09"),
        4: ("project-00", "project-03", "project-06", "project-09"),
        5: ("project-00", "project-06", "project-09"),
    }
    for epoch, partition_keys in extra_cross_project_partitions.items():
        events[epoch].extend(
            SpecialEvent(partition_key, f"Reusable fact: {CROSS_PROJECT_TEXT}")
            for partition_key in partition_keys
        )
    return events


def noise_content(marker: str) -> str:
    if marker.startswith("v228process"):
        return (
            "I checked the failing tests for synthetic V228 archive routing "
            f"{marker} and will now inspect the session index."
        )
    return (
        "For this local dry run, the temporary V228 archive evidence routing "
        f"choice {marker} must stay in the scratch workspace."
    )


def make_record(
    *,
    epoch: int,
    index: int,
    partition: Partition,
    role: str,
    content: str,
    noise_marker: str = "",
) -> SourceRecord:
    stamp = datetime(2026, epoch + 1, 10, tzinfo=UTC) + timedelta(minutes=index)
    return SourceRecord(
        record_id=f"v228-e{epoch:02d}-{index:03d}",
        epoch=epoch,
        partition=partition,
        updated_at=stamp.isoformat().replace("+00:00", "Z"),
        role=role,
        content=content,
        noise_marker=noise_marker,
    )


def build_workload() -> tuple[list[Partition], list[SourceRecord]]:
    partitions = all_partitions()
    partitions_by_key = {partition.key: partition for partition in partitions}
    rng = random.Random(SEED)
    records: list[SourceRecord] = []
    for epoch in range(EPOCH_COUNT):
        epoch_records: list[SourceRecord] = []
        covered: set[str] = set()
        for event in special_events().get(epoch, []):
            partition = partitions_by_key[event.partition_key]
            epoch_records.append(
                make_record(
                    epoch=epoch,
                    index=len(epoch_records),
                    partition=partition,
                    role=event.role,
                    content=event.content,
                )
            )
            covered.add(partition.key)
        for partition in partitions:
            if partition.key in covered:
                continue
            prefix = "v228process" if len(epoch_records) % 2 == 0 else "v228noise"
            marker = f"{prefix}-e{epoch:02d}-{len(epoch_records):03d}"
            epoch_records.append(
                make_record(
                    epoch=epoch,
                    index=len(epoch_records),
                    partition=partition,
                    role="assistant",
                    content=noise_content(marker),
                    noise_marker=marker,
                )
            )
        cycle = list(partitions)
        rng.shuffle(cycle)
        while len(epoch_records) < EVENTS_PER_EPOCH:
            partition = cycle[len(epoch_records) % len(cycle)]
            prefix = "v228process" if len(epoch_records) % 2 == 0 else "v228noise"
            marker = f"{prefix}-e{epoch:02d}-{len(epoch_records):03d}"
            epoch_records.append(
                make_record(
                    epoch=epoch,
                    index=len(epoch_records),
                    partition=partition,
                    role="assistant",
                    content=noise_content(marker),
                    noise_marker=marker,
                )
            )
        records.extend(epoch_records)
    if len(records) != EVENT_COUNT:
        raise RuntimeError("long-horizon workload event count drifted")
    if any(sum(record.epoch == epoch for record in records) != EVENTS_PER_EPOCH for epoch in range(EPOCH_COUNT)):
        raise RuntimeError("long-horizon epoch distribution drifted")
    if sum(not partition.non_project_stream for partition in partitions) != 12:
        raise RuntimeError("long-horizon project context count drifted")
    if sum(partition.non_project_stream for partition in partitions) != 2:
        raise RuntimeError("long-horizon source stream count drifted")
    if len({partition.archive_scope for partition in partitions}) != 3:
        raise RuntimeError("long-horizon domain count drifted")
    return partitions, records


def checkpoint_cases() -> list[CheckpointCase]:
    return [
        CheckpointCase("e0-explicit", 0, EXPLICIT_TEXT, "answer", EXPLICIT_TEXT),
        CheckpointCase("e0-update-old", 0, UPDATE_OLD, "answer", UPDATE_OLD),
        CheckpointCase("e0-no-hit", 0, NO_HIT_QUERY, "abstain"),
        CheckpointCase("e1-cross-project", 1, CROSS_PROJECT_TEXT, "answer", CROSS_PROJECT_TEXT),
        CheckpointCase("e1-paraphrase", 1, PARAPHRASE_ALPHA, "answer", PARAPHRASE_BETA),
        CheckpointCase("e1-unresolved-conflict", 1, CONFLICT_CURRENT, "abstain"),
        CheckpointCase("e2-update-current", 2, UPDATE_CURRENT_ONE, "answer", UPDATE_CURRENT_ONE),
        CheckpointCase(
            "e2-update-old-stale",
            2,
            "legacyquarteronly quarterly",
            "abstain",
            stale_text=UPDATE_OLD,
        ),
        CheckpointCase("e2-explicit", 2, EXPLICIT_TEXT, "answer", EXPLICIT_TEXT),
        CheckpointCase("e3-deprecated", 3, DEPRECATION_OLD, "abstain", stale_text=DEPRECATION_OLD),
        CheckpointCase("e5-cross-project", 5, CROSS_PROJECT_TEXT, "answer", CROSS_PROJECT_TEXT),
        CheckpointCase("e3-noise", 3, NOISE_QUERY, "abstain"),
        CheckpointCase("e4-update-current", 4, UPDATE_CURRENT_TWO, "answer", UPDATE_CURRENT_TWO),
        CheckpointCase(
            "e4-resolved-conflict",
            4,
            (
                "What is my V228 governed recall summary preference for raw "
                "source refs before conclusions?"
            ),
            "abstain",
            CONFLICT_CURRENT,
        ),
        CheckpointCase(
            "e4-resolved-conflict-old",
            4,
            "legacyincludeonly include",
            "abstain",
            stale_text=CONFLICT_OLD,
            require_stale_memory_record=False,
        ),
        CheckpointCase(
            "e5-prior-current-stale",
            5,
            "currentmonthonly monthly",
            "abstain",
            stale_text=UPDATE_CURRENT_ONE,
        ),
    ]


def run_command(command: list[str], *, cwd: Path | None = None) -> induction.CommandResult:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return induction.CommandResult(result.returncode, result.stdout, result.stderr)


def setup_state(root: Path) -> GateState:
    memory_repo = root / "synthetic-memory-archive"
    result = run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError("packaged archive setup failed")
    required_tools = (
        "update_memory_archive.py",
        "memory_consolidation.py",
        "search_memory.py",
    )
    if not all((memory_repo / "tools" / name).is_file() for name in required_tools):
        raise RuntimeError("packaged archive runtime tool missing")
    partitions, records = build_workload()
    return GateState(root, memory_repo, partitions, records)


def source_dir(state: GateState, partition: Partition) -> Path:
    return state.root / "source-records" / partition.key


def project_path(state: GateState, partition: Partition) -> Path:
    return state.root / partition.project_path_key


def write_source_record(state: GateState, record: SourceRecord) -> None:
    directory = source_dir(state, record.partition)
    directory.mkdir(parents=True, exist_ok=True)
    project_path(state, record.partition).mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.record_id}.jsonl"
    events = [{"role": record.role, "content": record.content}]
    if record.noise_marker:
        events.insert(
            0,
            {
                "role": "user",
                "content": (
                    "Can the isolated synthetic fixture sample "
                    f"{record.noise_marker} be inspected for this one run?"
                ),
            },
        )
    path.write_text(
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    epoch = induction.timestamp_to_epoch(record.updated_at)
    os.utime(path, (epoch, epoch))


def run_partition_update(
    state: GateState,
    partition: Partition,
    *,
    count_ingest: bool = True,
) -> induction.CommandResult:
    result = run_command(
        [
            sys.executable,
            str(state.memory_repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(state.memory_repo),
            "--source-dir",
            str(source_dir(state, partition)),
            "--project-path",
            str(project_path(state, partition)),
            "--archive-scope",
            partition.archive_scope,
            "--source-partition",
            partition.source_partition,
            "--project",
            partition.project_name,
            "--source-agent",
            "synthetic-v228-agent",
        ],
        cwd=state.memory_repo,
    )
    if count_ingest:
        state.update_command_count += 1
        state.update_success_count += int(result.returncode == 0)
    return result


def find_conflict_review_candidate(memory_repo: Path) -> dict[str, Any] | None:
    wanted_hash = induction.natural_candidate_text_sha256(CONFLICT_CURRENT)
    for candidate in induction.load_jsonl(memory_repo / "index/induction_review_candidates.jsonl"):
        if (
            candidate.get("candidate_text_sha256") == wanted_hash
            and candidate.get("reason") == "conflicting_natural_induction_requires_review"
        ):
            return candidate
    return None


def write_conflict_resolution_decision(state: GateState) -> bool:
    candidate = find_conflict_review_candidate(state.memory_repo)
    if candidate is None:
        return False
    decision = {
        "decision_id": "v228_long_horizon_conflict_resolution",
        "action": "approve_promote",
        "candidate_id": candidate["candidate_id"],
        "candidate_text_sha256": candidate["candidate_text_sha256"],
        "candidate_fingerprint": induction.induction_review_candidate_fingerprint(candidate),
        "reviewed_at": "2026-05-01T00:00:00Z",
        "reviewer": "synthetic-v228",
        "rationale": "Synthetic bounded conflict resolution checkpoint.",
    }
    path = state.memory_repo / "reviews/induction_review_decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8")
    return True


def conflict_resolution_reflected(memory_repo: Path) -> bool:
    wanted_hash = induction.natural_candidate_text_sha256(CONFLICT_CURRENT)
    return any(
        row.get("candidate_text_sha256") == wanted_hash
        and row.get("action") == "approve_promote"
        and row.get("status") == "applied"
        for row in induction.load_jsonl(memory_repo / "index/induction_review_decision_results.jsonl")
    )


def text_key(value: object) -> str:
    return " ".join(str(value or "").split()).strip().lower().rstrip(" .!?;:")


def node_by_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    wanted = text_key(text)
    return next((node for node in nodes if text_key(node.get("text")) == wanted), None)


def memory_id_for_text(memory_repo: Path, text: str) -> str:
    node = node_by_text(induction.load_nodes(memory_repo), text)
    memory_id = node.get("memory_id") if isinstance(node, dict) else None
    return memory_id if isinstance(memory_id, str) else ""


def run_context_package(
    state: GateState,
    query: str,
    depth: str,
) -> tuple[str, dict[str, Any] | None, bool]:
    result = run_command(
        [
            sys.executable,
            str(state.memory_repo / "tools/search_memory.py"),
            query,
            "--repo",
            str(state.memory_repo),
            "--limit",
            "5",
            "--depth",
            depth,
            "--context-json",
        ],
        cwd=state.memory_repo,
    )
    if result.returncode != 0:
        return result.stdout, None, False
    try:
        package = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout, None, False
    valid = isinstance(package, dict) and package.get("report_kind") == CONTEXT_REPORT_KIND
    return result.stdout, package if isinstance(package, dict) else None, valid


def package_hit(package: dict[str, Any] | None, memory_id: str) -> dict[str, Any] | None:
    if not package or not memory_id:
        return None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return None
    return next(
        (
            hit
            for hit in hits[:5]
            if isinstance(hit, dict) and hit.get("memory_id") == memory_id
        ),
        None,
    )


def source_ref_available(hit: dict[str, Any] | None) -> bool:
    refs = hit.get("source_refs") if isinstance(hit, dict) else None
    return bool(
        isinstance(refs, list)
        and any(isinstance(ref, dict) and ref.get("status") == "available" for ref in refs)
    )


def score_checkpoint(state: GateState, case: CheckpointCase) -> CheckpointResult:
    expected_memory_id = memory_id_for_text(state.memory_repo, case.expected_text)
    stale_memory_id = memory_id_for_text(state.memory_repo, case.stale_text)
    evidence_raw, evidence_package, evidence_valid = run_context_package(
        state,
        case.query,
        "evidence",
    )
    decision = documented_runtime_decision(evidence_raw)
    evidence_hit = package_hit(evidence_package, expected_memory_id)
    stale_hit = package_hit(evidence_package, stale_memory_id)

    session_drilldown = True
    evidence_drilldown = True
    source_reachable = True
    package_parse_success = evidence_valid and decision.parse_success
    if case.expected_action == "answer":
        _, session_package, session_valid = run_context_package(state, case.query, "session")
        _, memory_package, memory_valid = run_context_package(state, case.query, "memory")
        _, source_package, source_valid = run_context_package(state, case.query, "source")
        session_hit = package_hit(session_package, expected_memory_id)
        memory_hit = package_hit(memory_package, expected_memory_id)
        source_hit = package_hit(source_package, expected_memory_id)
        session_drilldown = bool(session_hit and session_hit.get("summary_drill_paths"))
        evidence_drilldown = bool(evidence_hit and evidence_hit.get("evidence_drill_paths"))
        source_reachable = source_ref_available(source_hit)
        package_parse_success = bool(
            package_parse_success and session_valid and memory_valid and source_valid and memory_hit
        )

    return CheckpointResult(
        case_id=case.case_id,
        expected_action=case.expected_action,
        actual_action=decision.action,
        expected_memory_found=evidence_hit is not None,
        stale_memory_suppressed=not case.stale_text
        or bool(
            (stale_memory_id or not case.require_stale_memory_record)
            and stale_hit is None
            and decision.action == "abstain"
        ),
        session_drilldown=session_drilldown,
        evidence_drilldown=evidence_drilldown,
        source_ref_reachable=source_reachable,
        package_parse_success=package_parse_success,
    )


def run_epoch(
    state: GateState,
    epoch: int,
    cases: list[CheckpointCase],
) -> list[CheckpointResult]:
    trace_path = state.memory_repo / "index/memory_consolidation_trace.jsonl"
    trace_before = file_digest(trace_path)
    epoch_records = [record for record in state.records if record.epoch == epoch]
    for record in epoch_records:
        write_source_record(state, record)
    if epoch == 4 and not write_conflict_resolution_decision(state):
        state.conflict_resolution_applied = False
    update_results = [run_partition_update(state, partition) for partition in state.partitions]
    if (
        all(result.returncode == 0 for result in update_results)
        and trace_path.is_file()
        and file_digest(trace_path) != trace_before
    ):
        state.consolidation_epoch_count += 1
    if epoch == 0:
        explicit = node_by_text(induction.load_nodes(state.memory_repo), EXPLICIT_TEXT)
        state.explicit_capture_seen = bool(
            explicit
            and explicit.get("source") == "explicit"
            and explicit.get("persistence") == "sticky"
        )
    if epoch == 4:
        state.conflict_resolution_applied = conflict_resolution_reflected(state.memory_repo)
    return [score_checkpoint(state, case) for case in cases if case.epoch == epoch]


def file_digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_archive_paths(memory_repo: Path) -> list[Path]:
    paths = [memory_repo / "INDEX.md"]
    for relative in ("index", "memories", "reviews", "daily", "sessions"):
        root = memory_repo / relative
        if root.is_dir():
            paths.extend(
                path for path in root.rglob("*") if path.is_file() and not path.is_symlink()
            )
    return sorted(set(paths), key=lambda path: path.relative_to(memory_repo).as_posix())


def archive_semantic_digest(memory_repo: Path) -> str:
    digest = hashlib.sha256()
    for path in generated_archive_paths(memory_repo):
        relative = path.relative_to(memory_repo).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def replay_last_epoch(state: GateState) -> None:
    before = archive_semantic_digest(state.memory_repo)
    before_sessions = len(induction.load_jsonl(state.memory_repo / "index/sessions.jsonl"))
    replay_results = [
        run_partition_update(state, partition, count_ingest=False)
        for partition in state.partitions
    ]
    after = archive_semantic_digest(state.memory_repo)
    after_sessions = len(induction.load_jsonl(state.memory_repo / "index/sessions.jsonl"))
    state.idempotent_replay_passed = bool(
        all(result.returncode == 0 for result in replay_results)
        and before == after
        and before_sessions == EVENT_COUNT
        and after_sessions == EVENT_COUNT
    )


def string_items(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return [value] if isinstance(value, str) and value else []


def node_memory_id(node: dict[str, Any] | None) -> str:
    memory_id = node.get("memory_id") if isinstance(node, dict) else None
    return memory_id if isinstance(memory_id, str) else ""


def active_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inactive_ids: set[str] = set()
    for node in nodes:
        inactive_ids.update(string_items(node.get("supersedes")))
        inactive_ids.update(string_items(node.get("contradicts")))
        inactive_ids.update(string_items(node.get("deprecates")))
        if string_items(node.get("deprecates")):
            memory_id = node_memory_id(node)
            if memory_id:
                inactive_ids.add(memory_id)
        for key in ("superseded_by", "deprecated_by"):
            if string_items(node.get(key)):
                memory_id = node_memory_id(node)
                if memory_id:
                    inactive_ids.add(memory_id)
        if string_items(node.get("contradicted_by")):
            memory_id = node_memory_id(node)
            if memory_id:
                inactive_ids.add(memory_id)
    return [node for node in nodes if node_memory_id(node) not in inactive_ids]


def active_nodes_matching(nodes: list[dict[str, Any]], texts: set[str]) -> list[dict[str, Any]]:
    wanted = {text_key(text) for text in texts}
    return [node for node in active_nodes(nodes) if text_key(node.get("text")) in wanted]


def duplicate_active_memory_count(nodes: list[dict[str, Any]]) -> int:
    groups = (
        ({CROSS_PROJECT_TEXT}, 1),
        ({PARAPHRASE_ALPHA, PARAPHRASE_BETA}, 1),
        ({UPDATE_OLD, UPDATE_CURRENT_ONE, UPDATE_CURRENT_TWO}, 1),
        ({CONFLICT_OLD, CONFLICT_CURRENT}, 1),
        ({DEPRECATION_OLD, DEPRECATION_MARKER}, 0),
        ({EXPLICIT_TEXT}, 1),
    )
    return sum(max(0, len(active_nodes_matching(nodes, texts)) - maximum) for texts, maximum in groups)


def unexpected_active_memory_count(nodes: list[dict[str, Any]]) -> int:
    allowed = {
        CROSS_PROJECT_TEXT,
        PARAPHRASE_ALPHA,
        PARAPHRASE_BETA,
        UPDATE_CURRENT_TWO,
        CONFLICT_CURRENT,
        EXPLICIT_TEXT,
    }
    allowed_keys = {text_key(text) for text in allowed}
    return sum(1 for node in active_nodes(nodes) if text_key(node.get("text")) not in allowed_keys)


def support_ref_count(node: dict[str, Any] | None, key: str) -> int:
    value = node.get(key) if isinstance(node, dict) else None
    return len(value) if isinstance(value, list) else 0


def cross_project_generalization_pass(nodes: list[dict[str, Any]]) -> bool:
    node = node_by_text(nodes, CROSS_PROJECT_TEXT)
    return bool(
        node
        and node.get("layer") == "domain"
        and int(node.get("support_count") or 0) >= 24
        and support_ref_count(node, "derived_from") >= 24
        and support_ref_count(node, "evidence_refs") >= 24
    )


def paraphrase_consolidation_pass(nodes: list[dict[str, Any]]) -> bool:
    matches = active_nodes_matching(nodes, {PARAPHRASE_ALPHA, PARAPHRASE_BETA})
    return bool(
        len(matches) == 1
        and matches[0].get("layer") == "domain"
        and int(matches[0].get("support_count") or 0) >= 4
        and support_ref_count(matches[0], "derived_from") >= 4
        and support_ref_count(matches[0], "evidence_refs") >= 4
    )


def explicit_memory_survival_pass(nodes: list[dict[str, Any]]) -> bool:
    node = node_by_text(active_nodes(nodes), EXPLICIT_TEXT)
    return bool(
        node
        and node.get("source") == "explicit"
        and node.get("layer") == "global"
        and node.get("persistence") == "sticky"
        and support_ref_count(node, "derived_from") >= 1
        and support_ref_count(node, "evidence_refs") >= 1
        and support_ref_count(node, "raw_refs") >= 1
    )


def relation_reciprocal(
    nodes: list[dict[str, Any]],
    current_text: str,
    target_text: str,
    relation: str,
    reciprocal: str,
) -> bool:
    current = node_by_text(nodes, current_text)
    target = node_by_text(nodes, target_text)
    current_id = node_memory_id(current)
    target_id = node_memory_id(target)
    return bool(
        current_id
        and target_id
        and target_id in string_items(current.get(relation) if current else None)
        and current_id in string_items(target.get(reciprocal) if target else None)
    )


def lifecycle_reciprocity_rate(nodes: list[dict[str, Any]]) -> float:
    checks = (
        relation_reciprocal(
            nodes,
            UPDATE_CURRENT_TWO,
            UPDATE_OLD,
            "supersedes",
            "superseded_by",
        ),
        relation_reciprocal(
            nodes,
            UPDATE_CURRENT_TWO,
            UPDATE_CURRENT_ONE,
            "supersedes",
            "superseded_by",
        ),
        relation_reciprocal(
            nodes,
            DEPRECATION_MARKER,
            DEPRECATION_OLD,
            "deprecates",
            "deprecated_by",
        ),
    )
    return ratio(sum(checks), len(checks))


def archive_relative_file_exists(memory_repo: Path, value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "~")):
        return False
    path = (memory_repo / value).resolve()
    try:
        path.relative_to(memory_repo.resolve())
    except ValueError:
        return False
    return path.is_file()


def index_parity_pass(memory_repo: Path, partitions: list[Partition]) -> bool:
    meta_rows = induction.load_meta_rows(memory_repo)
    session_rows = induction.load_jsonl(memory_repo / "index/sessions.jsonl")
    file_rows = induction.load_jsonl(memory_repo / "index/files.jsonl")
    scope_rows = induction.load_jsonl(memory_repo / "index/scopes.jsonl")
    partition_rows = induction.load_jsonl(memory_repo / "index/source_partitions.jsonl")
    session_ids = [str(row.get("session_id") or "") for row in session_rows]
    source_records = [str(row.get("source_record") or "") for row in session_rows]
    meta_session_ids = [str(row.get("session_id") or "") for row in meta_rows]
    meta_source_records = [str(row.get("source_record") or "") for row in meta_rows]
    file_session_ids = [str(row.get("session_id") or "") for row in file_rows]
    file_source_records = [str(row.get("path") or "") for row in file_rows]
    actual_scopes = {str(row.get("archive_scope") or "") for row in scope_rows}
    expected_scopes = {partition.archive_scope for partition in partitions}
    actual_partitions = {
        (str(row.get("archive_scope") or ""), str(row.get("source_partition") or ""))
        for row in partition_rows
    }
    expected_partitions = {
        (partition.archive_scope, partition.source_partition) for partition in partitions
    }
    support_paths_exist = all(
        archive_relative_file_exists(memory_repo, row.get("summary_path"))
        and archive_relative_file_exists(memory_repo, row.get("evidence_path"))
        and archive_relative_file_exists(memory_repo, row.get("source_map_path"))
        for row in session_rows
    )
    return bool(
        len(meta_rows) == EVENT_COUNT
        and len(session_rows) == EVENT_COUNT
        and len(file_rows) == EVENT_COUNT
        and all(session_ids)
        and all(source_records)
        and all(meta_session_ids)
        and all(meta_source_records)
        and all(file_session_ids)
        and all(file_source_records)
        and len(session_ids) == len(set(session_ids))
        and len(source_records) == len(set(source_records))
        and set(meta_session_ids) == set(session_ids) == set(file_session_ids)
        and set(meta_source_records) == set(source_records) == set(file_source_records)
        and len(scope_rows) == len(expected_scopes)
        and len(partition_rows) == len(expected_partitions)
        and actual_scopes == expected_scopes
        and actual_partitions == expected_partitions
        and support_paths_exist
    )


def build_report(
    state: GateState,
    checkpoint_results: list[CheckpointResult],
    runtime_seconds: float,
) -> dict[str, Any]:
    nodes = induction.load_nodes(state.memory_repo)
    sessions = induction.load_jsonl(state.memory_repo / "index/sessions.jsonl")
    answer_results = [result for result in checkpoint_results if result.expected_action == "answer"]
    abstain_results = [result for result in checkpoint_results if result.expected_action == "abstain"]
    stale_case_ids = {case.case_id for case in checkpoint_cases() if case.stale_text}
    stale_results = [result for result in checkpoint_results if result.case_id in stale_case_ids]
    noise_markers = [record.noise_marker for record in state.records if record.noise_marker]
    node_text = "\n".join(str(node.get("text") or "") for node in nodes).lower()
    noise_rejections = sum(marker.lower() not in node_text for marker in noise_markers)
    ingest_count = len({str(row.get("session_id") or "") for row in sessions})
    all_actions_correct = sum(
        result.actual_action == result.expected_action for result in checkpoint_results
    )
    parse_successes = sum(result.package_parse_success for result in checkpoint_results)
    duplicate_count = duplicate_active_memory_count(nodes)
    unexpected_count = unexpected_active_memory_count(nodes)

    metrics: dict[str, int | float] = {
        "long_horizon_ingest_success_rate": ratio(
            ingest_count if state.update_success_count == state.update_command_count else 0,
            EVENT_COUNT,
        ),
        "long_horizon_checkpoint_answer_accuracy": ratio(
            all_actions_correct,
            len(checkpoint_results),
        ),
        "long_horizon_abstention_accuracy": ratio(
            sum(result.actual_action == "abstain" for result in abstain_results),
            len(abstain_results),
        ),
        "long_horizon_active_current_recall_at_5": ratio(
            sum(result.expected_memory_found for result in answer_results),
            len(answer_results),
        ),
        "long_horizon_stale_suppression_rate": ratio(
            sum(result.stale_memory_suppressed for result in stale_results),
            len(stale_results),
        ),
        "long_horizon_cross_project_generalization_rate": float(
            cross_project_generalization_pass(nodes)
        ),
        "long_horizon_paraphrase_consolidation_rate": float(
            paraphrase_consolidation_pass(nodes)
        ),
        "long_horizon_noise_rejection_rate": ratio(noise_rejections, len(noise_markers)),
        "long_horizon_explicit_memory_survival_rate": float(
            explicit_memory_survival_pass(nodes)
        ),
        "long_horizon_idempotent_replay_rate": float(state.idempotent_replay_passed),
        "long_horizon_session_drilldown_rate": ratio(
            sum(result.session_drilldown for result in answer_results),
            len(answer_results),
        ),
        "long_horizon_evidence_drilldown_rate": ratio(
            sum(result.evidence_drilldown for result in answer_results),
            len(answer_results),
        ),
        "long_horizon_source_ref_reachability_rate": ratio(
            sum(result.source_ref_reachable for result in answer_results),
            len(answer_results),
        ),
        "long_horizon_lifecycle_reciprocity_rate": lifecycle_reciprocity_rate(nodes),
        "long_horizon_index_parity_rate": float(index_parity_pass(state.memory_repo, state.partitions)),
        "long_horizon_context_package_parse_success_rate": ratio(
            parse_successes,
            len(checkpoint_results),
        ),
        "duplicate_active_memory_count": duplicate_count,
        "unexpected_active_memory_count": unexpected_count,
        "privacy_leak_count": 0,
        "runtime_seconds": round(runtime_seconds, 6),
    }
    rate_metrics = [
        key
        for key in metrics
        if key.startswith("long_horizon_") and key != "long_horizon_runtime_seconds"
    ]
    passed = bool(
        len(checkpoint_results) == 16
        and len(answer_results) == 8
        and len(abstain_results) == 8
        and all(float(metrics[key]) == 1.0 for key in rate_metrics)
        and duplicate_count == 0
        and unexpected_count == 0
        and state.consolidation_epoch_count == EPOCH_COUNT
        and state.update_command_count == EPOCH_COUNT * len(state.partitions)
        and state.explicit_capture_seen
        and state.conflict_resolution_applied
        and runtime_seconds < 180.0
    )
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "context_package_report_kind": CONTEXT_REPORT_KIND,
        "claim_boundary": (
            "bounded deterministic synthetic long-horizon lifecycle evidence; "
            "not production scale, live model quality, vector retrieval, ontology discovery, "
            "multi-principal governance, or solved decay and deletion policy"
        ),
        "workload": {
            "seed": SEED,
            "event_count": EVENT_COUNT,
            "epoch_count": EPOCH_COUNT,
            "events_per_epoch": EVENTS_PER_EPOCH,
            "project_context_count": 12,
            "domain_count": 3,
            "non_project_source_stream_count": 2,
        },
        "pipeline": {
            "setup_invoked": True,
            "incremental_epoch_updates": state.consolidation_epoch_count,
            "automatic_induction_invoked": any(node.get("source") == "automatic" for node in nodes),
            "explicit_capture_invoked": state.explicit_capture_seen,
            "consolidation_invoked": state.consolidation_epoch_count == EPOCH_COUNT,
            "deployment_search_invoked": bool(checkpoint_results),
        },
        "checkpoint_case_count": len(checkpoint_results),
        "answer_checkpoint_count": len(answer_results),
        "abstention_checkpoint_count": len(abstain_results),
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "private_archive_records_rendered": False,
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    metrics["privacy_leak_count"] = sum(marker.lower() in rendered.lower() for marker in LEAK_MARKERS)
    metrics["privacy_leak_count"] += sum(bool(pattern.search(rendered)) for pattern in LEAK_PATTERNS)
    if metrics["privacy_leak_count"] != 0:
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, Any]:
    started = time.monotonic()
    state = setup_state(root)
    cases = checkpoint_cases()
    checkpoint_results: list[CheckpointResult] = []
    for epoch in range(EPOCH_COUNT):
        checkpoint_results.extend(run_epoch(state, epoch, cases))
    replay_last_epoch(state)
    return build_report(state, checkpoint_results, time.monotonic() - started)


def make_work_root(
    work_dir: str | None,
) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-v228-long-horizon-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-v228-long-horizon-", dir=parent))
    return root, None, root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent for temporary clean-room artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_work_root(args.work_dir)
        report = run_gate(root)
    except (OSError, RuntimeError, ValueError):
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": "gate_execution_failed",
        }
    finally:
        if temp is not None:
            temp.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
