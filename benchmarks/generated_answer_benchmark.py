#!/usr/bin/env python3
"""Score generated answers against benchmark cases without rendering answer text."""

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


ABSTENTION_OUTPUT_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"did\s+not\s+mention|"
    r"not\s+mention(?:ed)?|"
    r"never\s+mention(?:ed)?|"
    r"not\s+discuss(?:ed)?|"
    r"not\s+provided|"
    r"not\s+specified|"
    r"not\s+enough\s+information|"
    r"cannot\s+answer|"
    r"can't\s+answer|"
    r"no\s+answer|"
    r"unknown|"
    r"unanswerable"
    r")\b"
)
SENSITIVE_OUTPUT_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b(?:api[_-]?key|authorization|bearer|cookie|credential|password|"
    r"private[_ -]?key|secret|session[_-]?id|token)\b\s*[:=]|"
    r"\bbearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)
TOKEN_F1_PASS_THRESHOLD = 0.8


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


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{path.name}:{line_no}: expected object benchmark case")
        case_id = required_text(value, "case_id", path, line_no)
        if case_id in seen:
            raise SystemExit(f"{path.name}:{line_no}: duplicate case_id")
        seen.add(case_id)
        required_text(value, "query", path, line_no)
        if "expected_abstain" in value and not isinstance(value["expected_abstain"], bool):
            raise SystemExit(f"{path.name}:{line_no}: expected_abstain must be boolean")
        optional_text(value, "category", path, line_no)
        optional_text(value, "source_benchmark", path, line_no)
        text_list(value, "reference_answer", path, line_no)
        compile_forbidden_patterns(value, path, line_no)
        cases.append(dict(value, _case_line_no=line_no))
    if not cases:
        raise SystemExit(f"no generated-answer benchmark cases found in {path.name}")
    return cases


def load_answers(path: Path) -> tuple[dict[str, str], Counter[str], list[str]]:
    answers: dict[str, str] = {}
    duplicates: Counter[str] = Counter()
    answer_case_ids: list[str] = []
    for line_no, value in iter_jsonl(path):
        if not isinstance(value, dict):
            raise SystemExit(f"{path.name}:{line_no}: expected object generated-answer record")
        case_id = required_text(value, "case_id", path, line_no)
        generated_answer = required_text(value, "generated_answer", path, line_no)
        answer_case_ids.append(case_id)
        if case_id in answers:
            duplicates[case_id] += 1
            continue
        answers[case_id] = generated_answer
    return answers, duplicates, answer_case_ids


def compile_forbidden_patterns(row: dict[str, Any], path: Path, line_no: int) -> list[re.Pattern[str]]:
    patterns = []
    for index, pattern in enumerate(text_list(row, "forbidden_output_patterns", path, line_no)):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise SystemExit(f"{path.name}:{line_no}: invalid forbidden_output_patterns[{index}]") from exc
    return patterns


def normalized_answer_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def answer_tokens(text: str) -> list[str]:
    return [token for token in normalized_answer_text(text).split() if token]


def answer_token_f1_score(output: str, reference_answer: str) -> float:
    reference_tokens = answer_tokens(reference_answer)
    output_tokens = answer_tokens(output)
    if not reference_tokens or not output_tokens:
        return 0.0
    reference_counts = Counter(reference_tokens)
    window_size = len(reference_tokens)
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


def answer_token_f1(output: str, reference_answers: list[str]) -> float:
    if not reference_answers:
        return 0.0
    return sum(answer_token_f1_score(output, answer) for answer in reference_answers) / len(reference_answers)


def exact_answer_hit(output: str, reference_answers: list[str]) -> bool:
    return bool(reference_answers) and all(answer in output for answer in reference_answers)


def normalized_answer_hit(output: str, reference_answers: list[str]) -> bool:
    if not reference_answers:
        return False
    normalized_output = normalized_answer_text(output)
    return all(normalized_answer_text(answer) in normalized_output for answer in reference_answers)


def privacy_leak(output: str, forbidden_patterns: list[re.Pattern[str]]) -> bool:
    return SENSITIVE_OUTPUT_PATTERN.search(output) is not None or any(pattern.search(output) for pattern in forbidden_patterns)


def hash_case_id(case_id: str) -> str:
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:12]


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def evaluate_case(
    *,
    ordinal: int,
    case: dict[str, Any],
    answer: str | None,
    duplicate_answer: bool,
    cases_path: Path,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    line_no = int(case["_case_line_no"])
    expected_abstain = case.get("expected_abstain") is True
    reference_answers = text_list(case, "reference_answer", cases_path, line_no)
    forbidden_patterns = compile_forbidden_patterns(case, cases_path, line_no)
    missing_answer = answer is None
    failed_checks: list[str] = []
    exact_hit = False
    normalized_hit = False
    token_f1 = 0.0
    abstention_hit = False
    leak = False

    if missing_answer:
        failed_checks.append("missing_generated_answer")
    else:
        leak = privacy_leak(answer, forbidden_patterns)
        if leak:
            failed_checks.append("privacy_boundary")
        if expected_abstain:
            abstention_hit = ABSTENTION_OUTPUT_PATTERN.search(answer) is not None
            if not abstention_hit:
                failed_checks.append("abstention_accuracy")
        else:
            if not reference_answers:
                failed_checks.append("missing_reference_answer")
            exact_hit = exact_answer_hit(answer, reference_answers)
            normalized_hit = normalized_answer_hit(answer, reference_answers)
            token_f1 = answer_token_f1(answer, reference_answers)
            if not (exact_hit or normalized_hit or token_f1 >= TOKEN_F1_PASS_THRESHOLD):
                failed_checks.append("answer_match")

    if duplicate_answer:
        failed_checks.append("duplicate_answer")

    case_pass = not failed_checks
    return {
        "case_ordinal": ordinal,
        "case_id_hash": hash_case_id(case_id),
        "category": optional_text(case, "category", cases_path, line_no),
        "source_benchmark": optional_text(case, "source_benchmark", cases_path, line_no),
        "expected_abstain": expected_abstain,
        "generated_answer_present": not missing_answer,
        "duplicate_answer": duplicate_answer,
        "answer_exact_match": exact_hit,
        "answer_normalized_match": normalized_hit,
        "answer_token_f1": round(token_f1, 6),
        "abstention_hit": abstention_hit,
        "privacy_boundary_pass": not leak,
        "case_pass": case_pass,
        "failed_checks": failed_checks,
    }


def evaluate(cases_path: Path, answers_path: Path, details_path: Path | None) -> dict[str, Any]:
    cases = load_cases(cases_path)
    answers, duplicate_case_counts, answer_case_ids = load_answers(answers_path)
    case_ids = {str(case["case_id"]) for case in cases}
    unknown_answer_count = sum(1 for case_id in answer_case_ids if case_id not in case_ids)
    details = []
    source_benchmarks: Counter[str] = Counter()
    case_origins: Counter[str] = Counter()

    for case in cases:
        source_benchmark = str(case.get("source_benchmark") or "")
        if source_benchmark:
            source_benchmarks[source_benchmark] += 1
        case_origin = str(case.get("case_origin") or case.get("origin") or "")
        if case_origin:
            case_origins[case_origin] += 1

    for ordinal, case in enumerate(cases, 1):
        case_id = str(case["case_id"])
        details.append(
            evaluate_case(
                ordinal=ordinal,
                case=case,
                answer=answers.get(case_id),
                duplicate_answer=duplicate_case_counts[case_id] > 0,
                cases_path=cases_path,
            )
        )

    total_cases = len(details)
    positive_details = [detail for detail in details if not detail["expected_abstain"]]
    abstain_details = [detail for detail in details if detail["expected_abstain"]]
    passed_cases = sum(1 for detail in details if detail["case_pass"])
    privacy_hits = sum(1 for detail in details if detail["privacy_boundary_pass"])
    missing_answer_count = sum(1 for detail in details if not detail["generated_answer_present"])
    duplicate_answer_count = sum(duplicate_case_counts.values())
    failed_case_count = total_cases - passed_cases
    exact_hits = sum(1 for detail in positive_details if detail["answer_exact_match"])
    normalized_hits = sum(1 for detail in positive_details if detail["answer_normalized_match"])
    token_f1_total = sum(float(detail["answer_token_f1"]) for detail in positive_details)
    abstention_hits = sum(1 for detail in abstain_details if detail["abstention_hit"])

    report: dict[str, Any] = {
        "report_kind": "generated_answer_benchmark",
        "report_version": 1,
        "claim_boundary": "offline generated-answer grading only; no model generation or semantic equivalence claim",
        "cases": total_cases,
        "answer_cases": len(answer_case_ids),
        "positive_cases": len(positive_details),
        "abstain_cases": len(abstain_details),
        "case_pass_rate": ratio(passed_cases, total_cases),
        "answer_exact_match_rate": ratio(exact_hits, len(positive_details)),
        "answer_normalized_match_rate": ratio(normalized_hits, len(positive_details)),
        "answer_token_f1": ratio(token_f1_total, len(positive_details)),
        "abstention_accuracy": ratio(abstention_hits, len(abstain_details)),
        "privacy_boundary_pass_rate": ratio(privacy_hits, total_cases),
        "privacy_leak_count": total_cases - privacy_hits,
        "failed_case_count": failed_case_count,
        "missing_answer_count": missing_answer_count,
        "duplicate_answer_count": duplicate_answer_count,
        "unknown_answer_count": unknown_answer_count,
        "cases_sha256": file_sha256(cases_path),
        "answers_sha256": file_sha256(answers_path),
        "source_benchmarks": dict(sorted(source_benchmarks.items())),
        "case_origins": dict(sorted(case_origins.items())),
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "generated_answers_rendered": False,
            "reference_answers_rendered": False,
            "private_probe_cases_rendered": False,
        },
    }
    if details_path is not None:
        details_path.write_text(
            "".join(json.dumps(detail, sort_keys=True) + "\n" for detail in details),
            encoding="utf-8",
        )
    return report


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Generated-answer benchmark cases JSONL")
    parser.add_argument("--answers", required=True, help="Generated answer records JSONL")
    parser.add_argument("--details-jsonl", help="Optional privacy-safe per-case details JSONL")
    parser.add_argument("--fail-under", action="append", default=[], help="Require metric >= value")
    parser.add_argument("--fail-over", action="append", default=[], help="Require metric <= value")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = evaluate(
        Path(args.cases).expanduser().resolve(),
        Path(args.answers).expanduser().resolve(),
        Path(args.details_jsonl).expanduser().resolve() if args.details_jsonl else None,
    )
    print(json.dumps(report, sort_keys=True))
    failures = threshold_failures(report, args.fail_under, args.fail_over)
    if failures:
        failed_metrics = ", ".join(failure["metric"] for failure in failures)
        print(f"generated answer benchmark failed: {failed_metrics}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
