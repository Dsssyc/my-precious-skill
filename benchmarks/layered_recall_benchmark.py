#!/usr/bin/env python3
"""Run a synthetic layered recall benchmark against a memory archive."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple


DEFAULT_SEARCH_SCRIPT = "templates/agent-memory-repo/tools/search_memory.py"


class Case(NamedTuple):
    data: dict
    path: Path
    line_no: int


def iter_jsonl(path: Path) -> Iterable[tuple[int, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {path}:{line_no}: {exc}") from exc
            yield line_no, value


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{path}:{line_no}: expected object benchmark case")
        validate_case(value, path, line_no)
        cases.append(Case(value, path, line_no))
    if not cases:
        raise SystemExit(f"no benchmark cases found in {path}")
    return cases


def validate_case(case: dict, path: Path, line_no: int) -> None:
    for key in ("query", "expected_memory_id", "expected_summary_path", "expected_source_anchor"):
        required_case_text(case, key, path, line_no)


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
    if result.returncode != 0:
        stderr = result.stderr.strip() or "(empty stderr)"
        raise SystemExit(
            "search failed: "
            f"depth={depth} query={query!r} returncode={result.returncode} "
            f"script={search_script}\nstderr:\n{stderr}"
        )
    return result.stdout


def load_memory_records(repo: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for _, value in iter_jsonl(repo / "index" / "memories.jsonl"):
        if not isinstance(value, dict):
            continue
        record = value
        memory_id = record.get("memory_id")
        if isinstance(memory_id, str) and memory_id:
            records[memory_id] = record
    return records


def required_case_text(case: dict, key: str, path: Path, line_no: int) -> str:
    value = case.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{path}:{line_no}: benchmark case missing required string field: {key}")
    return value


def parse_hit_blocks(output: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in output.splitlines():
        if re.match(r"^\d+\.\s", line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return ["\n".join(block) for block in blocks]


def is_memory_block(block: str) -> bool:
    return bool(re.search(r"^\s*source:\s*memory\s*$", block, flags=re.MULTILINE))


def section_items(block: str, section_name: str) -> list[str]:
    items: list[str] = []
    in_section = False
    for line in block.splitlines():
        stripped = line.strip()
        if stripped == f"{section_name}:":
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
            continue
        if stripped and not line.startswith("     "):
            break
    return items


def block_has_drill_path(block: str, expected_summary_path: str) -> bool:
    return expected_summary_path in section_items(block, "drill")


def memory_record_is_visible(block: str, record: dict) -> bool:
    text = record.get("text")
    if isinstance(text, str) and clip(text) in block:
        return True
    topic = record.get("topic")
    return isinstance(topic, str) and topic in block


def memory_recall_hit(blocks: list[str], expected_memory_id: str, expected_summary_path: str, record: dict | None) -> bool:
    for block in blocks:
        if not is_memory_block(block) or not block_has_drill_path(block, expected_summary_path):
            continue
        if expected_memory_id in block:
            return True
        if record is not None and memory_record_is_visible(block, record):
            return True
    return False


def session_drilldown_hit(blocks: list[str], expected_summary_path: str) -> bool:
    return any(expected_summary_path in block for block in blocks)


def source_reachability_hit(blocks: list[str], expected_summary_path: str, expected_source_anchor: str) -> bool:
    for block in blocks:
        if not block_has_drill_path(block, expected_summary_path):
            continue
        if expected_source_anchor in section_items(block, "source anchors"):
            return True
    return False


def score_cases(repo: Path, cases: list[Case], search_script: Path) -> dict:
    memory_records = load_memory_records(repo)
    memory_hits = 0
    session_hits = 0
    reachable_sources = 0

    for case in cases:
        query = required_case_text(case.data, "query", case.path, case.line_no)
        expected_memory_id = required_case_text(case.data, "expected_memory_id", case.path, case.line_no)
        expected_summary_path = required_case_text(case.data, "expected_summary_path", case.path, case.line_no)
        expected_source_anchor = required_case_text(case.data, "expected_source_anchor", case.path, case.line_no)

        memory_blocks = parse_hit_blocks(run_search(search_script, repo, query, "memory"))
        session_blocks = parse_hit_blocks(run_search(search_script, repo, query, "session"))
        source_blocks = parse_hit_blocks(run_search(search_script, repo, query, "source"))

        expected_record = memory_records.get(expected_memory_id)
        if memory_recall_hit(memory_blocks, expected_memory_id, expected_summary_path, expected_record):
            memory_hits += 1
        if session_drilldown_hit(session_blocks, expected_summary_path):
            session_hits += 1
        if source_reachability_hit(source_blocks, expected_summary_path, expected_source_anchor):
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
    cases = load_cases(Path(args.cases).expanduser().resolve())
    search_script = Path(args.search_script).expanduser().resolve()

    print(json.dumps(score_cases(repo, cases, search_script), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
