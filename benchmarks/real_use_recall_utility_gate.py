#!/usr/bin/env python3
"""Gate the V2.49-V2.51 real-use recall slice on clean packaged archives.

The gate executes the updater and search tool copied by setup, verifies those
copies match the current source tools, and emits aggregate metrics only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
RUNTIME_SOURCES = (
    REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py",
    REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py",
)
REPORT_KIND = "real_use_recall_utility_gate"
CONTEXT_KIND = "memory_recall_context_package"
MAX_VARIANTS = 2
SYNTHETIC_CASES = (
    "canonical_skill_prefixed_preference",
    "saturated_source_bound_goal_preference",
    "multi_skill_prefixed_preference",
    "invocation_only",
    "arbitrary_markdown_path",
    "malformed_prefix",
    "body_skill_link",
    "prefixed_temporary",
    "prefixed_hypothetical",
    "prefixed_quoted",
    "prefixed_acknowledgement",
    "prefixed_sensitive",
    "durable_chinese_noisy",
    "durable_chinese_control",
    "durable_english",
    "temporary_constraint",
    "hypothetical_statement",
    "quoted_prompt",
    "assistant_acknowledgement",
    "project_history",
    "wrong_project",
    "unsupported_no_hit",
    "broad_query",
    "live_state",
)

CHINESE_PREFERENCE = (
    "以后编写 GoalSpec-Zeta 目标提示词时，我默认要求每个子目标都可验证、可收敛，"
    "并避免无限堆叠细节。"
)
CANONICAL_PREFIX = (
    "[$using-agent-skills]"
    "(/Users/example/.codex/skills/using-agent-skills/SKILL.md)"
)
SECOND_CANONICAL_PREFIX = (
    "[$using-superpowers]"
    "(/Users/example/.agents/skills/using-superpowers/SKILL.md)"
)
PREFIXED_CHINESE_BODY = (
    "以后编写 PrefixGoal-Lambda 目标提示词时，我默认要求每个子目标都可验证、可收敛。"
)
PREFIXED_CHINESE_PREFERENCE = f"{CANONICAL_PREFIX} {PREFIXED_CHINESE_BODY}"
MULTI_PREFIXED_ENGLISH_BODY = (
    "I prefer PrefixEnglish-Lambda plans to preserve original source anchors."
)
MULTI_PREFIXED_ENGLISH_PREFERENCE = (
    f"{CANONICAL_PREFIX}\n{SECOND_CANONICAL_PREFIX}\n{MULTI_PREFIXED_ENGLISH_BODY}"
)
SATURATED_GOAL_BODY = (
    "I prefer SaturatedGoal-Omega plans to preserve source-bound evidence."
)
SATURATED_GOAL_PREFERENCE = f"{CANONICAL_PREFIX} {SATURATED_GOAL_BODY}"
SATURATED_FINAL_STATE = "Final state: Synthetic bounded allocation fixture is complete."
INVOCATION_ONLY = CANONICAL_PREFIX
ARBITRARY_MARKDOWN_PATH = (
    "[notes](/Users/example/private/notes.md) "
    "I prefer PathLeak-Lambda plans to include verification."
)
MALFORMED_PREFIX = (
    "[$using-agent-skills]"
    "(/Users/example/.codex/skills/using-agent-skills/SKILL.md "
    "I prefer Malformed-Lambda plans to include verification."
)
BODY_SKILL_LINK = (
    "I prefer BodyLink-Lambda plans to include verification "
    "[$using-agent-skills]"
    "(/Users/example/.codex/skills/using-agent-skills/SKILL.md)."
)
PREFIXED_TEMPORARY = f"{CANONICAL_PREFIX} 这次任务我希望只输出 PREFIX-TEMP-LAMBDA 三段。"
PREFIXED_HYPOTHETICAL = (
    f"{CANONICAL_PREFIX} 如果以后编写目标，是不是每个阶段都要包含 PREFIX-HYPOTHETICAL-LAMBDA？"
)
PREFIXED_QUOTED = (
    f"{CANONICAL_PREFIX} 引用提示词：我的偏好是所有计划都包含 PREFIX-QUOTED-LAMBDA。"
)
PREFIXED_ACKNOWLEDGEMENT = (
    f"{CANONICAL_PREFIX} 好的，我会记住每个计划都包含 PREFIX-ACK-LAMBDA。"
)
PREFIXED_SENSITIVE = (
    f"{CANONICAL_PREFIX} My preference is that private key values use PREFIX-SENSITIVE-LAMBDA."
)
ENGLISH_PREFERENCE = (
    "I prefer durable English plans to separate verified history from live repository state."
)
TEMPORARY = "这一个任务我默认要求只输出 TEMP-OMEGA 三段。"
HYPOTHETICAL = "我的偏好可能是每次只输出 HYPOTHETICAL-OMEGA 三段，但我还没决定。"
QUOTED = "示例：‘我默认要求所有计划都只有 QUOTED-OMEGA 一个阶段。’"
ACKNOWLEDGEMENT = "明白了，我会记住 ACKPROMOTE-OMEGA 用户偏好，每个计划都必须可验证。"
ASSISTANT_LITERAL = f"用户偏好：{CHINESE_PREFERENCE}"
UNRELATED_HISTORY = (
    "Decision: CedarCanvas renderer ownership remains in the client adapter after the migration."
)
PROJECT_HISTORY = (
    "Decision: QuartzLedger history completed the P1 storage review before the staged program map."
)
PROJECT_MAP = (
    "Reusable fact: QuartzLedger program map orders P2 ingestion, P3 planning, "
    "P4 execution, and P5 observability."
)
LIVE_MARKER = "LIVE-HEAD-ZETA"

GOAL_QUERIES = (
    "请按我长期偏好编写下一步 GoalSpec-Zeta 目标提示词，要求详细、可验证、可收敛，并避免无限堆叠细节",
    "GoalSpec-Zeta 可验证 可收敛",
)
PREFIXED_GOAL_QUERY = "PrefixGoal-Lambda 可验证 可收敛"
SATURATED_GOAL_QUERY = "SaturatedGoal-Omega source-bound evidence"
ENGLISH_QUERY = "durable English plans verified"
PROJECT_QUERY = "QuartzLedger program map P2"
WRONG_PROJECT_QUERY = "CedarCanvas renderer ownership"
NO_HIT_QUERY = "AbsentNimbus UnrecordedFacet QX-404"
BROAD_QUERY = (
    "请结合 QuartzLedger 当前 HEAD reviewed tests P1 P2 P3 P4 P5 program map "
    "以及 GoalSpec-Zeta 可验证 可收敛 长期偏好判断现在是否全部完成"
)

CHINESE_MARKERS = ("GoalSpec-Zeta", "可验证", "可收敛", "无限堆叠")
PREFIXED_CHINESE_MARKERS = ("PrefixGoal-Lambda", "可验证", "可收敛")
MULTI_PREFIXED_ENGLISH_MARKERS = ("PrefixEnglish-Lambda", "source anchors")
SATURATED_GOAL_MARKERS = ("SaturatedGoal-Omega", "source-bound evidence")
SATURATED_DECISION_MARKERS = ("SaturationDecision", "bounded review")
ENGLISH_MARKERS = ("durable English plans", "verified history", "live repository state")
PROJECT_MARKERS = ("QuartzLedger", "program map", "P2", "P5")
REJECTION_MARKERS = {
    "temporary": ("TEMP-OMEGA",),
    "hypothetical": ("HYPOTHETICAL-OMEGA",),
    "quoted": ("QUOTED-OMEGA",),
    "acknowledgement": ("ACKPROMOTE-OMEGA",),
}
SOURCE_ADAPTER_REJECTION_MARKERS = {
    "arbitrary_markdown_path": ("PathLeak-Lambda",),
    "malformed_prefix": ("Malformed-Lambda",),
    "body_skill_link": ("BodyLink-Lambda",),
    "prefixed_temporary": ("PREFIX-TEMP-LAMBDA",),
    "prefixed_hypothetical": ("PREFIX-HYPOTHETICAL-LAMBDA",),
    "prefixed_quoted": ("PREFIX-QUOTED-LAMBDA",),
    "prefixed_acknowledgement": ("PREFIX-ACK-LAMBDA",),
    "prefixed_sensitive": ("PREFIX-SENSITIVE-LAMBDA",),
}
INVOCATION_ARTIFACT_MARKERS = ("[$using-", "/Users/example/", "SKILL.md")
PROCESS_MARKERS = ("transient checklist item",)
PRIVACY_MARKERS = (
    CANONICAL_PREFIX,
    SECOND_CANONICAL_PREFIX,
    PREFIXED_CHINESE_PREFERENCE,
    MULTI_PREFIXED_ENGLISH_PREFERENCE,
    SATURATED_GOAL_PREFERENCE,
    SATURATED_FINAL_STATE,
    INVOCATION_ONLY,
    ARBITRARY_MARKDOWN_PATH,
    MALFORMED_PREFIX,
    BODY_SKILL_LINK,
    PREFIXED_TEMPORARY,
    PREFIXED_HYPOTHETICAL,
    PREFIXED_QUOTED,
    PREFIXED_ACKNOWLEDGEMENT,
    PREFIXED_SENSITIVE,
    CHINESE_PREFERENCE,
    ENGLISH_PREFERENCE,
    TEMPORARY,
    HYPOTHETICAL,
    QUOTED,
    ACKNOWLEDGEMENT,
    ASSISTANT_LITERAL,
    UNRELATED_HISTORY,
    PROJECT_HISTORY,
    PROJECT_MAP,
    *GOAL_QUERIES,
    PREFIXED_GOAL_QUERY,
    SATURATED_GOAL_QUERY,
    ENGLISH_QUERY,
    PROJECT_QUERY,
    WRONG_PROJECT_QUERY,
    NO_HIT_QUERY,
    BROAD_QUERY,
    LIVE_MARKER,
)
REQUIRED_METRICS = frozenset(
    {
        "canonical_skill_prefixed_preference_recall",
        "multi_skill_prefix_recall",
        "prefixed_preference_source_binding_rate",
        "selected_natural_user_fact_evidence_binding_rate",
        "selected_natural_user_fact_source_anchor_rate",
        "selected_natural_user_fact_candidate_materialization_rate",
        "selected_natural_user_fact_active_memory_rate",
        "goal_preference_context_package_support_rate",
        "remaining_evidence_priority_regression_rate",
        "evidence_budget_overflow_count",
        "non_target_memory_promotion_count",
        "invocation_only_rejection_rate",
        "arbitrary_markdown_path_rejection_rate",
        "malformed_prefix_rejection_rate",
        "prefixed_non_durable_rejection_rate",
        "standalone_preference_regression_rate",
        "invocation_artifact_leak_count",
        "synthetic_case_count",
        "durable_chinese_preference_extraction_recall",
        "durable_english_preference_regression_rate",
        "long_session_middle_preference_recall",
        "noise_insertion_stability_rate",
        "temporary_constraint_rejection_rate",
        "hypothetical_statement_rejection_rate",
        "quoted_prompt_rejection_rate",
        "assistant_acknowledgement_promotion_count",
        "global_preference_scope_accuracy",
        "bounded_facet_plan_accuracy",
        "natural_goal_preference_supported_recall",
        "project_history_supported_recall",
        "live_state_memory_answer_count",
        "wrong_project_supported_hit_count",
        "broad_query_false_answer_count",
        "max_query_variants_per_facet",
        "unsupported_claim_count",
        "privacy_leak_count",
    }
)


class GateFailure(RuntimeError):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def report(self) -> dict[str, object]:
        result: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            result["returncode"] = self.returncode
        return result


@dataclass(frozen=True)
class Fixture:
    noisy_record: Path
    control_record: Path
    saturated_record: Path
    long_project: Path
    neutral_project: Path
    long_turn_count: int
    noisy_user_line: int
    prefixed_user_line: int
    multi_prefixed_user_line: int
    saturated_user_line: int


@dataclass(frozen=True)
class Facet:
    kind: str
    packages: tuple[object, ...] = ()
    layer: str = ""
    scope: str = ""
    project_context: bool | None = None
    free_form: str = ""


@dataclass(frozen=True)
class Decision:
    action: str
    package_supported: bool
    variants_examined: int
    free_form_used: bool = False


def command(argv: list[str], stage: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )
    if result.returncode:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result.stdout


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_packaged_archive(root: Path) -> Path:
    repo = root / "archive"
    command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        "setup_archive",
    )
    for source in RUNTIME_SOURCES:
        target = repo / "tools" / source.name
        if not source.is_file() or not target.is_file():
            raise GateFailure("packaged_runtime", "runtime_tool_missing")
        if digest(source) != digest(target):
            raise GateFailure("packaged_runtime", "runtime_tool_hash_mismatch")
    return repo


def timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def write_record(root: Path, name: str, events: list[dict[str, str]], updated_at: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "record.jsonl"
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    stamp = timestamp(updated_at)
    os.utime(path, (stamp, stamp))
    return path


def noise(start: int, stop: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ordinal in range(start, stop):
        rows.extend(
            [
                {
                    "role": "user",
                    "content": f"Can you inspect transient checklist item {ordinal:02d}?",
                },
                {
                    "role": "assistant",
                    "content": f"I will inspect transient checklist item {ordinal:02d} and report status.",
                },
            ]
        )
    return rows


def long_events() -> list[dict[str, str]]:
    rows = noise(1, 9)
    rows.append({"role": "assistant", "content": UNRELATED_HISTORY})
    rows.extend(noise(9, 17))
    rows.append({"role": "assistant", "content": ASSISTANT_LITERAL})
    rows.append({"role": "user", "content": CHINESE_PREFERENCE})
    rows.append({"role": "user", "content": PREFIXED_CHINESE_PREFERENCE})
    rows.append({"role": "user", "content": MULTI_PREFIXED_ENGLISH_PREFERENCE})
    rows.extend(noise(17, 25))
    rows.extend(
        [
            {"role": "user", "content": INVOCATION_ONLY},
            {"role": "user", "content": ARBITRARY_MARKDOWN_PATH},
            {"role": "user", "content": MALFORMED_PREFIX},
            {"role": "user", "content": BODY_SKILL_LINK},
            {"role": "user", "content": PREFIXED_TEMPORARY},
            {"role": "user", "content": PREFIXED_HYPOTHETICAL},
            {"role": "user", "content": PREFIXED_QUOTED},
            {"role": "user", "content": PREFIXED_ACKNOWLEDGEMENT},
            {"role": "user", "content": PREFIXED_SENSITIVE},
            {"role": "user", "content": ENGLISH_PREFERENCE},
            {"role": "user", "content": TEMPORARY},
            {"role": "user", "content": HYPOTHETICAL},
            {"role": "user", "content": QUOTED},
            {"role": "assistant", "content": ACKNOWLEDGEMENT},
            {"role": "assistant", "content": "I will finish this transient inspection."},
        ]
    )
    return rows


def saturated_events() -> list[dict[str, str]]:
    rows = [
        {
            "role": "assistant",
            "content": f"Decision: SaturationDecision-{name} requires bounded review.",
        }
        for name in ("alpha", "beta", "gamma", "delta", "epsilon")
    ]
    rows.extend(
        {
            "role": "assistant",
            "content": f"Synthetic retrieval endpoint is 127.0.0.1:{port}.",
        }
        for port in range(4300, 4308)
    )
    rows.extend(
        [
            {"role": "user", "content": SATURATED_GOAL_PREFERENCE},
            {"role": "assistant", "content": SATURATED_FINAL_STATE},
        ]
    )
    return rows


def create_fixture(root: Path) -> Fixture:
    long_source, project_source = root / "long", root / "project"
    long_project, neutral_project = root / "c", root / "q"
    long_project.mkdir(parents=True)
    neutral_project.mkdir()
    events = long_events()
    noisy_user_line = next(
        index
        for index, event in enumerate(events, 1)
        if event.get("role") == "user" and event.get("content") == CHINESE_PREFERENCE
    )
    prefixed_user_line = next(
        index
        for index, event in enumerate(events, 1)
        if event.get("role") == "user" and event.get("content") == PREFIXED_CHINESE_PREFERENCE
    )
    multi_prefixed_user_line = next(
        index
        for index, event in enumerate(events, 1)
        if event.get("role") == "user"
        and event.get("content") == MULTI_PREFIXED_ENGLISH_PREFERENCE
    )
    noisy = write_record(long_source, "noisy", events, "2026-07-02T10:00:00Z")
    saturated = saturated_events()
    saturated_user_line = next(
        index
        for index, event in enumerate(saturated, 1)
        if event.get("role") == "user" and event.get("content") == SATURATED_GOAL_PREFERENCE
    )
    saturated_record = write_record(
        long_source,
        "saturated",
        saturated,
        "2026-07-04T10:00:00Z",
    )
    control = write_record(
        long_source,
        "control",
        [
            {"role": "user", "content": CHINESE_PREFERENCE},
            {"role": "assistant", "content": "I will finish this synthetic control."},
        ],
        "2026-07-01T10:00:00Z",
    )
    write_record(
        project_source,
        "history",
        [
            {"role": "user", "content": "Summarize the durable program history."},
            {"role": "assistant", "content": PROJECT_HISTORY},
            {"role": "assistant", "content": PROJECT_MAP},
        ],
        "2026-07-03T10:00:00Z",
    )
    return Fixture(
        noisy,
        control,
        saturated_record,
        long_project,
        neutral_project,
        len(events),
        noisy_user_line,
        prefixed_user_line,
        multi_prefixed_user_line,
        saturated_user_line,
    )


def update(repo: Path, source: Path, project: Path, name: str) -> None:
    command(
        [
            sys.executable,
            str(repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--source-dir",
            str(source),
            "--project-path",
            str(project),
            "--project",
            name,
            "--source-agent",
            "v250-public-synthetic",
            "--rewrite-existing",
        ],
        "update_archive",
        repo,
    )


def parse_package(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) and value.get("report_kind") == CONTEXT_KIND else None


def search(
    repo: Path,
    query: str,
    *,
    scope: str = "all",
    preferred: str = "",
    project: Path | None = None,
) -> dict[str, Any]:
    argv = [
        sys.executable,
        str(repo / "tools/search_memory.py"),
        query,
        "--repo",
        str(repo),
        "--limit",
        "5",
        "--depth",
        "evidence",
        "--context-json",
        "--scope",
        scope,
    ]
    if preferred:
        argv.extend(["--preferred-scope", preferred])
    if project is not None:
        argv.extend(["--project-path", str(project)])
    package = parse_package(command(argv, "search_archive", repo))
    if package is None:
        raise GateFailure("search_archive", "context_package_invalid")
    return package


def package_supported_hit(hit: object) -> bool:
    if not isinstance(hit, dict) or hit.get("active_current") is not True:
        return False
    answerability, support = hit.get("answerability"), hit.get("query_support")
    return bool(
        isinstance(answerability, dict)
        and answerability.get("status") == "supported"
        and isinstance(support, dict)
        and support.get("status") == "supported"
        and hit.get("summary_drill_paths")
        and hit.get("evidence_drill_paths")
    )


def supported_hit(hit: object, facet: Facet) -> bool:
    return bool(
        package_supported_hit(hit)
        and isinstance(hit, dict)
        and (not facet.layer or hit.get("layer") == facet.layer)
        and (not facet.scope or hit.get("scope") == facet.scope)
    )


def decide(facet: Facet) -> Decision:
    if facet.kind == "live":
        return Decision("route_repository", False, 0)
    if facet.kind != "history" or len(facet.packages) > MAX_VARIANTS:
        return Decision("abstain", False, min(len(facet.packages), MAX_VARIANTS))
    for ordinal, value in enumerate(facet.packages, 1):
        package = parse_package(value)
        if package is None:
            continue
        query, answerability, hits = (
            package.get("query"),
            package.get("answerability"),
            package.get("hits"),
        )
        context_ok = facet.project_context is None or (
            isinstance(query, dict)
            and query.get("project_context_provided") is facet.project_context
        )
        if (
            context_ok
            and isinstance(answerability, dict)
            and answerability.get("status") == "supported"
            and isinstance(hits, list)
            and any(supported_hit(hit, facet) for hit in hits[:5])
        ):
            return Decision("answer", True, ordinal)
    return Decision("abstain", False, len(facet.packages))


def package_fixture(
    *,
    package_status: str = "supported",
    active: bool = True,
    hit_status: str = "supported",
    support_status: str = "supported",
    layer: str = "global",
    scope: str = "global",
    summary: bool = True,
    evidence: bool = True,
    project_context: bool = False,
) -> dict[str, Any]:
    return {
        "report_kind": CONTEXT_KIND,
        "query": {"project_context_provided": project_context},
        "answerability": {"status": package_status},
        "hits": [
            {
                "active_current": active,
                "answerability": {"status": hit_status},
                "query_support": {"status": support_status},
                "layer": layer,
                "scope": scope,
                "summary_drill_paths": ["fixture/summary.md"] if summary else [],
                "evidence_drill_paths": ["fixture/evidence.md"] if evidence else [],
            }
        ],
    }


def bounded_contract() -> tuple[float, int, int]:
    good = package_fixture()
    cases = (
        (Facet("history", (good,), layer="global", scope="global"), "answer"),
        (Facet("history", (package_fixture(package_status="unsupported"),), free_form="answer"), "abstain"),
        (Facet("history", (package_fixture(active=False),)), "abstain"),
        (Facet("history", (package_fixture(support_status="weak"),)), "abstain"),
        (Facet("history", (package_fixture(evidence=False),)), "abstain"),
        (Facet("history", ("{malformed",)), "abstain"),
        (
            Facet(
                "history",
                (package_fixture(layer="project", scope="project:other", project_context=True),),
                layer="project",
                scope="project:current",
                project_context=True,
            ),
            "abstain",
        ),
        (Facet("live", (good,), free_form="answer"), "route_repository"),
    )
    decisions = [(decide(facet), expected) for facet, expected in cases]
    correct = sum(
        decision.action == expected and not decision.free_form_used
        for decision, expected in decisions
    )
    unsupported = sum(
        decision.action == "answer" and not decision.package_supported
        for decision, _ in decisions
    )
    return correct / len(cases), 1, unsupported


def jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def meta_rows(repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((repo / "sessions").glob("**/meta.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def contains(value: object, markers: tuple[str, ...]) -> bool:
    text = str(value or "").lower()
    return all(marker.lower() in text for marker in markers)


def active(node: dict[str, Any]) -> bool:
    return not (
        isinstance(node.get("superseded_by"), str)
        or isinstance(node.get("deprecated_by"), str)
        or bool(node.get("contradicted_by"))
    )


def drillable(repo: Path, node: dict[str, Any]) -> bool:
    summaries = [repo / path for path in node.get("derived_from", []) if isinstance(path, str)]
    evidence = [
        repo / ref["path"]
        for ref in node.get("evidence_refs", [])
        if isinstance(ref, dict) and isinstance(ref.get("path"), str)
    ]
    return bool(summaries and evidence) and all(path.is_file() for path in (*summaries, *evidence))


def nodes_for(repo: Path, nodes: list[dict[str, Any]], markers: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        node
        for node in nodes
        if node.get("source") == "automatic"
        and active(node)
        and contains(node.get("text"), markers)
        and drillable(repo, node)
    ]


def meta_for(rows: list[dict[str, Any]], record: Path) -> dict[str, Any] | None:
    target = record.resolve()
    for row in rows:
        source = row.get("source_record")
        if isinstance(source, str) and source and Path(source).resolve() == target:
            return row
    return None


def bound_user_fact(
    repo: Path,
    meta: dict[str, Any] | None,
    markers: tuple[str, ...],
    *,
    expected_line: int,
    expected_text: str,
) -> bool:
    if not isinstance(meta, dict):
        return False
    facts = meta.get("reusable_facts")
    if not isinstance(facts, list) or not any(contains(fact, markers) for fact in facts):
        return False
    sources: list[dict[str, Any]] = []
    for key in ("reusable_fact_sources", "memory_candidate_sources"):
        values = meta.get(key)
        if isinstance(values, list):
            sources.extend(value for value in values if isinstance(value, dict))
    source = next(
        (
            value
            for value in sources
            if contains(value.get("text"), markers)
            and value.get("source") == "natural_user"
            and bool(value.get("evidence_quote_id"))
            and bool(value.get("source_anchor_id"))
        ),
        None,
    )
    source_map_path = meta.get("source_map_path")
    if source is None or not isinstance(source_map_path, str):
        return False
    path = repo / source_map_path
    try:
        source_map = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    anchors = source_map.get("evidence_source_anchors") if isinstance(source_map, dict) else None
    if not isinstance(anchors, list):
        return False
    normalized_expected = " ".join(expected_text.split())
    expected_hash = hashlib.sha256(normalized_expected.encode("utf-8")).hexdigest()
    return any(
        isinstance(anchor, dict)
        and anchor.get("source_anchor_id") == source.get("source_anchor_id")
        and anchor.get("quote_id") == source.get("evidence_quote_id")
        and anchor.get("line_number") == expected_line
        and anchor.get("event_ordinal") == 1
        and anchor.get("event_sha256") == expected_hash
        for anchor in anchors
    )


def source_entry(
    meta: dict[str, Any] | None,
    key: str,
    markers: tuple[str, ...],
) -> dict[str, Any] | None:
    if not isinstance(meta, dict):
        return None
    values = meta.get(key)
    if not isinstance(values, list):
        return None
    return next(
        (
            value
            for value in values
            if isinstance(value, dict) and contains(value.get("text"), markers)
        ),
        None,
    )


def evidence_quote_count(repo: Path, meta: dict[str, Any] | None) -> int:
    if not isinstance(meta, dict) or not isinstance(meta.get("evidence_path"), str):
        return 0
    try:
        lines = (repo / meta["evidence_path"]).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(
        line.startswith("ev_") and line.partition(":")[0][3:].isdigit()
        for line in lines
    )


def evidence_contains(
    repo: Path,
    meta: dict[str, Any] | None,
    markers: tuple[str, ...],
) -> bool:
    if not isinstance(meta, dict) or not isinstance(meta.get("evidence_path"), str):
        return False
    try:
        text = (repo / meta["evidence_path"]).read_text(encoding="utf-8")
    except OSError:
        return False
    return contains(text, markers)


def all_candidate_texts(rows: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[str]:
    texts = [str(node.get("text") or "") for node in nodes]
    for row in rows:
        facts = row.get("reusable_facts")
        if isinstance(facts, list):
            texts.extend(str(fact) for fact in facts)
        for key in ("reusable_fact_sources", "memory_candidate_sources"):
            sources = row.get(key)
            if not isinstance(sources, list):
                continue
            texts.extend(
                str(source.get("text") or "")
                for source in sources
                if isinstance(source, dict)
            )
    return texts


def leak_count(report: dict[str, Any], paths: Iterable[Path]) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return sum(marker in rendered for marker in PRIVACY_MARKERS) + sum(
        str(path) in rendered for path in paths if str(path)
    )


def run_once(root: Path) -> dict[str, Any]:
    repo = setup_packaged_archive(root)
    fixture = create_fixture(root / "fixture")
    update(repo, root / "fixture/long", fixture.long_project, "CedarCanvas")
    update(repo, root / "fixture/project", fixture.neutral_project, "QuartzLedger")

    nodes = jsonl(repo / "index" / "memories.jsonl")
    rows = meta_rows(repo)
    noisy, control = meta_for(rows, fixture.noisy_record), meta_for(rows, fixture.control_record)
    saturated = meta_for(rows, fixture.saturated_record)
    chinese_nodes = nodes_for(repo, nodes, CHINESE_MARKERS)
    prefixed_chinese_nodes = nodes_for(repo, nodes, PREFIXED_CHINESE_MARKERS)
    multi_prefixed_english_nodes = nodes_for(repo, nodes, MULTI_PREFIXED_ENGLISH_MARKERS)
    saturated_nodes = nodes_for(repo, nodes, SATURATED_GOAL_MARKERS)
    english_nodes = nodes_for(repo, nodes, ENGLISH_MARKERS)
    project_nodes = nodes_for(repo, nodes, PROJECT_MARKERS)

    goal_packages = tuple(
        search(repo, query, scope="global", preferred="global") for query in GOAL_QUERIES
    )
    prefixed_package = search(
        repo,
        PREFIXED_GOAL_QUERY,
        scope="global",
        preferred="global",
    )
    saturated_package = search(
        repo,
        SATURATED_GOAL_QUERY,
        scope="global",
        preferred="global",
    )
    english_package = search(repo, ENGLISH_QUERY, scope="global", preferred="global")
    project_package = search(
        repo,
        PROJECT_QUERY,
        scope="project",
        preferred="project",
        project=fixture.neutral_project,
    )
    wrong_package = search(
        repo,
        WRONG_PROJECT_QUERY,
        scope="project",
        preferred="project",
        project=fixture.neutral_project,
    )
    no_hit_package = search(repo, NO_HIT_QUERY, scope="global", preferred="global")
    broad_package = search(repo, BROAD_QUERY, project=fixture.neutral_project)

    neutral_scope = f"project:{fixture.neutral_project.resolve()}"
    goal = decide(Facet("history", goal_packages, "global", "global", False))
    prefixed = decide(Facet("history", (prefixed_package,), "global", "global", False))
    saturated_goal = decide(
        Facet("history", (saturated_package,), "global", "global", False)
    )
    english = decide(Facet("history", (english_package,), "global", "global", False))
    project = decide(Facet("history", (project_package,), "project", neutral_scope, True))
    wrong = decide(Facet("history", (wrong_package,), "project", neutral_scope, True))
    no_hit = decide(Facet("history", (no_hit_package,), free_form="answer"))
    broad = decide(Facet("history", (broad_package,)))
    live = decide(Facet("live", (project_package,), free_form="answer"))

    noisy_bound = bound_user_fact(
        repo,
        noisy,
        CHINESE_MARKERS,
        expected_line=fixture.noisy_user_line,
        expected_text=CHINESE_PREFERENCE,
    )
    control_bound = bound_user_fact(
        repo,
        control,
        CHINESE_MARKERS,
        expected_line=1,
        expected_text=CHINESE_PREFERENCE,
    )
    prefixed_bound = bound_user_fact(
        repo,
        noisy,
        PREFIXED_CHINESE_MARKERS,
        expected_line=fixture.prefixed_user_line,
        expected_text=PREFIXED_CHINESE_PREFERENCE,
    )
    multi_prefixed_bound = bound_user_fact(
        repo,
        noisy,
        MULTI_PREFIXED_ENGLISH_MARKERS,
        expected_line=fixture.multi_prefixed_user_line,
        expected_text=MULTI_PREFIXED_ENGLISH_PREFERENCE,
    )
    saturated_bound = bound_user_fact(
        repo,
        saturated,
        SATURATED_GOAL_MARKERS,
        expected_line=fixture.saturated_user_line,
        expected_text=SATURATED_GOAL_PREFERENCE,
    )
    saturated_fact_source = source_entry(
        saturated,
        "reusable_fact_sources",
        SATURATED_GOAL_MARKERS,
    )
    saturated_candidate_source = source_entry(
        saturated,
        "memory_candidate_sources",
        SATURATED_GOAL_MARKERS,
    )
    saturated_evidence_count = evidence_quote_count(repo, saturated)
    support_paths = {
        path
        for node in chinese_nodes
        for path in node.get("derived_from", [])
        if isinstance(path, str)
    }
    noisy_summary = str(noisy.get("summary_path") or "") if isinstance(noisy, dict) else ""
    control_summary = str(control.get("summary_path") or "") if isinstance(control, dict) else ""
    chinese_materialized = bool(chinese_nodes and noisy_bound)
    middle_recalled = bool(chinese_materialized and noisy_summary in support_paths)
    noise_stable = bool(
        noisy_bound
        and control_bound
        and {noisy_summary, control_summary}.issubset(support_paths)
    )
    english_bound = bool(
        isinstance(noisy, dict)
        and any(
            contains(source.get("text"), ENGLISH_MARKERS)
            and source.get("source") == "natural_user"
            for source in noisy.get("reusable_fact_sources", [])
            if isinstance(source, dict)
        )
    )
    chinese_global = any(node.get("layer") == "global" and node.get("scope") == "global" for node in chinese_nodes)
    english_global = any(node.get("layer") == "global" and node.get("scope") == "global" for node in english_nodes)
    project_scoped = any(node.get("layer") == "project" and node.get("scope") == neutral_scope for node in project_nodes)
    texts = all_candidate_texts(rows, nodes)
    bounded_accuracy, bounded_variants, bounded_unsupported = bounded_contract()
    decisions = (goal, prefixed, saturated_goal, english, project, wrong, no_hit, broad, live)
    unsupported = bounded_unsupported + sum(
        decision.action == "answer" and not decision.package_supported for decision in decisions
    )
    live_nodes = sum(contains(node.get("text"), (LIVE_MARKER,)) for node in nodes)
    wrong_facet = Facet("history", (), "project", neutral_scope, True)
    wrong_hits = wrong_package.get("hits")
    wrong_hits = wrong_hits if isinstance(wrong_hits, list) else []
    raw_wrong_scope_supported_hits = sum(
        package_supported_hit(hit)
        and isinstance(hit, dict)
        and hit.get("scope") != neutral_scope
        for hit in wrong_hits
    )
    wrong_supported_hits = sum(
        package_supported_hit(hit)
        and isinstance(hit, dict)
        and hit.get("scope") != neutral_scope
        and supported_hit(hit, wrong_facet)
        for hit in wrong_hits
    )
    process_promotion_count = sum(contains(text, PROCESS_MARKERS) for text in texts)
    invocation_artifact_count = sum(
        any(marker.lower() in text.lower() for marker in INVOCATION_ARTIFACT_MARKERS)
        for text in texts
    )
    source_adapter_rejections = {
        name: not any(contains(text, markers) for text in texts)
        for name, markers in SOURCE_ADAPTER_REJECTION_MARKERS.items()
    }
    invocation_only_rejected = not any(text.strip() == INVOCATION_ONLY for text in texts)
    prefixed_materialized = bool(prefixed_chinese_nodes and prefixed_bound)
    multi_prefixed_materialized = bool(multi_prefixed_english_nodes and multi_prefixed_bound)
    saturated_evidence_bound = bool(
        isinstance(saturated_fact_source, dict)
        and saturated_fact_source.get("source") == "natural_user"
        and saturated_fact_source.get("evidence_quote_id")
    )
    saturated_anchor_bound = bool(
        saturated_bound
        and isinstance(saturated_fact_source, dict)
        and saturated_fact_source.get("source_anchor_id")
    )
    saturated_candidate_materialized = bool(
        isinstance(saturated_candidate_source, dict)
        and saturated_candidate_source.get("source") == "natural_user"
        and saturated_candidate_source.get("evidence_quote_id")
        and saturated_candidate_source.get("source_anchor_id")
    )
    remaining_priority_preserved = bool(
        evidence_contains(repo, saturated, SATURATED_DECISION_MARKERS)
    )
    non_target_promotions = sum(
        any(
            contains(node.get("text"), markers)
            for markers in SOURCE_ADAPTER_REJECTION_MARKERS.values()
        )
        for node in nodes
    )

    case_outcomes = {
        "canonical_skill_prefixed_preference": bool(
            prefixed_materialized and prefixed.action == "answer"
        ),
        "saturated_source_bound_goal_preference": bool(
            saturated_evidence_bound
            and saturated_anchor_bound
            and saturated_candidate_materialized
            and saturated_nodes
            and saturated_goal.action == "answer"
            and remaining_priority_preserved
            and saturated_evidence_count <= 6
        ),
        "multi_skill_prefixed_preference": multi_prefixed_materialized,
        "invocation_only": invocation_only_rejected,
        **source_adapter_rejections,
        "durable_chinese_noisy": bool(chinese_materialized and noisy_bound and middle_recalled),
        "durable_chinese_control": bool(control_bound),
        "durable_english": bool(english_bound and english_global and english.action == "answer"),
        "temporary_constraint": not any(
            contains(text, REJECTION_MARKERS["temporary"]) for text in texts
        ),
        "hypothetical_statement": not any(
            contains(text, REJECTION_MARKERS["hypothetical"]) for text in texts
        ),
        "quoted_prompt": not any(contains(text, REJECTION_MARKERS["quoted"]) for text in texts),
        "assistant_acknowledgement": not any(
            contains(text, REJECTION_MARKERS["acknowledgement"]) for text in texts
        ),
        "project_history": bool(project_nodes and project_scoped and project.action == "answer"),
        "wrong_project": bool(
            raw_wrong_scope_supported_hits >= 1
            and wrong_supported_hits == 0
            and wrong.action == "abstain"
        ),
        "unsupported_no_hit": no_hit.action == "abstain",
        "broad_query": bool(
            isinstance(broad_package.get("query"), dict)
            and broad_package["query"].get("decomposition_recommended") is True
            and broad.action == "abstain"
        ),
        "live_state": bool(live.action == "route_repository" and live_nodes == 0),
    }

    metrics: dict[str, Any] = {
        "canonical_skill_prefixed_preference_recall": float(
            prefixed_materialized and prefixed.action == "answer"
        ),
        "multi_skill_prefix_recall": float(multi_prefixed_materialized),
        "prefixed_preference_source_binding_rate": (
            int(prefixed_bound) + int(multi_prefixed_bound)
        )
        / 2,
        "selected_natural_user_fact_evidence_binding_rate": float(
            saturated_evidence_bound
        ),
        "selected_natural_user_fact_source_anchor_rate": float(saturated_anchor_bound),
        "selected_natural_user_fact_candidate_materialization_rate": float(
            saturated_candidate_materialized
        ),
        "selected_natural_user_fact_active_memory_rate": float(bool(saturated_nodes)),
        "goal_preference_context_package_support_rate": float(
            saturated_goal.action == "answer"
        ),
        "remaining_evidence_priority_regression_rate": float(
            remaining_priority_preserved
        ),
        "evidence_budget_overflow_count": int(saturated_evidence_count > 6),
        "non_target_memory_promotion_count": non_target_promotions,
        "invocation_only_rejection_rate": float(invocation_only_rejected),
        "arbitrary_markdown_path_rejection_rate": float(
            source_adapter_rejections["arbitrary_markdown_path"]
        ),
        "malformed_prefix_rejection_rate": float(
            source_adapter_rejections["malformed_prefix"]
        ),
        "prefixed_non_durable_rejection_rate": sum(
            source_adapter_rejections[name]
            for name in (
                "prefixed_temporary",
                "prefixed_hypothetical",
                "prefixed_quoted",
                "prefixed_acknowledgement",
                "prefixed_sensitive",
            )
        )
        / 5,
        "standalone_preference_regression_rate": float(
            chinese_materialized
            and english_bound
            and english_global
            and goal.action == "answer"
            and english.action == "answer"
        ),
        "invocation_artifact_leak_count": invocation_artifact_count,
        "synthetic_case_count": len(case_outcomes),
        "durable_chinese_preference_extraction_recall": float(chinese_materialized),
        "durable_english_preference_regression_rate": float(
            english_bound and english_global and english.action == "answer"
        ),
        "long_session_middle_preference_recall": float(middle_recalled),
        "noise_insertion_stability_rate": float(noise_stable),
        "temporary_constraint_rejection_rate": float(case_outcomes["temporary_constraint"]),
        "hypothetical_statement_rejection_rate": float(case_outcomes["hypothetical_statement"]),
        "quoted_prompt_rejection_rate": float(case_outcomes["quoted_prompt"]),
        "assistant_acknowledgement_promotion_count": int(
            not case_outcomes["assistant_acknowledgement"]
        ),
        "global_preference_scope_accuracy": (int(chinese_global) + int(english_global)) / 2,
        "bounded_facet_plan_accuracy": bounded_accuracy,
        "natural_goal_preference_supported_recall": float(goal.action == "answer"),
        "project_history_supported_recall": float(case_outcomes["project_history"]),
        "live_state_memory_answer_count": int(not case_outcomes["live_state"]),
        "wrong_project_supported_hit_count": wrong_supported_hits,
        "broad_query_false_answer_count": int(broad.action == "answer"),
        "max_query_variants_per_facet": max(bounded_variants, len(goal_packages)),
        "unsupported_claim_count": unsupported,
        "privacy_leak_count": 0,
    }
    observations = {
        "canonical_skill_invocation_boundary_closed": bool(
            metrics["canonical_skill_prefixed_preference_recall"] == 1.0
            and metrics["multi_skill_prefix_recall"] == 1.0
            and metrics["prefixed_preference_source_binding_rate"] == 1.0
            and metrics["invocation_only_rejection_rate"] == 1.0
            and metrics["arbitrary_markdown_path_rejection_rate"] == 1.0
            and metrics["malformed_prefix_rejection_rate"] == 1.0
            and metrics["prefixed_non_durable_rejection_rate"] == 1.0
            and metrics["standalone_preference_regression_rate"] == 1.0
            and metrics["invocation_artifact_leak_count"] == 0
        ),
        "source_bound_goal_preference_boundary_closed": bool(
            metrics["selected_natural_user_fact_evidence_binding_rate"] == 1.0
            and metrics["selected_natural_user_fact_source_anchor_rate"] == 1.0
            and metrics["selected_natural_user_fact_candidate_materialization_rate"] == 1.0
            and metrics["selected_natural_user_fact_active_memory_rate"] == 1.0
            and metrics["goal_preference_context_package_support_rate"] == 1.0
            and metrics["remaining_evidence_priority_regression_rate"] == 1.0
            and metrics["evidence_budget_overflow_count"] == 0
            and metrics["non_target_memory_promotion_count"] == 0
        ),
        "durable_chinese_preference_boundary_closed": bool(
            metrics["durable_chinese_preference_extraction_recall"] == 1.0
            and metrics["long_session_middle_preference_recall"] == 1.0
            and metrics["noise_insertion_stability_rate"] == 1.0
            and metrics["natural_goal_preference_supported_recall"] == 1.0
        ),
        "broad_query_decomposition_boundary_closed": bool(
            isinstance(broad_package.get("query"), dict)
            and broad_package["query"].get("decomposition_recommended") is True
            and broad.action == "abstain"
        ),
        "process_only_rejection_closed": process_promotion_count == 0,
        "wrong_project_scope_rejection_closed": case_outcomes["wrong_project"],
        "synthetic_case_registry_closed": bool(
            set(case_outcomes) == set(SYNTHETIC_CASES) and all(case_outcomes.values())
        ),
    }
    result = {
        "metrics": metrics,
        "closure_observations": observations,
        "execution": {
            "packaged_setup_success_rate": 1.0,
            "packaged_runtime_tool_count": len(RUNTIME_SOURCES),
            "packaged_runtime_hash_match_rate": 1.0,
            "packaged_updater_success_rate": 1.0,
            "context_package_parse_success_rate": 1.0,
            "source_record_count": 4,
            "long_session_turn_count": fixture.long_turn_count,
            "saturated_session_turn_count": len(saturated_events()),
            "noise_turn_count": 48,
            "direct_final_memory_write_count": 0,
            "free_form_search_use_count": 0,
            "raw_wrong_project_related_supported_hit_count": raw_wrong_scope_supported_hits,
            "synthetic_case_pass_rate": sum(case_outcomes.values()) / len(case_outcomes),
        },
    }
    metrics["privacy_leak_count"] = leak_count(
        result,
        (
            root,
            repo,
            fixture.noisy_record,
            fixture.control_record,
            fixture.saturated_record,
        ),
    )
    return result


def metrics_pass(metrics: dict[str, Any]) -> bool:
    return bool(
        set(metrics) == REQUIRED_METRICS
        and metrics["synthetic_case_count"] >= 8
        and all(
            metrics[key] == 1.0
            for key in (
                "canonical_skill_prefixed_preference_recall",
                "multi_skill_prefix_recall",
                "prefixed_preference_source_binding_rate",
                "selected_natural_user_fact_evidence_binding_rate",
                "selected_natural_user_fact_source_anchor_rate",
                "selected_natural_user_fact_candidate_materialization_rate",
                "selected_natural_user_fact_active_memory_rate",
                "goal_preference_context_package_support_rate",
                "remaining_evidence_priority_regression_rate",
                "invocation_only_rejection_rate",
                "arbitrary_markdown_path_rejection_rate",
                "malformed_prefix_rejection_rate",
                "prefixed_non_durable_rejection_rate",
                "standalone_preference_regression_rate",
                "durable_chinese_preference_extraction_recall",
                "durable_english_preference_regression_rate",
                "long_session_middle_preference_recall",
                "noise_insertion_stability_rate",
                "temporary_constraint_rejection_rate",
                "hypothetical_statement_rejection_rate",
                "quoted_prompt_rejection_rate",
                "global_preference_scope_accuracy",
                "bounded_facet_plan_accuracy",
                "natural_goal_preference_supported_recall",
                "project_history_supported_recall",
            )
        )
        and metrics["invocation_artifact_leak_count"] == 0
        and metrics["evidence_budget_overflow_count"] == 0
        and metrics["non_target_memory_promotion_count"] == 0
        and metrics["assistant_acknowledgement_promotion_count"] == 0
        and metrics["live_state_memory_answer_count"] == 0
        and metrics["wrong_project_supported_hit_count"] == 0
        and metrics["broad_query_false_answer_count"] == 0
        and metrics["max_query_variants_per_facet"] <= MAX_VARIANTS
        and metrics["unsupported_claim_count"] == 0
        and metrics["privacy_leak_count"] == 0
    )


def build_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    match = len(runs) == 2 and runs[0] == runs[1]
    metrics = dict(runs[0]["metrics"])
    observations = dict(runs[0]["closure_observations"])
    failures: list[str] = []
    if not observations["canonical_skill_invocation_boundary_closed"]:
        failures.append("canonical_skill_invocation_boundary_open")
    if not observations["source_bound_goal_preference_boundary_closed"]:
        failures.append("source_bound_goal_preference_boundary_open")
    if not observations["durable_chinese_preference_boundary_closed"]:
        failures.append("durable_chinese_preference_boundary_open")
    if not observations["broad_query_decomposition_boundary_closed"]:
        failures.append("broad_query_decomposition_boundary_open")
    if not observations["process_only_rejection_closed"]:
        failures.append("process_only_rejection_open")
    if not observations["wrong_project_scope_rejection_closed"]:
        failures.append("wrong_project_scope_rejection_open")
    if not observations["synthetic_case_registry_closed"]:
        failures.append("synthetic_case_registry_open")
    if not metrics_pass(metrics):
        failures.append("public_metric_contract_failed")
    if not match:
        failures.append("aggregate_report_nondeterminism")
    return {
        "report_kind": REPORT_KIND,
        "report_version": 3,
        "status": "passed" if not failures else "failed",
        "failure_codes": failures,
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "metrics": metrics,
        "closure_observations": observations,
        "determinism": {"runs": len(runs), "aggregate_reports_match": match},
        "execution_contract": runs[0]["execution"],
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "memory_ids_rendered": False,
            "source_record_ids_rendered": False,
            "raw_refs_rendered": False,
            "local_paths_rendered": False,
        },
        "claim_boundary": (
            "public synthetic packaged utility only; not complete three-layer distribution parity, "
            "general semantic-memory quality, ranking quality, vector search, private archive "
            "correctness, live repository truth, public leaderboard parity, or LLM answer quality"
        ),
    }


def run_gate(root: Path) -> dict[str, Any]:
    return build_report([run_once(root / f"r{ordinal}") for ordinal in (1, 2)])


def work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="mpru-")
        return Path(temporary.name), temporary, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="mpru-", dir=parent))
    return root, None, root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir")
    args = parser.parse_args(argv)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    cleanup: Path | None = None
    try:
        root, temporary, cleanup = work_root(args.work_dir)
        report = run_gate(root)
    except (GateFailure, subprocess.TimeoutExpired) as failure:
        detail = failure.report() if isinstance(failure, GateFailure) else {"stage": "subprocess", "reason": "timeout"}
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure_codes": ["packaged_gate_execution_failed"],
            "failures": [detail],
            "privacy": {"aggregate_only": True},
        }
    finally:
        if temporary is not None:
            temporary.cleanup()
        elif cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
