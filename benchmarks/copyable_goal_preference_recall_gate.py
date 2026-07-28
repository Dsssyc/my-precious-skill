#!/usr/bin/env python3
"""Gate source-bound recall and runtime use of the copyable-goal preference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
TEMPLATE_UPDATER = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
TARGET_FACT = (
    "用户偏好：goal 提示词格式偏好是，默认将完整 Markdown goal 放入单独的 text 代码块，"
    "以可直接复制的纯文本形式交付，方便复制；代码块外不添加解释性前言或结语，"
    "内部存在代码围栏时使用更长且不冲突的外层围栏。"
)
GOAL_QUERIES = (
    "可直接复制 Markdown goal",
    "goal 提示词格式偏好",
    "纯文本 goal 方便复制",
    "我的 goal 应该怎样交付",
)
ABSENT_QUERY = "NebulaAbsentGoalFormat QX-917"
NON_TARGET_MARKERS = (
    "SpreadsheetComplaint-Zeta",
    "QuotedGoalFormat-Zeta",
    "HypotheticalGoalFormat-Zeta",
)
PRIVATE_LEAK_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
)
BASELINE_ABLATION_RUNNER = """
import importlib.util
import sys
from pathlib import Path

updater_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("copyable_goal_baseline_updater", updater_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.induce_copyable_goal_preference = lambda events: None
sys.argv = [str(updater_path), *sys.argv[2:]]
raise SystemExit(module.main())
""".strip()


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
class DeliveryDecision:
    history_action: str
    history_preference_used: bool
    current_instruction_used: bool
    artifact_first: bool | None
    copy_container: str
    explanatory_preamble: bool | None
    explanatory_epilogue: bool | None
    outer_fence: str


@dataclass(frozen=True)
class SourceBindingCounts:
    valid_evidence_count: int
    valid_source_anchor_count: int
    user_source_anchor_count: int
    non_user_source_anchor_count: int
    distinct_user_source_event_count: int


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def run_command(argv: list[str], stage: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
    )
    if result.returncode:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result.stdout


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_packaged_archive(root: Path, name: str) -> Path:
    memory_repo = root / name
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        f"setup_{name}",
    )
    packaged_updater = memory_repo / "tools/update_memory_archive.py"
    packaged_search = memory_repo / "tools/search_memory.py"
    if not packaged_updater.is_file() or not packaged_search.is_file():
        raise GateFailure("packaged_runtime", "required_tool_missing")
    if digest(packaged_updater) != digest(TEMPLATE_UPDATER):
        raise GateFailure("packaged_runtime", "updater_hash_mismatch")
    return memory_repo


def timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def write_record(path: Path, rows: list[dict[str, str]], updated_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    stamp = timestamp(updated_at)
    os.utime(path, (stamp, stamp))


def write_synthetic_sources(root: Path) -> tuple[Path, Path]:
    source_dir = root / "source-records"
    project_path = root / "synthetic-project"
    project_path.mkdir(parents=True, exist_ok=True)
    write_record(
        source_dir / "copyable-goal-corrections.jsonl",
        [
            {"role": "user", "content": "给一个 Markdown 版本的 goal。"},
            {"role": "assistant", "content": "I will describe the artifact before rendering it."},
            {"role": "user", "content": "注意排版一定要正确，不然我无法复制。"},
            {"role": "assistant", "content": "I will try another rendered layout."},
            {"role": "user", "content": "你看看你给的是纯 Markdown 吗，这个格式已经乱了。"},
            {"role": "assistant", "content": TARGET_FACT},
            {"role": "user", "content": "那你倒是把完整 goal 给我，不要继续解释。"},
        ],
        "2026-07-21T08:00:00Z",
    )
    write_record(
        source_dir / "non-target-corrections.jsonl",
        [
            {"role": "user", "content": "SpreadsheetComplaint-Zeta 页面排版很乱。"},
            {"role": "user", "content": "SpreadsheetComplaint-Zeta 表格内容无法复制。"},
            {"role": "user", "content": "给我一个 goal。"},
            {
                "role": "user",
                "content": "引用提示词：QuotedGoalFormat-Zeta 把完整 goal 放进 text 代码块。",
            },
            {
                "role": "user",
                "content": "如果以后写 goal，HypotheticalGoalFormat-Zeta 是不是应该用纯文本？",
            },
            {"role": "assistant", "content": TARGET_FACT},
        ],
        "2026-07-21T08:05:00Z",
    )
    return source_dir, project_path


def run_updater(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path,
    stage: str,
    *,
    allow_redacted_secrets: bool = False,
    disable_goal_induction: bool = False,
) -> None:
    updater = memory_repo / "tools/update_memory_archive.py"
    updater_argv = [
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--project",
        "synthetic-copyable-goal",
        "--source-agent",
        "synthetic-agent",
        "--rewrite-existing",
    ]
    if allow_redacted_secrets:
        updater_argv.append("--allow-redacted-secrets")
    argv = [sys.executable, str(updater), *updater_argv]
    if disable_goal_induction:
        argv = [
            sys.executable,
            "-c",
            BASELINE_ABLATION_RUNNER,
            str(updater),
            *updater_argv,
        ]
    run_command(
        argv,
        stage,
        cwd=memory_repo,
    )


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


def target_nodes(memory_repo: Path) -> list[dict[str, Any]]:
    return [
        row
        for row in read_jsonl(memory_repo / "index/memories.jsonl")
        if row.get("text") == TARGET_FACT
    ]


def session_meta_rows(memory_repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            rows.append(value)
    return rows


def run_context_package(memory_repo: Path, query: str) -> str:
    return run_command(
        [
            sys.executable,
            str(memory_repo / "tools/search_memory.py"),
            query,
            "--repo",
            str(memory_repo),
            "--depth",
            "evidence",
            "--context-json",
        ],
        "context_package_search",
        cwd=memory_repo,
    )


def load_context_package(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("report_kind") != CONTEXT_REPORT_KIND:
        return None
    return payload


def supported_hit(package: dict[str, Any] | None) -> dict[str, Any] | None:
    if package is None:
        return None
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return None
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
            and hit.get("summary_drill_paths")
            and hit.get("evidence_drill_paths")
        ):
            return hit
    return None


def archive_drill_paths_exist(memory_repo: Path, paths: object) -> bool:
    if not isinstance(paths, list) or not paths:
        return False
    repo_root = memory_repo.resolve()
    for path_text in paths:
        path = (memory_repo / str(path_text)).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            return False
        if not path.is_file():
            return False
    return True


def target_supported_hit(
    package: dict[str, Any] | None,
    memory_repo: Path,
    target_memory_ids: frozenset[str],
) -> dict[str, Any] | None:
    if package is None or not target_memory_ids:
        return None
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return None
    for hit in hits:
        if not isinstance(hit, dict) or str(hit.get("memory_id") or "") not in target_memory_ids:
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and archive_drill_paths_exist(memory_repo, hit.get("summary_drill_paths"))
            and archive_drill_paths_exist(memory_repo, hit.get("evidence_drill_paths"))
            and resolved_summary_fact(memory_repo, hit)
        ):
            return hit
    return None


def package_history_action(
    raw: str,
    *,
    memory_repo: Path | None = None,
    target_memory_ids: frozenset[str] = frozenset(),
) -> str:
    package = load_context_package(raw)
    if package is None or memory_repo is None or not target_memory_ids:
        return "abstain"
    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return "abstain"
    return (
        "answer"
        if target_supported_hit(package, memory_repo, target_memory_ids) is not None
        else "abstain"
    )


def current_format_instruction(text: str) -> str:
    if re.search(
        r"(?i)(?:不要|别|不用).{0,20}(?:代码块|围栏)|directly\s+render|直接.{0,12}渲染",
        text,
    ):
        return "rendered_markdown"
    if re.search(r"(?i)text\s*(?:代码块|围栏|fence|block)|纯文本|可复制", text):
        return "text_fence"
    return ""


def outer_backtick_fence(goal: str) -> str:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", goal)), default=0)
    return "`" * max(3, longest + 1)


def delivery_decision(
    raw_package: str,
    current_turn: str,
    goal: str,
    *,
    memory_repo: Path | None = None,
    target_memory_ids: frozenset[str] = frozenset(),
) -> DeliveryDecision:
    history_action = package_history_action(
        raw_package,
        memory_repo=memory_repo,
        target_memory_ids=target_memory_ids,
    )
    instruction = current_format_instruction(current_turn)
    if instruction == "rendered_markdown":
        return DeliveryDecision(
            history_action=history_action,
            history_preference_used=False,
            current_instruction_used=True,
            artifact_first=True,
            copy_container="rendered_markdown",
            explanatory_preamble=False,
            explanatory_epilogue=False,
            outer_fence="",
        )
    use_text_fence = instruction == "text_fence" or history_action == "answer"
    if not use_text_fence:
        return DeliveryDecision(
            history_action=history_action,
            history_preference_used=False,
            current_instruction_used=False,
            artifact_first=None,
            copy_container="unspecified",
            explanatory_preamble=None,
            explanatory_epilogue=None,
            outer_fence="",
        )
    return DeliveryDecision(
        history_action=history_action,
        history_preference_used=history_action == "answer" and not instruction,
        current_instruction_used=bool(instruction),
        artifact_first=True,
        copy_container="text_fence",
        explanatory_preamble=False,
        explanatory_epilogue=False,
        outer_fence=outer_backtick_fence(goal),
    )


def render_copyable_goal(goal: str, decision: DeliveryDecision) -> str:
    if decision.copy_container != "text_fence":
        return goal
    return f"{decision.outer_fence}text\n{goal}\n{decision.outer_fence}"


def inactive_package_text() -> str:
    return json.dumps(
        {
            "report_kind": CONTEXT_REPORT_KIND,
            "answerability": {"status": "unsupported", "reason": "no_active_current_support"},
            "hits": [],
        },
        sort_keys=True,
    )


def runtime_metrics(
    supported_package: str,
    unsupported_package: str,
    memory_repo: Path,
    target_memory_ids: frozenset[str],
) -> dict[str, float]:
    ordinary_goal = "# Goal\n\nDeliver one bounded result."
    nested_goal = "# Goal\n\n```bash\npython3 verify.py\n```"
    history_kwargs = {
        "memory_repo": memory_repo,
        "target_memory_ids": target_memory_ids,
    }
    supported = delivery_decision(
        supported_package,
        "请继续给出下一步 goal。",
        ordinary_goal,
        **history_kwargs,
    )
    explicit = delivery_decision(unsupported_package, "请把完整 goal 放进 text 代码块，方便复制。", ordinary_goal)
    neutral = delivery_decision(unsupported_package, "请继续给出下一步 goal。", ordinary_goal)
    inactive = delivery_decision(inactive_package_text(), "请用纯文本代码块交付 goal。", ordinary_goal)
    malformed = delivery_decision("{not-json", "请用 text 代码块交付 goal。", ordinary_goal)
    current_override = delivery_decision(
        supported_package,
        "这次不要代码块，直接渲染 Markdown。",
        ordinary_goal,
        **history_kwargs,
    )
    nested = delivery_decision(
        supported_package,
        "请继续给出下一步 goal。",
        nested_goal,
        **history_kwargs,
    )
    rendered_nested = render_copyable_goal(nested_goal, nested)

    copyable_cases = (supported, explicit, inactive, malformed)
    copyable_correct = sum(
        1
        for decision in copyable_cases
        if decision.artifact_first is True
        and decision.copy_container == "text_fence"
        and decision.explanatory_preamble is False
        and decision.explanatory_epilogue is False
    )
    precedence_cases = (explicit, inactive, malformed, current_override)
    precedence_correct = sum(
        1
        for decision in precedence_cases
        if decision.current_instruction_used
        and (
            decision.copy_container == "text_fence"
            if decision is not current_override
            else decision.copy_container == "rendered_markdown"
        )
    )
    nested_correct = int(
        nested.outer_fence == "````"
        and rendered_nested.startswith("````text\n")
        and rendered_nested.endswith("\n````")
        and nested_goal in rendered_nested
    )
    neutral_correct = int(
        neutral.history_action == "abstain"
        and not neutral.history_preference_used
        and neutral.copy_container == "unspecified"
    )
    return {
        "current_turn_instruction_precedence_accuracy": safe_rate(
            precedence_correct,
            len(precedence_cases),
        ),
        "copyable_text_block_decision_accuracy": safe_rate(
            copyable_correct + neutral_correct,
            len(copyable_cases) + 1,
        ),
        "nested_fence_collision_avoidance_accuracy": float(nested_correct),
    }


def source_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (source_text(item) for item in value))).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            text = source_text(value.get(key))
            if text:
                return text
    return ""


def source_events(value: object) -> list[tuple[str, str]]:
    if isinstance(value, list):
        events: list[tuple[str, str]] = []
        for item in value:
            events.extend(source_events(item))
        return events
    if not isinstance(value, dict):
        text = source_text(value)
        return [("record", text)] if text else []
    event_type = str(value.get("type") or "")
    if event_type in {"session_meta", "turn_context", "event_msg"}:
        return []
    payload = value.get("payload")
    body = payload if isinstance(payload, dict) else value
    body_type = str(body.get("type") or event_type)
    if body_type in {"function_call", "function_call_output"}:
        return [(body_type, "")]
    text = (
        source_text(body.get("content"))
        or source_text(body.get("text"))
        or source_text(body.get("message"))
    )
    if not text:
        return []
    role = str(body.get("role") or value.get("role") or "").lower()
    if role in {"user", "human"}:
        return [("user", text)]
    if role == "assistant":
        return [("assistant", text)]
    return [("record", text)]


def source_anchor_event(
    source_record: Path,
    line_number: int,
    event_ordinal: int,
) -> tuple[str, str]:
    if line_number <= 0 or event_ordinal <= 0 or not source_record.is_file():
        return "", ""
    try:
        line = source_record.read_text(encoding="utf-8").splitlines()[line_number - 1]
        events = source_events(json.loads(line))
    except (IndexError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", ""
    return events[event_ordinal - 1] if event_ordinal <= len(events) else ("", "")


def normalized_source_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def source_event_sha256(text: str) -> str:
    compacted = " ".join(text.split()).strip()
    return hashlib.sha256(compacted.encode("utf-8")).hexdigest()


def source_binding_counts(memory_repo: Path, node: dict[str, Any]) -> SourceBindingCounts:
    evidence_refs = node.get("evidence_refs") if isinstance(node.get("evidence_refs"), list) else []
    raw_refs = node.get("raw_refs") if isinstance(node.get("raw_refs"), list) else []
    valid_evidence_quotes: dict[str, str] = {}
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            continue
        path = memory_repo / str(ref.get("path") or "")
        quote_id = str(ref.get("quote_id") or "")
        if not path.is_file() or not quote_id:
            continue
        match = re.search(
            rf"(?m)^\s*{re.escape(quote_id)}\s*:\s*(?P<text>.*)$",
            path.read_text(encoding="utf-8"),
        )
        if match:
            valid_evidence_quotes[quote_id] = match.group("text")
    valid_raw = 0
    user_raw = 0
    non_user_raw = 0
    distinct_user_events: set[tuple[str, int, int]] = set()
    for ref in raw_refs:
        if not isinstance(ref, dict):
            continue
        path = memory_repo / str(ref.get("path") or "")
        anchor = str(ref.get("anchor") or "")
        if not path.is_file() or path.name != "source-map.json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        anchors = value.get("evidence_source_anchors") if isinstance(value, dict) else []
        anchor_row = next(
            (
                row
                for row in anchors or []
                if isinstance(row, dict) and row.get("source_anchor_id") == anchor
            ),
            None,
        )
        if anchor_row is None:
            continue
        quote_id = str(anchor_row.get("quote_id") or "")
        evidence_text = valid_evidence_quotes.get(quote_id, "")
        if not evidence_text:
            continue
        source_record_text = str(value.get("source_record") or "")
        source_record = Path(source_record_text).expanduser()
        if not source_record.is_absolute():
            source_record = memory_repo / source_record
        line_number = int(anchor_row.get("line_number") or 0)
        event_ordinal = int(anchor_row.get("event_ordinal") or 0)
        event_sha256 = str(anchor_row.get("event_sha256") or "")
        role, event_text = source_anchor_event(source_record, line_number, event_ordinal)
        normalized_evidence = normalized_source_text(evidence_text)
        normalized_event = normalized_source_text(event_text)
        if (
            not role
            or not normalized_evidence
            or normalized_evidence not in normalized_event
            or event_sha256 != source_event_sha256(event_text)
        ):
            continue
        valid_raw += 1
        if role == "user":
            user_raw += 1
            distinct_user_events.add(
                (str(source_record.resolve()), line_number, event_ordinal)
            )
        else:
            non_user_raw += 1
    return SourceBindingCounts(
        valid_evidence_count=len(valid_evidence_quotes),
        valid_source_anchor_count=valid_raw,
        user_source_anchor_count=user_raw,
        non_user_source_anchor_count=non_user_raw,
        distinct_user_source_event_count=len(distinct_user_events),
    )


def resolved_summary_fact(memory_repo: Path, hit: dict[str, Any]) -> bool:
    paths = hit.get("summary_drill_paths")
    if not isinstance(paths, list) or not paths:
        return False
    repo_root = memory_repo.resolve()
    for path_text in paths:
        path = (memory_repo / str(path_text)).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            continue
        if path.is_file() and TARGET_FACT in path.read_text(encoding="utf-8"):
            return True
    return False


def private_leak_count(report: dict[str, object]) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return sum(1 for pattern in PRIVATE_LEAK_PATTERNS if pattern.search(rendered))


def build_synthetic_report(root: Path) -> dict[str, object]:
    baseline_repo = setup_packaged_archive(root, "synthetic-baseline")
    memory_repo = setup_packaged_archive(root, "synthetic-candidate")
    source_dir, project_path = write_synthetic_sources(root)
    run_updater(
        baseline_repo,
        source_dir,
        project_path,
        "baseline_ablation_update",
        disable_goal_induction=True,
    )
    baseline_nodes = target_nodes(baseline_repo)
    baseline_target_ids = frozenset(
        str(node.get("memory_id") or "")
        for node in baseline_nodes
        if node.get("memory_id")
    )
    baseline_packages = [run_context_package(baseline_repo, query) for query in GOAL_QUERIES]
    baseline_supported = sum(
        target_supported_hit(load_context_package(raw), baseline_repo, baseline_target_ids)
        is not None
        for raw in baseline_packages
    )
    baseline_archived_sessions = len(session_meta_rows(baseline_repo))
    if not baseline_nodes and baseline_archived_sessions:
        baseline_failure_class = "memory_not_materialized"
    elif baseline_nodes and baseline_supported == 0:
        baseline_failure_class = "memory_materialized_but_not_recalled"
    elif baseline_supported:
        baseline_failure_class = "unexpected_supported_recall"
    else:
        baseline_failure_class = "source_not_archived"

    run_updater(memory_repo, source_dir, project_path, "candidate_update")

    nodes = target_nodes(memory_repo)
    node = nodes[0] if len(nodes) == 1 else {}
    target_memory_ids = frozenset(
        str(candidate.get("memory_id") or "")
        for candidate in nodes
        if candidate.get("memory_id")
    )
    bindings = source_binding_counts(memory_repo, node)
    candidate_packages = [run_context_package(memory_repo, query) for query in GOAL_QUERIES]
    candidate_hits = [
        target_supported_hit(load_context_package(raw), memory_repo, target_memory_ids)
        for raw in candidate_packages
    ]
    supported_count = sum(hit is not None for hit in candidate_hits)
    summary_resolution_count = sum(
        1
        for hit in candidate_hits
        if hit is not None and resolved_summary_fact(memory_repo, hit)
    )
    unsupported_package = run_context_package(memory_repo, ABSENT_QUERY)
    runtime = runtime_metrics(
        candidate_packages[0],
        unsupported_package,
        memory_repo,
        target_memory_ids,
    )

    meta_rows = session_meta_rows(memory_repo)
    correction_sources = [
        source
        for row in meta_rows
        for source in row.get("reusable_fact_sources") or []
        if isinstance(source, dict)
        and source.get("text") == TARGET_FACT
        and source.get("source") == "natural_user_correction"
    ]
    all_memory_text = "\n".join(
        str(row.get("text") or "")
        for row in read_jsonl(memory_repo / "index/memories.jsonl")
    )
    non_target_promotions = sum(marker in all_memory_text for marker in NON_TARGET_MARKERS)
    expected_support_count = max(
        2,
        len(node.get("evidence_refs") or []),
        len(node.get("raw_refs") or []),
    )

    metrics: dict[str, object] = {
        "correction_sequence_qualification_rate": safe_rate(len(correction_sources), 1),
        "correction_induced_fact_materialization_rate": safe_rate(len(nodes), 1),
        "correction_source_anchor_binding_rate": safe_rate(
            min(
                bindings.valid_evidence_count,
                bindings.valid_source_anchor_count,
                bindings.user_source_anchor_count,
                bindings.distinct_user_source_event_count,
            ),
            expected_support_count,
        ),
        "goal_format_query_supported_recall": safe_rate(supported_count, len(GOAL_QUERIES)),
        "supported_summary_fact_resolution_rate": safe_rate(
            summary_resolution_count,
            len(GOAL_QUERIES),
        ),
        "global_scope_accuracy": float(
            len(nodes) == 1
            and node.get("layer") == "global"
            and node.get("scope") == "global"
            and node.get("superseded_by") is None
        ),
        **runtime,
        "assistant_evidence_promotion_count": bindings.non_user_source_anchor_count,
        "non_target_memory_promotion_count": non_target_promotions,
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "copyable_goal_preference_recall_gate",
        "report_version": 1,
        "status": "passed",
        "baseline": {
            "baseline_kind": "goal_correction_induction_disabled_ablation",
            "updater_executed": True,
            "archived_session_count": baseline_archived_sessions,
            "target_materialization_count": len(baseline_nodes),
            "supported_query_count": baseline_supported,
            "failure_class": baseline_failure_class,
        },
        "candidate": {
            "target_materialization_count": len(nodes),
            "supported_query_count": supported_count,
            "bound_evidence_count": bindings.valid_evidence_count,
            "bound_source_anchor_count": bindings.valid_source_anchor_count,
            "bound_user_source_anchor_count": bindings.user_source_anchor_count,
            "distinct_user_source_event_count": bindings.distinct_user_source_event_count,
        },
        "answerability_source": CONTEXT_REPORT_KIND,
        "free_form_search_used": False,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "source_text_rendered": False,
            "query_text_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "session_ids_rendered": False,
        },
    }
    metrics["privacy_leak_count"] = private_leak_count(report)
    required_rates = (
        "correction_sequence_qualification_rate",
        "correction_induced_fact_materialization_rate",
        "correction_source_anchor_binding_rate",
        "goal_format_query_supported_recall",
        "supported_summary_fact_resolution_rate",
        "global_scope_accuracy",
        "current_turn_instruction_precedence_accuracy",
        "copyable_text_block_decision_accuracy",
        "nested_fence_collision_avoidance_accuracy",
    )
    required_zeroes = (
        "assistant_evidence_promotion_count",
        "non_target_memory_promotion_count",
        "free_form_answerability_use_count",
        "privacy_leak_count",
    )
    if (
        baseline_supported != 0
        or len(baseline_nodes) != 0
        or baseline_archived_sessions < 1
        or baseline_failure_class != "memory_not_materialized"
        or any(metrics[key] != 1.0 for key in required_rates)
        or any(metrics[key] != 0 for key in required_zeroes)
    ):
        report["status"] = "failed"
    return report


def copy_private_source(source_record: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"source{source_record.suffix or '.jsonl'}"
    shutil.copy2(source_record, target)
    return target


def run_private_ab(
    root: Path,
    source_record: Path,
    baseline_updater: Path,
    source_project_path: Path | None = None,
) -> dict[str, object]:
    baseline_repo = setup_packaged_archive(root, "private-baseline")
    candidate_repo = setup_packaged_archive(root, "private-candidate")
    shutil.copy2(baseline_updater, baseline_repo / "tools/update_memory_archive.py")
    source_dir = root / "private-source"
    copy_private_source(source_record, source_dir)
    project_path = source_project_path or (root / "private-project")
    if source_project_path is None:
        project_path.mkdir(parents=True, exist_ok=True)

    run_updater(
        baseline_repo,
        source_dir,
        project_path,
        "private_baseline_update",
        allow_redacted_secrets=True,
    )
    run_updater(
        candidate_repo,
        source_dir,
        project_path,
        "private_candidate_update",
        allow_redacted_secrets=True,
    )
    baseline_nodes = target_nodes(baseline_repo)
    candidate_nodes = target_nodes(candidate_repo)
    baseline_target_ids = frozenset(
        str(node.get("memory_id") or "")
        for node in baseline_nodes
        if node.get("memory_id")
    )
    candidate_target_ids = frozenset(
        str(node.get("memory_id") or "")
        for node in candidate_nodes
        if node.get("memory_id")
    )
    baseline_supported = sum(
        target_supported_hit(
            load_context_package(run_context_package(baseline_repo, query)),
            baseline_repo,
            baseline_target_ids,
        )
        is not None
        for query in GOAL_QUERIES
    )
    candidate_supported = sum(
        target_supported_hit(
            load_context_package(run_context_package(candidate_repo, query)),
            candidate_repo,
            candidate_target_ids,
        )
        is not None
        for query in GOAL_QUERIES
    )
    baseline_materialized = len(baseline_nodes)
    candidate_materialized = len(candidate_nodes)
    report: dict[str, object] = {
        "executed": True,
        "status": "passed",
        "baseline_no_hit_rate": safe_rate(len(GOAL_QUERIES) - baseline_supported, len(GOAL_QUERIES)),
        "candidate_supported_recall": safe_rate(candidate_supported, len(GOAL_QUERIES)),
        "baseline_target_materialization_count": baseline_materialized,
        "candidate_target_materialization_count": candidate_materialized,
        "privacy": {
            "aggregate_only": True,
            "source_text_rendered": False,
            "query_text_rendered": False,
            "source_paths_rendered": False,
            "session_ids_rendered": False,
        },
    }
    if (
        baseline_supported != 0
        or baseline_materialized != 0
        or candidate_supported != len(GOAL_QUERIES)
        or candidate_materialized != 1
        or private_leak_count(report) != 0
    ):
        report["status"] = "failed"
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent for disposable gate artifacts")
    parser.add_argument("--private-source-record", help="Optional external real source record for aggregate-only A/B")
    parser.add_argument("--private-baseline-updater", help="Required with --private-source-record")
    parser.add_argument("--private-project-path", help="Optional matching project path for the external source record")
    return parser.parse_args(argv)


def make_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="copyable-goal-gate-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="copyable-goal-gate-", dir=parent))
    return root, None, root


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(args.private_source_record) != bool(args.private_baseline_updater):
        print(
            json.dumps(
                {
                    "report_kind": "copyable_goal_preference_recall_gate",
                    "status": "failed",
                    "failures": [{"stage": "arguments", "reason": "private_ab_arguments_must_be_paired"}],
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
        report = build_synthetic_report(root)
        if args.private_source_record:
            source_record = Path(args.private_source_record).expanduser().resolve()
            baseline_updater = Path(args.private_baseline_updater).expanduser().resolve()
            private_project_path = (
                Path(args.private_project_path).expanduser().resolve()
                if args.private_project_path
                else None
            )
            if not source_record.is_file() or not baseline_updater.is_file():
                raise GateFailure("private_ab", "external_input_missing")
            if private_project_path is not None and not private_project_path.is_dir():
                raise GateFailure("private_ab", "external_project_path_missing")
            report["private_ab"] = run_private_ab(
                root,
                source_record,
                baseline_updater,
                private_project_path,
            )
            if report["private_ab"]["status"] != "passed":
                report["status"] = "failed"
    except (GateFailure, json.JSONDecodeError, OSError) as failure:
        payload = (
            failure.report()
            if isinstance(failure, GateFailure)
            else {"stage": "gate", "reason": type(failure).__name__}
        )
        print(
            json.dumps(
                {
                    "report_kind": "copyable_goal_preference_recall_gate",
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

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
