#!/usr/bin/env python3
"""Audit generated-answer case-set scoreability without rendering private text."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SAFE_AGGREGATE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
SECRET_LIKE_AGGREGATE_KEY = re.compile(
    r"(?i)(?:"
    r"\b(?:api[_-]?key|authorization|bearer|cookie|credential|password|"
    r"private[_ -]?key|secret|session[_-]?id|token)\b|"
    r"\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)


def iter_jsonl(path: Path) -> Iterable[tuple[int, object]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to read JSONL {path.name}: {exc}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {path.name}:{line_no}: {exc}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_text(row: dict[str, Any], key: str, path: Path, line_no: int) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{path.name}:{line_no}: field must be non-empty text: {key}")
    return value.strip()


def optional_text(row: dict[str, Any], key: str, path: Path, line_no: int) -> str:
    value = row.get(key)
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise SystemExit(f"{path.name}:{line_no}: field must be text: {key}")
    return value.strip()


def text_list(row: dict[str, Any], key: str, path: Path, line_no: int) -> list[str]:
    value = row.get(key)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        texts = []
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise SystemExit(f"{path.name}:{line_no}: {key}[{index}] must be non-empty text")
            texts.append(item.strip())
        return texts
    raise SystemExit(f"{path.name}:{line_no}: field must be text or list of text: {key}")


def compile_forbidden_patterns(row: dict[str, Any], path: Path, line_no: int) -> list[re.Pattern[str]]:
    patterns = []
    for index, pattern in enumerate(text_list(row, "forbidden_output_patterns", path, line_no)):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise SystemExit(f"{path.name}:{line_no}: invalid forbidden_output_patterns[{index}]") from exc
    return patterns


def safe_aggregate_key(value: str) -> bool:
    return SAFE_AGGREGATE_KEY.fullmatch(value) is not None and SECRET_LIKE_AGGREGATE_KEY.search(value) is None


def validate_required_keys(values: list[str], option: str) -> tuple[str, ...]:
    keys: list[str] = []
    for value in values:
        if not safe_aggregate_key(value):
            raise SystemExit(f"{option} values must be safe aggregate identifiers")
        keys.append(value)
    return tuple(keys)


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{path.name}:{line_no}: expected object generated-answer case")
        case_id = required_text(value, "case_id", path, line_no)
        if case_id in seen:
            raise SystemExit(f"{path.name}:{line_no}: duplicate case_id")
        seen.add(case_id)
        required_text(value, "query", path, line_no)
        if "expected_abstain" in value and not isinstance(value["expected_abstain"], bool):
            raise SystemExit(f"{path.name}:{line_no}: expected_abstain must be boolean")
        optional_text(value, "category", path, line_no)
        optional_text(value, "source_benchmark", path, line_no)
        optional_text(value, "case_origin", path, line_no)
        optional_text(value, "origin", path, line_no)
        text_list(value, "reference_answer", path, line_no)
        compile_forbidden_patterns(value, path, line_no)
        cases.append(dict(value, _case_line_no=line_no))
    if not cases:
        raise SystemExit(f"no generated-answer cases found in {path.name}")
    return cases


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def record_aggregate_key(counter: Counter[str], value: str) -> bool:
    if not value:
        return True
    if not safe_aggregate_key(value):
        return False
    counter[value] += 1
    return True


def audit(cases_path: Path) -> dict[str, Any]:
    cases = load_cases(cases_path)
    source_benchmarks: Counter[str] = Counter()
    case_origins: Counter[str] = Counter()
    positive_cases = 0
    abstain_cases = 0
    reference_answer_cases = 0
    answer_scorable_cases = 0
    positive_without_reference_answer = 0
    forbidden_output_pattern_cases = 0
    forbidden_output_pattern_count = 0
    source_benchmark_cases = 0
    case_origin_cases = 0
    unsafe_aggregate_identifier_count = 0

    for case in cases:
        line_no = int(case["_case_line_no"])
        expected_abstain = case.get("expected_abstain") is True
        reference_answers = text_list(case, "reference_answer", cases_path, line_no)
        forbidden_patterns = text_list(case, "forbidden_output_patterns", cases_path, line_no)
        source_benchmark = optional_text(case, "source_benchmark", cases_path, line_no)
        case_origin = optional_text(case, "case_origin", cases_path, line_no) or optional_text(
            case, "origin", cases_path, line_no
        )

        if expected_abstain:
            abstain_cases += 1
        else:
            positive_cases += 1
        if reference_answers:
            reference_answer_cases += 1
        if expected_abstain or reference_answers:
            answer_scorable_cases += 1
        if not expected_abstain and not reference_answers:
            positive_without_reference_answer += 1
        if forbidden_patterns:
            forbidden_output_pattern_cases += 1
            forbidden_output_pattern_count += len(forbidden_patterns)
        if source_benchmark:
            source_benchmark_cases += 1
            if not record_aggregate_key(source_benchmarks, source_benchmark):
                unsafe_aggregate_identifier_count += 1
        if case_origin:
            case_origin_cases += 1
            if not record_aggregate_key(case_origins, case_origin):
                unsafe_aggregate_identifier_count += 1

    total_cases = len(cases)
    return {
        "report_kind": "generated_answer_case_audit",
        "report_version": 1,
        "claim_boundary": "case-set scoreability audit only; no answer generation or answer correctness claim",
        "cases": total_cases,
        "positive_cases": positive_cases,
        "abstain_cases": abstain_cases,
        "reference_answer_cases": reference_answer_cases,
        "answer_scorable_cases": answer_scorable_cases,
        "positive_without_reference_answer": positive_without_reference_answer,
        "answer_scorable_case_rate": ratio(answer_scorable_cases, total_cases),
        "source_benchmark_cases": source_benchmark_cases,
        "case_origin_cases": case_origin_cases,
        "forbidden_output_pattern_cases": forbidden_output_pattern_cases,
        "forbidden_output_pattern_count": forbidden_output_pattern_count,
        "unsafe_aggregate_identifier_count": unsafe_aggregate_identifier_count,
        "cases_sha256": file_sha256(cases_path),
        "source_benchmarks": dict(sorted(source_benchmarks.items())),
        "case_origins": dict(sorted(case_origins.items())),
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "reference_answers_rendered": False,
            "case_ids_rendered": False,
            "private_probe_cases_rendered": False,
            "source_paths_rendered": False,
        },
    }


def parse_threshold(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise SystemExit(f"threshold must use metric=value form: {raw}")
    key, value_text = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"threshold metric is empty: {raw}")
    try:
        value = float(value_text)
    except ValueError as exc:
        raise SystemExit(f"threshold value must be numeric for {key}") from exc
    if not math.isfinite(value):
        raise SystemExit(f"threshold value must be finite for {key}")
    return key, value


def numeric_metric(report: dict[str, Any], key: str) -> float | None:
    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def positive_count_for_key(value: object, key: str) -> int:
    if not isinstance(value, dict):
        return 0
    count = value.get(key)
    if isinstance(count, bool) or not isinstance(count, int):
        return 0
    return count if count > 0 else 0


def threshold_failures(
    report: dict[str, Any], fail_under: list[str], fail_over: list[str]
) -> list[dict[str, Any]]:
    failures = []
    for raw in fail_under:
        key, threshold = parse_threshold(raw)
        value = numeric_metric(report, key)
        if value is None or value < threshold:
            failures.append(
                {
                    "metric": key,
                    "comparison": "min",
                    "threshold": threshold,
                    "value": value,
                    "reason": "missing_or_below_threshold" if value is None else "below_threshold",
                }
            )
    for raw in fail_over:
        key, threshold = parse_threshold(raw)
        value = numeric_metric(report, key)
        if value is None or value > threshold:
            failures.append(
                {
                    "metric": key,
                    "comparison": "max",
                    "threshold": threshold,
                    "value": value,
                    "reason": "missing_or_above_threshold" if value is None else "above_threshold",
                }
            )
    return failures


def required_count_failures(
    report: dict[str, Any],
    required_source_benchmarks: tuple[str, ...],
    required_case_origins: tuple[str, ...],
) -> list[dict[str, Any]]:
    failures = []
    for source in required_source_benchmarks:
        if positive_count_for_key(report.get("source_benchmarks"), source) <= 0:
            failures.append(
                {
                    "metric": f"source_benchmarks.{source}",
                    "comparison": "positive_count",
                    "threshold": 1,
                    "value": 0,
                    "reason": "missing_required_source_benchmark",
                }
            )
    for origin in required_case_origins:
        if positive_count_for_key(report.get("case_origins"), origin) <= 0:
            failures.append(
                {
                    "metric": f"case_origins.{origin}",
                    "comparison": "positive_count",
                    "threshold": 1,
                    "value": 0,
                    "reason": "missing_required_case_origin",
                }
            )
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Generated-answer benchmark cases JSONL")
    parser.add_argument("--require-source-benchmark", action="append", default=[], help="Require source_benchmarks key")
    parser.add_argument("--require-case-origin", action="append", default=[], help="Require case_origins key")
    parser.add_argument("--fail-under", action="append", default=[], help="Require metric >= value")
    parser.add_argument("--fail-over", action="append", default=[], help="Require metric <= value")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    required_source_benchmarks = validate_required_keys(args.require_source_benchmark, "--require-source-benchmark")
    required_case_origins = validate_required_keys(args.require_case_origin, "--require-case-origin")
    report = audit(Path(args.cases).expanduser().resolve())
    print(json.dumps(report, sort_keys=True))
    failures = threshold_failures(report, args.fail_under, args.fail_over)
    failures.extend(required_count_failures(report, required_source_benchmarks, required_case_origins))
    if failures:
        failed_metrics = ", ".join(failure["metric"] for failure in failures)
        print(f"generated answer case audit failed: {failed_metrics}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
