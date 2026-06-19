#!/usr/bin/env python3
"""Run a synthetic layered recall benchmark against a memory archive."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, NamedTuple


DEFAULT_SEARCH_SCRIPT = "templates/agent-memory-repo/tools/search_memory.py"
NO_HIT_MARKER = "No memory hits for:"


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
    required_case_text(case, "query", path, line_no)
    expected_abstain = case.get("expected_abstain") is True
    if not expected_abstain:
        for key in ("expected_memory_id", "expected_summary_path", "expected_source_anchor"):
            required_case_text(case, key, path, line_no)
    if "expected_abstain" in case and not isinstance(case["expected_abstain"], bool):
        raise SystemExit(f"{path}:{line_no}: benchmark case field must be boolean: expected_abstain")
    for key in (
        "category",
        "expected_not_memory_id",
        "stale_memory_id",
        "temporal_scope",
    ):
        optional_case_text_or_texts(case, key, path, line_no)
    for key in ("required_evidence_paths", "forbidden_output_patterns"):
        optional_case_texts(case, key, path, line_no)


def optional_case_text_or_texts(case: dict, key: str, path: Path, line_no: int) -> list[str]:
    if key not in case or case.get(key) in (None, ""):
        return []
    value = case.get(key)
    if isinstance(value, str):
        if value.strip():
            return [value.strip()]
    elif isinstance(value, list):
        return optional_case_texts(case, key, path, line_no)
    raise SystemExit(f"{path}:{line_no}: benchmark case field must be string or list of strings: {key}")


def optional_case_texts(case: dict, key: str, path: Path, line_no: int) -> list[str]:
    if key not in case or case.get(key) in (None, ""):
        return []
    value = case.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"{path}:{line_no}: benchmark case field must be list of strings: {key}")
    out: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SystemExit(f"{path}:{line_no}: benchmark case field {key}[{idx}] must be a non-empty string")
        out.append(item.strip())
    return out


def optional_case_text(case: dict, key: str) -> str:
    value = case.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def case_texts(case: dict, key: str) -> list[str]:
    value = case.get(key)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def positive_case(case: dict) -> bool:
    return case.get("expected_abstain") is not True


def category_name(case: dict) -> str:
    return optional_case_text(case, "category") or "uncategorized"


def no_hits(*block_groups: list[str]) -> bool:
    return not any(block for blocks in block_groups for block in blocks)


def new_totals() -> dict[str, float]:
    return {
        "cases": 0,
        "positive_cases": 0,
        "memory_hit_1": 0,
        "memory_hit_5": 0,
        "memory_rr": 0.0,
        "session_cases": 0,
        "session_hits": 0,
        "source_cases": 0,
        "source_hits": 0,
        "evidence_cases": 0,
        "evidence_hits": 0,
        "abstain_cases": 0,
        "abstain_hits": 0,
        "negative_cases": 0,
        "negative_hits": 0,
        "stale_cases": 0,
        "stale_hits": 0,
        "update_cases": 0,
        "update_hits": 0,
        "privacy_cases": 0,
        "privacy_hits": 0,
        "latency_ms": 0.0,
    }


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def finalize_totals(totals: dict[str, float]) -> dict:
    return {
        "cases": int(totals["cases"]),
        "memory_recall_at_1": ratio(totals["memory_hit_1"], totals["positive_cases"]),
        "memory_recall_at_5": ratio(totals["memory_hit_5"], totals["positive_cases"]),
        "memory_mrr": ratio(totals["memory_rr"], totals["positive_cases"]),
        "session_drilldown_at_5": ratio(totals["session_hits"], totals["session_cases"]),
        "source_reachability": ratio(totals["source_hits"], totals["source_cases"]),
        "evidence_reachability": ratio(totals["evidence_hits"], totals["evidence_cases"]),
        "abstention_accuracy": ratio(totals["abstain_hits"], totals["abstain_cases"]),
        "negative_memory_suppression": ratio(totals["negative_hits"], totals["negative_cases"]),
        "stale_memory_suppression": ratio(totals["stale_hits"], totals["stale_cases"]),
        "update_consistency": ratio(totals["update_hits"], totals["update_cases"]),
        "privacy_boundary_pass_rate": ratio(totals["privacy_hits"], totals["privacy_cases"]),
        "latency_ms": round(totals["latency_ms"], 3),
    }


def add_result(totals: dict[str, float], result: dict) -> None:
    totals["cases"] += 1
    totals["latency_ms"] += result["latency_ms"]
    totals["privacy_cases"] += 1
    totals["privacy_hits"] += int(result["privacy_boundary_pass"])
    if result["positive_case"]:
        totals["positive_cases"] += 1
        totals["memory_hit_1"] += int(result["memory_rank"] == 1)
        totals["memory_hit_5"] += int(result["memory_rank"] is not None and result["memory_rank"] <= 5)
        if result["memory_rank"] is not None:
            totals["memory_rr"] += 1 / result["memory_rank"]
        totals["session_cases"] += 1
        totals["session_hits"] += int(result["session_drilldown_hit"])
        totals["source_cases"] += int(result["source_expected"])
        totals["source_hits"] += int(result["source_reachability_hit"])
        totals["evidence_cases"] += int(result["evidence_expected"])
        totals["evidence_hits"] += int(result["evidence_reachability_hit"])
    if result["expected_abstain"]:
        totals["abstain_cases"] += 1
        totals["abstain_hits"] += int(result["abstention_hit"])
    if result["negative_expected"]:
        totals["negative_cases"] += 1
        totals["negative_hits"] += int(result["negative_memory_suppression_hit"])
    if result["stale_expected"]:
        totals["stale_cases"] += 1
        totals["stale_hits"] += int(result["stale_memory_suppression_hit"])
    if result["update_expected"]:
        totals["update_cases"] += 1
        totals["update_hits"] += int(result["update_consistency_hit"])


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
        if NO_HIT_MARKER in result.stdout:
            return result.stdout
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


def session_drilldown_hit(blocks: list[str], expected_summary_path: str) -> bool:
    return any(expected_summary_path in block for block in blocks)


def source_reachability_hit(blocks: list[str], expected_summary_path: str, expected_source_anchor: str) -> bool:
    for block in blocks:
        if not block_has_drill_path(block, expected_summary_path):
            continue
        if expected_source_anchor in section_items(block, "source anchors"):
            return True
    return False


def block_contains_memory(block: str, memory_id: str, record: dict | None) -> bool:
    if memory_id and memory_id in block:
        return True
    return record is not None and memory_record_is_visible(block, record)


def memory_hit_rank(
    blocks: list[str],
    expected_memory_id: str,
    expected_summary_path: str,
    record: dict | None,
) -> int | None:
    for rank, block in enumerate(blocks, 1):
        if not is_memory_block(block) or not block_has_drill_path(block, expected_summary_path):
            continue
        if block_contains_memory(block, expected_memory_id, record):
            return rank
    return None


def blocks_contain_memory_ids(blocks: list[str], memory_ids: list[str], records: dict[str, dict]) -> bool:
    for memory_id in memory_ids:
        record = records.get(memory_id)
        for block in blocks:
            if block_contains_memory(block, memory_id, record):
                return True
    return False


def evidence_reachability_hit(blocks: list[str], required_paths: list[str]) -> bool:
    if not required_paths:
        return False
    return all(any(required_path in block for block in blocks) for required_path in required_paths)


def privacy_boundary_pass(outputs: list[str], forbidden_patterns: list[str]) -> bool:
    if not forbidden_patterns:
        return True
    combined = "\n".join(outputs)
    return not any(pattern in combined for pattern in forbidden_patterns)


def score_case(repo: Path, case: Case, memory_records: dict[str, dict], search_script: Path) -> dict:
    data = case.data
    query = required_case_text(data, "query", case.path, case.line_no)

    started = time.perf_counter()
    memory_output = run_search(search_script, repo, query, "memory")
    session_output = run_search(search_script, repo, query, "session")
    source_output = run_search(search_script, repo, query, "source")
    latency_ms = (time.perf_counter() - started) * 1000

    memory_blocks = parse_hit_blocks(memory_output)
    session_blocks = parse_hit_blocks(session_output)
    source_blocks = parse_hit_blocks(source_output)
    expected_abstain = data.get("expected_abstain") is True
    is_positive = positive_case(data)
    expected_memory_id = optional_case_text(data, "expected_memory_id")
    expected_summary_path = optional_case_text(data, "expected_summary_path")
    expected_source_anchor = optional_case_text(data, "expected_source_anchor")
    required_evidence_paths = case_texts(data, "required_evidence_paths")
    negative_memory_ids = case_texts(data, "expected_not_memory_id")
    stale_memory_ids = case_texts(data, "stale_memory_id")
    forbidden_patterns = case_texts(data, "forbidden_output_patterns")

    expected_record = memory_records.get(expected_memory_id)
    rank = None
    session_hit = False
    source_hit = False
    evidence_hit = False
    if is_positive:
        rank = memory_hit_rank(memory_blocks, expected_memory_id, expected_summary_path, expected_record)
        session_hit = session_drilldown_hit(session_blocks, expected_summary_path)
        if expected_source_anchor:
            source_hit = source_reachability_hit(source_blocks, expected_summary_path, expected_source_anchor)
        if required_evidence_paths:
            evidence_hit = evidence_reachability_hit(source_blocks + memory_blocks, required_evidence_paths)

    no_result_hits = no_hits(memory_blocks, session_blocks, source_blocks)
    negative_suppressed = not blocks_contain_memory_ids(memory_blocks, negative_memory_ids, memory_records)
    stale_suppressed = not blocks_contain_memory_ids(memory_blocks, stale_memory_ids, memory_records)
    update_expected = bool(is_positive and stale_memory_ids)

    return {
        "positive_case": is_positive,
        "expected_abstain": expected_abstain,
        "memory_rank": rank,
        "session_drilldown_hit": session_hit,
        "source_expected": bool(is_positive and expected_source_anchor),
        "source_reachability_hit": source_hit,
        "evidence_expected": bool(is_positive and required_evidence_paths),
        "evidence_reachability_hit": evidence_hit,
        "abstention_hit": bool(expected_abstain and no_result_hits),
        "negative_expected": bool(negative_memory_ids),
        "negative_memory_suppression_hit": negative_suppressed,
        "stale_expected": bool(stale_memory_ids),
        "stale_memory_suppression_hit": stale_suppressed,
        "update_expected": update_expected,
        "update_consistency_hit": bool(update_expected and rank is not None and stale_suppressed),
        "privacy_boundary_pass": privacy_boundary_pass(
            [memory_output, session_output, source_output],
            forbidden_patterns,
        ),
        "latency_ms": latency_ms,
    }


def score_cases(repo: Path, cases: list[Case], search_script: Path) -> dict:
    memory_records = load_memory_records(repo)
    totals = new_totals()
    category_totals: dict[str, dict[str, float]] = {}

    for case in cases:
        result = score_case(repo, case, memory_records, search_script)
        add_result(totals, result)
        category = category_name(case.data)
        category_totals.setdefault(category, new_totals())
        add_result(category_totals[category], result)

    payload = finalize_totals(totals)
    payload["categories"] = {
        category: finalize_totals(category_total)
        for category, category_total in sorted(category_totals.items())
    }
    return payload


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
