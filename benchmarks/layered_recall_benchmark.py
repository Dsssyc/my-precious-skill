#!/usr/bin/env python3
"""Run a synthetic layered recall benchmark against a memory archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, NamedTuple


DEFAULT_SEARCH_SCRIPT = "templates/agent-memory-repo/tools/search_memory.py"
NO_HIT_MARKER = "No memory hits for:"
DEFAULT_SEARCH_TIMEOUT_S = 30.0
UNSAFE_RESULT_IDENTIFIER = "[unsafe-result-identifier]"
UNSAFE_SOURCE_REF = "[unsafe-source-ref]"
UNSAFE_SOURCE_ANCHOR_MARKERS = {UNSAFE_RESULT_IDENTIFIER, UNSAFE_SOURCE_REF}
EXPLAINABLE_MEMORY_REASON_PREFIXES = ("field:", "phrase:")
EXPLAINABLE_MEMORY_REASONS = {"important-token-coverage", "project-context"}
UNEXPLAINABLE_MEMORY_REASONS = {"low-signal-only", "broad-field-only"}
MEMORY_LAYERS = ("global", "domain", "project")
SENSITIVE_RESULT_IDENTIFIER_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b(?:api[_-]?key|authorization|bearer|cookie|credential|password|"
    r"private[_ -]?key|secret|session[_-]?id|token)\b\s*[:=]|"
    r"\bbearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)


class Case(NamedTuple):
    data: dict
    path: Path
    line_no: int


class MemoryPrecisionAt5(NamedTuple):
    score: float
    result_count: int
    relevant_count: int


Totals = dict[str, Any]


def has_diagnostic_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def safe_diagnostic_text(value: object) -> str:
    text = str(value)
    if has_diagnostic_control_chars(text) or SENSITIVE_RESULT_IDENTIFIER_PATTERN.search(text):
        return UNSAFE_RESULT_IDENTIFIER
    return text


def safe_diagnostic_path(path: Path) -> str:
    return safe_diagnostic_text(path)


def case_location(path: Path, line_no: int) -> str:
    return f"{safe_diagnostic_path(path)}:{line_no}"


def iter_jsonl(path: Path) -> Iterable[tuple[int, object]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to read JSONL {safe_diagnostic_path(path)}: {safe_diagnostic_text(exc)}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {case_location(path, line_no)}: {exc}") from exc
            yield line_no, value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_memory_repo(repo: Path) -> None:
    required_path = repo / "index" / "memories.jsonl"
    if not required_path.is_file():
        raise SystemExit(f"memory archive is missing required file: {safe_diagnostic_path(required_path)}")


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    seen_case_ids: dict[str, int] = {}
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{case_location(path, line_no)}: expected object benchmark case")
        validate_case(value, path, line_no)
        case_id = optional_case_text(value, "case_id")
        if case_id:
            first_line = seen_case_ids.get(case_id)
            if first_line is not None:
                display_case_id = safe_result_identifier(case_id)
                raise SystemExit(
                    f"{case_location(path, line_no)}: duplicate case_id {display_case_id!r}; "
                    f"first seen at {case_location(path, first_line)}"
                )
            seen_case_ids[case_id] = line_no
        cases.append(Case(value, path, line_no))
    if not cases:
        raise SystemExit(f"no benchmark cases found in {safe_diagnostic_path(path)}")
    return cases


def validate_case(case: dict, path: Path, line_no: int) -> None:
    required_case_text(case, "query", path, line_no)
    expected_abstain = case.get("expected_abstain") is True
    if not expected_abstain:
        for key in ("expected_memory_id", "expected_summary_path", "expected_source_anchor"):
            required_case_text(case, key, path, line_no)
    if "expected_abstain" in case and not isinstance(case["expected_abstain"], bool):
        raise SystemExit(f"{case_location(path, line_no)}: benchmark case field must be boolean: expected_abstain")
    for key in ("case_id", "source_benchmark"):
        optional_case_text_only(case, key, path, line_no)
    expected_layer = optional_case_text_only(case, "expected_layer", path, line_no)
    if expected_layer and expected_layer not in MEMORY_LAYERS:
        raise SystemExit(f"{case_location(path, line_no)}: expected_layer must be global, domain, or project")
    for key in (
        "category",
        "expected_not_memory_id",
        "reference_answer",
        "reference_evidence",
        "stale_memory_id",
        "temporal_scope",
    ):
        optional_case_text_or_texts(case, key, path, line_no)
    expected_memory_id = optional_case_text(case, "expected_memory_id")
    if expected_memory_id:
        for key in ("expected_not_memory_id", "stale_memory_id"):
            if expected_memory_id in case_texts(case, key):
                raise SystemExit(
                    f"{case_location(path, line_no)}: expected_memory_id must not also appear in {key}"
                )
    validate_case_archive_path(case, "expected_summary_path", path, line_no)
    validate_case_archive_path(case, "expected_source_anchor", path, line_no)
    for evidence_path in optional_case_texts(case, "required_evidence_paths", path, line_no):
        validate_archive_relative_path(evidence_path, "required_evidence_paths", path, line_no)
    validate_forbidden_output_patterns(case, path, line_no)


def validate_case_archive_path(case: dict, key: str, path: Path, line_no: int) -> None:
    value = optional_case_text(case, key)
    if value:
        validate_archive_relative_path(value, key, path, line_no)


def validate_archive_relative_path(value: str, key: str, path: Path, line_no: int) -> None:
    if has_unsafe_path_reference(value):
        raise SystemExit(f"{case_location(path, line_no)}: unsafe archive path in benchmark case field: {key}")


def optional_case_text_or_texts(case: dict, key: str, path: Path, line_no: int) -> list[str]:
    if key not in case or case.get(key) in (None, ""):
        return []
    value = case.get(key)
    if isinstance(value, str):
        if value.strip():
            return [value.strip()]
    elif isinstance(value, list):
        return optional_case_texts(case, key, path, line_no)
    raise SystemExit(f"{case_location(path, line_no)}: benchmark case field must be string or list of strings: {key}")


def optional_case_texts(case: dict, key: str, path: Path, line_no: int) -> list[str]:
    if key not in case or case.get(key) in (None, ""):
        return []
    value = case.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"{case_location(path, line_no)}: benchmark case field must be list of strings: {key}")
    out: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SystemExit(f"{case_location(path, line_no)}: benchmark case field {key}[{idx}] must be a non-empty string")
        out.append(item.strip())
    return out


def validate_forbidden_output_patterns(case: dict, path: Path, line_no: int) -> list[str]:
    patterns = optional_case_texts(case, "forbidden_output_patterns", path, line_no)
    for idx, pattern in enumerate(patterns):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SystemExit(f"{case_location(path, line_no)}: invalid forbidden_output_patterns[{idx}]: {exc}") from exc
    return patterns


def optional_case_text_only(case: dict, key: str, path: Path, line_no: int) -> str:
    if key not in case or case.get(key) in (None, ""):
        return ""
    value = case.get(key)
    if isinstance(value, str):
        return value.strip()
    raise SystemExit(f"{case_location(path, line_no)}: benchmark case field must be string: {key}")


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


def safe_category_name(case: dict) -> str:
    return safe_result_identifier(category_name(case))


def no_hits(*block_groups: list[str]) -> bool:
    return not any(block for blocks in block_groups for block in blocks)


def new_totals() -> Totals:
    return {
        "cases": 0,
        "positive_cases": 0,
        "memory_hit_1": 0,
        "memory_hit_5": 0,
        "memory_rr": 0.0,
        "memory_rank_sum": 0.0,
        "memory_rank_counts": {},
        "memory_ndcg_at_5": 0.0,
        "memory_precision_at_5": 0.0,
        "memory_explainability_cases": 0,
        "memory_explainability_hits": 0,
        "layer_cases": 0,
        "layer_hits": 0,
        "scope_filter_cases": 0,
        "scope_filter_hits": 0,
        "wrong_scope_cases": 0,
        "wrong_scope_hits": 0,
        "memory_result_count_at_5": 0,
        "memory_relevant_count_at_5": 0,
        "session_cases": 0,
        "session_hits": 0,
        "source_cases": 0,
        "source_hits": 0,
        "source_precision_at_5": 0.0,
        "source_result_count_at_5": 0,
        "source_relevant_count_at_5": 0,
        "unsafe_source_anchor_count_at_5": 0,
        "evidence_cases": 0,
        "evidence_hits": 0,
        "evidence_text_cases": 0,
        "evidence_text_hits": 0,
        "answer_cases": 0,
        "answer_hits": 0,
        "answer_normalized_hits": 0,
        "answer_f1": 0.0,
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
        "failed_cases": 0,
        "latency_ms": 0.0,
        "latency_max_ms": 0.0,
    }


def ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def memory_rank_counts(totals: Totals) -> dict[int, int]:
    counts = totals.get("memory_rank_counts")
    return counts if isinstance(counts, dict) else {}


def memory_rank_median(rank_counts: dict[int, int]) -> float:
    total = sum(rank_counts.values())
    if not total:
        return 0.0

    def rank_at(position: int) -> int:
        seen = 0
        for rank, count in sorted(rank_counts.items()):
            seen += count
            if position <= seen:
                return rank
        return 0

    if total % 2:
        return float(rank_at(total // 2 + 1))
    return (rank_at(total // 2) + rank_at(total // 2 + 1)) / 2


def memory_rank_histogram(rank_counts: dict[int, int], missing_cases: int) -> dict[str, int]:
    histogram = {str(rank): int(rank_counts.get(rank, 0)) for rank in range(1, 6)}
    histogram[">5"] = sum(count for rank, count in rank_counts.items() if rank > 5)
    histogram["missing"] = max(0, missing_cases)
    return histogram


def finalize_totals(totals: Totals) -> dict:
    positive_cases = int(totals["positive_cases"])
    rank_counts = memory_rank_counts(totals)
    ranked_cases = sum(rank_counts.values())
    missing_rank_cases = max(0, positive_cases - ranked_cases)
    return {
        "cases": int(totals["cases"]),
        "positive_cases": positive_cases,
        "session_cases": int(totals["session_cases"]),
        "source_cases": int(totals["source_cases"]),
        "evidence_cases": int(totals["evidence_cases"]),
        "answer_cases": int(totals["answer_cases"]),
        "abstain_cases": int(totals["abstain_cases"]),
        "negative_cases": int(totals["negative_cases"]),
        "stale_cases": int(totals["stale_cases"]),
        "update_cases": int(totals["update_cases"]),
        "privacy_cases": int(totals["privacy_cases"]),
        "memory_recall_at_1": ratio(totals["memory_hit_1"], totals["positive_cases"]),
        "memory_recall_at_5": ratio(totals["memory_hit_5"], totals["positive_cases"]),
        "memory_precision_at_5": ratio(totals["memory_precision_at_5"], totals["positive_cases"]),
        "memory_micro_precision_at_5": ratio(
            totals["memory_relevant_count_at_5"],
            totals["memory_result_count_at_5"],
        ),
        "memory_result_count_at_5": int(totals["memory_result_count_at_5"]),
        "memory_relevant_count_at_5": int(totals["memory_relevant_count_at_5"]),
        "memory_mrr": ratio(totals["memory_rr"], totals["positive_cases"]),
        "memory_ndcg_at_5": ratio(totals["memory_ndcg_at_5"], totals["positive_cases"]),
        "memory_explainability_cases": int(totals["memory_explainability_cases"]),
        "memory_explainability": ratio(
            totals["memory_explainability_hits"],
            totals["memory_explainability_cases"],
        ),
        "layer_calibration_cases": int(totals["layer_cases"]),
        "layer_calibration": ratio(totals["layer_hits"], totals["layer_cases"]),
        "scope_filter_cases": int(totals["scope_filter_cases"]),
        "scope_filter_recall": ratio(totals["scope_filter_hits"], totals["scope_filter_cases"]),
        "wrong_scope_suppression_cases": int(totals["wrong_scope_cases"]),
        "wrong_scope_suppression": ratio(totals["wrong_scope_hits"], totals["wrong_scope_cases"]),
        "memory_ranked_cases": ranked_cases,
        "memory_rank_missing_cases": missing_rank_cases,
        "memory_rank_mean": ratio(totals["memory_rank_sum"], ranked_cases),
        "memory_rank_median": memory_rank_median(rank_counts),
        "memory_rank_histogram": memory_rank_histogram(rank_counts, missing_rank_cases),
        "session_drilldown_at_5": ratio(totals["session_hits"], totals["session_cases"]),
        "source_reachability": ratio(totals["source_hits"], totals["source_cases"]),
        "source_precision_at_5": ratio(totals["source_precision_at_5"], totals["source_cases"]),
        "source_micro_precision_at_5": ratio(
            totals["source_relevant_count_at_5"],
            totals["source_result_count_at_5"],
        ),
        "source_result_count_at_5": int(totals["source_result_count_at_5"]),
        "source_relevant_count_at_5": int(totals["source_relevant_count_at_5"]),
        "unsafe_source_anchor_count_at_5": int(totals["unsafe_source_anchor_count_at_5"]),
        "unsafe_source_anchor_rate_at_5": ratio(
            totals["unsafe_source_anchor_count_at_5"],
            totals["source_result_count_at_5"],
        ),
        "evidence_reachability": ratio(totals["evidence_hits"], totals["evidence_cases"]),
        "evidence_text_cases": int(totals["evidence_text_cases"]),
        "evidence_text_reachability": ratio(totals["evidence_text_hits"], totals["evidence_text_cases"]),
        "answer_reachability": ratio(totals["answer_hits"], totals["answer_cases"]),
        "answer_normalized_reachability": ratio(totals["answer_normalized_hits"], totals["answer_cases"]),
        "answer_token_f1": ratio(totals["answer_f1"], totals["answer_cases"]),
        "abstention_accuracy": ratio(totals["abstain_hits"], totals["abstain_cases"]),
        "negative_memory_suppression": ratio(totals["negative_hits"], totals["negative_cases"]),
        "stale_memory_suppression": ratio(totals["stale_hits"], totals["stale_cases"]),
        "update_consistency": ratio(totals["update_hits"], totals["update_cases"]),
        "privacy_boundary_pass_rate": ratio(totals["privacy_hits"], totals["privacy_cases"]),
        "failed_case_count": int(totals["failed_cases"]),
        "case_pass_rate": ratio(totals["cases"] - totals["failed_cases"], totals["cases"]),
        "latency_ms": round(totals["latency_ms"], 3),
        "latency_mean_ms": round(ratio(totals["latency_ms"], totals["cases"]), 3),
        "latency_max_ms": round(totals["latency_max_ms"], 3),
    }


def add_result(totals: Totals, result: dict) -> None:
    totals["cases"] += 1
    totals["latency_ms"] += result["latency_ms"]
    totals["latency_max_ms"] = max(totals["latency_max_ms"], result["latency_ms"])
    totals["privacy_cases"] += 1
    totals["privacy_hits"] += int(result["privacy_boundary_pass"])
    totals["failed_cases"] += int(bool(failed_checks(result)))
    if result["positive_case"]:
        totals["positive_cases"] += 1
        totals["memory_hit_1"] += int(result["memory_rank"] == 1)
        totals["memory_hit_5"] += int(result["memory_rank"] is not None and result["memory_rank"] <= 5)
        if result["memory_rank"] is not None:
            totals["memory_rr"] += 1 / result["memory_rank"]
            totals["memory_rank_sum"] += result["memory_rank"]
            rank_counts = memory_rank_counts(totals)
            rank_counts[result["memory_rank"]] = rank_counts.get(result["memory_rank"], 0) + 1
        totals["memory_ndcg_at_5"] += result["memory_ndcg_at_5"]
        totals["memory_precision_at_5"] += result["memory_precision_at_5"]
        if result["memory_rank"] is not None:
            totals["memory_explainability_cases"] += 1
            totals["memory_explainability_hits"] += int(result["memory_explainability_hit"])
        if result["layer_expected"]:
            totals["layer_cases"] += 1
            totals["layer_hits"] += int(result["layer_calibration_hit"])
            totals["scope_filter_cases"] += 1
            totals["scope_filter_hits"] += int(result["scope_filter_hit"])
            totals["wrong_scope_cases"] += 1
            totals["wrong_scope_hits"] += int(result["wrong_scope_suppression_hit"])
        totals["memory_result_count_at_5"] += result["memory_result_count_at_5"]
        totals["memory_relevant_count_at_5"] += result["memory_relevant_count_at_5"]
        totals["session_cases"] += 1
        totals["session_hits"] += int(result["session_drilldown_hit"])
        totals["source_cases"] += int(result["source_expected"])
        totals["source_hits"] += int(result["source_reachability_hit"])
        if result["source_expected"]:
            totals["source_precision_at_5"] += result["source_precision_at_5"]
            totals["source_result_count_at_5"] += result["source_result_count_at_5"]
            totals["source_relevant_count_at_5"] += result["source_relevant_count_at_5"]
            totals["unsafe_source_anchor_count_at_5"] += result["unsafe_source_anchor_count_at_5"]
        totals["evidence_cases"] += int(result["evidence_expected"])
        totals["evidence_hits"] += int(result["evidence_reachability_hit"])
        totals["evidence_text_cases"] += int(result["evidence_text_expected"])
        totals["evidence_text_hits"] += int(result["evidence_text_reachability_hit"])
        totals["answer_cases"] += int(result["answer_expected"])
        totals["answer_hits"] += int(result["answer_reachability_hit"])
        totals["answer_normalized_hits"] += int(result["answer_normalized_reachability_hit"])
        totals["answer_f1"] += result["answer_token_f1"] if result["answer_expected"] else 0.0
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


def has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def has_unsafe_path_reference(text: str) -> bool:
    path_text = text.split("#", 1)[0].strip()
    if not path_text:
        return False
    if path_text.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", path_text):
        return True
    return any(part == ".." for part in re.split(r"[\\/]+", path_text))


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
                "secret",
                "token",
            }
        )
        or token_pairs.intersection({("api", "key"), ("private", "key"), ("session", "id")})
    )


def safe_result_identifier(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if (
        has_control_chars(text)
        or SENSITIVE_RESULT_IDENTIFIER_PATTERN.search(text)
        or has_sensitive_identifier_token(text)
        or has_unsafe_path_reference(text)
    ):
        return UNSAFE_RESULT_IDENTIFIER
    return clip(text)


def safe_result_identifiers(values: list[str]) -> list[str]:
    return unique_texts(identifier for value in values if (identifier := safe_result_identifier(value)))


def safe_reason_identifier(value: str) -> str:
    reason = value.strip()
    if not reason:
        return ""
    if reason in EXPLAINABLE_MEMORY_REASONS or reason in UNEXPLAINABLE_MEMORY_REASONS:
        if has_control_chars(reason) or SENSITIVE_RESULT_IDENTIFIER_PATTERN.search(reason):
            return UNSAFE_RESULT_IDENTIFIER
        return clip(reason)
    return safe_result_identifier(reason)


def safe_reason_identifiers(values: list[str]) -> list[str]:
    return unique_texts(identifier for value in values if (identifier := safe_reason_identifier(value)))


def run_search(search_script: Path, repo: Path, query: str, depth: str, timeout_s: float, scope: str = "all") -> str:
    display_query = safe_result_identifier(query)
    display_script = safe_diagnostic_path(search_script)
    command = [
        sys.executable,
        str(search_script),
        query,
        "--repo",
        str(repo),
        "--depth",
        depth,
        "--limit",
        "5",
    ]
    if scope != "all":
        command.extend(["--scope", scope])
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "search timed out: "
            f"depth={depth} scope={scope} query={display_query!r} timeout_s={timeout_s:g} "
            f"script={display_script}"
        ) from exc
    if result.returncode != 0:
        if NO_HIT_MARKER in result.stdout:
            return result.stdout
        stderr = safe_result_identifier(result.stderr.strip() or "(empty stderr)")
        raise SystemExit(
            "search failed: "
            f"depth={depth} scope={scope} query={display_query!r} returncode={result.returncode} "
            f"script={display_script}\nstderr:\n{stderr}"
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
        raise SystemExit(f"{case_location(path, line_no)}: benchmark case missing required string field: {key}")
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


def unique_texts(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def block_field_values(blocks: list[str], field_name: str) -> list[str]:
    values: list[str] = []
    prefix = f"{field_name}:"
    for block in blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped.startswith(prefix):
                continue
            value = stripped[len(prefix) :].strip()
            if value:
                values.append(value)
    return unique_texts(values)


def block_memory_ids(block: str) -> list[str]:
    return block_field_values([block], "memory_id")


def block_reason_values(block: str) -> list[str]:
    reasons: list[str] = []
    for value in block_field_values([block], "why"):
        for reason in value.split(";"):
            reason = reason.strip()
            if reason:
                reasons.append(reason)
    return unique_texts(reasons)


def explainable_reason(reason: str) -> bool:
    return reason in EXPLAINABLE_MEMORY_REASONS or reason.startswith(EXPLAINABLE_MEMORY_REASON_PREFIXES)


def unexplainable_reason(reason: str) -> bool:
    return reason in UNEXPLAINABLE_MEMORY_REASONS or reason.startswith("quality-penalty:")


def block_has_explainable_memory_reason(block: str) -> bool:
    reasons = block_reason_values(block)
    if any(unexplainable_reason(reason) for reason in reasons):
        return False
    return any(explainable_reason(reason) for reason in reasons)


def block_section_values(blocks: list[str], section_name: str) -> list[str]:
    return unique_texts(item for block in blocks for item in section_items(block, section_name))


def block_title_path(block: str) -> str:
    first_line = block.splitlines()[0] if block.splitlines() else ""
    match = re.match(r"^\d+\.\s+(.+)$", first_line)
    if not match:
        return ""
    candidate = match.group(1).strip()
    if not candidate or candidate.startswith("["):
        return ""
    if re.search(r"\s", candidate):
        return ""
    if "/" not in candidate and not candidate.endswith((".md", ".jsonl", ".json")):
        return ""
    return candidate


def block_memory_layer(block: str) -> str:
    first_line = block.splitlines()[0] if block.splitlines() else ""
    match = re.match(r"^\d+\.\s+\[([^\]]+)\]", first_line)
    if not match:
        return ""
    return match.group(1).strip()


def block_memory_title(block: str) -> str:
    first_line = block.splitlines()[0] if block.splitlines() else ""
    match = re.match(r"^\d+\.\s+\[[^\]]+\]\s+(.+)$", first_line)
    if not match:
        return ""
    return match.group(1).strip()


def block_result_paths(blocks: list[str]) -> list[str]:
    title_paths = [path for block in blocks if (path := block_title_path(block))]
    drill_paths = block_section_values(blocks, "drill")
    return unique_texts([*title_paths, *drill_paths])


def memory_result_diagnostics(blocks: list[str]) -> list[dict]:
    diagnostics: list[dict] = []
    for rank, block in enumerate(blocks, 1):
        if not is_memory_block(block):
            continue
        memory_ids = safe_result_identifiers(block_field_values([block], "memory_id"))
        diagnostics.append(
            {
                "rank": rank,
                "memory_id": memory_ids[0] if memory_ids else "",
                "layer": safe_result_identifier(block_memory_layer(block)),
                "reasons": safe_reason_identifiers(block_reason_values(block)),
                "drill_paths": safe_result_identifiers(section_items(block, "drill")),
            }
        )
        if len(diagnostics) >= 5:
            break
    return diagnostics


def block_has_drill_path(block: str, expected_summary_path: str) -> bool:
    return expected_summary_path in section_items(block, "drill")


def memory_record_is_visible(block: str, record: dict) -> bool:
    title = block_memory_title(block)
    text = record.get("text")
    if isinstance(text, str) and title == clip(text):
        return True
    topic = record.get("topic")
    return isinstance(topic, str) and title == topic


def session_drilldown_hit(blocks: list[str], expected_summary_path: str) -> bool:
    return expected_summary_path in block_result_paths(blocks)


def source_reachability_hit(blocks: list[str], expected_summary_path: str, expected_source_anchor: str) -> bool:
    for block in blocks:
        if not block_has_drill_path(block, expected_summary_path):
            continue
        if expected_source_anchor in section_items(block, "source anchors"):
            return True
    return False


def source_anchor_precision_at_5(blocks: list[str], expected_source_anchor: str) -> MemoryPrecisionAt5:
    anchors = block_section_values(blocks[:5], "source anchors")
    if not anchors:
        return MemoryPrecisionAt5(score=0.0, result_count=0, relevant_count=0)
    relevant = sum(int(anchor == expected_source_anchor) for anchor in anchors)
    return MemoryPrecisionAt5(
        score=relevant / len(anchors),
        result_count=len(anchors),
        relevant_count=relevant,
    )


def unsafe_source_anchor_count_at_5(blocks: list[str]) -> int:
    anchors = block_section_values(blocks[:5], "source anchors")
    return sum(
        int(anchor in UNSAFE_SOURCE_ANCHOR_MARKERS or safe_result_identifier(anchor) == UNSAFE_RESULT_IDENTIFIER)
        for anchor in anchors
    )


def block_contains_memory(block: str, memory_id: str, record: dict | None) -> bool:
    memory_ids = block_memory_ids(block)
    if memory_ids:
        return memory_id in memory_ids
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


def memory_ndcg_at_5(memory_rank: int | None) -> float:
    if memory_rank is None or memory_rank > 5:
        return 0.0
    return 1 / math.log2(memory_rank + 1)


def memory_precision_at_5(
    blocks: list[str],
    expected_memory_id: str,
    expected_summary_path: str,
    record: dict | None,
) -> MemoryPrecisionAt5:
    memory_blocks = [block for block in blocks if is_memory_block(block)][:5]
    if not memory_blocks:
        return MemoryPrecisionAt5(score=0.0, result_count=0, relevant_count=0)
    relevant = sum(
        int(block_has_drill_path(block, expected_summary_path) and block_contains_memory(block, expected_memory_id, record))
        for block in memory_blocks
    )
    return MemoryPrecisionAt5(
        score=relevant / len(memory_blocks),
        result_count=len(memory_blocks),
        relevant_count=relevant,
    )


def memory_explainability_hit(
    blocks: list[str],
    expected_memory_id: str,
    expected_summary_path: str,
    record: dict | None,
) -> bool:
    for block in blocks:
        if not is_memory_block(block) or not block_has_drill_path(block, expected_summary_path):
            continue
        if block_contains_memory(block, expected_memory_id, record):
            return block_has_explainable_memory_reason(block)
    return False


def layer_calibration_hit(
    blocks: list[str],
    expected_memory_id: str,
    expected_summary_path: str,
    record: dict | None,
    expected_layer: str,
) -> bool:
    if not expected_layer:
        return False
    for block in blocks:
        if not is_memory_block(block) or not block_has_drill_path(block, expected_summary_path):
            continue
        if block_contains_memory(block, expected_memory_id, record):
            return block_memory_layer(block) == expected_layer
    return False


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
    result_paths = set(block_result_paths(blocks))
    return all(required_path in result_paths for required_path in required_paths)


def safe_repo_file(repo: Path, path_text: str) -> Path | None:
    if not path_text.strip():
        return None
    candidate = Path(path_text)
    if candidate.is_absolute():
        return None
    try:
        repo_resolved = repo.resolve()
        resolved = (repo / candidate).resolve(strict=False)
        resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def read_repo_texts(repo: Path, paths: list[str]) -> list[str]:
    texts = []
    for path_text in paths:
        path = safe_repo_file(repo, path_text)
        if path is None:
            continue
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    return texts


def evidence_text_reachability_hit(repo: Path, evidence_paths: list[str], reference_evidence: list[str]) -> bool:
    if not evidence_paths or not reference_evidence:
        return False
    evidence_texts = read_repo_texts(repo, evidence_paths)
    if not evidence_texts:
        return False
    return all(any(snippet in text for text in evidence_texts) for snippet in reference_evidence)


def answer_reachability_hit(blocks: list[str], reference_answers: list[str]) -> bool:
    if not reference_answers:
        return False
    return all(any(answer in block for block in blocks) for answer in reference_answers)


def normalized_answer_text(text: str) -> str:
    return compact_whitespace(re.sub(r"[^\w]+", " ", text.lower()))


def answer_tokens(text: str) -> list[str]:
    return [token for token in normalized_answer_text(text).split() if token]


def answer_token_f1_score(output: str, reference_answer: str) -> float:
    reference_tokens = answer_tokens(reference_answer)
    output_tokens = answer_tokens(output)
    if not reference_tokens:
        return 0.0
    window_size = len(reference_tokens)
    if not output_tokens:
        return 0.0
    reference_counts = Counter(reference_tokens)
    best = 0.0
    for start in range(0, max(1, len(output_tokens) - window_size + 1)):
        window = output_tokens[start : start + window_size]
        overlap = sum((Counter(window) & reference_counts).values())
        if not overlap:
            continue
        precision = overlap / max(1, len(window))
        recall = overlap / len(reference_tokens)
        best = max(best, 2 * precision * recall / (precision + recall))
    return best


def answer_normalized_reachability_hit(output: str, reference_answers: list[str]) -> bool:
    if not reference_answers:
        return False
    normalized_output = normalized_answer_text(output)
    return all(normalized_answer_text(answer) in normalized_output for answer in reference_answers)


def answer_token_f1(output: str, reference_answers: list[str]) -> float:
    if not reference_answers:
        return 0.0
    return sum(answer_token_f1_score(output, answer) for answer in reference_answers) / len(reference_answers)


def privacy_boundary_pass(outputs: list[str], forbidden_patterns: list[str]) -> bool:
    if not forbidden_patterns:
        return True
    combined = "\n".join(outputs)
    return not any(re.search(pattern, combined) for pattern in forbidden_patterns)


def failed_checks(result: dict) -> list[str]:
    checks: list[str] = []
    memory_rank = result["memory_rank"]
    if result["positive_case"]:
        if memory_rank != 1:
            checks.append("memory_recall_at_1")
        if memory_rank is None or memory_rank > 5:
            checks.append("memory_recall_at_5")
        if memory_rank is not None and not result["memory_explainability_hit"]:
            checks.append("memory_explainability")
        if result["layer_expected"] and not result["layer_calibration_hit"]:
            checks.append("layer_calibration")
        if result["scope_filter_expected"] and not result["scope_filter_hit"]:
            checks.append("scope_filter_recall")
        if result["wrong_scope_expected"] and not result["wrong_scope_suppression_hit"]:
            checks.append("wrong_scope_suppression")
        if not result["session_drilldown_hit"]:
            checks.append("session_drilldown_at_5")
        if result["source_expected"] and not result["source_reachability_hit"]:
            checks.append("source_reachability")
        if result["evidence_expected"] and not result["evidence_reachability_hit"]:
            checks.append("evidence_reachability")
        if result["evidence_text_expected"] and not result["evidence_text_reachability_hit"]:
            checks.append("evidence_text_reachability")
        if result["answer_expected"]:
            if not result["answer_reachability_hit"]:
                checks.append("answer_reachability")
            if not result["answer_normalized_reachability_hit"]:
                checks.append("answer_normalized_reachability")
            if result["answer_token_f1"] < 1.0:
                checks.append("answer_token_f1")
    if result["expected_abstain"] and not result["abstention_hit"]:
        checks.append("abstention_accuracy")
    if result["negative_expected"] and not result["negative_memory_suppression_hit"]:
        checks.append("negative_memory_suppression")
    if result["stale_expected"] and not result["stale_memory_suppression_hit"]:
        checks.append("stale_memory_suppression")
    if result["update_expected"] and not result["update_consistency_hit"]:
        checks.append("update_consistency")
    if not result["privacy_boundary_pass"]:
        checks.append("privacy_boundary_pass_rate")
    return checks


def case_detail(case: Case, result: dict) -> dict:
    data = case.data
    query = safe_result_identifier(optional_case_text(data, "query"))
    memory_rank = result["memory_rank"]
    checks = failed_checks(result)
    return {
        "case_path": safe_diagnostic_path(case.path),
        "case_line": case.line_no,
        "case_id": safe_result_identifier(optional_case_text(data, "case_id")),
        "query": query,
        "category": safe_category_name(data),
        "source_benchmark": safe_result_identifier(optional_case_text(data, "source_benchmark")),
        "temporal_scope": safe_result_identifier(optional_case_text(data, "temporal_scope")),
        "expected_layer": safe_result_identifier(optional_case_text(data, "expected_layer")),
        "expected_memory_id": safe_result_identifier(optional_case_text(data, "expected_memory_id")),
        "expected_not_memory_ids": safe_result_identifiers(case_texts(data, "expected_not_memory_id")),
        "stale_memory_ids": safe_result_identifiers(case_texts(data, "stale_memory_id")),
        "expected_summary_path": safe_result_identifier(optional_case_text(data, "expected_summary_path")),
        "expected_source_anchor": safe_result_identifier(optional_case_text(data, "expected_source_anchor")),
        "required_evidence_paths": safe_result_identifiers(case_texts(data, "required_evidence_paths")),
        "reference_evidence_count": len(case_texts(data, "reference_evidence")),
        "forbidden_output_patterns_count": len(case_texts(data, "forbidden_output_patterns")),
        "positive_case": result["positive_case"],
        "expected_abstain": result["expected_abstain"],
        "memory_rank": memory_rank,
        "memory_recall_at_1": bool(memory_rank == 1),
        "memory_recall_at_5": bool(memory_rank is not None and memory_rank <= 5),
        "memory_ndcg_at_5": round(result["memory_ndcg_at_5"], 6),
        "memory_precision_at_5": round(result["memory_precision_at_5"], 6),
        "memory_explainability_hit": result["memory_explainability_hit"],
        "layer_calibration_hit": result["layer_calibration_hit"],
        "scope_filter_hit": result["scope_filter_hit"],
        "wrong_scope_suppression_hit": result["wrong_scope_suppression_hit"],
        "memory_result_count_at_5": result["memory_result_count_at_5"],
        "memory_relevant_count_at_5": result["memory_relevant_count_at_5"],
        "session_drilldown_hit": result["session_drilldown_hit"],
        "source_reachability_hit": result["source_reachability_hit"],
        "evidence_reachability_hit": result["evidence_reachability_hit"],
        "evidence_text_reachability_hit": result["evidence_text_reachability_hit"],
        "answer_expected": result["answer_expected"],
        "answer_reachability_hit": result["answer_reachability_hit"],
        "answer_normalized_reachability_hit": result["answer_normalized_reachability_hit"],
        "answer_token_f1": round(result["answer_token_f1"], 6),
        "abstention_hit": result["abstention_hit"],
        "negative_memory_suppression_hit": result["negative_memory_suppression_hit"],
        "stale_memory_suppression_hit": result["stale_memory_suppression_hit"],
        "update_consistency_hit": result["update_consistency_hit"],
        "privacy_boundary_pass": result["privacy_boundary_pass"],
        "memory_result_ids": result["memory_result_ids"],
        "memory_results_at_5": result["memory_results_at_5"],
        "session_result_paths": result["session_result_paths"],
        "source_result_ids": result["source_result_ids"],
        "source_result_anchors": result["source_result_anchors"],
        "source_precision_at_5": round(result["source_precision_at_5"], 6),
        "source_result_count_at_5": result["source_result_count_at_5"],
        "source_relevant_count_at_5": result["source_relevant_count_at_5"],
        "unsafe_source_anchor_count_at_5": result["unsafe_source_anchor_count_at_5"],
        "unsafe_source_anchor_rate_at_5": round(result["unsafe_source_anchor_rate_at_5"], 6),
        "case_pass": not checks,
        "failed_checks": checks,
        "latency_ms": round(result["latency_ms"], 3),
    }


def score_case(
    repo: Path,
    case: Case,
    memory_records: dict[str, dict],
    search_script: Path,
    search_timeout_s: float,
) -> dict:
    data = case.data
    query = required_case_text(data, "query", case.path, case.line_no)
    expected_layer = optional_case_text(data, "expected_layer")
    expected_abstain = data.get("expected_abstain") is True
    is_positive = positive_case(data)

    started = time.perf_counter()
    memory_output = run_search(search_script, repo, query, "memory", search_timeout_s)
    session_output = run_search(search_script, repo, query, "session", search_timeout_s)
    source_output = run_search(search_script, repo, query, "source", search_timeout_s)
    scope_output = ""
    wrong_scope_outputs: list[str] = []
    abstain_scope_outputs: list[str] = []
    if expected_abstain:
        for abstain_scope in MEMORY_LAYERS:
            abstain_scope_outputs.append(
                run_search(search_script, repo, query, "memory", search_timeout_s, abstain_scope)
            )
    elif is_positive and expected_layer:
        scope_output = run_search(search_script, repo, query, "memory", search_timeout_s, expected_layer)
        for wrong_scope in MEMORY_LAYERS:
            if wrong_scope != expected_layer:
                wrong_scope_outputs.append(run_search(search_script, repo, query, "memory", search_timeout_s, wrong_scope))
    latency_ms = (time.perf_counter() - started) * 1000

    memory_blocks = parse_hit_blocks(memory_output)
    session_blocks = parse_hit_blocks(session_output)
    source_blocks = parse_hit_blocks(source_output)
    scope_blocks = parse_hit_blocks(scope_output) if scope_output else []
    wrong_scope_blocks = [block for output in wrong_scope_outputs for block in parse_hit_blocks(output)]
    abstain_scope_blocks = [block for output in abstain_scope_outputs for block in parse_hit_blocks(output)]
    suppression_blocks = [
        *memory_blocks,
        *session_blocks,
        *source_blocks,
        *scope_blocks,
        *wrong_scope_blocks,
        *abstain_scope_blocks,
    ]
    all_search_outputs = [memory_output, session_output, source_output, scope_output, *wrong_scope_outputs, *abstain_scope_outputs]
    combined_output = "\n".join([memory_output, session_output, source_output])
    expected_memory_id = optional_case_text(data, "expected_memory_id")
    expected_summary_path = optional_case_text(data, "expected_summary_path")
    expected_source_anchor = optional_case_text(data, "expected_source_anchor")
    required_evidence_paths = case_texts(data, "required_evidence_paths")
    reference_evidence = case_texts(data, "reference_evidence")
    reference_answers = case_texts(data, "reference_answer")
    negative_memory_ids = case_texts(data, "expected_not_memory_id")
    stale_memory_ids = case_texts(data, "stale_memory_id")
    forbidden_patterns = case_texts(data, "forbidden_output_patterns")

    expected_record = memory_records.get(expected_memory_id)
    rank = None
    session_hit = False
    source_hit = False
    evidence_hit = False
    evidence_text_hit = False
    answer_hit = False
    normalized_answer_hit = False
    answer_f1 = 0.0
    memory_ndcg = 0.0
    explainability_hit = False
    layer_hit = False
    scope_hit = False
    wrong_scope_hit = False
    memory_precision = MemoryPrecisionAt5(score=0.0, result_count=0, relevant_count=0)
    source_precision = MemoryPrecisionAt5(score=0.0, result_count=0, relevant_count=0)
    unsafe_source_anchor_count = unsafe_source_anchor_count_at_5(source_blocks)
    if is_positive:
        rank = memory_hit_rank(memory_blocks, expected_memory_id, expected_summary_path, expected_record)
        memory_ndcg = memory_ndcg_at_5(rank)
        memory_precision = memory_precision_at_5(memory_blocks, expected_memory_id, expected_summary_path, expected_record)
        if rank is not None:
            explainability_hit = memory_explainability_hit(
                memory_blocks,
                expected_memory_id,
                expected_summary_path,
                expected_record,
            )
            layer_hit = layer_calibration_hit(
                memory_blocks,
                expected_memory_id,
                expected_summary_path,
                expected_record,
                expected_layer,
            )
        if expected_layer:
            scope_rank = memory_hit_rank(scope_blocks, expected_memory_id, expected_summary_path, expected_record)
            scope_hit = bool(scope_rank is not None and scope_rank <= 5)
            wrong_scope_hit = not bool(
                memory_hit_rank(wrong_scope_blocks, expected_memory_id, expected_summary_path, expected_record)
            )
        session_hit = session_drilldown_hit(session_blocks, expected_summary_path)
        if expected_source_anchor:
            source_hit = source_reachability_hit(source_blocks, expected_summary_path, expected_source_anchor)
            source_precision = source_anchor_precision_at_5(source_blocks, expected_source_anchor)
        if required_evidence_paths:
            evidence_hit = evidence_reachability_hit(source_blocks + memory_blocks, required_evidence_paths)
        if required_evidence_paths and reference_evidence:
            evidence_text_hit = evidence_text_reachability_hit(repo, required_evidence_paths, reference_evidence)
        if reference_answers:
            answer_hit = answer_reachability_hit(memory_blocks + session_blocks + source_blocks, reference_answers)
            normalized_answer_hit = answer_normalized_reachability_hit(combined_output, reference_answers)
            answer_f1 = answer_token_f1(combined_output, reference_answers)

    no_result_hits = no_hits(memory_blocks, session_blocks, source_blocks, abstain_scope_blocks)
    negative_suppressed = not blocks_contain_memory_ids(suppression_blocks, negative_memory_ids, memory_records)
    stale_suppressed = not blocks_contain_memory_ids(suppression_blocks, stale_memory_ids, memory_records)
    update_expected = bool(is_positive and stale_memory_ids)

    return {
        "positive_case": is_positive,
        "expected_abstain": expected_abstain,
        "memory_rank": rank,
        "memory_ndcg_at_5": memory_ndcg,
        "memory_precision_at_5": memory_precision.score,
        "memory_explainability_hit": explainability_hit,
        "layer_expected": bool(is_positive and expected_layer),
        "layer_calibration_hit": layer_hit,
        "scope_filter_expected": bool(is_positive and expected_layer),
        "scope_filter_hit": scope_hit,
        "wrong_scope_expected": bool(is_positive and expected_layer),
        "wrong_scope_suppression_hit": wrong_scope_hit,
        "memory_result_count_at_5": memory_precision.result_count,
        "memory_relevant_count_at_5": memory_precision.relevant_count,
        "session_drilldown_hit": session_hit,
        "source_expected": bool(is_positive and expected_source_anchor),
        "source_reachability_hit": source_hit,
        "source_precision_at_5": source_precision.score,
        "source_result_count_at_5": source_precision.result_count,
        "source_relevant_count_at_5": source_precision.relevant_count,
        "unsafe_source_anchor_count_at_5": unsafe_source_anchor_count,
        "unsafe_source_anchor_rate_at_5": ratio(unsafe_source_anchor_count, source_precision.result_count),
        "evidence_expected": bool(is_positive and required_evidence_paths),
        "evidence_reachability_hit": evidence_hit,
        "evidence_text_expected": bool(is_positive and required_evidence_paths and reference_evidence),
        "evidence_text_reachability_hit": evidence_text_hit,
        "answer_expected": bool(is_positive and reference_answers),
        "answer_reachability_hit": answer_hit,
        "answer_normalized_reachability_hit": normalized_answer_hit,
        "answer_token_f1": answer_f1,
        "abstention_hit": bool(expected_abstain and no_result_hits),
        "negative_expected": bool(negative_memory_ids),
        "negative_memory_suppression_hit": negative_suppressed,
        "stale_expected": bool(stale_memory_ids),
        "stale_memory_suppression_hit": stale_suppressed,
        "update_expected": update_expected,
        "update_consistency_hit": bool(update_expected and rank is not None and stale_suppressed),
        "privacy_boundary_pass": privacy_boundary_pass(
            all_search_outputs,
            forbidden_patterns,
        ),
        "memory_result_ids": safe_result_identifiers(block_field_values(memory_blocks, "memory_id")),
        "memory_results_at_5": memory_result_diagnostics(memory_blocks),
        "session_result_paths": safe_result_identifiers(block_result_paths(session_blocks)),
        "source_result_ids": safe_result_identifiers(block_field_values(source_blocks, "memory_id")),
        "source_result_anchors": safe_result_identifiers(block_section_values(source_blocks, "source anchors")),
        "latency_ms": latency_ms,
    }


def score_cases(
    repo: Path,
    cases: list[Case],
    search_script: Path,
    search_timeout_s: float = DEFAULT_SEARCH_TIMEOUT_S,
) -> tuple[dict, list[dict]]:
    memory_records = load_memory_records(repo)
    totals = new_totals()
    category_totals: dict[str, Totals] = {}
    details: list[dict] = []

    for case in cases:
        result = score_case(repo, case, memory_records, search_script, search_timeout_s)
        add_result(totals, result)
        details.append(case_detail(case, result))
        category = safe_category_name(case.data)
        category_totals.setdefault(category, new_totals())
        add_result(category_totals[category], result)

    payload = finalize_totals(totals)
    payload["categories"] = {
        category: finalize_totals(category_total)
        for category, category_total in sorted(category_totals.items())
    }
    return payload, details


def write_details_jsonl(path: Path, details: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for detail in details:
                handle.write(json.dumps(detail, sort_keys=True) + "\n")
    except OSError as exc:
        display_path = safe_diagnostic_path(path)
        display_error = safe_diagnostic_text(exc)
        raise SystemExit(f"unable to write --details-jsonl {display_path}: {display_error}") from exc


def threshold_metric_value(payload: dict, metric: str, option: str) -> float:
    display_metric = safe_result_identifier(metric)
    value: object = payload
    for part in metric.split("."):
        if not part or not isinstance(value, dict) or part not in value:
            raise SystemExit(f"{option} metric is not numeric in benchmark output: {display_metric}")
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"{option} metric is not numeric in benchmark output: {display_metric}")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise SystemExit(f"{option} metric is not finite in benchmark output: {display_metric}")
    return numeric_value


def fail_under_metric_value(payload: dict, metric: str) -> float:
    return threshold_metric_value(payload, metric, "--fail-under")


def fail_over_metric_value(payload: dict, metric: str) -> float:
    return threshold_metric_value(payload, metric, "--fail-over")


def parse_thresholds(values: list[str], payload: dict, option: str) -> list[tuple[str, float]]:
    thresholds: list[tuple[str, float]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{option} must use metric=threshold, got: {safe_result_identifier(value)}")
        metric, raw_threshold = value.split("=", 1)
        metric = metric.strip()
        raw_threshold = raw_threshold.strip()
        threshold_metric_value(payload, metric, option)
        display_metric = safe_result_identifier(metric)
        display_threshold = safe_result_identifier(raw_threshold)
        try:
            threshold = float(raw_threshold)
        except ValueError as exc:
            raise SystemExit(f"{option} threshold must be numeric for {display_metric}: {display_threshold}") from exc
        if not math.isfinite(threshold):
            raise SystemExit(f"{option} threshold must be finite for {display_metric}: {display_threshold}")
        thresholds.append((metric, threshold))
    return thresholds


def parse_fail_under(values: list[str], payload: dict) -> list[tuple[str, float]]:
    return parse_thresholds(values, payload, "--fail-under")


def parse_fail_over(values: list[str], payload: dict) -> list[tuple[str, float]]:
    return parse_thresholds(values, payload, "--fail-over")


def load_threshold_file(path: Path, payload: dict, option: str) -> list[tuple[str, float]]:
    display_path = safe_diagnostic_path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"unable to read {option} {display_path}: {safe_diagnostic_text(exc)}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON at {display_path}: {safe_diagnostic_text(exc)}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{option} must contain a JSON object: {display_path}")
    thresholds: list[tuple[str, float]] = []
    for metric, raw_threshold in data.items():
        if not isinstance(metric, str) or not metric.strip():
            raise SystemExit(f"{option} metric keys must be non-empty strings: {display_path}")
        metric = metric.strip()
        threshold_metric_value(payload, metric, option)
        if isinstance(raw_threshold, bool) or not isinstance(raw_threshold, (int, float)):
            raise SystemExit(f"{option} threshold must be numeric for {metric}")
        threshold = float(raw_threshold)
        if not math.isfinite(threshold):
            raise SystemExit(f"{option} threshold must be finite for {metric}")
        thresholds.append((metric, threshold))
    return thresholds


def load_fail_under_file(path: Path, payload: dict) -> list[tuple[str, float]]:
    return load_threshold_file(path, payload, "--fail-under-file")


def load_fail_over_file(path: Path, payload: dict) -> list[tuple[str, float]]:
    return load_threshold_file(path, payload, "--fail-over-file")


def merge_thresholds(*groups: list[tuple[str, float]]) -> list[tuple[str, float]]:
    merged: dict[str, float] = {}
    for group in groups:
        for metric, threshold in group:
            merged[metric] = threshold
    return list(merged.items())


def threshold_failure_details(payload: dict, thresholds: list[tuple[str, float]]) -> list[dict]:
    failures: list[dict] = []
    for metric, threshold in thresholds:
        value = fail_under_metric_value(payload, metric)
        if value < threshold:
            failures.append({"comparison": "below", "metric": metric, "value": value, "threshold": threshold})
    return failures


def threshold_over_failure_details(payload: dict, thresholds: list[tuple[str, float]]) -> list[dict]:
    failures: list[dict] = []
    for metric, threshold in thresholds:
        value = fail_over_metric_value(payload, metric)
        if value > threshold:
            failures.append({"comparison": "above", "metric": metric, "value": value, "threshold": threshold})
    return failures


def failed_case_summaries(details: list[dict]) -> list[dict]:
    summaries = []
    for detail in details:
        failed = detail.get("failed_checks") or []
        if not failed:
            continue
        summaries.append(
            {
                "case_id": detail.get("case_id", ""),
                "case_line": detail.get("case_line"),
                "category": detail.get("category", ""),
                "failed_checks": failed,
                "memory_ndcg_at_5": detail.get("memory_ndcg_at_5"),
                "memory_precision_at_5": detail.get("memory_precision_at_5"),
                "memory_explainability_hit": detail.get("memory_explainability_hit"),
                "layer_calibration_hit": detail.get("layer_calibration_hit"),
                "scope_filter_hit": detail.get("scope_filter_hit"),
                "wrong_scope_suppression_hit": detail.get("wrong_scope_suppression_hit"),
                "memory_rank": detail.get("memory_rank"),
                "memory_recall_at_1": detail.get("memory_recall_at_1"),
                "memory_recall_at_5": detail.get("memory_recall_at_5"),
                "memory_relevant_count_at_5": detail.get("memory_relevant_count_at_5"),
                "memory_result_count_at_5": detail.get("memory_result_count_at_5"),
                "memory_result_ids": detail.get("memory_result_ids", []),
                "memory_results_at_5": detail.get("memory_results_at_5", []),
                "session_drilldown_hit": detail.get("session_drilldown_hit"),
                "session_result_paths": detail.get("session_result_paths", []),
                "evidence_reachability_hit": detail.get("evidence_reachability_hit"),
                "answer_expected": detail.get("answer_expected"),
                "evidence_text_reachability_hit": detail.get("evidence_text_reachability_hit"),
                "answer_reachability_hit": detail.get("answer_reachability_hit"),
                "answer_normalized_reachability_hit": detail.get("answer_normalized_reachability_hit"),
                "answer_token_f1": detail.get("answer_token_f1"),
                "source_benchmark": detail.get("source_benchmark", ""),
                "source_result_anchors": detail.get("source_result_anchors", []),
                "source_result_ids": detail.get("source_result_ids", []),
                "source_reachability_hit": detail.get("source_reachability_hit"),
                "source_precision_at_5": detail.get("source_precision_at_5"),
                "source_relevant_count_at_5": detail.get("source_relevant_count_at_5"),
                "source_result_count_at_5": detail.get("source_result_count_at_5"),
                "unsafe_source_anchor_count_at_5": detail.get("unsafe_source_anchor_count_at_5"),
                "unsafe_source_anchor_rate_at_5": detail.get("unsafe_source_anchor_rate_at_5"),
                "negative_memory_suppression_hit": detail.get("negative_memory_suppression_hit"),
                "stale_memory_suppression_hit": detail.get("stale_memory_suppression_hit"),
                "update_consistency_hit": detail.get("update_consistency_hit"),
                "privacy_boundary_pass": detail.get("privacy_boundary_pass"),
            }
        )
    return summaries


def write_failures_json(path: Path, failures: list[dict], payload: dict, details: list[dict]) -> None:
    output = {
        "cases": payload.get("cases"),
        "failed_case_count": payload.get("failed_case_count"),
        "case_pass_rate": payload.get("case_pass_rate"),
        "cases_path": payload.get("cases_path"),
        "cases_sha256": payload.get("cases_sha256"),
        "search_script_path": payload.get("search_script_path"),
        "search_script_sha256": payload.get("search_script_sha256"),
        "failure_count": len(failures),
        "failed_cases": failed_case_summaries(details),
        "failures": failures,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(output, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        display_path = safe_diagnostic_path(path)
        display_error = safe_diagnostic_text(exc)
        raise SystemExit(f"unable to write --failures-json {display_path}: {display_error}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the memory archive")
    parser.add_argument("--cases", required=True, help="Path to JSONL benchmark cases")
    parser.add_argument("--search-script", default=DEFAULT_SEARCH_SCRIPT, help="Path to search_memory.py")
    parser.add_argument(
        "--search-timeout-s",
        type=float,
        default=DEFAULT_SEARCH_TIMEOUT_S,
        help="Per-depth search subprocess timeout in seconds",
    )
    parser.add_argument("--details-jsonl", help="Write one JSON object per scored benchmark case")
    parser.add_argument(
        "--fail-under",
        action="append",
        default=[],
        metavar="METRIC=THRESHOLD",
        help="Exit non-zero when a numeric metric or dotted metric path is below a threshold",
    )
    parser.add_argument(
        "--fail-under-file",
        action="append",
        default=[],
        help="JSON object of metric or dotted metric path thresholds",
    )
    parser.add_argument(
        "--fail-over",
        action="append",
        default=[],
        metavar="METRIC=THRESHOLD",
        help="Exit non-zero when a numeric metric or dotted metric path is above a threshold",
    )
    parser.add_argument(
        "--fail-over-file",
        action="append",
        default=[],
        help="JSON object of metric or dotted metric path maximum thresholds",
    )
    parser.add_argument("--failures-json", help="Write structured threshold failures JSON")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    cases_path = Path(args.cases).expanduser().resolve()
    if not math.isfinite(args.search_timeout_s):
        raise SystemExit("--search-timeout-s must be finite")
    if args.search_timeout_s <= 0:
        raise SystemExit("--search-timeout-s must be greater than 0")
    cases = load_cases(cases_path)
    search_script = Path(args.search_script).expanduser().resolve()

    validate_memory_repo(repo)
    payload, details = score_cases(repo, cases, search_script, args.search_timeout_s)
    payload["cases_path"] = safe_diagnostic_path(cases_path)
    payload["cases_sha256"] = file_sha256(cases_path)
    payload["search_script_path"] = safe_diagnostic_path(search_script)
    payload["search_script_sha256"] = file_sha256(search_script)
    print(json.dumps(payload, sort_keys=True), flush=True)
    if args.details_jsonl:
        write_details_jsonl(Path(args.details_jsonl).expanduser().resolve(), details)
    file_thresholds: list[tuple[str, float]] = []
    for threshold_file in args.fail_under_file:
        file_thresholds.extend(load_fail_under_file(Path(threshold_file).expanduser().resolve(), payload))
    file_over_thresholds: list[tuple[str, float]] = []
    for threshold_file in args.fail_over_file:
        file_over_thresholds.extend(load_fail_over_file(Path(threshold_file).expanduser().resolve(), payload))
    thresholds = merge_thresholds(file_thresholds, parse_fail_under(args.fail_under, payload))
    over_thresholds = merge_thresholds(file_over_thresholds, parse_fail_over(args.fail_over, payload))
    failure_details = threshold_failure_details(payload, thresholds) + threshold_over_failure_details(payload, over_thresholds)
    if args.failures_json:
        write_failures_json(Path(args.failures_json).expanduser().resolve(), failure_details, payload, details)
    failures = []
    for failure in failure_details:
        comparison = failure.get("comparison")
        direction = "above" if comparison == "above" else "below"
        failures.append(f"{failure['metric']}={failure['value']} {direction} threshold {failure['threshold']}")
    if failures:
        print("benchmark threshold failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
