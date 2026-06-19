#!/usr/bin/env python3
"""Convert locally downloaded public long-memory benchmarks to case JSONL.

The converter does not download datasets. Keep public benchmark downloads
outside this repository, then map them into the My Precious layered recall case
schema for local evaluation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


SOURCE_LABELS = {
    "longmemeval": "LongMemEval",
    "locomo": "LoCoMo",
    "memora": "Memora",
}


def load_payload(path: Path) -> object:
    if path.suffix == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"invalid JSON at {path}:{line_no}: {exc}") from exc
        return rows
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON at {path}: {exc}") from exc


def sequence_payload(payload: object, *, source: str) -> list[dict]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        values = payload["data"]
    else:
        raise SystemExit(f"{source} input must be a JSON array or an object with a data array")
    out = [value for value in values if isinstance(value, dict)]
    if len(out) != len(values):
        raise SystemExit(f"{source} input contains a non-object row")
    return out


def safe_id(value: object, fallback: str = "item") -> str:
    text = str(value or "").strip()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-").lower()
    return slug or fallback


def first_text(record: dict, *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def text_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def category_from_text(value: str, *, default: str = "information_extraction") -> str:
    lowered = value.lower().replace("_", "-").strip()
    if not lowered:
        return default
    if "abstain" in lowered or "unanswer" in lowered or lowered.endswith("-abs"):
        return "abstention"
    if "privacy" in lowered or "secret" in lowered:
        return "privacy_boundary"
    if "temporal" in lowered or "time" in lowered:
        return "temporal_reasoning"
    if "update" in lowered or "latest" in lowered:
        return "knowledge_update"
    if "forget" in lowered or "stale" in lowered:
        return "stale_memory_suppression"
    if "multi" in lowered or "reason" in lowered:
        return "multi_session_reasoning"
    if "source" in lowered or "evidence" in lowered:
        return "source_reachability"
    if "cross" in lowered or "global" in lowered:
        return "cross_project_recall"
    return default


def positive_case(source: str, item_id: str, query: str, category: str, source_anchor: str, extra: dict) -> dict:
    source_slug = safe_id(source)
    item_slug = safe_id(item_id)
    summary_path = f"sessions/external/{source_slug}/{item_slug}/summary.md"
    case = {
        "query": query,
        "category": category,
        "source_benchmark": SOURCE_LABELS[source],
        "expected_memory_id": f"external_{source_slug}_{item_slug}",
        "expected_summary_path": summary_path,
        "expected_source_anchor": f"records/external/{source_slug}.json#{source_anchor}",
        "required_evidence_paths": [summary_path.replace("/summary.md", "/evidence.md")],
    }
    case.update({key: value for key, value in extra.items() if value not in ("", [], None)})
    return case


def abstention_case(source: str, query: str, category: str, extra: dict) -> dict:
    case = {
        "query": query,
        "category": category,
        "source_benchmark": SOURCE_LABELS[source],
        "expected_abstain": True,
    }
    case.update({key: value for key, value in extra.items() if value not in ("", [], None)})
    return case


def convert_longmemeval(payload: object) -> list[dict]:
    cases = []
    for idx, item in enumerate(sequence_payload(payload, source="LongMemEval"), 1):
        question_id = first_text(item, "question_id", "id") or f"longmemeval-{idx}"
        question = first_text(item, "question", "query")
        if not question:
            raise SystemExit(f"LongMemEval row {idx} is missing question")
        question_type = first_text(item, "question_type", "type")
        extra = {
            "reference_answer": first_text(item, "answer", "reference_answer"),
            "question_date": first_text(item, "question_date", "date"),
            "question_type": question_type,
        }
        if question_id.endswith("_abs") or category_from_text(question_type) == "abstention":
            cases.append(abstention_case("longmemeval", question, "abstention", extra))
            continue
        cases.append(
            positive_case(
                "longmemeval",
                question_id,
                question,
                category_from_text(question_type),
                f"question_id:{question_id}",
                extra,
            )
        )
    return cases


def convert_locomo(payload: object) -> list[dict]:
    cases = []
    for sample_idx, sample in enumerate(sequence_payload(payload, source="LoCoMo"), 1):
        sample_id = first_text(sample, "sample_id", "conversation_id", "conv_id", "id") or f"sample-{sample_idx}"
        qa_items = sample.get("qa") or sample.get("qas") or sample.get("questions")
        if not isinstance(qa_items, list):
            raise SystemExit(f"LoCoMo sample {sample_idx} is missing qa list")
        for qa_idx, qa in enumerate(qa_items, 1):
            if not isinstance(qa, dict):
                raise SystemExit(f"LoCoMo sample {sample_idx} qa {qa_idx} is not an object")
            question = first_text(qa, "question", "query")
            if not question:
                raise SystemExit(f"LoCoMo sample {sample_idx} qa {qa_idx} is missing question")
            raw_category = first_text(qa, "category", "question_type", "type")
            item_id = first_text(qa, "question_id", "id") or f"{sample_id}_qa-{qa_idx}"
            cases.append(
                positive_case(
                    "locomo",
                    item_id,
                    question,
                    category_from_text(raw_category),
                    f"sample:{sample_id}:qa:{qa_idx}",
                    {
                        "reference_answer": first_text(qa, "answer", "reference_answer", "final_answer"),
                        "reference_evidence": text_list(qa.get("evidence") or qa.get("evidences")),
                        "locomo_sample_id": sample_id,
                        "locomo_qa_index": qa_idx,
                    },
                )
            )
    return cases


def memora_question_groups(payload: object) -> Iterable[tuple[str, list[dict]]]:
    if isinstance(payload, list):
        yield "uncategorized", [item for item in payload if isinstance(item, dict)]
        return
    if not isinstance(payload, dict):
        raise SystemExit("Memora input must be a JSON object or array")
    questions = payload.get("questions") or payload.get("data")
    if isinstance(questions, list):
        yield "uncategorized", [item for item in questions if isinstance(item, dict)]
        return
    if isinstance(questions, dict):
        for task, values in questions.items():
            if not isinstance(values, list):
                raise SystemExit(f"Memora task {task} must contain a list")
            yield str(task), [item for item in values if isinstance(item, dict)]
        return
    raise SystemExit("Memora input is missing questions")


def memora_evaluation_types(item: dict) -> list[str]:
    evaluation = item.get("evaluation") or item.get("evaluations") or {}
    if isinstance(evaluation, dict):
        questions = evaluation.get("evaluation_questions") or evaluation.get("questions") or []
    elif isinstance(evaluation, list):
        questions = evaluation
    else:
        questions = []
    types = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        evaluation_type = first_text(question, "evaluation_type", "type")
        if evaluation_type:
            types.append(evaluation_type)
    return types


def convert_memora(payload: object) -> list[dict]:
    cases = []
    for task, items in memora_question_groups(payload):
        for idx, item in enumerate(items, 1):
            question_id = first_text(item, "question_id", "id") or f"memora-{safe_id(task)}-{idx}"
            question = first_text(item, "question", "query")
            if not question:
                raise SystemExit(f"Memora task {task} item {idx} is missing question")
            evaluation_types = memora_evaluation_types(item)
            case = positive_case(
                "memora",
                question_id,
                question,
                category_from_text(task),
                f"question_id:{question_id}",
                {
                    "reference_answer": first_text(item, "answer", "reference_answer", "expected_answer"),
                    "question_date": first_text(item, "question_date", "date"),
                    "evaluation_types": evaluation_types,
                },
            )
            if "forgetting_absence" in evaluation_types:
                case["stale_memory_id"] = f"{case['expected_memory_id']}_stale"
                case["expected_not_memory_id"] = case["stale_memory_id"]
                case["temporal_scope"] = "latest"
            cases.append(case)
    return cases


def write_cases(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_LABELS), help="Input benchmark schema")
    parser.add_argument("--input", required=True, help="Downloaded public benchmark JSON or JSONL file")
    parser.add_argument("--output", required=True, help="Output My Precious benchmark cases JSONL")
    parser.add_argument("--limit", type=int, help="Limit converted cases after schema conversion")
    args = parser.parse_args(argv)

    payload = load_payload(Path(args.input).expanduser().resolve())
    if args.source == "longmemeval":
        cases = convert_longmemeval(payload)
    elif args.source == "locomo":
        cases = convert_locomo(payload)
    else:
        cases = convert_memora(payload)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    output = Path(args.output).expanduser().resolve()
    write_cases(output, cases)
    print(json.dumps({"cases": len(cases), "output": str(output), "source": SOURCE_LABELS[args.source]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
