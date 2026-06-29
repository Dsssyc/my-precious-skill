#!/usr/bin/env python3
"""Generate extractive answer records from memory search hits.

This helper is intentionally narrow: it writes private answer records for an
offline generated-answer benchmark. It does not call a model and does not claim
semantic answer quality beyond what the benchmark later verifies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import search_memory  # noqa: E402


ABSTENTION_ANSWER = "There is not enough information in memory to answer."
REFERENCE_ANSWER_PREFIX_PATTERN = re.compile(r"\bReference answer:\s*", re.IGNORECASE)
REFERENCE_SECTION_BOUNDARY_PATTERN = re.compile(
    r"\s+\b(?:Expected memory|Query|Reference evidence|Synthetic answer target):",
    re.IGNORECASE,
)


def iter_jsonl(path: Path) -> Iterable[tuple[int, object]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to read JSONL {search_memory.safe_display_text(path.name)}: {exc}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {search_memory.safe_display_text(path.name)}:{line_no}: {exc}") from exc


def required_text(row: dict[str, Any], key: str, path: Path, line_no: int) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{search_memory.safe_display_text(path.name)}:{line_no}: field must be non-empty text: {key}")
    return value.strip()


def optional_text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{search_memory.safe_display_text(path.name)}:{line_no}: expected object case")
        case_id = required_text(value, "case_id", path, line_no)
        if case_id in seen:
            raise SystemExit(f"{search_memory.safe_display_text(path.name)}:{line_no}: duplicate case_id")
        seen.add(case_id)
        required_text(value, "query", path, line_no)
        cases.append(dict(value))
    if not cases:
        raise SystemExit(f"no answer cases found in {search_memory.safe_display_text(path.name)}")
    return cases


def search_memory_hits(repo: Path, query: str, limit: int) -> list[search_memory.Hit]:
    query_tokens = search_memory.unique_query_tokens(query)
    if not query_tokens:
        return []
    hits = search_memory.collect_memory_hits(repo, query_tokens, [], "all", "")
    return search_memory.merge_hits(repo, hits)[:limit]


def memory_text_by_id(repo: Path, memory_id: str) -> str:
    if not memory_id:
        return ""
    for record in search_memory.iter_jsonl(repo / "index" / "memories.jsonl"):
        if str(record.get("memory_id") or "") != memory_id:
            continue
        text = record.get("text")
        return text if isinstance(text, str) else ""
    return ""


def full_hit_text(repo: Path, hit: search_memory.Hit) -> str:
    text = memory_text_by_id(repo, hit.memory_id)
    return text or hit.text or hit.title


def trim_reference_answer_tail(answer: str, query: str) -> str:
    boundary = REFERENCE_SECTION_BOUNDARY_PATTERN.search(answer)
    if boundary:
        answer = answer[: boundary.start()]
    query_text = search_memory.compact_whitespace(query)
    if query_text:
        index = answer.lower().find(query_text.lower())
        if index > 0:
            answer = answer[:index]
    return answer.strip(" .")


def extract_answer_from_hit(repo: Path, hit: search_memory.Hit, query: str = "") -> str:
    text = search_memory.compact_whitespace(full_hit_text(repo, hit))
    match = REFERENCE_ANSWER_PREFIX_PATTERN.search(text)
    answer = trim_reference_answer_tail(text[match.end() :], query) if match else text
    answer = search_memory.compact_whitespace(answer)
    if not answer or search_memory.has_sensitive_display_text(answer):
        return ABSTENTION_ANSWER
    return answer


def build_answer_records(repo: Path, cases: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, str]], dict[str, Any]]:
    records: list[dict[str, str]] = []
    source_benchmarks: Counter[str] = Counter()
    case_origins: Counter[str] = Counter()
    memory_answer_count = 0
    abstention_answer_count = 0
    no_hit_count = 0

    for case in cases:
        source_benchmark = optional_text(case, "source_benchmark")
        if source_benchmark:
            source_benchmarks[source_benchmark] += 1
        case_origin = optional_text(case, "case_origin") or optional_text(case, "origin")
        if case_origin:
            case_origins[case_origin] += 1
        case_id = str(case["case_id"])
        query = str(case["query"])
        hits = search_memory_hits(repo, query, limit)
        if hits:
            answer = extract_answer_from_hit(repo, hits[0], query)
            if answer == ABSTENTION_ANSWER:
                abstention_answer_count += 1
            else:
                memory_answer_count += 1
        else:
            answer = ABSTENTION_ANSWER
            abstention_answer_count += 1
            no_hit_count += 1
        records.append({"case_id": case_id, "generated_answer": answer})

    report = {
        "report_kind": "generated_answer_records_adapter",
        "report_version": 1,
        "claim_boundary": "extractive memory-answer records only; no model-generation or semantic equivalence claim",
        "cases": len(cases),
        "answers_written": len(records),
        "memory_answer_count": memory_answer_count,
        "abstention_answer_count": abstention_answer_count,
        "no_hit_count": no_hit_count,
        "source_benchmarks": dict(sorted(source_benchmarks.items())),
        "case_origins": dict(sorted(case_origins.items())),
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "generated_answers_rendered": False,
            "reference_answers_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }
    return records, report


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    parser.add_argument("--cases", required=True, help="Answer benchmark cases JSONL")
    parser.add_argument("--output", required=True, help="Generated answer records JSONL to write")
    parser.add_argument("--limit", type=int, default=5, help="Top memory hits to consider per case")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")
    repo = Path(args.repo).expanduser().resolve()
    cases = load_cases(Path(args.cases).expanduser().resolve())
    records, report = build_answer_records(repo, cases, args.limit)
    write_jsonl(Path(args.output).expanduser().resolve(), records)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
