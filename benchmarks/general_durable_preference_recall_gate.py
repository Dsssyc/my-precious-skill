#!/usr/bin/env python3
"""Measure generic durable-preference induction and package-first recall."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = REPO_ROOT / "benchmarks/cases/general_durable_preference_recall_synthetic.jsonl"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
BASELINE_COMMIT = "b076f5585ee3bfe0a8b2db07718ec9b32a3e03dd"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
REPORT_KIND = "general_durable_preference_recall_gate"
RUNTIME_RELATIVE_PATHS = (
    "templates/agent-memory-repo/tools/update_memory_archive.py",
    "templates/agent-memory-repo/tools/memory_consolidation.py",
    "templates/agent-memory-repo/tools/search_memory.py",
    "templates/agent-memory-repo/tools/resolve_memory_source.py",
)
FIRST_LOSS_STAGES = (
    "source_event_recognized",
    "durable_preference_qualified",
    "evidence_quote_allocated",
    "source_anchor_created",
    "memory_materialized",
    "correct_scope",
    "active_current",
    "retrieved_at_5",
    "retrieved_at_1",
    "query_support_accepted",
    "package_decision_accepted",
)
PUBLIC_THRESHOLDS = {
    "generic_preference_qualification_recall": (">=", 0.85),
    "generic_preference_materialization_recall": (">=", 0.85),
    "generic_preference_source_anchor_binding_rate": ("==", 1.0),
    "generic_preference_scope_accuracy": ("==", 1.0),
    "unseen_paraphrase_recall_at_5": (">=", 0.85),
    "unseen_paraphrase_supported_recall": (">=", 0.75),
    "supported_decision_precision": ("==", 1.0),
    "hard_negative_rejection_rate": ("==", 1.0),
    "inactive_preference_rejection_rate": ("==", 1.0),
    "current_turn_precedence_accuracy": ("==", 1.0),
    "legacy_goal_preference_regression_rate": ("==", 1.0),
    "legacy_goal_alias_ablation_supported_recall": (">=", 0.75),
    "free_form_answerability_use_count": ("==", 0),
    "new_case_specific_runtime_literal_count": ("==", 0),
    "holdout_query_literal_overlap_count": ("==", 0),
    "preference_specific_candidate_branch_count": ("==", 0),
    "privacy_leak_count": ("==", 0),
    "performance_runtime_ratio": ("<=", 1.5),
    "performance_peak_memory_ratio": ("<=", 1.5),
    "deterministic_result_ordering_rate": ("==", 1.0),
}
PRIVATE_THRESHOLDS = {
    "private_context_package_parse_success_rate": ("==", 1.0),
    "private_unseen_preference_supported_recall": (">=", 0.75),
    "private_supported_decision_precision": ("==", 1.0),
    "private_false_support_count": ("==", 0),
    "private_wrong_scope_supported_count": ("==", 0),
    "private_inactive_answer_count": ("==", 0),
    "private_free_form_answerability_use_count": ("==", 0),
    "canonical_archive_mutation_count": ("==", 0),
    "privacy_leak_count": ("==", 0),
}
PRIVATE_LEAK_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    ),
)
GOAL_ABLATION_RUNNER = """
import importlib.util
import sys
from pathlib import Path

updater_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("v255_goal_ablation_updater", updater_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.induce_copyable_goal_preference = lambda events: None
sys.argv = [str(updater_path), *sys.argv[2:]]
raise SystemExit(module.main())
""".strip()
LEGACY_GOAL_QUERIES = (
    "可直接复制 Markdown goal",
    "goal 提示词格式偏好",
    "纯文本 goal 方便复制",
    "我的 goal 应该怎样交付",
)


class GateFailure(RuntimeError):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def report(self) -> dict[str, object]:
        payload: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            payload["returncode"] = self.returncode
        return payload


@dataclass(frozen=True)
class SourceFixture:
    project: str
    updated_at: str
    events: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class PreferenceCase:
    case_id: str
    cohort: str
    expected_action: str
    language: str
    shape: str
    query: str
    expected_fact: str
    expected_scope: str
    sources: tuple[SourceFixture, ...]
    query_mode: str = "literal"
    ablation_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseObservation:
    expected_action: str
    shape: str
    checks: dict[str, bool]
    decision: str
    package_parsed: bool
    target_rank: int
    wrong_scope_supported: bool


def safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def run_command(
    argv: list[str],
    stage: str,
    *,
    cwd: Path | None = None,
    timeout: int = 360,
) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result.stdout


def load_cases(path: Path = CASE_FILE) -> list[PreferenceCase]:
    cases: list[PreferenceCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateFailure("cases", f"invalid_json_line_{line_number}") from exc
        if not isinstance(row, dict):
            raise GateFailure("cases", f"non_object_line_{line_number}")
        sources: list[SourceFixture] = []
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                raise GateFailure("cases", f"invalid_source_line_{line_number}")
            events = source.get("events")
            if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
                raise GateFailure("cases", f"invalid_events_line_{line_number}")
            sources.append(
                SourceFixture(
                    project=str(source.get("project") or ""),
                    updated_at=str(source.get("updated_at") or ""),
                    events=tuple(
                        {
                            "role": str(event.get("role") or ""),
                            "content": str(event.get("content") or ""),
                        }
                        for event in events
                    ),
                )
            )
        case = PreferenceCase(
            case_id=str(row.get("case_id") or ""),
            cohort=str(row.get("cohort") or ""),
            expected_action=str(row.get("expected_action") or ""),
            language=str(row.get("language") or ""),
            shape=str(row.get("shape") or ""),
            query=str(row.get("query") or ""),
            expected_fact=str(row.get("expected_fact") or ""),
            expected_scope=str(row.get("expected_scope") or "all"),
            sources=tuple(sources),
            query_mode=str(row.get("query_mode") or "literal"),
            ablation_queries=tuple(str(value) for value in row.get("ablation_queries") or []),
        )
        if (
            not case.case_id
            or case.cohort not in {"calibration", "holdout"}
            or case.expected_action not in {"answer", "abstain"}
            or not case.query
        ):
            raise GateFailure("cases", f"invalid_case_line_{line_number}")
        cases.append(case)
    if len({case.case_id for case in cases}) != len(cases):
        raise GateFailure("cases", "duplicate_case_id")
    return cases


def cohort_cases(cases: list[PreferenceCase], cohort: str) -> list[PreferenceCase]:
    selected = [case for case in cases if case.cohort == cohort]
    if not selected:
        raise GateFailure("cases", "empty_cohort")
    return selected


def cohort_fingerprint(cases: list[PreferenceCase]) -> str:
    rows = [
        {
            "case_id": case.case_id,
            "expected_action": case.expected_action,
            "language": case.language,
            "shape": case.shape,
            "query": case.query,
            "expected_fact": case.expected_fact,
            "expected_scope": case.expected_scope,
            "query_mode": case.query_mode,
            "sources": [
                {
                    "project": source.project,
                    "updated_at": source.updated_at,
                    "events": list(source.events),
                }
                for source in case.sources
            ],
            "ablation_queries": list(case.ablation_queries),
        }
        for case in sorted(cases, key=lambda value: value.case_id)
    ]
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def first_loss(checks: dict[str, bool]) -> str:
    for stage in FIRST_LOSS_STAGES:
        if not checks.get(stage, False):
            return stage
    return "none"


def load_context_package(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("report_kind") != CONTEXT_REPORT_KIND:
        return None
    return payload


def package_decision(raw: str, target_memory_ids: set[str] | frozenset[str]) -> str:
    package = load_context_package(raw)
    if package is None or not target_memory_ids:
        return "abstain"
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return "abstain"
    hits = package.get("hits")
    if not isinstance(hits, list):
        return "abstain"
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            str(hit.get("memory_id") or "") in target_memory_ids
            and hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and bool(hit.get("summary_drill_paths"))
            and bool(hit.get("evidence_drill_paths"))
        ):
            return "answer"
    return "abstain"


def package_supported_decision(raw: str) -> str:
    package = load_context_package(raw)
    if package is None:
        return "abstain"
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return "abstain"
    hits = package.get("hits")
    if not isinstance(hits, list):
        return "abstain"
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and bool(hit.get("summary_drill_paths"))
            and bool(hit.get("evidence_drill_paths"))
        ):
            return "answer"
    return "abstain"


def timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def write_source(path: Path, source: SourceFixture) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in source.events
        ),
        encoding="utf-8",
    )
    stamp = timestamp(source.updated_at)
    os.utime(path, (stamp, stamp))


def setup_archive(root: Path, name: str) -> Path:
    repo = root / name
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        f"setup_{name}",
    )
    return repo


def git_show(relative_path: str) -> str:
    return run_command(
        ["git", "show", f"{BASELINE_COMMIT}:{relative_path}"],
        "baseline_git_show",
        cwd=REPO_ROOT,
    )


def install_baseline_runtime(memory_repo: Path) -> None:
    for relative_path in RUNTIME_RELATIVE_PATHS:
        target = memory_repo / "tools" / Path(relative_path).name
        target.write_text(git_show(relative_path), encoding="utf-8")


def update_archive(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path,
    project: str,
    *,
    disable_goal_induction: bool = False,
) -> None:
    updater = memory_repo / "tools/update_memory_archive.py"
    updater_args = [
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--project",
        project,
        "--source-agent",
        "v255-synthetic",
        "--rewrite-existing",
    ]
    argv = [sys.executable, str(updater), *updater_args]
    if disable_goal_induction:
        argv = [
            sys.executable,
            "-c",
            GOAL_ABLATION_RUNNER,
            str(updater),
            *updater_args,
        ]
    run_command(argv, "archive_update", cwd=memory_repo)


def populate_archive(
    root: Path,
    memory_repo: Path,
    cases: list[PreferenceCase],
    *,
    disable_goal_induction: bool = False,
) -> dict[str, set[str]]:
    projects_by_case: dict[str, set[str]] = {}
    source_rows: list[tuple[float, PreferenceCase, int, SourceFixture]] = []
    for case in cases:
        for index, source in enumerate(case.sources, 1):
            source_rows.append((timestamp(source.updated_at), case, index, source))
    for _, case, index, source in sorted(source_rows, key=lambda row: (row[0], row[1].case_id, row[2])):
        source_dir = root / "sources" / memory_repo.name / case.case_id / str(index)
        source_path = source_dir / "record.jsonl"
        project_path = root / "projects" / source.project
        project_path.mkdir(parents=True, exist_ok=True)
        write_source(source_path, source)
        update_archive(
            memory_repo,
            source_dir,
            project_path,
            source.project,
            disable_goal_induction=disable_goal_induction,
        )
        projects_by_case.setdefault(case.case_id, set()).add(source.project)
    return projects_by_case


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def session_meta_rows(memory_repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            rows.append(value)
    return rows


def memory_nodes(memory_repo: Path, expected_fact: str) -> list[dict[str, Any]]:
    return [
        row
        for row in read_jsonl(memory_repo / "index/memories.jsonl")
        if str(row.get("text") or "") == expected_fact
    ]


def fact_source_rows(meta_rows: list[dict[str, Any]], expected_fact: str) -> list[dict[str, Any]]:
    return [
        source
        for row in meta_rows
        for source in row.get("reusable_fact_sources") or []
        if isinstance(source, dict)
        and (
            str(source.get("text") or "") == expected_fact
            or str(source.get("text") or "").endswith(f"=> {expected_fact}")
        )
    ]


def node_has_bound_drill_paths(memory_repo: Path, node: dict[str, Any]) -> bool:
    evidence_refs = node.get("evidence_refs")
    raw_refs = node.get("raw_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return False
    if not isinstance(raw_refs, list) or not raw_refs:
        return False
    evidence_ok = all(
        isinstance(ref, dict)
        and bool(ref.get("quote_id"))
        and (memory_repo / str(ref.get("path") or "")).is_file()
        for ref in evidence_refs
    )
    raw_ok = all(
        isinstance(ref, dict)
        and bool(ref.get("anchor"))
        and (memory_repo / str(ref.get("path") or "")).is_file()
        for ref in raw_refs
    )
    return evidence_ok and raw_ok and len(evidence_refs) == len(raw_refs)


def node_active_current(node: dict[str, Any]) -> bool:
    return not (
        node.get("superseded_by")
        or node.get("contradicted_by")
        or node.get("deprecated_by")
        or str(node.get("text") or "").startswith(("Deleted fact:", "Deprecated fact:"))
    )


def run_context_package(
    search_tool: Path,
    memory_repo: Path,
    query: str,
    scope: str,
) -> str:
    argv = [
        sys.executable,
        str(search_tool),
        query,
        "--repo",
        str(memory_repo),
        "--depth",
        "evidence",
        "--context-json",
        "--limit",
        "5",
    ]
    if scope in {"global", "domain", "project"}:
        argv.extend(["--scope", scope])
    return run_command(argv, "context_package_search", cwd=memory_repo)


def target_hit(package: dict[str, Any] | None, target_ids: set[str]) -> tuple[int, dict[str, Any] | None]:
    if package is None:
        return 0, None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return 0, None
    for index, hit in enumerate(hits, 1):
        if isinstance(hit, dict) and str(hit.get("memory_id") or "") in target_ids:
            return index, hit
    return 0, None


def positive_checks(
    case: PreferenceCase,
    memory_repo: Path,
    projects: set[str],
    package_raw: str,
) -> dict[str, bool]:
    meta_rows = session_meta_rows(memory_repo)
    recognized_projects = {
        str(row.get("project") or "")
        for row in meta_rows
        if str(row.get("project") or "") in projects
    }
    source_rows = fact_source_rows(meta_rows, case.expected_fact)
    nodes = memory_nodes(memory_repo, case.expected_fact)
    active_nodes = [node for node in nodes if node_active_current(node)]
    target_ids = {
        str(node.get("memory_id") or "")
        for node in active_nodes
        if node.get("memory_id")
    }
    package = load_context_package(package_raw)
    rank, hit = target_hit(package, target_ids)
    query_support = hit.get("query_support") if isinstance(hit, dict) else None
    return {
        "source_event_recognized": bool(projects) and recognized_projects == projects,
        "durable_preference_qualified": bool(source_rows),
        "evidence_quote_allocated": bool(source_rows)
        and all(
            bool(row.get("evidence_quote_id") or row.get("evidence_quote_ids"))
            for row in source_rows
        ),
        "source_anchor_created": bool(source_rows)
        and all(
            bool(row.get("source_anchor_id") or row.get("source_anchor_ids"))
            for row in source_rows
        ),
        "memory_materialized": bool(nodes),
        "correct_scope": bool(nodes)
        and all(
            node.get("layer") == case.expected_scope
            and node.get("scope") == case.expected_scope
            for node in nodes
        ),
        "active_current": bool(active_nodes),
        "retrieved_at_5": 1 <= rank <= 5,
        "retrieved_at_1": rank == 1,
        "query_support_accepted": isinstance(query_support, dict)
        and query_support.get("status") == "supported",
        "package_decision_accepted": package_decision(package_raw, target_ids) == "answer",
    }


def observe_cases(
    memory_repo: Path,
    cases: list[PreferenceCase],
    projects_by_case: dict[str, set[str]],
) -> list[CaseObservation]:
    search_tool = memory_repo / "tools/search_memory.py"
    observations: list[CaseObservation] = []
    for case in cases:
        nodes = memory_nodes(memory_repo, case.expected_fact) if case.expected_fact else []
        target_ids = {
            str(node.get("memory_id") or "")
            for node in nodes
            if node.get("memory_id")
        }
        query = case.query
        if case.query_mode == "target_memory_id":
            query = min(target_ids) if target_ids else case.query
        if case.shape == "malformed_package":
            raw = "{not-json"
        elif case.shape == "missing_package":
            raw = ""
        else:
            raw = run_context_package(
                search_tool,
                memory_repo,
                query,
                case.expected_scope,
            )
        package = load_context_package(raw)
        decision = (
            package_decision(raw, target_ids)
            if case.expected_action == "answer"
            else package_supported_decision(raw)
        )
        rank, hit = target_hit(package, target_ids)
        if case.expected_action == "answer":
            checks = positive_checks(
                case,
                memory_repo,
                projects_by_case.get(case.case_id, set()),
                raw,
            )
        else:
            checks = {stage: True for stage in FIRST_LOSS_STAGES}
        wrong_scope_supported = bool(
            decision == "answer"
            and isinstance(hit, dict)
            and str(hit.get("layer") or "") != case.expected_scope
        )
        observations.append(
            CaseObservation(
                expected_action=case.expected_action,
                shape=case.shape,
                checks=checks,
                decision=decision,
                package_parsed=package is not None,
                target_rank=rank,
                wrong_scope_supported=wrong_scope_supported,
            )
        )
    return observations


def first_loss_distribution(observations: list[CaseObservation]) -> dict[str, int]:
    counter = Counter(
        first_loss(observation.checks)
        for observation in observations
        if observation.expected_action == "answer"
    )
    return {
        key: counter.get(key, 0)
        for key in (*FIRST_LOSS_STAGES, "none")
        if counter.get(key, 0)
    }


def added_runtime_diff() -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
            BASELINE_COMMIT,
            "--",
            *RUNTIME_RELATIVE_PATHS,
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if result.returncode:
        raise GateFailure("runtime_diff", "command_failed", result.returncode)
    return "\n".join(
        line[1:]
        for line in result.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def case_specific_runtime_metrics(
    added_diff: str,
    holdout: list[PreferenceCase],
) -> dict[str, int]:
    lowered = added_diff.casefold()
    query_overlaps = sum(
        bool(case.query.strip()) and case.query.casefold() in lowered
        for case in holdout
    )
    query_overlaps += sum(
        query.casefold() in lowered
        for case in holdout
        for query in case.ablation_queries
        if query.strip()
    )
    case_id_overlaps = sum(case.case_id.casefold() in lowered for case in holdout)
    benchmark_label_count = len(
        re.findall(r"(?i)\b(?:holdout-query|hold-pos|hold-neg|v255-case)\b", added_diff)
    )
    domain_branch_count = sum(
        1
        for line in added_diff.splitlines()
        if re.search(
            r"(?i)^\s*(?:if|elif)\b.*(?:risk table|status summar|breaking change|"
            r"compatibility matrix|goal preference|copyable goal)",
            line,
        )
    )
    return {
        "new_case_specific_runtime_literal_count": (
            query_overlaps + case_id_overlaps + benchmark_label_count
        ),
        "holdout_query_literal_overlap_count": query_overlaps,
        "preference_specific_candidate_branch_count": domain_branch_count,
    }


def legacy_ablation_rate(
    root: Path,
    cases: list[PreferenceCase],
    *,
    baseline: bool,
) -> float:
    legacy_cases = [case for case in cases if case.shape == "legacy_goal_ablation"]
    if not legacy_cases:
        return 0.0
    memory_repo = setup_archive(
        root,
        "baseline-goal-ablation" if baseline else "candidate-goal-ablation",
    )
    if baseline:
        install_baseline_runtime(memory_repo)
    populate_archive(
        root,
        memory_repo,
        legacy_cases,
        disable_goal_induction=True,
    )
    rows = read_jsonl(memory_repo / "index/memories.jsonl")
    target_ids = {
        str(row.get("memory_id") or "")
        for row in rows
        if row.get("memory_id")
        and row.get("layer") == "global"
        and row.get("source") == "automatic"
        and node_active_current(row)
    }
    queries = [
        query
        for case in legacy_cases
        for query in case.ablation_queries
    ]
    supported = 0
    for query in queries:
        raw = run_context_package(
            memory_repo / "tools/search_memory.py",
            memory_repo,
            query,
            "global",
        )
        supported += package_decision(raw, target_ids) == "answer"
    return safe_rate(supported, len(queries))


def legacy_goal_regression_rate(
    memory_repo: Path,
    cases: list[PreferenceCase],
) -> float:
    legacy_facts = {
        case.expected_fact
        for case in cases
        if case.shape == "legacy_goal_ablation" and case.expected_fact
    }
    rows = read_jsonl(memory_repo / "index/memories.jsonl")
    target_ids = {
        str(row.get("memory_id") or "")
        for row in rows
        if str(row.get("text") or "") in legacy_facts
        and row.get("memory_id")
        and node_active_current(row)
    }
    supported = 0
    for query in LEGACY_GOAL_QUERIES:
        raw = run_context_package(
            memory_repo / "tools/search_memory.py",
            memory_repo,
            query,
            "global",
        )
        supported += package_decision(raw, target_ids) == "answer"
    return safe_rate(supported, len(LEGACY_GOAL_QUERIES))


def seed_performance_archive(memory_repo: Path, count: int = 500) -> None:
    summary = memory_repo / "sessions/performance/summary.md"
    evidence = memory_repo / "sessions/performance/evidence.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("Synthetic deterministic preference performance fixture.\n", encoding="utf-8")
    evidence.write_text("ev_001: synthetic public fixture\n", encoding="utf-8")
    now = "2026-02-20T00:00:00Z"
    rows = []
    for index in range(count):
        rows.append(
            {
                "memory_id": f"mem_perf_{index:04d}",
                "layer": "global",
                "scope": "global",
                "topic": "synthetic-performance",
                "text": (
                    f"The user prefers synthetic report {index:04d} to retain "
                    f"deterministic marker group {index % 17:02d}."
                ),
                "rationale": "Synthetic public performance fixture.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "sticky",
                "support_count": 1,
                "first_seen": now,
                "last_seen": now,
                "derived_from": ["sessions/performance/summary.md"],
                "evidence_refs": [
                    {
                        "path": "sessions/performance/evidence.md",
                        "quote_id": "ev_001",
                    }
                ],
                "raw_refs": [],
                "supersedes": [],
                "superseded_by": None,
                "contradicts": [],
                "contradicted_by": [],
                "deprecates": [],
                "deprecated_by": None,
                "tags": ["synthetic", "performance"],
            }
        )
    (memory_repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def timed_search(
    search_tool: Path,
    memory_repo: Path,
    query: str,
    *,
    repeats: int = 5,
) -> tuple[float, list[tuple[str, ...]]]:
    durations: list[float] = []
    orderings: list[tuple[str, ...]] = []
    for _ in range(repeats):
        started = time.perf_counter()
        raw = run_context_package(search_tool, memory_repo, query, "global")
        durations.append(time.perf_counter() - started)
        package = load_context_package(raw) or {}
        orderings.append(
            tuple(
                str(hit.get("memory_id") or "")
                for hit in package.get("hits") or []
                if isinstance(hit, dict)
            )
        )
    return statistics.median(durations), orderings


def peak_memory_bytes(search_tool: Path, memory_repo: Path, query: str) -> int:
    time_tool = Path("/usr/bin/time")
    if not time_tool.is_file():
        return 1
    result = subprocess.run(
        [
            str(time_tool),
            "-l",
            sys.executable,
            str(search_tool),
            query,
            "--repo",
            str(memory_repo),
            "--depth",
            "evidence",
            "--context-json",
            "--scope",
            "global",
        ],
        cwd=memory_repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode:
        raise GateFailure("performance_peak_memory", "command_failed", result.returncode)
    match = re.search(r"(\d+)\s+maximum resident set size", result.stderr)
    return int(match.group(1)) if match else 1


def performance_metrics(root: Path) -> dict[str, float]:
    baseline_repo = setup_archive(root, "performance-baseline")
    candidate_repo = setup_archive(root, "performance-candidate")
    install_baseline_runtime(baseline_repo)
    seed_performance_archive(baseline_repo)
    seed_performance_archive(candidate_repo)
    query = "synthetic report 0317 deterministic marker group 11"
    baseline_median, baseline_orders = timed_search(
        baseline_repo / "tools/search_memory.py",
        baseline_repo,
        query,
    )
    candidate_median, candidate_orders = timed_search(
        candidate_repo / "tools/search_memory.py",
        candidate_repo,
        query,
    )
    baseline_peak = peak_memory_bytes(
        baseline_repo / "tools/search_memory.py",
        baseline_repo,
        query,
    )
    candidate_peak = peak_memory_bytes(
        candidate_repo / "tools/search_memory.py",
        candidate_repo,
        query,
    )
    deterministic = (
        len(set(baseline_orders)) == 1
        and len(set(candidate_orders)) == 1
        and baseline_orders[0] == candidate_orders[0]
    )
    return {
        "performance_runtime_ratio": candidate_median / max(baseline_median, 0.000001),
        "performance_peak_memory_ratio": candidate_peak / max(baseline_peak, 1),
        "deterministic_result_ordering_rate": float(deterministic),
    }


def metrics_from_observations(
    cases: list[PreferenceCase],
    observations: list[CaseObservation],
    *,
    ablation_rate: float,
    legacy_regression_rate: float,
    static_metrics: dict[str, int],
    performance: dict[str, float],
) -> dict[str, int | float]:
    paired = list(zip(cases, observations, strict=True))
    generic_positive = [
        observation
        for case, observation in paired
        if case.expected_action == "answer" and case.shape != "legacy_goal_ablation"
    ]
    negatives = [
        observation
        for case, observation in paired
        if case.expected_action == "abstain"
    ]
    inactive = [
        observation
        for case, observation in paired
        if case.shape == "inactive_only"
    ]
    current_turn_precedence = [
        (case, observation)
        for case, observation in paired
        if case.shape in {"replacement", "temporary"}
    ]
    answer_decisions = [
        (case, observation)
        for case, observation in paired
        if observation.decision == "answer"
    ]
    correct_answer_decisions = sum(
        case.expected_action == "answer"
        for case, _ in answer_decisions
    )
    bound_count = sum(
        observation.checks["evidence_quote_allocated"]
        and observation.checks["source_anchor_created"]
        for observation in generic_positive
    )
    metrics: dict[str, int | float] = {
        "generic_preference_qualification_recall": safe_rate(
            sum(item.checks["durable_preference_qualified"] for item in generic_positive),
            len(generic_positive),
        ),
        "generic_preference_materialization_recall": safe_rate(
            sum(item.checks["memory_materialized"] for item in generic_positive),
            len(generic_positive),
        ),
        "generic_preference_source_anchor_binding_rate": safe_rate(
            bound_count,
            len(generic_positive),
        ),
        "generic_preference_scope_accuracy": safe_rate(
            sum(item.checks["correct_scope"] for item in generic_positive),
            len(generic_positive),
        ),
        "unseen_paraphrase_recall_at_5": safe_rate(
            sum(item.checks["retrieved_at_5"] for item in generic_positive),
            len(generic_positive),
        ),
        "unseen_paraphrase_supported_recall": safe_rate(
            sum(item.checks["package_decision_accepted"] for item in generic_positive),
            len(generic_positive),
        ),
        "supported_decision_precision": safe_rate(
            correct_answer_decisions,
            len(answer_decisions),
        ),
        "hard_negative_rejection_rate": safe_rate(
            sum(item.decision == "abstain" for item in negatives),
            len(negatives),
        ),
        "inactive_preference_rejection_rate": safe_rate(
            sum(item.decision == "abstain" for item in inactive),
            len(inactive),
        ),
        "current_turn_precedence_accuracy": safe_rate(
            sum(
                (
                    case.expected_action == "answer"
                    and observation.decision == "answer"
                    and observation.checks["package_decision_accepted"]
                )
                or (
                    case.expected_action == "abstain"
                    and observation.decision == "abstain"
                )
                for case, observation in current_turn_precedence
            ),
            len(current_turn_precedence),
        ),
        "legacy_goal_preference_regression_rate": legacy_regression_rate,
        "legacy_goal_alias_ablation_supported_recall": ablation_rate,
        "free_form_answerability_use_count": 0,
        **static_metrics,
        **performance,
        "privacy_leak_count": 0,
    }
    return metrics


def threshold_failures(
    metrics: dict[str, int | float],
    thresholds: dict[str, tuple[str, float]],
) -> list[str]:
    failures: list[str] = []
    for name, (operator, threshold) in thresholds.items():
        value = float(metrics.get(name, -1))
        if operator == "==" and value != threshold:
            failures.append(name)
        elif operator == ">=" and value < threshold:
            failures.append(name)
        elif operator == "<=" and value > threshold:
            failures.append(name)
    return failures


def privacy_leak_count(report: dict[str, object]) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return sum(bool(pattern.search(rendered)) for pattern in PRIVATE_LEAK_PATTERNS)


def run_public(cohort: str, root: Path) -> dict[str, object]:
    cases = cohort_cases(load_cases(), cohort)
    all_cases = load_cases()
    holdout = cohort_cases(all_cases, "holdout")
    baseline_repo = setup_archive(root, "baseline")
    candidate_repo = setup_archive(root, "candidate")
    install_baseline_runtime(baseline_repo)
    baseline_projects = populate_archive(root, baseline_repo, cases)
    candidate_projects = populate_archive(root, candidate_repo, cases)
    baseline_observations = observe_cases(baseline_repo, cases, baseline_projects)
    candidate_observations = observe_cases(candidate_repo, cases, candidate_projects)
    static_metrics = case_specific_runtime_metrics(added_runtime_diff(), holdout)
    performance = performance_metrics(root)
    baseline_ablation = legacy_ablation_rate(root, cases, baseline=True)
    candidate_ablation = legacy_ablation_rate(root, cases, baseline=False)
    baseline_metrics = metrics_from_observations(
        cases,
        baseline_observations,
        ablation_rate=baseline_ablation,
        legacy_regression_rate=legacy_goal_regression_rate(
            baseline_repo,
            cases,
        ),
        static_metrics={"new_case_specific_runtime_literal_count": 0,
                        "holdout_query_literal_overlap_count": 0,
                        "preference_specific_candidate_branch_count": 0},
        performance={
            "performance_runtime_ratio": 1.0,
            "performance_peak_memory_ratio": 1.0,
            "deterministic_result_ordering_rate": 1.0,
        },
    )
    candidate_metrics = metrics_from_observations(
        cases,
        candidate_observations,
        ablation_rate=candidate_ablation,
        legacy_regression_rate=legacy_goal_regression_rate(
            candidate_repo,
            cases,
        ),
        static_metrics=static_metrics,
        performance=performance,
    )
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "cohort": cohort,
        "cohort_fingerprint": cohort_fingerprint(cases),
        "calibration_fingerprint": cohort_fingerprint(
            cohort_cases(all_cases, "calibration")
        ),
        "holdout_fingerprint": cohort_fingerprint(holdout),
        "case_counts": {
            "positive": sum(case.expected_action == "answer" for case in cases),
            "negative": sum(case.expected_action == "abstain" for case in cases),
        },
        "answerability_source": CONTEXT_REPORT_KIND,
        "free_form_search_used": False,
        "baseline": {
            "commit": BASELINE_COMMIT[:7],
            "first_loss_distribution": first_loss_distribution(baseline_observations),
            "metrics": baseline_metrics,
        },
        "candidate": {
            "candidate_count": 1,
            "first_loss_distribution": first_loss_distribution(candidate_observations),
            "metrics": candidate_metrics,
        },
        "privacy": {
            "aggregate_only": True,
            "case_text_rendered": False,
            "query_text_rendered": False,
            "memory_text_rendered": False,
            "paths_rendered": False,
            "ids_rendered": False,
            "context_packages_rendered": False,
        },
    }
    candidate_metrics["privacy_leak_count"] = privacy_leak_count(report)
    failures = threshold_failures(candidate_metrics, PUBLIC_THRESHOLDS)
    report["candidate"]["threshold_failures"] = failures
    report["status"] = "passed" if not failures else "failed"
    report["decision"] = "go" if not failures else "no_go"
    return report


def archive_identity(memory_repo: Path) -> str:
    digest = hashlib.sha256()
    for relative in ("index/memories.jsonl", "index/sessions.jsonl", "INDEX.md"):
        path = memory_repo / relative
        digest.update(relative.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    if (memory_repo / ".git").exists():
        for argv in (
            ["git", "rev-parse", "HEAD"],
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        ):
            result = subprocess.run(
                argv,
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            digest.update(result.stdout.encode("utf-8"))
            digest.update(str(result.returncode).encode("ascii"))
    return digest.hexdigest()


def load_private_manifest(path: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    if len(rows) < 12:
        raise GateFailure("private_manifest", "at_least_twelve_cases_required")
    positive = sum(row.get("expected_action") == "answer" for row in rows)
    negative = sum(row.get("expected_action") == "abstain" for row in rows)
    if positive < 6 or negative < 6:
        raise GateFailure("private_manifest", "six_positive_and_six_negative_required")
    for row in rows:
        if (
            not isinstance(row.get("query"), str)
            or row.get("expected_action") not in {"answer", "abstain"}
            or not isinstance(row.get("target_memory_ids", []), list)
        ):
            raise GateFailure("private_manifest", "invalid_case")
    return rows


def private_tool(root: Path, baseline: bool) -> Path:
    tool_dir = root / ("private-baseline-tool" if baseline else "private-candidate-tool")
    tool_dir.mkdir(parents=True, exist_ok=True)
    target = tool_dir / "search_memory.py"
    if baseline:
        target.write_text(
            git_show("templates/agent-memory-repo/tools/search_memory.py"),
            encoding="utf-8",
        )
    else:
        shutil.copy2(
            REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py",
            target,
        )
    return target


def run_private(
    root: Path,
    memory_repo: Path,
    manifest_path: Path,
) -> dict[str, object]:
    cases = load_private_manifest(manifest_path)
    before = archive_identity(memory_repo)
    baseline_search = private_tool(root, baseline=True)
    candidate_search = private_tool(root, baseline=False)
    baseline_actions: list[str] = []
    candidate_rows: list[dict[str, object]] = []
    for row in cases:
        scope = str(row.get("scope") or "all")
        target_ids = {str(value) for value in row.get("target_memory_ids") or []}
        baseline_raw = run_context_package(
            baseline_search,
            memory_repo,
            str(row["query"]),
            scope,
        )
        candidate_raw = run_context_package(
            candidate_search,
            memory_repo,
            str(row["query"]),
            scope,
        )
        baseline_actions.append(
            package_decision(baseline_raw, target_ids)
            if row["expected_action"] == "answer"
            else package_supported_decision(baseline_raw)
        )
        package = load_context_package(candidate_raw)
        decision = (
            package_decision(candidate_raw, target_ids)
            if row["expected_action"] == "answer"
            else package_supported_decision(candidate_raw)
        )
        target_rank, target = target_hit(package, target_ids)
        expected_scope = str(row.get("expected_scope") or "")
        wrong_scope = bool(
            decision == "answer"
            and expected_scope
            and isinstance(target, dict)
            and str(target.get("layer") or "") != expected_scope
        )
        candidate_rows.append(
            {
                "expected_action": row["expected_action"],
                "shape": str(row.get("shape") or ""),
                "parsed": package is not None,
                "decision": decision,
                "wrong_scope": wrong_scope,
                "target_rank": target_rank,
            }
        )
    after = archive_identity(memory_repo)
    positives = [row for row in candidate_rows if row["expected_action"] == "answer"]
    answer_rows = [row for row in candidate_rows if row["decision"] == "answer"]
    correct_answers = sum(row["expected_action"] == "answer" for row in answer_rows)
    metrics: dict[str, int | float] = {
        "private_context_package_parse_success_rate": safe_rate(
            sum(bool(row["parsed"]) for row in candidate_rows),
            len(candidate_rows),
        ),
        "private_unseen_preference_supported_recall": safe_rate(
            sum(row["decision"] == "answer" for row in positives),
            len(positives),
        ),
        "private_supported_decision_precision": safe_rate(
            correct_answers,
            len(answer_rows),
        ),
        "private_false_support_count": sum(
            row["expected_action"] == "abstain" and row["decision"] == "answer"
            for row in candidate_rows
        ),
        "private_wrong_scope_supported_count": sum(
            bool(row["wrong_scope"]) for row in candidate_rows
        ),
        "private_inactive_answer_count": sum(
            row["shape"] == "inactive_only" and row["decision"] == "answer"
            for row in candidate_rows
        ),
        "private_free_form_answerability_use_count": 0,
        "canonical_archive_mutation_count": int(before != after),
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "cohort": "private-holdout",
        "manifest_fingerprint": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "case_counts": {
            "positive": len(positives),
            "negative": len(candidate_rows) - len(positives),
        },
        "baseline": {
            "commit": BASELINE_COMMIT[:7],
            "supported_count": sum(action == "answer" for action in baseline_actions),
        },
        "candidate": {"candidate_count": 1, "metrics": metrics},
        "answerability_source": CONTEXT_REPORT_KIND,
        "free_form_search_used": False,
        "privacy": {
            "aggregate_only": True,
            "query_text_rendered": False,
            "memory_text_rendered": False,
            "paths_rendered": False,
            "ids_rendered": False,
            "context_packages_rendered": False,
        },
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report)
    failures = threshold_failures(metrics, PRIVATE_THRESHOLDS)
    report["candidate"]["threshold_failures"] = failures
    report["status"] = "passed" if not failures else "failed"
    report["decision"] = "go" if not failures else "no_go"
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort",
        choices=("calibration", "holdout", "private-holdout"),
        required=True,
    )
    parser.add_argument("--private-memory-repo")
    parser.add_argument("--private-case-manifest")
    parser.add_argument("--report-file")
    parser.add_argument("--work-dir")
    return parser.parse_args(argv)


def make_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="v255-preference-gate-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="v255-preference-gate-", dir=parent))
    return root, None, root


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.cohort == "private-holdout" and (
        not args.private_memory_repo or not args.private_case_manifest
    ):
        print(
            json.dumps(
                {
                    "report_kind": REPORT_KIND,
                    "status": "failed",
                    "failures": [
                        {
                            "stage": "arguments",
                            "reason": "private_repo_and_manifest_required",
                        }
                    ],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_root(args.work_dir)
        if args.cohort == "private-holdout":
            memory_repo = Path(args.private_memory_repo).expanduser().resolve()
            manifest = Path(args.private_case_manifest).expanduser().resolve()
            if not memory_repo.is_dir() or not manifest.is_file():
                raise GateFailure("private_inputs", "input_missing")
            report = run_private(root, memory_repo, manifest)
        else:
            report = run_public(args.cohort, root)
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if args.report_file:
            report_path = Path(args.report_file).expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output + "\n", encoding="utf-8")
        print(output)
        return 0 if report["status"] == "passed" else 1
    except (GateFailure, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as failure:
        payload = (
            failure.report()
            if isinstance(failure, GateFailure)
            else {"stage": "gate", "reason": type(failure).__name__}
        )
        print(
            json.dumps(
                {
                    "report_kind": REPORT_KIND,
                    "status": "failed",
                    "failures": [payload],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if temp is not None:
            temp.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
