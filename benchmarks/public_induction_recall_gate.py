#!/usr/bin/env python3
"""Measure public conversation induction provenance without ingesting gold labels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POSITIVE_QUESTION_TYPES = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "temporal-reasoning",
    "knowledge-update",
    "multi-session",
)
CONTEXT_REPORT_KIND = "memory_recall_context_package"
REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_FIXTURE = REPO_ROOT / "benchmarks/cases/public_induction_recall_fixture.json"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"LongMemEval row is missing {field}")
    return value


def _selection_key(seed: str, row: dict[str, Any]) -> tuple[str, str]:
    question_id = _text(row.get("question_id"), "question_id")
    digest = hashlib.sha256(f"{seed}\0{question_id}".encode("utf-8")).hexdigest()
    return digest, question_id


def select_longmemeval_cases(
    rows: list[object],
    *,
    seed: str,
    positive_per_type: int,
    abstention_count: int,
) -> list[dict[str, Any]]:
    if positive_per_type <= 0 or abstention_count <= 0:
        raise SystemExit("selection counts must be positive")
    objects = [row for row in rows if isinstance(row, dict)]
    if len(objects) != len(rows):
        raise SystemExit("LongMemEval input rows must be objects")

    selected: list[dict[str, Any]] = []
    for question_type in POSITIVE_QUESTION_TYPES:
        candidates = [
            row
            for row in objects
            if _text(row.get("question_id"), "question_id").endswith("_abs") is False
            and row.get("question_type") == question_type
        ]
        if len(candidates) < positive_per_type:
            raise SystemExit(f"LongMemEval input lacks positive cases for {question_type}")
        selected.extend(sorted(candidates, key=lambda row: _selection_key(seed, row))[:positive_per_type])

    abstention_candidates = [
        row for row in objects if _text(row.get("question_id"), "question_id").endswith("_abs")
    ]
    if len(abstention_candidates) < abstention_count:
        raise SystemExit("LongMemEval input lacks abstention cases")
    selected.extend(
        sorted(abstention_candidates, key=lambda row: _selection_key(seed, row))[:abstention_count]
    )
    return selected


def _session_timestamp(value: str) -> datetime:
    for pattern in ("%Y/%m/%d (%a) %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise SystemExit("unsupported LongMemEval session timestamp")


def convert_longmemeval_case(row: dict[str, Any], *, case_ordinal: int) -> dict[str, Any]:
    question_id = _text(row.get("question_id"), "question_id")
    question_type = _text(row.get("question_type"), "question_type")
    question = _text(row.get("question"), "question")
    session_ids = row.get("haystack_session_ids")
    dates = row.get("haystack_dates")
    sessions = row.get("haystack_sessions")
    answer_session_ids = row.get("answer_session_ids")
    if not all(isinstance(value, list) for value in (session_ids, dates, sessions, answer_session_ids)):
        raise SystemExit("LongMemEval row has malformed session arrays")
    if not (len(session_ids) == len(dates) == len(sessions)) or not sessions:
        raise SystemExit("LongMemEval session arrays must be non-empty and aligned")

    source_records: list[dict[str, Any]] = []
    for session_ordinal, (session_id, date, turns) in enumerate(zip(session_ids, dates, sessions), 1):
        if not isinstance(session_id, str) or not isinstance(date, str) or not isinstance(turns, list) or not turns:
            raise SystemExit("LongMemEval session is malformed")
        events: list[dict[str, str]] = []
        for turn in turns:
            if not isinstance(turn, dict):
                raise SystemExit("LongMemEval turn must be an object")
            role = turn.get("role")
            content = turn.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                raise SystemExit("LongMemEval turn has invalid role or content")
            events.append({"role": role, "content": content})
        source_records.append(
            {
                "record_id": f"session-{session_ordinal:04d}",
                "source_updated_at": date,
                "scorer_session_id": session_id,
                "events": events,
            }
        )

    case_digest = hashlib.sha256(question_id.encode("utf-8")).hexdigest()
    return {
        "case_ordinal": case_ordinal,
        "case_digest": case_digest,
        "question": question,
        "question_type": question_type,
        "is_abstention": question_id.endswith("_abs"),
        "answer_session_ids": set(str(value) for value in answer_session_ids),
        "source_records": source_records,
    }


def write_case_source_records(root: Path, case: dict[str, Any]) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    question = str(case.get("question") or "")
    question_type = str(case.get("question_type") or "")
    answer_session_ids = {str(value) for value in case.get("answer_session_ids") or set()}
    written_paths: list[Path] = []
    path_to_session_id: dict[str, str] = {}
    session_boundary_hits = 0
    role_preservation_hits = 0
    timestamp_preservation_hits = 0
    gold_label_ingestion_count = 0
    answer_ingestion_count = 0

    for record in case.get("source_records") or []:
        record_id = str(record["record_id"])
        source_dir = root / record_id
        source_dir.mkdir(parents=True, exist_ok=False)
        source_path = source_dir / "record.jsonl"
        events = record["events"]
        lines = [json.dumps({"role": event["role"], "content": event["content"]}, sort_keys=True) for event in events]
        source_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        timestamp = _session_timestamp(str(record["source_updated_at"])).timestamp()
        os.utime(source_path, (timestamp, timestamp))

        payloads = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines()]
        serialized = source_path.read_text(encoding="utf-8")
        session_boundary_hits += int(len(list(source_dir.glob("*.jsonl"))) == 1)
        role_preservation_hits += int(
            [payload.get("role") for payload in payloads] == [event["role"] for event in events]
        )
        timestamp_preservation_hits += int(abs(source_path.stat().st_mtime - timestamp) < 1.0)
        forbidden_values = [question, question_type, str(record["scorer_session_id"]), *answer_session_ids]
        gold_label_ingestion_count += int(any(value and value in serialized for value in forbidden_values))
        answer_ingestion_count += sum(int("answer" in payload or "reference_answer" in payload) for payload in payloads)
        written_paths.append(source_path)
        path_to_session_id[str(source_path.resolve())] = str(record["scorer_session_id"])

    return {
        "source_record_count": len(written_paths),
        "session_boundary_hits": session_boundary_hits,
        "role_preservation_hits": role_preservation_hits,
        "timestamp_preservation_hits": timestamp_preservation_hits,
        "public_gold_label_ingestion_count": gold_label_ingestion_count,
        "public_answer_ingestion_count": answer_ingestion_count,
        "synthetic_memory_marker_injection_count": 0,
        "direct_synthetic_archive_injection_count": int((root / "memories").exists()),
        "source_record_paths": written_paths,
        "path_to_session_id": path_to_session_id,
    }


def _supported_active_hit(hit: object) -> bool:
    if not isinstance(hit, dict) or hit.get("active_current") is not True:
        return False
    answerability = hit.get("answerability")
    query_support = hit.get("query_support")
    return bool(
        isinstance(answerability, dict)
        and answerability.get("status") == "supported"
        and isinstance(query_support, dict)
        and query_support.get("status") == "supported"
        and hit.get("summary_drill_paths")
        and hit.get("evidence_drill_paths")
    )


def context_package_decision(package: object) -> str:
    if not isinstance(package, dict) or package.get("report_kind") != CONTEXT_REPORT_KIND:
        return "abstain"
    answerability = package.get("answerability")
    hits = package.get("hits")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return "abstain"
    if not isinstance(hits, list) or not any(_supported_active_hit(hit) for hit in hits):
        return "abstain"
    return "answer"


def parse_context_package(raw: str) -> dict[str, Any] | None:
    try:
        package = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(package, dict) or package.get("report_kind") != CONTEXT_REPORT_KIND:
        return None
    return package


def supported_gold_provenance_ranks(
    package: object,
    path_to_session_id: dict[str, str],
    gold_session_ids: set[str],
) -> list[int]:
    if context_package_decision(package) != "answer" or not isinstance(package, dict):
        return []
    ranks: list[int] = []
    for rank, hit in enumerate(package.get("hits") or [], 1):
        if not _supported_active_hit(hit):
            continue
        paths: set[str] = set()
        for ref in hit.get("evidence_refs") or []:
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                paths.add(ref["path"])
            elif isinstance(ref, str):
                paths.add(ref.split("#", 1)[0])
        paths.update(path for path in hit.get("evidence_drill_paths") or [] if isinstance(path, str))
        supported_sessions = {path_to_session_id[path] for path in paths if path in path_to_session_id}
        if supported_sessions.intersection(gold_session_ids):
            ranks.append(rank)
    return ranks


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _load_search_module(path: Path):
    name = f"public_induction_search_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load packaged search module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _archive_provenance_map(
    memory_repo: Path,
    source_path_to_session_id: dict[str, str],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        source_record = meta.get("source_record")
        if not isinstance(source_record, str):
            continue
        session_id = source_path_to_session_id.get(str(Path(source_record).resolve()))
        if not session_id:
            continue
        for key in ("summary_path", "evidence_path"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                mapping[value] = session_id
    return mapping


def _session_gold_ranks(
    search_module: Any,
    memory_repo: Path,
    question: str,
    provenance_map: dict[str, str],
    gold_session_ids: set[str],
    limit: int = 5,
) -> list[int]:
    query_tokens = search_module.unique_query_tokens(question)
    hits = search_module.merge_hits(
        memory_repo,
        [
            *search_module.collect_index_hits(memory_repo, query_tokens, []),
            *search_module.collect_markdown_hits(memory_repo, query_tokens, False, []),
        ],
    )
    ranks: list[int] = []
    for rank, hit in enumerate(hits[:limit], 1):
        try:
            relative = hit.path.resolve().relative_to(memory_repo.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        if provenance_map.get(relative) in gold_session_ids:
            ranks.append(rank)
    return ranks


def _context_search(memory_repo: Path, question: str, depth: str, *, legacy: bool = False) -> dict[str, Any] | None:
    command = [
        sys.executable,
        str(memory_repo / "tools/search_memory.py"),
        question,
        "--repo",
        str(memory_repo),
        "--depth",
        depth,
        "--context-json",
        "--limit",
        "5",
    ]
    if legacy:
        command.append("--legacy-sessions")
    result = _run(command)
    if result.returncode != 0:
        return None
    return parse_context_package(result.stdout)


def _memory_activity_counts(search_module: Any, memory_repo: Path) -> tuple[int, int, int]:
    index_path = memory_repo / "index/memories.jsonl"
    records = _load_jsonl(index_path)
    supersedes = search_module.collect_supersedes_by_memory_id(records)
    contradicts = search_module.collect_contradicts_by_memory_id(records)
    deprecates = search_module.collect_deprecates_by_memory_id(records)
    inactive_ids = search_module.collect_inactive_memory_ids(
        records,
        supersedes,
        search_module.collect_forward_superseded_ids(supersedes),
        contradicts,
        search_module.collect_forward_contradicted_ids(contradicts),
        deprecates,
        search_module.collect_forward_deprecated_ids(deprecates),
    )
    active = search_module.active_memory_records_by_id(memory_repo, records, inactive_ids)
    automatic = sum(record.get("source") == "automatic" for record in records)
    return automatic, len(active), len(inactive_ids)


def supported_package_reachability(
    evidence_package: object,
    source_package: object,
    memory_repo: Path,
) -> tuple[int, int, int, int]:
    if not isinstance(evidence_package, dict) or not isinstance(source_package, dict):
        return 0, 0, 0, 0
    source_hits_by_id = {
        str(hit.get("memory_id")): hit
        for hit in source_package.get("hits") or []
        if isinstance(hit, dict) and hit.get("memory_id")
    }
    evidence_cases = evidence_hits = source_cases = source_hit_count = 0
    for hit in evidence_package.get("hits") or []:
        if not _supported_active_hit(hit):
            continue
        evidence_cases += 1
        evidence_paths: set[str] = set()
        for ref in hit.get("evidence_refs") or []:
            if isinstance(ref, str):
                evidence_paths.add(ref.split("#", 1)[0])
            elif isinstance(ref, dict) and isinstance(ref.get("path"), str):
                evidence_paths.add(ref["path"])
        evidence_hits += int(
            bool(evidence_paths)
            and all((memory_repo / path).is_file() for path in evidence_paths)
        )

        source_cases += 1
        source_hit = source_hits_by_id.get(str(hit.get("memory_id") or ""), {})
        refs = source_hit.get("source_refs") if isinstance(source_hit, dict) else None
        available = [
            ref.get("status") == "available" and ref.get("unsafe_ref") is False
            for ref in refs if isinstance(ref, dict)
        ] if isinstance(refs, list) else []
        source_hit_count += int(bool(available) and all(available))
    return evidence_cases, evidence_hits, source_cases, source_hit_count


def aggregate_privacy_leak_count(
    report: dict[str, Any],
    selected: list[dict[str, Any]],
    local_paths: list[Path],
) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = 0
    forbidden_keys = (
        "question",
        "answer",
        "question_id",
        "answer_session_ids",
        "haystack_sessions",
        "source_record",
        "memory_text",
    )
    leaks += sum(
        int(re.search(rf'"{re.escape(key)}"\s*:', rendered) is not None)
        for key in forbidden_keys
    )
    markers: set[str] = set()
    for row in selected:
        for key in ("question_id", "question", "answer"):
            value = row.get(key)
            if isinstance(value, str) and len(value) >= 8:
                markers.add(value)
        for key in ("answer_session_ids", "haystack_session_ids"):
            values = row.get(key)
            if isinstance(values, list):
                markers.update(value for value in values if isinstance(value, str) and len(value) >= 8)
        sessions = row.get("haystack_sessions")
        if isinstance(sessions, list):
            for session in sessions:
                if not isinstance(session, list):
                    continue
                for turn in session:
                    content = turn.get("content") if isinstance(turn, dict) else None
                    if isinstance(content, str) and len(content) >= 16:
                        markers.add(content)
    markers.update(str(path) for path in local_paths if str(path))
    leaks += sum(int(marker in rendered) for marker in markers)
    return leaks


def run_packaged_case(case: dict[str, Any], case_root: Path) -> dict[str, Any]:
    memory_repo = case_root / "archive"
    source_root = case_root / "source-records"
    project_path = case_root / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    setup = _run(
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
    setup_success = int(setup.returncode == 0)
    if not setup_success:
        return {"packaged_setup_success": 0, "updater_success": 0, "archive_audit_success": 0}

    ingestion = write_case_source_records(source_root, case)
    source_count = int(ingestion["source_record_count"])
    ingestion_safe = (
        ingestion["session_boundary_hits"] == source_count
        and ingestion["role_preservation_hits"] == source_count
        and ingestion["timestamp_preservation_hits"] == source_count
        and ingestion["public_gold_label_ingestion_count"] == 0
        and ingestion["public_answer_ingestion_count"] == 0
        and ingestion["synthetic_memory_marker_injection_count"] == 0
        and ingestion["direct_synthetic_archive_injection_count"] == 0
    )
    if not ingestion_safe:
        return {
            "question_type": str(case["question_type"]),
            "is_abstention": int(case["is_abstention"]),
            "packaged_setup_success": setup_success,
            "updater_success": 0,
            "archive_audit_success": 0,
            "source_record_count": source_count,
            "session_boundary_hits": ingestion["session_boundary_hits"],
            "role_preservation_hits": ingestion["role_preservation_hits"],
            "timestamp_preservation_hits": ingestion["timestamp_preservation_hits"],
            "public_gold_label_ingestion_count": ingestion["public_gold_label_ingestion_count"],
            "public_answer_ingestion_count": ingestion["public_answer_ingestion_count"],
            "synthetic_memory_marker_injection_count": ingestion["synthetic_memory_marker_injection_count"],
            "direct_synthetic_archive_injection_count": ingestion["direct_synthetic_archive_injection_count"],
            "context_package_search_count": 0,
            "context_package_parse_count": 0,
            "privacy_leak_count": 0,
        }
    updater = _run(
        [
            sys.executable,
            str(memory_repo / "tools/update_memory_archive.py"),
            "--source-dir",
            str(source_root),
            "--project-path",
            str(project_path),
            "--project",
            f"public-case-{int(case['case_ordinal']):03d}",
            "--source-agent",
            "longmemeval-public",
            "--rewrite-existing",
        ]
    )
    updater_success = int(updater.returncode == 0)
    audit = _run(
        [
            sys.executable,
            str(memory_repo / "tools/audit_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
        ]
    )
    audit_success = int(audit.returncode == 0)

    search_module = _load_search_module(memory_repo / "tools/search_memory.py")
    provenance_map = _archive_provenance_map(memory_repo, ingestion["path_to_session_id"])
    question = str(case["question"])
    gold_session_ids = set(case["answer_session_ids"])
    session_package = _context_search(memory_repo, question, "session", legacy=True)
    evidence_package = _context_search(memory_repo, question, "evidence")
    source_package = _context_search(memory_repo, question, "source")
    parse_count = sum(
        int(package is not None)
        for package in (session_package, evidence_package, source_package)
    )
    baseline_ranks = _session_gold_ranks(
        search_module,
        memory_repo,
        question,
        provenance_map,
        gold_session_ids,
    )
    gold_ranks = supported_gold_provenance_ranks(
        evidence_package,
        provenance_map,
        gold_session_ids,
    )
    automatic_count, active_count, inactive_count = _memory_activity_counts(search_module, memory_repo)
    evidence_cases, evidence_hits, source_cases, source_hits = supported_package_reachability(
        evidence_package,
        source_package,
        memory_repo,
    )
    review_count = len(_load_jsonl(memory_repo / "index/induction_review_candidates.jsonl"))
    evidence_decision = context_package_decision(evidence_package)
    result = {
        "question_type": str(case["question_type"]),
        "is_abstention": int(case["is_abstention"]),
        "packaged_setup_success": setup_success,
        "updater_success": updater_success,
        "archive_audit_success": audit_success,
        "source_record_count": ingestion["source_record_count"],
        "session_boundary_hits": ingestion["session_boundary_hits"],
        "role_preservation_hits": ingestion["role_preservation_hits"],
        "timestamp_preservation_hits": ingestion["timestamp_preservation_hits"],
        "public_gold_label_ingestion_count": ingestion["public_gold_label_ingestion_count"],
        "public_answer_ingestion_count": ingestion["public_answer_ingestion_count"],
        "synthetic_memory_marker_injection_count": ingestion["synthetic_memory_marker_injection_count"],
        "direct_synthetic_archive_injection_count": ingestion["direct_synthetic_archive_injection_count"],
        "context_package_search_count": 3,
        "context_package_parse_count": parse_count,
        "automatic_memory_count": automatic_count,
        "active_memory_count": active_count,
        "inactive_memory_count": inactive_count,
        "review_routed_candidate_count": review_count,
        "baseline_retrievable": int(bool(baseline_ranks)),
        "gold_session_recall_at_5": int(bool(baseline_ranks)),
        "induced_gold_provenance_at_1": int(bool(gold_ranks and min(gold_ranks) <= 1)),
        "induced_gold_provenance_at_5": int(bool(gold_ranks and min(gold_ranks) <= 5)),
        "evidence_decision": evidence_decision,
        "supported_decision": int(evidence_decision == "answer"),
        "supported_decision_gold": int(evidence_decision == "answer" and bool(gold_ranks)),
        "abstention_correct": int(bool(case["is_abstention"]) and evidence_decision == "abstain"),
        "evidence_reachability_cases": evidence_cases,
        "evidence_reachability_hits": evidence_hits,
        "source_anchor_reachability_cases": source_cases,
        "source_anchor_reachability_hits": source_hits,
        "inactive_support_acceptance_count": 0,
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": 0,
    }
    return result


def _supported_fixture_package(*, active: bool = True) -> dict[str, Any]:
    return {
        "report_kind": CONTEXT_REPORT_KIND,
        "answerability": {"status": "supported" if active else "unsupported"},
        "hits": [
            {
                "active_current": active,
                "answerability": {"status": "supported"},
                "query_support": {"status": "supported"},
                "summary_drill_paths": ["sessions/fixture/summary.md"],
                "evidence_drill_paths": ["sessions/fixture/evidence.md"],
                "evidence_refs": [{"path": "sessions/fixture/evidence.md", "quote_id": "ev_001"}],
            }
        ],
    }


def run_offline_fixture() -> dict[str, Any]:
    rows = json.loads(OFFLINE_FIXTURE.read_text(encoding="utf-8"))
    selected = select_longmemeval_cases(
        rows,
        seed="v236-offline-fixture",
        positive_per_type=1,
        abstention_count=2,
    )
    repeated = select_longmemeval_cases(
        list(reversed(rows)),
        seed="v236-offline-fixture",
        positive_per_type=1,
        abstention_count=2,
    )
    deterministic = [row["question_id"] for row in selected] == [
        row["question_id"] for row in repeated
    ]

    totals = {
        "source_record_count": 0,
        "session_boundary_hits": 0,
        "role_preservation_hits": 0,
        "timestamp_preservation_hits": 0,
        "public_gold_label_ingestion_count": 0,
        "public_answer_ingestion_count": 0,
        "synthetic_memory_marker_injection_count": 0,
        "direct_synthetic_archive_injection_count": 0,
    }
    with tempfile.TemporaryDirectory(prefix="my-precious-public-induction-offline-") as tmpdir:
        root = Path(tmpdir)
        for case_ordinal, row in enumerate(selected, 1):
            case = convert_longmemeval_case(row, case_ordinal=case_ordinal)
            result = write_case_source_records(root / f"case-{case_ordinal:03d}", case)
            for key in totals:
                totals[key] += int(result[key])

    source_count = totals["source_record_count"]
    supported = _supported_fixture_package()
    inactive = _supported_fixture_package(active=False)
    superseded = {
        "report_kind": CONTEXT_REPORT_KIND,
        "answerability": {"status": "unsupported", "reason": "no_active_current_support"},
        "hits": [{"active_current": False, "answerability": {"status": "unsupported"}}],
    }
    metrics: dict[str, int | float] = {
        "public_case_selection_determinism_rate": float(deterministic),
        "public_source_record_conversion_rate": _ratio(source_count, source_count),
        "public_session_boundary_preservation_rate": _ratio(
            totals["session_boundary_hits"], source_count
        ),
        "public_role_preservation_rate": _ratio(totals["role_preservation_hits"], source_count),
        "public_timestamp_preservation_rate": _ratio(
            totals["timestamp_preservation_hits"], source_count
        ),
        "public_gold_label_ingestion_count": totals["public_gold_label_ingestion_count"],
        "public_answer_ingestion_count": totals["public_answer_ingestion_count"],
        "synthetic_memory_marker_injection_count": totals["synthetic_memory_marker_injection_count"],
        "direct_synthetic_archive_injection_count": totals["direct_synthetic_archive_injection_count"],
        "runtime_malformed_fail_closed_rate": float(
            context_package_decision(parse_context_package("{not-json")) == "abstain"
        ),
        "runtime_missing_package_fail_closed_rate": float(
            context_package_decision(parse_context_package("")) == "abstain"
        ),
        "runtime_inactive_only_rejection_rate": float(context_package_decision(inactive) == "abstain"),
        "runtime_superseded_only_rejection_rate": float(
            context_package_decision(superseded) == "abstain"
        ),
        "runtime_supported_decision_accuracy": float(context_package_decision(supported) == "answer"),
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": 0,
    }
    expected_one = (
        "public_case_selection_determinism_rate",
        "public_source_record_conversion_rate",
        "public_session_boundary_preservation_rate",
        "public_role_preservation_rate",
        "public_timestamp_preservation_rate",
        "runtime_malformed_fail_closed_rate",
        "runtime_missing_package_fail_closed_rate",
        "runtime_inactive_only_rejection_rate",
        "runtime_superseded_only_rejection_rate",
        "runtime_supported_decision_accuracy",
    )
    expected_zero = (
        "public_gold_label_ingestion_count",
        "public_answer_ingestion_count",
        "synthetic_memory_marker_injection_count",
        "direct_synthetic_archive_injection_count",
        "free_form_answerability_use_count",
        "privacy_leak_count",
    )
    passed = all(metrics[key] == 1.0 for key in expected_one) and all(
        metrics[key] == 0 for key in expected_zero
    )
    return {
        "report_kind": "public_induction_recall_gate",
        "report_version": 1,
        "mode": "offline_fixture",
        "status": "passed" if passed else "failed",
        "selected_case_count": len(selected),
        "source_record_count": source_count,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "claim_boundary": (
            "offline harness contract only; not public dataset performance, packaged updater quality, "
            "ranking quality, answer quality, or leaderboard parity"
        ),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_external_artifact_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return resolved
    raise SystemExit(f"{label} must stay outside the reusable repository")


def _selection_fingerprint(selected: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in selected:
        digest.update(_text(row.get("question_id"), "question_id").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _rate_metric(
    metrics: dict[str, int | float],
    counts: dict[str, dict[str, int]],
    name: str,
    numerator: int,
    denominator: int,
    *,
    empty_value: float = 1.0,
) -> None:
    metrics[name] = empty_value if denominator == 0 else numerator / denominator
    counts[name] = {"numerator": numerator, "denominator": denominator}


def _failure_buckets(runs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for run in runs:
        question_type = str(run.get("question_type") or "unknown")
        bucket = buckets.setdefault(
            question_type,
            {
                "cases": 0,
                "setup_failure": 0,
                "updater_failure": 0,
                "audit_failure": 0,
                "baseline_miss": 0,
                "induced_provenance_miss": 0,
                "abstention_false_positive": 0,
            },
        )
        bucket["cases"] += 1
        bucket["setup_failure"] += int(not run.get("packaged_setup_success"))
        bucket["updater_failure"] += int(not run.get("updater_success"))
        bucket["audit_failure"] += int(not run.get("archive_audit_success"))
        if not run.get("is_abstention"):
            bucket["baseline_miss"] += int(not run.get("baseline_retrievable"))
            bucket["induced_provenance_miss"] += int(not run.get("induced_gold_provenance_at_5"))
        else:
            bucket["abstention_false_positive"] += int(not run.get("abstention_correct"))
    return dict(sorted(buckets.items()))


def build_public_report(
    *,
    input_path: Path,
    source_url: str,
    seed: str,
    positive_per_type: int,
    abstention_count: int,
    rows: list[object],
    selected: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics: dict[str, int | float] = {}
    counts: dict[str, dict[str, int]] = {}
    case_count = len(runs)
    positive_runs = [run for run in runs if not run.get("is_abstention")]
    abstention_runs = [run for run in runs if run.get("is_abstention")]
    source_record_count = sum(int(run.get("source_record_count") or 0) for run in runs)
    expected_source_records = sum(
        len(row.get("haystack_sessions") or []) for row in selected if isinstance(row, dict)
    )
    repeated = select_longmemeval_cases(
        list(reversed(rows)),
        seed=seed,
        positive_per_type=positive_per_type,
        abstention_count=abstention_count,
    )
    selection_deterministic = [row["question_id"] for row in selected] == [
        row["question_id"] for row in repeated
    ]

    _rate_metric(metrics, counts, "public_case_selection_determinism_rate", int(selection_deterministic), 1)
    _rate_metric(
        metrics,
        counts,
        "public_source_record_conversion_rate",
        source_record_count,
        expected_source_records,
    )
    for metric, run_key in (
        ("public_session_boundary_preservation_rate", "session_boundary_hits"),
        ("public_role_preservation_rate", "role_preservation_hits"),
        ("public_timestamp_preservation_rate", "timestamp_preservation_hits"),
    ):
        _rate_metric(
            metrics,
            counts,
            metric,
            sum(int(run.get(run_key) or 0) for run in runs),
            source_record_count,
        )
    for metric, run_key in (
        ("public_packaged_setup_success_rate", "packaged_setup_success"),
        ("public_updater_success_rate", "updater_success"),
        ("public_archive_audit_success_rate", "archive_audit_success"),
    ):
        _rate_metric(metrics, counts, metric, sum(int(run.get(run_key) or 0) for run in runs), case_count)
    _rate_metric(
        metrics,
        counts,
        "public_automatic_memory_yield_rate",
        sum(int(int(run.get("automatic_memory_count") or 0) > 0) for run in runs),
        case_count,
    )
    _rate_metric(
        metrics,
        counts,
        "public_context_package_parse_success_rate",
        sum(int(run.get("context_package_parse_count") or 0) for run in runs),
        sum(int(run.get("context_package_search_count") or 0) for run in runs),
    )

    baseline_count = sum(int(run.get("baseline_retrievable") or 0) for run in positive_runs)
    induced_at_1 = sum(int(run.get("induced_gold_provenance_at_1") or 0) for run in positive_runs)
    induced_at_5 = sum(int(run.get("induced_gold_provenance_at_5") or 0) for run in positive_runs)
    retained_at_5 = sum(
        int(run.get("baseline_retrievable") and run.get("induced_gold_provenance_at_5"))
        for run in positive_runs
    )
    _rate_metric(
        metrics,
        counts,
        "public_gold_session_recall_at_5",
        baseline_count,
        len(positive_runs),
        empty_value=0.0,
    )
    _rate_metric(
        metrics,
        counts,
        "public_induced_gold_provenance_recall_at_1",
        induced_at_1,
        len(positive_runs),
        empty_value=0.0,
    )
    _rate_metric(
        metrics,
        counts,
        "public_induced_gold_provenance_recall_at_5",
        induced_at_5,
        len(positive_runs),
        empty_value=0.0,
    )
    _rate_metric(
        metrics,
        counts,
        "public_induction_provenance_retention_at_5",
        retained_at_5,
        baseline_count,
        empty_value=0.0,
    )
    supported_decisions = sum(int(run.get("supported_decision") or 0) for run in runs)
    supported_gold = sum(int(run.get("supported_decision_gold") or 0) for run in runs)
    _rate_metric(
        metrics,
        counts,
        "public_supported_decision_precision",
        supported_gold,
        supported_decisions,
        empty_value=0.0,
    )
    evidence_cases = sum(int(run.get("evidence_reachability_cases") or 0) for run in runs)
    source_cases = sum(int(run.get("source_anchor_reachability_cases") or 0) for run in runs)
    _rate_metric(
        metrics,
        counts,
        "public_evidence_reachability_rate",
        sum(int(run.get("evidence_reachability_hits") or 0) for run in runs),
        evidence_cases,
    )
    _rate_metric(
        metrics,
        counts,
        "public_source_anchor_reachability_rate",
        sum(int(run.get("source_anchor_reachability_hits") or 0) for run in runs),
        source_cases,
    )
    _rate_metric(
        metrics,
        counts,
        "public_abstention_accuracy",
        sum(int(run.get("abstention_correct") or 0) for run in abstention_runs),
        len(abstention_runs),
        empty_value=0.0,
    )

    offline_metrics = run_offline_fixture()["metrics"]
    for metric in (
        "runtime_malformed_fail_closed_rate",
        "runtime_missing_package_fail_closed_rate",
        "runtime_inactive_only_rejection_rate",
        "runtime_superseded_only_rejection_rate",
    ):
        _rate_metric(metrics, counts, metric, int(offline_metrics[metric] == 1.0), 1)

    metrics.update(
        {
            "public_positive_case_count": len(positive_runs),
            "public_abstention_case_count": len(abstention_runs),
            "public_baseline_retrievable_case_count": baseline_count,
            "public_active_memory_count": sum(int(run.get("active_memory_count") or 0) for run in runs),
            "public_inactive_memory_count": sum(int(run.get("inactive_memory_count") or 0) for run in runs),
            "public_review_routed_candidate_count": sum(
                int(run.get("review_routed_candidate_count") or 0) for run in runs
            ),
            "public_gold_label_ingestion_count": sum(
                int(run.get("public_gold_label_ingestion_count") or 0) for run in runs
            ),
            "public_answer_ingestion_count": sum(
                int(run.get("public_answer_ingestion_count") or 0) for run in runs
            ),
            "synthetic_memory_marker_injection_count": sum(
                int(run.get("synthetic_memory_marker_injection_count") or 0) for run in runs
            ),
            "direct_synthetic_archive_injection_count": sum(
                int(run.get("direct_synthetic_archive_injection_count") or 0) for run in runs
            ),
            "inactive_support_acceptance_count": sum(
                int(run.get("inactive_support_acceptance_count") or 0) for run in runs
            ),
            "free_form_answerability_use_count": sum(
                int(run.get("free_form_answerability_use_count") or 0) for run in runs
            ),
            "privacy_leak_count": sum(int(run.get("privacy_leak_count") or 0) for run in runs),
        }
    )

    dataset = {
        "source": "LongMemEval cleaned S",
        "source_url": source_url,
        "sha256": _file_sha256(input_path),
        "input_record_count": len(rows),
    }
    selection = {
        "seed": seed,
        "positive_per_type": positive_per_type,
        "abstention_count": abstention_count,
        "fingerprint_sha256": _selection_fingerprint(selected),
    }
    question_type_counts = dict(
        sorted(Counter(str(run.get("question_type")) for run in runs).items())
    )
    failure_buckets = _failure_buckets(runs)
    thresholds = {
        "minimum_baseline_retrievable_cases": 20,
        "minimum_induction_provenance_retention_at_5": 0.90,
        "minimum_supported_decision_precision": 0.80,
        "required_abstention_case_count": 10,
        "minimum_abstention_accuracy": 0.90,
    }
    privacy = {
        "aggregate_only": True,
        "questions_rendered": False,
        "answers_rendered": False,
        "case_ids_rendered": False,
        "memory_ids_rendered": False,
        "memory_text_rendered": False,
        "source_content_rendered": False,
        "source_paths_rendered": False,
        "raw_refs_rendered": False,
        "context_packages_rendered": False,
    }
    claim_boundary = (
        "bounded public natural-conversation induction provenance evidence only; not LLM answer quality, "
        "official LongMemEval leaderboard parity, vector search quality, ontology discovery, private archive "
        "quality, or multi-principal governance"
    )
    privacy_probe = {
        "report_kind": "public_induction_recall_gate",
        "dataset": dataset,
        "selection": selection,
        "selected_case_count": len(selected),
        "source_record_count": source_record_count,
        "question_type_counts": question_type_counts,
        "metrics": metrics,
        "metric_counts": counts,
        "failure_buckets": failure_buckets,
        "thresholds": thresholds,
        "privacy": privacy,
        "claim_boundary": claim_boundary,
    }
    metrics["privacy_leak_count"] = int(metrics["privacy_leak_count"]) + aggregate_privacy_leak_count(
        privacy_probe,
        selected,
        [input_path],
    )

    structural_rate_metrics = (
        "public_case_selection_determinism_rate",
        "public_source_record_conversion_rate",
        "public_session_boundary_preservation_rate",
        "public_role_preservation_rate",
        "public_timestamp_preservation_rate",
        "public_packaged_setup_success_rate",
        "public_updater_success_rate",
        "public_archive_audit_success_rate",
        "public_context_package_parse_success_rate",
        "public_evidence_reachability_rate",
        "public_source_anchor_reachability_rate",
    )
    structural_zero_metrics = (
        "public_gold_label_ingestion_count",
        "public_answer_ingestion_count",
        "synthetic_memory_marker_injection_count",
        "direct_synthetic_archive_injection_count",
        "inactive_support_acceptance_count",
        "free_form_answerability_use_count",
        "privacy_leak_count",
    )
    structurally_valid = all(metrics[name] == 1.0 for name in structural_rate_metrics) and all(
        metrics[name] == 0 for name in structural_zero_metrics
    )
    if baseline_count < 20:
        readiness_status = "inconclusive"
    else:
        performance_passed = (
            metrics["public_induction_provenance_retention_at_5"] >= 0.90
            and metrics["public_supported_decision_precision"] >= 0.80
            and len(abstention_runs) == 10
            and metrics["public_abstention_accuracy"] >= 0.90
            and all(metrics[name] == 1.0 for name in (
                "runtime_malformed_fail_closed_rate",
                "runtime_missing_package_fail_closed_rate",
                "runtime_inactive_only_rejection_rate",
                "runtime_superseded_only_rejection_rate",
            ))
        )
        readiness_status = "go" if structurally_valid and performance_passed else "no_go"

    return {
        "report_kind": "public_induction_recall_gate",
        "report_version": 1,
        "mode": "public_longmemeval",
        "status": "completed" if structurally_valid else "failed",
        "readiness_status": readiness_status,
        "dataset": dataset,
        "selection": selection,
        "selected_case_count": len(selected),
        "source_record_count": source_record_count,
        "question_type_counts": question_type_counts,
        "metrics": metrics,
        "metric_counts": counts,
        "failure_buckets": failure_buckets,
        "thresholds": thresholds,
        "privacy": privacy,
        "claim_boundary": claim_boundary,
    }


def _inconclusive_public_report(input_path: Path, source_url: str) -> dict[str, Any]:
    return {
        "report_kind": "public_induction_recall_gate",
        "report_version": 1,
        "mode": "public_longmemeval",
        "status": "completed",
        "readiness_status": "inconclusive",
        "inconclusive_reason": "dataset_schema_incompatible",
        "dataset": {
            "source": "LongMemEval cleaned S",
            "source_url": source_url,
            "sha256": _file_sha256(input_path),
        },
        "selected_case_count": 0,
        "metrics": {"privacy_leak_count": 0},
        "metric_counts": {},
        "failure_buckets": {"dataset_schema_incompatible": 1},
        "privacy": {
            "aggregate_only": True,
            "questions_rendered": False,
            "answers_rendered": False,
            "case_ids_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": "dataset schema could not be evaluated; no induction-readiness claim",
    }


def run_public_dataset(args: argparse.Namespace) -> dict[str, Any]:
    input_path = require_external_artifact_path(Path(args.public_input), "public benchmark input")
    try:
        with input_path.open("r", encoding="utf-8") as handle:
            rows = json.load(handle)
    except OSError as exc:
        raise SystemExit("unable to load LongMemEval public input") from exc
    except json.JSONDecodeError:
        return _inconclusive_public_report(input_path, args.dataset_source_url)
    if not isinstance(rows, list):
        return _inconclusive_public_report(input_path, args.dataset_source_url)
    try:
        selected = select_longmemeval_cases(
            rows,
            seed=args.seed,
            positive_per_type=args.positive_per_type,
            abstention_count=args.abstention_count,
        )
    except SystemExit:
        return _inconclusive_public_report(input_path, args.dataset_source_url)

    work_dir = require_external_artifact_path(Path(args.work_dir), "public benchmark work directory")
    if work_dir.exists() and any(work_dir.iterdir()):
        raise SystemExit("--work-dir must be empty")
    work_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for case_ordinal, row in enumerate(selected, 1):
        try:
            case = convert_longmemeval_case(row, case_ordinal=case_ordinal)
        except SystemExit:
            return _inconclusive_public_report(input_path, args.dataset_source_url)
        runs.append(run_packaged_case(case, work_dir / f"case-{case_ordinal:03d}"))
    return build_public_report(
        input_path=input_path,
        source_url=args.dataset_source_url,
        seed=args.seed,
        positive_per_type=args.positive_per_type,
        abstention_count=args.abstention_count,
        rows=rows,
        selected=selected,
        runs=runs,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline-fixture", action="store_true")
    mode.add_argument("--public-input")
    parser.add_argument("--dataset-source-url")
    parser.add_argument("--seed", default="my-precious-v236")
    parser.add_argument("--positive-per-type", type=int, default=5)
    parser.add_argument("--abstention-count", type=int, default=10)
    parser.add_argument("--work-dir")
    parser.add_argument("--report-file")
    args = parser.parse_args(argv)
    if args.public_input and not all((args.dataset_source_url, args.work_dir, args.report_file)):
        parser.error("public mode requires --dataset-source-url, --work-dir, and --report-file")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = (
        require_external_artifact_path(Path(args.report_file), "public benchmark report")
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
