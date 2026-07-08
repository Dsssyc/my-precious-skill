#!/usr/bin/env python3
"""Audit publish-facing archive surfaces before automatic Git sync."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


REPORT_KIND = "publish_readiness_audit"
PUBLISH_ROOTS = ("daily", "index")
TEXT_FIELDS = {
    "context",
    "decision",
    "decisions",
    "facts",
    "final_state",
    "problem",
    "problems",
    "rationale",
    "reusable_facts",
    "summary",
    "tag",
    "tags",
    "task",
    "text",
    "title",
    "topic",
    "unresolved_tasks",
    "user_intent",
}
RAW_SOURCE_FIELDS = {
    "full_queries",
    "full_query",
    "raw_prompt",
    "raw_prompts",
    "raw_source_path",
    "raw_source_paths",
}
ALL_CATEGORIES = (
    "command_progress",
    "prompt_or_environment",
    "permission_or_sandbox",
    "raw_source_reference",
    "secret_like_value",
    "automation_run_narration",
    "malformed_index_jsonl",
)
CATEGORY_PATTERNS = {
    "command_progress": re.compile(
        r"\b(?:command status|tool calls?|dry-run|live-run|would push|would commit|"
        r"archive already current|git status --short|process exited with code|wall time|chunk id|"
        r"running command|rerun(?:ning)?|py_compile|unit tests?)\b",
        re.IGNORECASE,
    ),
    "prompt_or_environment": re.compile(
        r"<environment_context\b|</environment_context>|AGENTS\.md instructions|<INSTRUCTIONS>|"
        r"\bsystem prompt\b|\bdeveloper message\b|base_instructions|model_context_window|# AGENTS\.md|"
        r"permissions instructions|you are codex, a coding agent",
        re.IGNORECASE,
    ),
    "permission_or_sandbox": re.compile(
        r"\b(?:sandbox|approval policy|filesystem sandboxing|permission_profile|workspace write|full access)\b",
        re.IGNORECASE,
    ),
    "raw_source_reference": re.compile(
        r"^\s*(?:[-*]\s*)?(?:raw\s+prompt|full\s+quer(?:y|ies)|raw_refs?|raw\s+source\s+path)\s*[:=]|"
        r"\braw_refs?\b\s*[:=]|"
        r"/(?:Users|private|var/folders|tmp|Volumes)/[^\s`)'\"]+|"
        r"\.codex/(?:sessions|attachments)|source-map\.json",
        re.IGNORECASE | re.MULTILINE,
    ),
    "secret_like_value": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
        r"Authorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]+|"
        r"\bCookie:\s*[^\n=;]+=[^\n]+|"
        r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
        r"\bsk-[A-Za-z0-9_-]{20,}\b|"
        r"\bAKIA[0-9A-Z]{16}\b",
        re.IGNORECASE,
    ),
    "automation_run_narration": re.compile(
        r"automation run status|scheduled run|blocked_before_publish|sync helper(?: was)?|"
        r"no memory hits for:|global memory update completed|memory archive (?:updated|pushed)|"
        r"committed and pushed|automatic update completed",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class FileAudit:
    path: str
    categories: Counter[str]

    @property
    def blocked(self) -> bool:
        return bool(self.categories)

    def to_report(self) -> dict[str, object]:
        return {
            "path": self.path,
            "categories": sorted(self.categories),
            "match_count": sum(self.categories.values()),
        }


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
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def safe_relative_path(repo: Path, path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(repo.resolve())
    except (OSError, ValueError):
        return None
    posix = PurePosixPath(relative.as_posix())
    if posix.is_absolute() or ".." in posix.parts:
        return None
    return posix.as_posix()


def iter_publish_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in PUBLISH_ROOTS:
        path = repo / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return sorted(files)


def category_counts_for_text(text: str, *, force_raw_source: bool = False) -> Counter[str]:
    counts: Counter[str] = Counter()
    if force_raw_source and text.strip():
        counts["raw_source_reference"] += 1
    for category, pattern in CATEGORY_PATTERNS.items():
        if pattern.search(text):
            counts[category] += 1
    return counts


def iter_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)


def audit_jsonl_index_file(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return counts
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            counts["malformed_index_jsonl"] += 1
            continue
        if not isinstance(row, dict):
            counts["malformed_index_jsonl"] += 1
            continue
        for key, value in row.items():
            normalized = str(key).lower()
            if normalized in TEXT_FIELDS:
                for text in iter_strings(value):
                    counts.update(category_counts_for_text(text))
            elif normalized in RAW_SOURCE_FIELDS:
                for text in iter_strings(value):
                    counts.update(category_counts_for_text(text, force_raw_source=True))
    return counts


def audit_raw_file(path: Path) -> Counter[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Counter()
    return category_counts_for_text(text)


def audit_file(repo: Path, path: Path) -> FileAudit | None:
    relative = safe_relative_path(repo, path)
    if relative is None:
        return None
    if relative.startswith("index/") and path.suffix == ".jsonl":
        counts = audit_jsonl_index_file(path)
    else:
        counts = audit_raw_file(path)
    return FileAudit(path=relative, categories=counts)


def audit_publish_readiness(repo: Path) -> dict[str, object]:
    audits = [audit for path in iter_publish_files(repo) if (audit := audit_file(repo, path)) is not None]
    blocked = [audit for audit in audits if audit.blocked]
    category_counts = {category: 0 for category in ALL_CATEGORIES}
    for audit in blocked:
        for category, count in audit.categories.items():
            category_counts[category] = category_counts.get(category, 0) + count
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "failed" if blocked else "passed",
        "scanned_file_count": len(audits),
        "blocked_file_count": len(blocked),
        "category_counts": category_counts,
        "blocked_paths": [audit.to_report() for audit in blocked],
        "privacy_leak_count": 0,
        "privacy": {
            "aggregate_only": True,
            "snippets_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "claim_boundary": (
            "publish-surface readiness only; not memory quality, ranking quality, "
            "LLM answer quality, GitHub availability, vector search, or ontology discovery"
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the memory repository")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_memory_repo(args.memory_repo)
    report = audit_publish_readiness(repo)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
