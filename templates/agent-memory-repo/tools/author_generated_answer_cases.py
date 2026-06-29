#!/usr/bin/env python3
"""Author private generated-answer case sets from layered memory nodes.

This helper writes private case JSONL inside the deployment archive. Its stdout
is aggregate-only and must not render memory text, queries, reference answers,
memory IDs, source paths, or raw refs.
"""

from __future__ import annotations

import argparse
import hashlib
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


DEFAULT_OUTPUT_RELATIVE_PATH = Path("eval/generated_answer_private_dogfood_cases.jsonl")
DEFAULT_SOURCE_BENCHMARK = "MyPreciousPrivateDogfood"
DEFAULT_CASE_ORIGIN = "private_dogfood"
DEFAULT_CATEGORY = "private_dogfood_memory_answer"
DEFAULT_LIMIT = 20
MIN_QUERY_TERMS = 3
MAX_QUERY_TERMS = 8
MAX_REFERENCE_ANSWER_CHARS = 500
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


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
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
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {search_memory.safe_display_text(path.name)}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"{search_memory.safe_display_text(path.name)}:{line_no}: expected object row")
            yield value


def resolve_output_path(repo: Path, output_arg: str | None) -> Path:
    output = Path(output_arg).expanduser() if output_arg else DEFAULT_OUTPUT_RELATIVE_PATH
    if not output.is_absolute():
        output = repo / output
    try:
        repo_resolved = repo.resolve()
        output_resolved = output.resolve(strict=False)
        output_resolved.relative_to(repo_resolved)
    except ValueError as exc:
        raise SystemExit("Refusing to write generated-answer case file outside the memory repository") from exc
    return output_resolved


def output_relative_path(repo: Path, output: Path) -> str:
    try:
        return output.relative_to(repo.resolve()).as_posix()
    except ValueError:
        return "[outside-repo]"


def safe_aggregate_key(value: str) -> bool:
    return SAFE_AGGREGATE_KEY.fullmatch(value) is not None and SECRET_LIKE_AGGREGATE_KEY.search(value) is None


def validate_aggregate_key(value: str, option: str) -> str:
    if not safe_aggregate_key(value):
        raise SystemExit(f"{option} must be a safe aggregate identifier")
    return value


def active_memory(record: dict[str, Any]) -> bool:
    return not any(record.get(field) for field in ("superseded_by", "contradicted_by", "deprecated_by"))


def record_text(record: dict[str, Any]) -> str:
    value = record.get("text")
    return search_memory.compact_whitespace(value) if isinstance(value, str) else ""


def record_memory_id(record: dict[str, Any]) -> str:
    value = record.get("memory_id")
    return value.strip() if isinstance(value, str) and value.strip() else ""


def query_terms(text: str) -> list[str]:
    tokens = search_memory.coverage_query_tokens(
        search_memory.meaningful_query_tokens(search_memory.unique_query_tokens(text))
    )
    terms: list[str] = []
    for token in tokens:
        if token in terms:
            continue
        terms.append(token)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    return terms


def query_from_text(text: str) -> str:
    terms = query_terms(text)
    if len(terms) < MIN_QUERY_TERMS:
        return ""
    return " ".join(terms)


def case_id_for(memory_id: str, text: str) -> str:
    digest = hashlib.sha256(f"{memory_id}\0{text}".encode("utf-8")).hexdigest()[:16]
    return f"private_dogfood_{digest}"


def case_row(
    record: dict[str, Any],
    *,
    source_benchmark: str,
    case_origin: str,
    category: str,
) -> dict[str, Any] | None:
    memory_id = record_memory_id(record)
    text = record_text(record)
    if not memory_id or not text:
        return None
    if len(text) > MAX_REFERENCE_ANSWER_CHARS:
        return None
    if search_memory.has_sensitive_display_text(text):
        return None
    query = query_from_text(text)
    if not query:
        return None
    return {
        "case_id": case_id_for(memory_id, text),
        "query": query,
        "category": category,
        "source_benchmark": source_benchmark,
        "case_origin": case_origin,
        "reference_answer": text,
        "expected_memory_id": memory_id,
    }


def load_memory_rows(repo: Path) -> list[dict[str, Any]]:
    index = repo / "index" / "memories.jsonl"
    if not index.exists():
        raise SystemExit("memory repository does not contain index/memories.jsonl")
    return list(iter_jsonl(index))


def build_cases(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    source_benchmark: str,
    case_origin: str,
    category: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cases: list[dict[str, Any]] = []
    skip_counts: Counter[str] = Counter()
    seen_case_ids: set[str] = set()
    for record in rows:
        if len(cases) >= limit:
            break
        if not active_memory(record):
            skip_counts["inactive_memory"] += 1
            continue
        memory_id = record_memory_id(record)
        text = record_text(record)
        if not memory_id or not text:
            skip_counts["missing_required_field"] += 1
            continue
        if len(text) > MAX_REFERENCE_ANSWER_CHARS:
            skip_counts["reference_answer_too_long"] += 1
            continue
        if search_memory.has_sensitive_display_text(text):
            skip_counts["sensitive_text"] += 1
            continue
        row = case_row(
            record,
            source_benchmark=source_benchmark,
            case_origin=case_origin,
            category=category,
        )
        if row is None:
            skip_counts["insufficient_query_terms"] += 1
            continue
        case_id = str(row["case_id"])
        if case_id in seen_case_ids:
            skip_counts["duplicate_case_id"] += 1
            continue
        seen_case_ids.add(case_id)
        cases.append(row)
    return cases, dict(sorted(skip_counts.items()))


def write_jsonl(path: Path, rows: list[dict[str, Any]], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise SystemExit("output already exists; use --overwrite to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def author_report(
    repo: Path,
    output: Path,
    *,
    limit: int,
    source_benchmark: str,
    case_origin: str,
    category: str,
    write_enabled: bool,
    overwrite: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = load_memory_rows(repo)
    cases, skip_counts = build_cases(
        rows,
        limit=limit,
        source_benchmark=source_benchmark,
        case_origin=case_origin,
        category=category,
    )
    source_benchmarks = Counter(str(row["source_benchmark"]) for row in cases)
    case_origins = Counter(str(row["case_origin"]) for row in cases)
    report = {
        "report_kind": "generated_answer_case_authoring",
        "report_version": 1,
        "claim_boundary": "private case-set authoring only; no answer generation or answer correctness claim",
        "write_enabled": write_enabled,
        "overwrite_enabled": overwrite,
        "output_relative_path": output_relative_path(repo, output),
        "candidate_memory_count": len(rows),
        "selected_case_count": len(cases),
        "would_write_count": len(cases),
        "written_count": 0,
        "skip_counts": skip_counts,
        "source_benchmarks": dict(sorted(source_benchmarks.items())),
        "case_origins": dict(sorted(case_origins.items())),
        "privacy": {
            "aggregate_only": True,
            "memory_text_rendered": False,
            "queries_rendered": False,
            "reference_answers_rendered": False,
            "memory_ids_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }
    return report, cases


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the private memory repository")
    parser.add_argument("--output", help="Output JSONL path inside the memory repository")
    parser.add_argument("--dry-run", action="store_true", help="Preview generated case counts without writing")
    parser.add_argument("--write", action="store_true", help="Write the private generated-answer case JSONL")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing output file")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum cases to author")
    parser.add_argument("--source-benchmark", default=DEFAULT_SOURCE_BENCHMARK, help="Aggregate source benchmark key")
    parser.add_argument("--case-origin", default=DEFAULT_CASE_ORIGIN, help="Aggregate case origin key")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Category value for authored cases")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        raise SystemExit("--dry-run and --write are mutually exclusive")
    if not args.dry_run and not args.write:
        raise SystemExit("Choose --dry-run or --write")
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")
    repo = Path(args.repo).expanduser().resolve()
    output = resolve_output_path(repo, args.output)
    source_benchmark = validate_aggregate_key(args.source_benchmark, "--source-benchmark")
    case_origin = validate_aggregate_key(args.case_origin, "--case-origin")
    category = validate_aggregate_key(args.category, "--category")
    report, cases = author_report(
        repo,
        output,
        limit=args.limit,
        source_benchmark=source_benchmark,
        case_origin=case_origin,
        category=category,
        write_enabled=bool(args.write),
        overwrite=bool(args.overwrite),
    )
    if args.write:
        write_jsonl(output, cases, overwrite=bool(args.overwrite))
        report["written_count"] = len(cases)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
