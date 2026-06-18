#!/usr/bin/env python3
"""Run a synthetic layered recall benchmark against a memory archive."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_SEARCH_SCRIPT = "templates/agent-memory-repo/tools/search_memory.py"


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {path}:{line_no}: {exc}") from exc
            if isinstance(value, dict):
                yield value


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int = 160) -> str:
    text = compact_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def run_search(search_script: Path, repo: Path, query: str, depth: str) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(search_script),
            query,
            "--repo",
            str(repo),
            "--depth",
            depth,
            "--limit",
            "5",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def load_memory_records(repo: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for record in iter_jsonl(repo / "index" / "memories.jsonl"):
        memory_id = record.get("memory_id")
        if isinstance(memory_id, str) and memory_id:
            records[memory_id] = record
    return records


def required_case_text(case: dict, key: str) -> str:
    value = case.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"benchmark case missing required string field: {key}")
    return value


def memory_record_is_visible(output: str, record: dict, expected_summary_path: str) -> bool:
    text = record.get("text")
    if isinstance(text, str) and clip(text) in output and expected_summary_path in output:
        return True
    topic = record.get("topic")
    return isinstance(topic, str) and topic in output and expected_summary_path in output


def source_anchor_is_visible(output: str, case: dict) -> bool:
    expected_anchor = case.get("expected_source_anchor")
    if isinstance(expected_anchor, str) and expected_anchor.strip():
        return expected_anchor in output
    return "source anchors:" in output


def score_cases(repo: Path, cases: list[dict], search_script: Path) -> dict:
    memory_records = load_memory_records(repo)
    memory_hits = 0
    session_hits = 0
    reachable_sources = 0

    for case in cases:
        query = required_case_text(case, "query")
        expected_memory_id = required_case_text(case, "expected_memory_id")
        expected_summary_path = required_case_text(case, "expected_summary_path")

        memory_output = run_search(search_script, repo, query, "memory")
        session_output = run_search(search_script, repo, query, "session")
        source_output = run_search(search_script, repo, query, "source")

        expected_record = memory_records.get(expected_memory_id)
        if expected_memory_id in memory_output or (
            expected_record is not None and memory_record_is_visible(memory_output, expected_record, expected_summary_path)
        ):
            memory_hits += 1
        if expected_summary_path in session_output:
            session_hits += 1
        if expected_summary_path in source_output and source_anchor_is_visible(source_output, case):
            reachable_sources += 1

    total = len(cases)
    denominator = total or 1
    return {
        "cases": total,
        "memory_recall_at_5": memory_hits / denominator,
        "session_drilldown_at_5": session_hits / denominator,
        "source_reachability": reachable_sources / denominator,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the memory archive")
    parser.add_argument("--cases", required=True, help="Path to JSONL benchmark cases")
    parser.add_argument("--search-script", default=DEFAULT_SEARCH_SCRIPT, help="Path to search_memory.py")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    cases = list(iter_jsonl(Path(args.cases).expanduser().resolve()))
    search_script = Path(args.search_script).expanduser().resolve()

    print(json.dumps(score_cases(repo, cases, search_script), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
