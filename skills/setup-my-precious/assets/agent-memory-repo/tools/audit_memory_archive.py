#!/usr/bin/env python3
"""Audit generated memory archive files for unsafe or low-quality index text."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Iterable


ALLOWED_ROOTS = (
    "INDEX.md",
    "config/projects.jsonl",
    "index",
    "memories",
    "daily",
    "sessions",
)
NOISE_PATTERNS = {
    "noise": re.compile(
        r"session_meta|response_item|event_msg|base_instructions|model_context_window|"
        r"subagent_notification|agent_path|"
        r"</?(?:oai-mem-citation|citation_entries|rollout_ids)>|"
        r"\b(?:MEMORY\.md|rollout_summaries/|skills/)[^\s|]*\|note=\[[^\]]*\]|"
        r"permissions instructions|AGENTS\.md instructions|<skill>|<turn_aborted>|<environment_context|"
        r"</environment_context>|<shell>|</shell>|<current_date>|</current_date>|<timezone>|</timezone>|"
        r"<filesystem>|</filesystem>|<workspace_roots>|</workspace_roots>|<permission_profile|</permission_profile>|"
        r"update_plan|"
        r"# AGENTS\.md|</permissions instructions>|</instructions>|<cwd>|"
        r"approval policy is currently|filesystem sandboxing defines|you are codex, a coding agent|"
        r"use when codex should|this skill should be used when users|"
        r"chunk id:|original token count:|process exited with code|wall time:|write_stdin failed:|"
        r"--- name:|# systematic debugging|"
        r"::inbox-item|inbox-item\{|"
        r"\*\*(?:Commands?|Command Status|Tool Calls?)\*\*|"
        r"# my precious skill development|"
        r"future messages should adhere|following personality|"
        r"you are a read-only verifier|continue working toward the active thread goal|"
        r"the objective below is user-provided data|"
        r"</?objective>|## my request for codex:|my request for codex:|"
        r"some of what we're working on might be easier to explain",
        re.IGNORECASE,
    ),
}
PLACEHOLDER_PATTERN = re.compile(
    r"No (?:reusable facts|decisions|problems|unresolved tasks|specific evidence snippets) "
    r"were (?:detected|selected) automatically|"
    r"Source file `[^`]+` was newer than the latest archived timestamp|"
    r"(?:archive|archived) source record for [A-Za-z0-9._-]+\.?",
    re.IGNORECASE,
)
RAW_TITLE_PATTERN = re.compile(
    r"(?:^# Session:)\s*.*(?:"
    r"/Users/|\.codex/attachments|Files mentioned by the user|Pasted text\.txt|AGENTS\.md instructions|<INSTRUCTIONS>"
    r")",
    re.IGNORECASE,
)
NOISY_TAGS = {
    "agent-memory",
    "my-precious",
    "subagent_notification",
    "agent_path",
    "secret-pattern",
    "subagent",
    "codespace",
    "mememe",
    "templates",
    "agent-memory-repo",
    "users",
    "soku",
    "desktop",
    "agents",
    "codex",
    "task",
    "you",
    "are",
    "run",
    "using-superpowers",
    "using-agent-skills",
    "worktree",
    "codex_home",
    "commands",
    "command",
    "status",
    "validator",
    "validators",
    "py_compile",
    "template",
    "sync",
    "implementation",
    "has",
    "meaningful",
    "improvements",
    "unit",
    "tests",
    "test",
    "pass",
    "passes",
    "passed",
    "audit",
    "script",
    "checks",
    "suggested",
    "concrete",
    "expected",
    "can",
    "but",
    "only",
    "title",
    "file",
    "files",
    "scripts",
    "saved",
    "remaining",
    "current",
    "diff",
    "three",
    "requested",
    "mostly",
    "there",
    "still",
    "without",
    "important",
    "actual",
    "completed",
    "complete",
    "continue",
    "previous",
    "after",
    "before",
    "once",
    "newly",
    "synced",
    "updater",
    "text",
    "module",
    "named",
    "review",
    "quality",
    "spec",
    "finding",
    "findings",
    "approved",
    "code",
    "message",
    "last",
    "dry",
    "live",
    "update",
    "updated",
    "secret",
    "gate",
    "cookie",
    "meta",
    "user",
    "intent",
    "facts",
    "fact",
    "verification",
    "verified",
    "invokes",
    "conversation",
    "feel",
    "easy",
    "alive",
    "move",
    "serious",
    "reflection",
    "unguarded",
    "fun",
    "either",
    "out",
    "new",
    "check",
    "records",
    "selected",
    "refused",
    "likely-secret",
    "project-scoped",
    "because",
    "matched",
    "categories",
    "private_key",
    "bearer_token",
    "github_token",
    "openai_key",
    "aws_access_key",
    "refusal",
    "stayed",
    "clean",
    "entry",
    "usable",
    "imperfect",
    "captures",
    "capture",
    "latest",
    "weaker",
    "retrieval",
    "durable",
    "generic",
    "critique",
    "critiques",
    "future",
    "messages",
    "adhere",
    "following",
    "personality",
    "doc",
    "http",
    "python",
    "cli",
    "top",
    "hit",
    "done",
    "changed",
    "accepts",
    "calls",
    "removes",
    "until",
    "open",
    "stronger",
    "standalone",
    "support",
    "setup",
    "contributor",
}
REDACTION_CATEGORY_LABELS = {
    "private_key",
    "bearer_token",
    "cookie",
    "github_token",
    "openai_key",
    "aws_access_key",
}
UNSAFE_PATH = "[unsafe-path]"
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    "bearer_token": re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    "cookie": re.compile(r"\bCookie:\s*[^\n=;]+=[^\n]+", re.IGNORECASE),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}
SOURCE_MAP_ANCHOR_ALIASES = {
    "explicit_memory": "source_record",
}
LOW_SIGNAL_PATTERN = re.compile(
    r"(?:"
    r"^\s*(?:[-*]\s*)?(?:验证结果|验证已跑|但阻塞点很明确|阻塞点很明确|阻塞原因|"
    r"原因很直接|原因是|我做过的验证|方案选择|常见原因|已验证|"
    r"APPROVED|CHANGES_REQUESTED|DONE_WITH_CONCERNS|DONE|"
    r"\*{0,3}\s*(?:commands?|command status|tool calls?|findings?|verified|what changed)\s*\*{0,3}|"
    r"\*{2}[^*]{2,24}\*{2})\s*[:：-]?\s*$|"
    r"\bdry[- ]?run\b.{0,120}(?:find|found|select(?:ed|s)?|record|update|exit|project|registration|enabled|选中|记录|产生|写入)|"
    r"\blive update\b|"
    r"(?:secret gate|likely-secret).{0,120}(?:refus(?:ed|es|al)|reject(?:ed|s|ion)|record|cookie|拒绝|命中)|"
    r"(?:没有产生新写入|产生新写入|默认 secret gate|source record 命中|命中\s*`?cookie|cookie\s*=)|"
    r"stopped (?:there|before).{0,120}(?:updater|allow-redacted-secrets|running)|"
    r"git status --short.{0,120}(?:exit 0|clean)|"
    r"global memory update completed|memory archive updated|memory archive pushed|committed and pushed|repo (?:is )?clean|"
    r"actual run processed.{0,80}(?:project|record)|"
    r"(?:比如\s*)?.{0,80}条目能恢复.{0,160}|"
    r"\b(?:latest\s+)?[\w.-]+\s+entry\s+is\s+(?:usable|imperfect|weaker|stronger).{0,160}|"
    r"\b[\w.-]+\s+entry\s+.{0,80}\bcaptures\b.{0,120}|"
    r"^continue working toward the active thread goal\.?$|"
    r"^you are a read-only verifier\b.*$|"
    r"(?:关键)?(?:查询|搜索|检索).{0,120}(?:目标条目|top\s+hit|top\s+result|排第一|排第[一二三123])|"
    r"(?:`[^`]{1,120}`|[^。.!?；;\n]{1,120})\s*(?:第[一二三123]|第一)\s*命中是.{0,120}|"
    r"(?:top\s+hit|top\s+result|search\s+verification|search\s+result|targeted\s+search).{0,160}(?:rank|match|hit|pass|排名|排第|正确|展示标题|review\s+语境)|"
    r"(?:已验证[:：]\s*)?.{0,80}\btags?\b.{0,120}(?:http/python/cli|泛词|broad)"
    r")",
    re.IGNORECASE,
)
INCOMPLETE_FRAGMENT_PATTERN = re.compile(
    r"(?:"
    r"^(?:.{0,80}(?:摘要|记忆|目录|路径|文件|仓库|repo|repository|skill)"
    r".{0,40}(?:在|位于|路径为|目录为|in|at|from|to|for|with|under|inside))$|"
    r"^(?:结论|评价|findings?)[:：]\s*\*\*[^*]+$"
    r")",
    re.IGNORECASE,
)
PROCESS_UPDATE_PATTERN = re.compile(
    r"(?:"
    r"^\s*(?:[-*]\s*)?(?:"
    r"i am |i'm |i’m |i will |i'll |i’ll |next i |now i |i also |"
        r"i checked |i confirmed |i found |i noticed |i reran |i rerun |"
        r"one search command failed|one command failed|a search command failed|"
        r"我先|我会|我再|接下来我|下一步我|当前我会|接着我会|随后我会|最后我会|最后一轮我会|"
        r"现在先|现在开始|现在改为|先读取|先检查|先看|先跑"
    r")|"
    r"\bi(?:'m|’m| am)\s+(?:proceeding|locating|checking|inspecting|running|rerunning|continuing|waiting|working|reading|verifying|starting)\b|"
    r"\bi(?:'m|’m| am)\s+not\s+(?:rerunning|running|proceeding|continuing)\b|"
    r"\bi(?:'ll|’ll| will)\s+(?:only\s+)?(?:inspect|check|verify|run|rerun|continue|wait|proceed|look|locate|report)\b|"
    r"\bthen\s+i(?:'ll|’ll| will)\b|"
    r"\bi\s+used\s+prior\s+workflow\s+memory\b|"
    r"^using\s+[`$]?(?:using-|brainstorming|test-driven|systematic|update-my-precious).*(?:as requested|i(?:'ll|’ll| will)\s+also\s+use)|"
    r"我会(?:先|只|把|用|继续|做|改|跑|等|查|核实|从|按|清|尝试|恢复)|"
    r"我继续|我先|接下来我|下一步我|下一块会|当前我会|接着我会|随后我会|最后我会|最后一轮我会|"
    r"我现在(?:检查|继续|先|会|加|跑|改|处理|验证|看)|"
    r"我正在(?:检查|处理|验证|跑|看|等待|继续|读取|定位|修复|更新|清理)|"
    r"现在我(?:检查|继续|先|会|加|跑|改|处理|验证|看|已经)|"
    r"现在(?:先|开始|改为|做|跑|检查|验证|清理|处理|读取)|"
    r"先(?:读取|检查|看|跑|做|定位|验证|清理)|"
    r"(?:unit\s+tests?|tests?)\s+pass(?:ed|es)?.*(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync)|"
    r"(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync).*(?:pass(?:ed|es)?|green|ok)|"
    r"(?:查询|搜索).*?(?:表现|命中|排第|排到|top\s+hit|rank|ranking)|"
    r"(?:`[^`]{1,120}`|[^。.!?；;\n]{1,120})\s*(?:第[一二三123]|第一)\s*命中是|"
    r"(?:top\s+hit|top\s+result|search\s+verification|search\s+result|targeted\s+search).*(?:rank|match|hit|pass)|"
    r"正在处理|继续等待|继续等最终输出|process_update|过程句.*(?:reusable|problem|unresolved)|"
    r"\bdry[- ]?run\b.{0,120}(?:find|found|select(?:ed|s)?|record|update|exit|project|registration|enabled|选中|记录|产生|写入)|"
    r"\blive update\b|"
    r"(?:secret gate|likely-secret).{0,120}(?:refus(?:ed|es|al)|reject(?:ed|s|ion)|record|cookie|拒绝|命中)|"
    r"(?:没有产生新写入|产生新写入|默认 secret gate|source record 命中|命中\s*`?cookie|cookie\s*=)|"
    r"stopped (?:there|before).{0,120}(?:updater|allow-redacted-secrets|running)|"
    r"git status --short.{0,120}(?:exit 0|clean)|"
    r"global memory update completed|memory archive updated|memory archive pushed|committed and pushed|repo (?:is )?clean|"
    r"actual run processed.{0,80}(?:project|record)"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: str
    line_number: int
    category: str


@dataclass(frozen=True)
class MemoryNodeLocation:
    signature: str
    path: str
    line_number: int


MEMORY_NODE_REQUIRED_FIELDS = {
    "memory_id",
    "layer",
    "scope",
    "topic",
    "text",
    "rationale",
    "source",
    "confidence",
    "persistence",
    "support_count",
    "first_seen",
    "last_seen",
    "derived_from",
    "evidence_refs",
    "raw_refs",
    "supersedes",
    "superseded_by",
    "tags",
}
MEMORY_NODE_OPTIONAL_FIELDS = {
    "contradicts",
    "contradicted_by",
    "deprecates",
    "deprecated_by",
}
MEMORY_NODE_STRING_FIELDS = {
    "memory_id",
    "layer",
    "scope",
    "topic",
    "text",
    "rationale",
    "source",
    "confidence",
    "persistence",
    "first_seen",
    "last_seen",
}
MEMORY_NODE_ENUM_FIELDS = {
    "layer": {"project", "domain", "global"},
    "source": {"automatic", "explicit"},
    "confidence": {"low", "medium", "high"},
    "persistence": {"normal", "sticky"},
}
MEMORY_NODE_STRING_LIST_FIELDS = {"derived_from", "supersedes", "tags"}
MEMORY_NODE_OPTIONAL_STRING_FIELDS = {"deprecated_by"}
MEMORY_NODE_OPTIONAL_STRING_LIST_FIELDS = {"contradicts", "contradicted_by", "deprecates"}
MEMORY_LAYER_ROOT_FILES = {
    "global": "memories/global.jsonl",
    "domain": "memories/domains.jsonl",
    "project": "memories/projects.jsonl",
}


def has_sensitive_identifier_token(text: str) -> bool:
    tokens = re.split(r"[^a-z0-9]+", text.lower().replace("_", " "))
    token_set = set(tokens)
    token_pairs = set(zip(tokens, tokens[1:]))
    return bool(
        token_set.intersection(
            {
                "apikey",
                "authorization",
                "bearer",
                "cookie",
                "credential",
                "password",
            }
        )
        or token_pairs.intersection(
            {
                ("api", "key"),
                ("auth", "token"),
                ("bearer", "token"),
                ("private", "key"),
                ("secret", "key"),
                ("session", "id"),
            }
        )
    )


def has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def safe_diagnostic_path(path_text: str) -> str:
    if has_control_chars(path_text) or has_sensitive_identifier_token(path_text):
        return UNSAFE_PATH
    return path_text


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates: list[str] = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "index").exists() and (repo / "sessions").exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def is_allowed_path(path: Path, repo: Path) -> bool:
    try:
        relative = path.resolve().relative_to(repo.resolve())
    except (OSError, ValueError):
        return False
    posix = PurePosixPath(relative.as_posix())
    if posix.is_absolute() or ".." in posix.parts:
        return False
    text = posix.as_posix()
    for root in ALLOWED_ROOTS:
        if text == root or text.startswith(f"{root}/"):
            return True
    return False


def iter_archive_files(repo: Path) -> Iterable[Path]:
    for root in ALLOWED_ROOTS:
        path = repo / root
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (item for item in path.rglob("*") if item.is_file())


def extract_quality_text(relative: str, line: str) -> str:
    if not (relative.startswith("index/") or relative.startswith("memories/")) or not relative.endswith(".jsonl"):
        return line
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(value, dict):
        return line

    keys_by_file = {
        "index/sessions.jsonl": (
            "title",
            "summary",
            "user_intent",
            "reusable_facts",
            "decisions",
            "unresolved_tasks",
            "tags",
        ),
        "index/decisions.jsonl": ("decision",),
        "index/unresolved.jsonl": ("task",),
        "index/tags.jsonl": ("tag",),
        "index/memories.jsonl": ("text", "rationale", "topic", "scope", "tags"),
    }
    keys = keys_by_file.get(relative)
    if keys is None and relative.startswith("memories/") and relative.endswith(".jsonl"):
        keys = ("text", "rationale", "topic", "scope", "tags")
    if not keys:
        return line

    parts: list[str] = []
    for key in keys:
        item = value.get(key)
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, list):
            parts.extend(str(child) for child in item if isinstance(child, (str, int, float)))
    return "\n".join(parts)


def quality_text_segments(text: str) -> tuple[str, ...]:
    segments = [text]
    if "\n" in text:
        segments.extend(line for line in text.splitlines() if line.strip())
    return tuple(segments)


def is_redaction_category_text(text: str) -> bool:
    compacted = re.sub(r"\s+", " ", text).strip().lower()
    if not compacted:
        return False
    markdown_stripped = re.sub(r"[*`]", "", compacted).strip(" .:;")
    if markdown_stripped in {"refusal", "stayed clean", "clean"}:
        return True
    tokens = [
        token.strip(" .:;()[]{}-")
        for token in re.split(r"[,/\s]+", markdown_stripped)
        if token.strip(" .:;()[]{}-")
    ]
    if not tokens:
        return False
    allowed = REDACTION_CATEGORY_LABELS | {
        "redaction",
        "redactions",
        "redacted",
        "secret",
        "secrets",
        "category",
        "categories",
        "refusal",
        "refused",
        "stayed",
        "clean",
        "matched",
        "detected",
        "none",
        "no",
    }
    return bool(REDACTION_CATEGORY_LABELS.intersection(tokens)) and all(token in allowed for token in tokens)


def has_unbalanced_markdown_emphasis(text: str) -> bool:
    compacted = re.sub(r"\s+", " ", text).strip()
    if not compacted:
        return False
    return compacted.count("**") % 2 == 1


def is_incomplete_memory_fragment(text: str) -> bool:
    raw = re.sub(r"\s+", " ", text).strip()
    if not raw:
        return False
    if has_unbalanced_markdown_emphasis(raw):
        return True
    compacted = raw.strip(" -")
    return len(compacted) <= 160 and bool(INCOMPLETE_FRAGMENT_PATTERN.search(compacted))


def scan_file(repo: Path, path: Path, check_process_updates: bool) -> list[Finding]:
    findings: list[Finding] = []
    if not is_allowed_path(path, repo):
        return findings
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return findings
    relative = path.relative_to(repo).as_posix()
    lines = text.splitlines()
    for line_number, line in enumerate(lines, start=1):
        quality_line = extract_quality_text(relative, line)
        quality_segments = quality_text_segments(quality_line)
        for category, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(relative, line_number, category))
        for category, pattern in NOISE_PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(relative, line_number, category))
        if PLACEHOLDER_PATTERN.search(line):
            findings.append(Finding(relative, line_number, "placeholder"))
        if RAW_TITLE_PATTERN.search(line):
            findings.append(Finding(relative, line_number, "raw_title"))
        if any(LOW_SIGNAL_PATTERN.search(segment) or is_incomplete_memory_fragment(segment) for segment in quality_segments):
            findings.append(Finding(relative, line_number, "low_signal"))
        if not relative.endswith("/redactions.md") and is_redaction_category_text(quality_line):
            findings.append(Finding(relative, line_number, "redaction_category"))
        if relative.endswith("index/sessions.jsonl"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                value = {}
            title = str(value.get("title", "")) if isinstance(value, dict) else ""
            if title and RAW_TITLE_PATTERN.search(f"# Session: {title}"):
                findings.append(Finding(relative, line_number, "raw_title"))
        if relative.endswith("index/tags.jsonl"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                value = {}
            tag = str(value.get("tag", "")).lower() if isinstance(value, dict) else ""
            if tag in NOISY_TAGS or tag.endswith(".py"):
                findings.append(Finding(relative, line_number, "noisy_tag"))
        elif line_number > 1 and lines[line_number - 2].strip() == "## Search Tags":
            tags = [tag.strip().lower() for tag in re.split(r"[, ]+", line) if tag.strip()]
            if any(tag in NOISY_TAGS or tag.endswith(".py") for tag in tags):
                findings.append(Finding(relative, line_number, "noisy_tag"))
        if check_process_updates and any(PROCESS_UPDATE_PATTERN.search(segment) for segment in quality_segments):
            findings.append(Finding(relative, line_number, "process_update"))
    return findings


def iter_memory_row_files(repo: Path) -> Iterable[tuple[str, Path]]:
    index_path = repo / "index" / "memories.jsonl"
    if index_path.is_file() and is_allowed_path(index_path, repo):
        yield "index/memories.jsonl", index_path
    memories_dir = repo / "memories"
    if memories_dir.is_dir():
        for path in sorted(item for item in memories_dir.glob("*.jsonl") if item.is_file()):
            if is_allowed_path(path, repo):
                yield path.relative_to(repo).as_posix(), path


def iter_memory_node_rows(repo: Path) -> Iterable[tuple[str, int, dict]]:
    for relative, path in iter_memory_row_files(repo):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                yield relative, line_number, {"__invalid_json__": True}
                continue
            if isinstance(value, dict):
                yield relative, line_number, value
            else:
                yield relative, line_number, {"__invalid_json__": True}


def iter_session_meta_rows(repo: Path) -> Iterable[tuple[str, int, dict]]:
    sessions_dir = repo / "sessions"
    if not sessions_dir.is_dir():
        return
    for path in sorted(sessions_dir.glob("**/meta.json")):
        if not path.is_file() or not is_allowed_path(path, repo):
            continue
        relative = path.relative_to(repo).as_posix()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            yield relative, 1, {"__invalid_json__": True}
            continue
        if isinstance(value, dict):
            yield relative, 1, value
        else:
            yield relative, 1, {"__invalid_json__": True}


def iter_session_source_map_rows(repo: Path) -> Iterable[tuple[str, int, dict]]:
    sessions_dir = repo / "sessions"
    if not sessions_dir.is_dir():
        return
    for path in sorted(sessions_dir.glob("**/source-map.json")):
        if not path.is_file() or not is_allowed_path(path, repo):
            continue
        relative = path.relative_to(repo).as_posix()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            yield relative, 1, {"__invalid_json__": True}
            continue
        if isinstance(value, dict):
            yield relative, 1, value
        else:
            yield relative, 1, {"__invalid_json__": True}


def safe_archive_ref_path(repo: Path, path_text: str) -> Path | None:
    if not path_text:
        return None
    raw_relative = PurePosixPath(path_text)
    if raw_relative.is_absolute() or ".." in raw_relative.parts:
        return None
    candidate = repo / path_text
    try:
        candidate.resolve(strict=False).relative_to(repo.resolve())
    except (OSError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return candidate


def safe_existing_archive_ref(repo: Path, path_text: str) -> bool:
    return safe_archive_ref_path(repo, path_text) is not None


def evidence_quote_id_exists(path: Path, quote_id: str) -> bool:
    if not quote_id.strip():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(re.search(rf"(?m)^\s*{re.escape(quote_id)}\s*:", text))


def source_map_anchor_exists(path: Path, anchor: str) -> bool:
    if not anchor.strip():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    anchor_key = SOURCE_MAP_ANCHOR_ALIASES.get(anchor, anchor)
    return isinstance(value, dict) and anchor_key in value


def is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def has_unsafe_identifier_path_reference(text: str) -> bool:
    if text.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    return any(part == ".." for part in re.split(r"[\\/]+", text))


def is_safe_memory_identifier(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return not (
        has_control_chars(value)
        or has_sensitive_identifier_token(value)
        or has_unsafe_identifier_path_reference(value)
    )


def is_valid_evidence_ref_shape(ref: object) -> bool:
    return (
        isinstance(ref, dict)
        and set(ref) == {"path", "quote_id"}
        and isinstance(ref.get("path"), str)
        and bool(ref.get("path", "").strip())
        and isinstance(ref.get("quote_id"), str)
        and bool(ref.get("quote_id", "").strip())
    )


def parse_memory_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def has_valid_memory_lifecycle(row: dict) -> bool:
    first_seen = parse_memory_timestamp(row.get("first_seen"))
    last_seen = parse_memory_timestamp(row.get("last_seen"))
    return first_seen is not None and last_seen is not None and first_seen <= last_seen


def is_valid_memory_node_shape(row: dict) -> bool:
    row_fields = set(row)
    if not MEMORY_NODE_REQUIRED_FIELDS.issubset(row_fields):
        return False
    if not row_fields.issubset(MEMORY_NODE_REQUIRED_FIELDS | MEMORY_NODE_OPTIONAL_FIELDS):
        return False
    if not is_safe_memory_identifier(row.get("memory_id")):
        return False
    for field in MEMORY_NODE_STRING_FIELDS:
        if not isinstance(row.get(field), str):
            return False
    for field, allowed_values in MEMORY_NODE_ENUM_FIELDS.items():
        if row.get(field) not in allowed_values:
            return False
    if not has_valid_memory_lifecycle(row):
        return False
    if not is_positive_int(row.get("support_count")):
        return False
    derived_from = row.get("derived_from")
    if not is_string_list(derived_from) or not derived_from:
        return False
    for field in MEMORY_NODE_STRING_LIST_FIELDS - {"derived_from"}:
        if not is_string_list(row.get(field)):
            return False
    if not all(is_safe_memory_identifier(target) for target in row.get("supersedes", [])):
        return False
    for field in MEMORY_NODE_OPTIONAL_STRING_LIST_FIELDS:
        if field in row:
            if not is_string_list(row.get(field)):
                return False
            if not all(is_safe_memory_identifier(target) for target in row.get(field, [])):
                return False
    for field in MEMORY_NODE_OPTIONAL_STRING_FIELDS:
        if field in row:
            value = row.get(field)
            if value is not None and not is_safe_memory_identifier(value):
                return False
    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(is_valid_evidence_ref_shape(ref) for ref in evidence_refs):
        return False
    superseded_by = row.get("superseded_by")
    return superseded_by is None or is_safe_memory_identifier(superseded_by)


def is_safe_raw_ref(ref: object) -> bool:
    if not isinstance(ref, dict):
        return False
    if set(ref) != {"path", "anchor"}:
        return False
    path_text = ref.get("path")
    anchor_text = ref.get("anchor")
    if not isinstance(path_text, str) or not isinstance(anchor_text, str):
        return False
    if not path_text.strip() or not anchor_text.strip():
        return False
    if has_control_chars(path_text) or has_control_chars(anchor_text):
        return False
    if has_unsafe_identifier_path_reference(path_text):
        return False
    return not (has_sensitive_identifier_token(path_text) or has_sensitive_identifier_token(anchor_text))


def is_archive_internal_ref_path(path_text: str) -> bool:
    return any(path_text == root or path_text.startswith(f"{root}/") for root in ALLOWED_ROOTS)


def memory_node_signature(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def audit_memory_id_uniqueness(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    index_ids: dict[str, MemoryNodeLocation] = {}
    durable_ids: dict[str, MemoryNodeLocation] = {}

    def add_id(target: dict[str, MemoryNodeLocation], relative: str, line_number: int, row: dict) -> None:
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str) or not is_valid_memory_node_shape(row):
            return
        location = MemoryNodeLocation(memory_node_signature(row), relative, line_number)
        if memory_id in target:
            findings.append(Finding(relative, line_number, "duplicate_memory_id"))
            return
        target[memory_id] = location

    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__"):
            continue
        if relative == "index/memories.jsonl":
            add_id(index_ids, relative, line_number, row)
        else:
            add_id(durable_ids, relative, line_number, row)
    return findings


def audit_memory_supersession_refs(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    valid_rows: list[tuple[str, int, dict]] = []
    rows_by_id: dict[str, list[dict]] = {}
    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__") or not is_valid_memory_node_shape(row):
            continue
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str):
            continue
        valid_rows.append((relative, line_number, row))
        rows_by_id.setdefault(memory_id, []).append(row)

    supersedes_by_id: dict[str, set[str]] = {}
    for _, _, row in valid_rows:
        memory_id = str(row.get("memory_id"))
        supersedes = row.get("supersedes", [])
        supersedes_by_id.setdefault(memory_id, set()).update(
            target for target in supersedes if target != memory_id and target in rows_by_id
        )

    def supersession_path_exists(start_id: str, target_id: str) -> bool:
        visited: set[str] = set()
        stack = list(supersedes_by_id.get(start_id, set()))
        while stack:
            current = stack.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(supersedes_by_id.get(current, set()) - visited)
        return False

    for relative, line_number, row in valid_rows:
        memory_id = str(row.get("memory_id"))
        supersedes = row.get("supersedes", [])
        superseded_by = row.get("superseded_by")
        broken_supersedes = any(
            target == memory_id
            or target not in rows_by_id
            or not all(target_row.get("superseded_by") == memory_id for target_row in rows_by_id[target])
            for target in supersedes
        )
        broken_superseded_by = isinstance(superseded_by, str) and (
            superseded_by == memory_id
            or superseded_by not in rows_by_id
            or not all(memory_id in target_row.get("supersedes", []) for target_row in rows_by_id[superseded_by])
        )
        cyclic_supersedes = any(
            target in rows_by_id and supersession_path_exists(target, memory_id) for target in supersedes
        )
        if broken_supersedes or broken_superseded_by or cyclic_supersedes:
            findings.append(Finding(relative, line_number, "broken_supersession_ref"))
    return findings


def audit_memory_contradiction_refs(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    valid_rows: list[tuple[str, int, dict]] = []
    rows_by_id: dict[str, list[dict]] = {}
    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__") or not is_valid_memory_node_shape(row):
            continue
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str):
            continue
        valid_rows.append((relative, line_number, row))
        rows_by_id.setdefault(memory_id, []).append(row)

    for relative, line_number, row in valid_rows:
        memory_id = str(row.get("memory_id"))
        contradicts = row.get("contradicts", [])
        contradicted_by = row.get("contradicted_by", [])
        broken_contradicts = any(
            target == memory_id
            or target not in rows_by_id
            or not all(memory_id in target_row.get("contradicted_by", []) for target_row in rows_by_id[target])
            for target in contradicts
        )
        broken_contradicted_by = any(
            target == memory_id
            or target not in rows_by_id
            or not all(memory_id in target_row.get("contradicts", []) for target_row in rows_by_id[target])
            for target in contradicted_by
        )
        if broken_contradicts or broken_contradicted_by:
            findings.append(Finding(relative, line_number, "broken_contradiction_ref"))
    return findings


def audit_memory_deprecation_refs(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    valid_rows: list[tuple[str, int, dict]] = []
    rows_by_id: dict[str, list[dict]] = {}
    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__") or not is_valid_memory_node_shape(row):
            continue
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str):
            continue
        valid_rows.append((relative, line_number, row))
        rows_by_id.setdefault(memory_id, []).append(row)

    for relative, line_number, row in valid_rows:
        memory_id = str(row.get("memory_id"))
        deprecates = row.get("deprecates", [])
        deprecated_by = row.get("deprecated_by")
        broken_deprecates = any(
            target == memory_id
            or target not in rows_by_id
            or not all(target_row.get("deprecated_by") == memory_id for target_row in rows_by_id[target])
            for target in deprecates
        )
        broken_deprecated_by = isinstance(deprecated_by, str) and (
            deprecated_by == memory_id
            or deprecated_by not in rows_by_id
            or not all(memory_id in target_row.get("deprecates", []) for target_row in rows_by_id[deprecated_by])
        )
        if broken_deprecates or broken_deprecated_by:
            findings.append(Finding(relative, line_number, "broken_deprecation_ref"))
    return findings


def audit_memory_lifecycle_states(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__") or not is_valid_memory_node_shape(row):
            continue
        supersedes = row.get("supersedes", [])
        superseded_by = row.get("superseded_by")
        deprecates = row.get("deprecates", [])
        deprecated_by = row.get("deprecated_by")
        if isinstance(superseded_by, str) and isinstance(deprecated_by, str):
            findings.append(Finding(relative, line_number, "invalid_memory_lifecycle_state"))
            continue
        if isinstance(supersedes, list) and supersedes and isinstance(deprecates, list) and deprecates:
            findings.append(Finding(relative, line_number, "invalid_memory_lifecycle_state"))
    return findings


def audit_memory_index_consistency(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    index_nodes: dict[str, MemoryNodeLocation] = {}
    durable_nodes: dict[str, MemoryNodeLocation] = {}

    def add_node(target: dict[str, MemoryNodeLocation], relative: str, line_number: int, row: dict) -> None:
        memory_id = row.get("memory_id")
        if not isinstance(memory_id, str) or not is_valid_memory_node_shape(row):
            return
        location = MemoryNodeLocation(memory_node_signature(row), relative, line_number)
        existing = target.get(memory_id)
        if existing and existing.signature != location.signature:
            findings.append(Finding(relative, line_number, "memory_index_mismatch"))
            return
        target[memory_id] = existing or location

    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__"):
            continue
        if relative == "index/memories.jsonl":
            add_node(index_nodes, relative, line_number, row)
        else:
            add_node(durable_nodes, relative, line_number, row)

    if not durable_nodes:
        return findings
    if not index_nodes:
        return [
            Finding(durable.path, durable.line_number, "memory_index_mismatch")
            for durable in durable_nodes.values()
        ]

    for memory_id, durable in durable_nodes.items():
        indexed = index_nodes.get(memory_id)
        if indexed is None or indexed.signature != durable.signature:
            findings.append(Finding(durable.path, durable.line_number, "memory_index_mismatch"))
    for memory_id, indexed in index_nodes.items():
        if memory_id not in durable_nodes:
            findings.append(Finding(indexed.path, indexed.line_number, "memory_index_mismatch"))
    return findings


def audit_memory_references(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative, line_number, row in iter_memory_node_rows(repo):
        if row.get("__invalid_json__"):
            findings.append(Finding(relative, line_number, "invalid_json"))
            continue
        missing = MEMORY_NODE_REQUIRED_FIELDS.difference(row)
        if missing:
            findings.append(Finding(relative, line_number, "invalid_memory_node"))
            continue
        if not is_valid_memory_node_shape(row):
            findings.append(Finding(relative, line_number, "invalid_memory_node"))
        derived_from = row.get("derived_from", [])
        if not isinstance(derived_from, list):
            findings.append(Finding(relative, line_number, "invalid_memory_node"))
        else:
            for path_text in derived_from:
                if not isinstance(path_text, str) or not safe_existing_archive_ref(repo, path_text):
                    findings.append(Finding(relative, line_number, "broken_memory_ref"))
        evidence_refs = row.get("evidence_refs", [])
        if not isinstance(evidence_refs, list):
            findings.append(Finding(relative, line_number, "invalid_memory_node"))
        else:
            for ref in evidence_refs:
                path_text = ref.get("path") if isinstance(ref, dict) else ""
                quote_id = ref.get("quote_id") if isinstance(ref, dict) else ""
                evidence_path = safe_archive_ref_path(repo, path_text) if isinstance(path_text, str) else None
                if (
                    evidence_path is None
                    or not isinstance(quote_id, str)
                    or not evidence_quote_id_exists(evidence_path, quote_id)
                ):
                    findings.append(Finding(relative, line_number, "broken_memory_ref"))
        raw_refs = row.get("raw_refs", [])
        if not isinstance(raw_refs, list):
            findings.append(Finding(relative, line_number, "unsafe_raw_ref"))
        else:
            for ref in raw_refs:
                if not is_safe_raw_ref(ref):
                    findings.append(Finding(relative, line_number, "unsafe_raw_ref"))
                    continue
                path_text = str(ref.get("path", ""))
                if is_archive_internal_ref_path(path_text):
                    raw_path = safe_archive_ref_path(repo, path_text)
                    if raw_path is None:
                        findings.append(Finding(relative, line_number, "unsafe_raw_ref"))
                    elif raw_path.name == "source-map.json" and not source_map_anchor_exists(
                        raw_path,
                        str(ref.get("anchor", "")),
                    ):
                        findings.append(Finding(relative, line_number, "unsafe_raw_ref"))
    return findings


def audit_memory_file_placement(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative, line_number, row in iter_memory_node_rows(repo):
        if relative == "index/memories.jsonl" or row.get("__invalid_json__"):
            continue
        if not is_valid_memory_node_shape(row):
            continue
        if row.get("source") == "explicit" and relative != "memories/explicit.jsonl":
            findings.append(Finding(relative, line_number, "memory_file_mismatch"))
            continue
        if relative == "memories/explicit.jsonl":
            if row.get("source") != "explicit":
                findings.append(Finding(relative, line_number, "memory_file_mismatch"))
            continue
        expected = MEMORY_LAYER_ROOT_FILES.get(str(row.get("layer", "")))
        if expected is not None and relative != expected:
            findings.append(Finding(relative, line_number, "memory_file_mismatch"))
    return findings


def audit_session_source_map_refs(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative, line_number, row in iter_session_meta_rows(repo):
        if row.get("__invalid_json__"):
            findings.append(Finding(relative, line_number, "invalid_json"))
            continue
        source_map_path = row.get("source_map_path")
        if source_map_path in (None, ""):
            continue
        expected_source_map = (PurePosixPath(relative).parent / "source-map.json").as_posix()
        if (
            not isinstance(source_map_path, str)
            or source_map_path.strip() != expected_source_map
            or safe_archive_ref_path(repo, source_map_path) is None
        ):
            findings.append(Finding(relative, line_number, "broken_source_map_ref"))
    for relative, line_number, row in iter_session_source_map_rows(repo):
        if row.get("__invalid_json__"):
            findings.append(Finding(relative, line_number, "invalid_json"))
            continue
        entry_dir = PurePosixPath(relative).parent
        expected_paths = {
            "summary_path": (entry_dir / "summary.md").as_posix(),
            "evidence_path": (entry_dir / "evidence.md").as_posix(),
            "source_map_path": (entry_dir / "source-map.json").as_posix(),
        }
        for field, expected_path in expected_paths.items():
            value = row.get(field)
            if (
                not isinstance(value, str)
                or value.strip() != expected_path
                or safe_archive_ref_path(repo, value) is None
            ):
                findings.append(Finding(relative, line_number, "broken_source_map_ref"))
                break
    return findings


def audit_repo(repo: Path, check_process_updates: bool) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(iter_archive_files(repo)):
        findings.extend(scan_file(repo, path, check_process_updates))
    findings.extend(audit_session_source_map_refs(repo))
    findings.extend(audit_memory_references(repo))
    findings.extend(audit_memory_file_placement(repo))
    findings.extend(audit_memory_id_uniqueness(repo))
    findings.extend(audit_memory_supersession_refs(repo))
    findings.extend(audit_memory_contradiction_refs(repo))
    findings.extend(audit_memory_deprecation_refs(repo))
    findings.extend(audit_memory_lifecycle_states(repo))
    findings.extend(audit_memory_index_consistency(repo))
    return sorted(set(findings), key=lambda item: (item.path, item.line_number, item.category))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--max-findings", type=int, default=50, help="Maximum findings to print")
    parser.add_argument(
        "--skip-process-update-check",
        action="store_true",
        help="Do not flag first-person process updates in generated archive text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_memory_repo(args.memory_repo)
    findings = audit_repo(repo, check_process_updates=not args.skip_process_update_check)
    if not findings:
        print("Archive audit passed.")
        return 0

    print("Archive audit failed:", file=sys.stderr)
    for finding in findings[: args.max_findings]:
        print(
            f"- {safe_diagnostic_path(finding.path)}:{finding.line_number} category={finding.category}",
            file=sys.stderr,
        )
    if len(findings) > args.max_findings:
        print(f"- ... and {len(findings) - args.max_findings} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
