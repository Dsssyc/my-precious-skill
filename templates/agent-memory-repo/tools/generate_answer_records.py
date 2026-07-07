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
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import search_memory  # noqa: E402


ABSTENTION_ANSWER = "There is not enough information in memory to answer."
ANSWERABILITY_POLICY = "context_package_answerability"
CONTEXT_PACKAGE_REPORT_KIND = "memory_recall_context_package"
HANDOFF_CONTRACT_VERSION = 1
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


def context_package_metadata(
    *,
    parse_success: bool,
    answerability_status: str = "unsupported",
    answerability_reason: str = "parse_failed",
) -> dict[str, Any]:
    return {
        "report_kind": CONTEXT_PACKAGE_REPORT_KIND,
        "parse_success": parse_success,
        "answerability_status": answerability_status,
        "answerability_reason": answerability_reason,
    }


def search_context_package(
    repo: Path,
    search_script: Path,
    query: str,
    limit: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    result = subprocess.run(
        [
            sys.executable,
            str(search_script),
            query,
            "--repo",
            str(repo),
            "--limit",
            str(limit),
            "--depth",
            "evidence",
            "--context-json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None, context_package_metadata(parse_success=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, context_package_metadata(parse_success=False)
    if not isinstance(payload, dict) or payload.get("report_kind") != CONTEXT_PACKAGE_REPORT_KIND:
        return None, context_package_metadata(parse_success=False)
    answerability = payload.get("answerability")
    if not isinstance(answerability, dict):
        return None, context_package_metadata(parse_success=False)
    status = answerability.get("status")
    reason = answerability.get("reason")
    if status not in {"supported", "unsupported"} or not isinstance(reason, str) or not reason:
        return None, context_package_metadata(parse_success=False)
    return payload, context_package_metadata(
        parse_success=True,
        answerability_status=status,
        answerability_reason=reason,
    )


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


def extract_answer_from_memory_id(repo: Path, memory_id: str, query: str = "") -> str:
    text = search_memory.compact_whitespace(memory_text_by_id(repo, memory_id))
    match = REFERENCE_ANSWER_PREFIX_PATTERN.search(text)
    answer = trim_reference_answer_tail(text[match.end() :], query) if match else text
    answer = search_memory.compact_whitespace(answer)
    if not answer or search_memory.has_sensitive_display_text(answer):
        return ABSTENTION_ANSWER
    return answer


def query_support_tokens(text: str) -> list[str]:
    return search_memory.coverage_query_tokens(
        search_memory.meaningful_query_tokens(search_memory.unique_query_tokens(text))
    )


def hit_supports_query(repo: Path, hit: search_memory.Hit, query: str) -> bool:
    full_text = search_memory.compact_whitespace(full_hit_text(repo, hit))
    query_text = search_memory.compact_whitespace(query)
    if not full_text or not query_text:
        return False
    if query_text.lower() in full_text.lower():
        return True
    required_tokens = query_support_tokens(query_text)
    if not required_tokens:
        return False
    full_text_tokens = set(query_support_tokens(full_text))
    return all(token in full_text_tokens for token in required_tokens)


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


def answer_support_refs(hit: search_memory.Hit) -> list[dict[str, Any]]:
    summary_paths = sorted(path for path in hit.drill_paths if Path(path).name == "summary.md")
    evidence_refs = sorted(hit.evidence_refs)
    if not hit.memory_id or not summary_paths or not evidence_refs:
        return []
    return [
        {
            "memory_id": hit.memory_id,
            "summary_paths": summary_paths,
            "evidence_refs": evidence_refs,
        }
    ]


def support_refs_cover_answer(support_refs: list[dict[str, Any]]) -> bool:
    for support_ref in support_refs:
        if not isinstance(support_ref, dict):
            continue
        memory_id = support_ref.get("memory_id")
        summary_paths = support_ref.get("summary_paths")
        evidence_refs = support_ref.get("evidence_refs")
        if (
            isinstance(memory_id, str)
            and memory_id.strip()
            and isinstance(summary_paths, list)
            and any(isinstance(path, str) and path.strip() for path in summary_paths)
            and isinstance(evidence_refs, list)
            and any(isinstance(ref, str) and ref.strip() for ref in evidence_refs)
        ):
            return True
    return False


def context_support_refs(context_hit: dict[str, Any]) -> list[dict[str, Any]]:
    memory_id = context_hit.get("memory_id")
    summary_paths = context_hit.get("summary_drill_paths")
    evidence_refs = context_hit.get("evidence_refs")
    if not isinstance(memory_id, str) or not memory_id.strip():
        return []
    if not isinstance(summary_paths, list) or not isinstance(evidence_refs, list):
        return []
    clean_summary_paths = [path for path in summary_paths if isinstance(path, str) and path.strip()]
    clean_evidence_refs = [ref for ref in evidence_refs if isinstance(ref, str) and ref.strip()]
    if not clean_summary_paths or not clean_evidence_refs:
        return []
    return [
        {
            "memory_id": memory_id,
            "summary_paths": sorted(clean_summary_paths),
            "evidence_refs": sorted(clean_evidence_refs),
        }
    ]


def context_hit_matched_tokens(context_hit: dict[str, Any]) -> set[str]:
    why = context_hit.get("why")
    if not isinstance(why, list):
        return set()
    for item in why:
        if not isinstance(item, str) or not item.startswith("matched:"):
            continue
        raw_tokens = item.removeprefix("matched:").split(",")
        return {token.strip() for token in raw_tokens if token.strip()}
    return set()


def context_hit_has_answer_support(context_hit: dict[str, Any], query: str) -> bool:
    if context_hit.get("active_current") is not True:
        return False
    answerability = context_hit.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return False
    required_tokens = query_support_tokens(search_memory.compact_whitespace(query))
    if not required_tokens:
        return False
    matched_tokens = context_hit_matched_tokens(context_hit)
    return all(token in matched_tokens for token in required_tokens)


def supported_context_hit(package: dict[str, Any], query: str) -> dict[str, Any] | None:
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return None
    for hit in hits:
        if isinstance(hit, dict) and context_hit_has_answer_support(hit, query):
            return hit
    return None


def answer_handoff(
    *,
    abstained: bool,
    support_refs: list[dict[str, Any]],
    context_package: dict[str, Any],
    abstain_reason: str = "",
) -> dict[str, Any]:
    handoff: dict[str, Any] = {
        "contract_version": HANDOFF_CONTRACT_VERSION,
        "abstained": abstained,
        "active_memory_only": True,
        "support_refs": support_refs,
        "context_package": context_package,
        "unsupported_claim_count": 0,
        "inactive_memory_answer_count": 0,
        "privacy_leak_count": 0,
    }
    if abstained:
        handoff["abstain_reason"] = abstain_reason or "no_supported_memory_hit"
    return handoff


def build_answer_records(
    repo: Path,
    cases: list[dict[str, Any]],
    limit: int,
    search_script: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    source_benchmarks: Counter[str] = Counter()
    case_origins: Counter[str] = Counter()
    memory_answer_count = 0
    abstention_answer_count = 0
    no_hit_count = 0
    unsupported_hit_count = 0
    answer_handoff_supported_case_count = 0
    answer_handoff_abstain_case_count = 0
    support_ref_covered_answer_count = 0
    context_package_parse_success_count = 0
    context_package_parse_failure_count = 0
    context_package_supported_case_count = 0
    context_package_abstain_case_count = 0
    context_package_support_covered_count = 0
    context_package_expected_abstain_count = 0
    context_package_abstention_hit_count = 0
    context_package_inactive_rejection_count = 0

    for case in cases:
        source_benchmark = optional_text(case, "source_benchmark")
        if source_benchmark:
            source_benchmarks[source_benchmark] += 1
        case_origin = optional_text(case, "case_origin") or optional_text(case, "origin")
        if case_origin:
            case_origins[case_origin] += 1
        case_id = str(case["case_id"])
        query = str(case["query"])
        expected_abstain = case.get("expected_abstain") is True
        if expected_abstain:
            context_package_expected_abstain_count += 1
        package, package_meta = search_context_package(repo, search_script, query, limit)
        if package_meta["parse_success"] is True:
            context_package_parse_success_count += 1
        else:
            context_package_parse_failure_count += 1
        reason = str(package_meta["answerability_reason"])
        if reason == "no_active_current_support":
            context_package_inactive_rejection_count += 1
        hit = supported_context_hit(package, query) if package is not None else None
        if hit is None and package_meta["answerability_status"] == "supported":
            package_meta = context_package_metadata(
                parse_success=True,
                answerability_status="unsupported",
                answerability_reason="missing_context_token_coverage",
            )
            reason = str(package_meta["answerability_reason"])
        if hit is not None:
            context_package_supported_case_count += 1
            support_refs = context_support_refs(hit)
            support_covered = support_refs_cover_answer(support_refs)
            if support_covered:
                context_package_support_covered_count += 1
            memory_id = str(hit.get("memory_id") or "")
            answer = extract_answer_from_memory_id(repo, memory_id, query)
            if answer == ABSTENTION_ANSWER or not support_covered:
                if answer != ABSTENTION_ANSWER:
                    unsupported_hit_count += 1
                answer = ABSTENTION_ANSWER
                abstention_answer_count += 1
                answer_handoff_abstain_case_count += 1
                handoff = answer_handoff(
                    abstained=True,
                    support_refs=[],
                    context_package=package_meta,
                    abstain_reason="missing_support_refs" if not support_covered else "privacy_boundary",
                )
            else:
                memory_answer_count += 1
                answer_handoff_supported_case_count += 1
                support_ref_covered_answer_count += 1
                handoff = answer_handoff(abstained=False, support_refs=support_refs, context_package=package_meta)
        else:
            answer = ABSTENTION_ANSWER
            abstention_answer_count += 1
            answer_handoff_abstain_case_count += 1
            context_package_abstain_case_count += 1
            if expected_abstain:
                context_package_abstention_hit_count += 1
            if package_meta["parse_success"] is False:
                abstain_reason = "context_package_unavailable"
            elif reason == "no_active_current_support":
                abstain_reason = "no_active_current_support"
            else:
                abstain_reason = "no_supported_memory_hit"
            if package is not None and package.get("hits"):
                unsupported_hit_count += 1
            else:
                no_hit_count += 1
            handoff = answer_handoff(
                abstained=True,
                support_refs=[],
                context_package=package_meta,
                abstain_reason=abstain_reason,
            )
        records.append({"case_id": case_id, "generated_answer": answer, "answer_handoff": handoff})

    report = {
        "report_kind": "generated_answer_records_adapter",
        "report_version": 1,
        "claim_boundary": (
            "extractive source-grounded answer handoff records only; "
            "no model-generation or semantic equivalence claim"
        ),
        "answerability_policy": ANSWERABILITY_POLICY,
        "answer_handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "cases": len(cases),
        "answers_written": len(records),
        "memory_answer_count": memory_answer_count,
        "abstention_answer_count": abstention_answer_count,
        "answer_handoff_supported_case_count": answer_handoff_supported_case_count,
        "answer_handoff_abstain_case_count": answer_handoff_abstain_case_count,
        "answer_handoff_support_coverage_rate": (
            1.0 if memory_answer_count == 0 else support_ref_covered_answer_count / memory_answer_count
        ),
        "context_package_report_kind": CONTEXT_PACKAGE_REPORT_KIND,
        "context_package_parse_success_count": context_package_parse_success_count,
        "context_package_parse_failure_count": context_package_parse_failure_count,
        "context_package_supported_case_count": context_package_supported_case_count,
        "context_package_abstain_case_count": context_package_abstain_case_count,
        "context_package_support_coverage_rate": (
            1.0
            if context_package_supported_case_count == 0
            else context_package_support_covered_count / context_package_supported_case_count
        ),
        "context_package_abstention_accuracy": (
            1.0
            if context_package_expected_abstain_count == 0
            else context_package_abstention_hit_count / context_package_expected_abstain_count
        ),
        "context_package_inactive_rejection_count": context_package_inactive_rejection_count,
        "unsupported_claim_count": 0,
        "inactive_memory_answer_count": 0,
        "privacy_leak_count": 0,
        "no_hit_count": no_hit_count,
        "unsupported_hit_count": unsupported_hit_count,
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    parser.add_argument("--cases", required=True, help="Answer benchmark cases JSONL")
    parser.add_argument("--output", required=True, help="Generated answer records JSONL to write")
    parser.add_argument("--limit", type=int, default=5, help="Top memory hits to consider per case")
    parser.add_argument(
        "--search-script",
        default=str(TOOLS_DIR / "search_memory.py"),
        help="Path to search_memory.py; used with --context-json for answerability",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")
    repo = Path(args.repo).expanduser().resolve()
    cases = load_cases(Path(args.cases).expanduser().resolve())
    records, report = build_answer_records(
        repo,
        cases,
        args.limit,
        Path(args.search_script).expanduser().resolve(),
    )
    write_jsonl(Path(args.output).expanduser().resolve(), records)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
