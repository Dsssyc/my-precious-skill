#!/usr/bin/env python3
"""Convert locally downloaded public long-memory benchmarks to case JSONL.

The converter does not download datasets. Keep public benchmark downloads
outside this repository, then map them into the My Precious layered recall case
schema for local evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Iterable


SOURCE_LABELS = {
    "longmemeval": "LongMemEval",
    "locomo": "LoCoMo",
    "memora": "Memora",
}
UNSAFE_PATH = "[unsafe-path]"
SENSITIVE_PATH_PATTERN = re.compile(
    r"(?i)(?:"
    r"\b(?:api[_-]?key|authorization|bearer|cookie|credential|password|"
    r"private[_ -]?key|secret|session[_-]?id|token)\b\s*[:=]|"
    r"\bbearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)


def safe_diagnostic_text(value: object) -> str:
    text = str(value)
    if any(ord(char) < 32 or ord(char) == 127 for char in text) or SENSITIVE_PATH_PATTERN.search(text):
        return UNSAFE_PATH
    return text


def safe_diagnostic_path(path: Path) -> str:
    return safe_diagnostic_text(path)


def safe_case_id_for_diagnostic(value: object) -> str:
    text = str(value)
    normalized_tokens = set(re.split(r"[^a-z0-9]+", text.lower().replace("_", " ")))
    if SENSITIVE_PATH_PATTERN.search(text) or normalized_tokens.intersection(
        {
            "apikey",
            "api",
            "authorization",
            "bearer",
            "cookie",
            "credential",
            "password",
            "private",
            "secret",
            "session",
            "token",
        }
    ):
        return UNSAFE_PATH
    return safe_diagnostic_text(text)


def load_payload(path: Path) -> object:
    if path.suffix == ".jsonl":
        rows = []
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError as exc:
            raise SystemExit(
                f"unable to read input benchmark file {safe_diagnostic_path(path)}: {safe_diagnostic_text(exc)}"
            ) from exc
        with handle:
            for line_no, line in enumerate(handle, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"invalid JSON at {safe_diagnostic_path(path)}:{line_no}: {exc}") from exc
        return rows
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(
            f"unable to read input benchmark file {safe_diagnostic_path(path)}: {safe_diagnostic_text(exc)}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON at {safe_diagnostic_path(path)}: {exc}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def case_id(source: str, item_id: str) -> str:
    return f"{safe_id(source)}:{safe_id(item_id)}"


def first_text(record: dict, *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def text_list(value: object, *, label: str) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        out = []
        for idx, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                raise SystemExit(f"{label}[{idx}] must be a non-empty string")
            out.append(item.strip())
        return out
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
        "case_id": case_id(source, item_id),
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


def abstention_case(source: str, item_id: str, query: str, category: str, extra: dict) -> dict:
    case = {
        "case_id": case_id(source, item_id),
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
            cases.append(abstention_case("longmemeval", question_id, question, "abstention", extra))
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
                        "reference_evidence": text_list(
                            qa.get("evidence") or qa.get("evidences"),
                            label=f"LoCoMo sample {sample_idx} qa {qa_idx} evidence",
                        ),
                        "locomo_sample_id": sample_id,
                        "locomo_qa_index": qa_idx,
                    },
                )
            )
    return cases


def memora_question_groups(payload: object) -> Iterable[tuple[str, list[dict]]]:
    if isinstance(payload, list):
        yield "uncategorized", memora_object_items(payload, "Memora input")
        return
    if not isinstance(payload, dict):
        raise SystemExit("Memora input must be a JSON object or array")
    questions = payload.get("questions") or payload.get("data")
    if isinstance(questions, list):
        yield "uncategorized", memora_object_items(questions, "Memora questions")
        return
    if isinstance(questions, dict):
        for task, values in questions.items():
            if not isinstance(values, list):
                raise SystemExit(f"Memora task {task} must contain a list")
            yield str(task), memora_object_items(values, f"Memora task {task}")
        return
    raise SystemExit("Memora input is missing questions")


def memora_object_items(values: list, label: str) -> list[dict]:
    out = []
    for idx, value in enumerate(values, 1):
        if not isinstance(value, dict):
            raise SystemExit(f"{label} item {idx} is not an object")
        out.append(value)
    return out


def memora_evaluation_types(item: dict) -> list[str]:
    evaluation = item.get("evaluation") or item.get("evaluations") or {}
    if isinstance(evaluation, dict):
        questions = evaluation.get("evaluation_questions") or evaluation.get("questions") or []
    elif isinstance(evaluation, list):
        questions = evaluation
    else:
        questions = []
    types = []
    for question in memora_object_items(questions, "Memora evaluation question"):
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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        display_path = safe_diagnostic_path(path)
        display_error = safe_diagnostic_text(exc)
        raise SystemExit(f"unable to write output benchmark file {display_path}: {display_error}") from exc


def validate_unique_case_ids(cases: list[dict]) -> None:
    seen: dict[str, int] = {}
    for idx, case in enumerate(cases, 1):
        value = case.get("case_id")
        if not isinstance(value, str) or not value:
            continue
        first_idx = seen.get(value)
        if first_idx is not None:
            display_value = safe_case_id_for_diagnostic(value)
            raise SystemExit(
                f"duplicate case_id {display_value!r} in converted case {idx}; "
                f"first seen in converted case {first_idx}"
            )
        seen[value] = idx


def validate_non_empty_cases(cases: list[dict]) -> None:
    if not cases:
        raise SystemExit("converted case set is empty")


def load_synthetic_builder():
    builder_path = Path(__file__).with_name("build_synthetic_recall_archive.py")
    spec = importlib.util.spec_from_file_location("build_synthetic_recall_archive", builder_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"unable to load synthetic archive builder from {builder_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_LABELS), help="Input benchmark schema")
    parser.add_argument("--input", required=True, help="Downloaded public benchmark JSON or JSONL file")
    parser.add_argument("--output", required=True, help="Output My Precious benchmark cases JSONL")
    parser.add_argument("--limit", type=int, help="Limit converted cases after schema conversion")
    parser.add_argument("--build-synthetic-archive", help="Optional output repo path for a synthetic dry-run archive")
    parser.add_argument(
        "--include-superseded-distractors",
        action="store_true",
        help="When building a synthetic archive, include superseded stale-memory distractors",
    )
    args = parser.parse_args(argv)

    if args.include_superseded_distractors and not args.build_synthetic_archive:
        parser.error("--include-superseded-distractors requires --build-synthetic-archive")

    input_path = Path(args.input).expanduser().resolve()
    payload = load_payload(input_path)
    if args.source == "longmemeval":
        cases = convert_longmemeval(payload)
    elif args.source == "locomo":
        cases = convert_locomo(payload)
    else:
        cases = convert_memora(payload)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    validate_non_empty_cases(cases)
    validate_unique_case_ids(cases)
    output = Path(args.output).expanduser().resolve()
    write_cases(output, cases)
    result = {
        "cases": len(cases),
        "input_sha256": file_sha256(input_path),
        "output": safe_diagnostic_path(output),
        "output_sha256": file_sha256(output),
        "source": SOURCE_LABELS[args.source],
    }
    if args.build_synthetic_archive:
        archive = Path(args.build_synthetic_archive).expanduser().resolve()
        builder = load_synthetic_builder()
        builder.write_archive(
            archive,
            cases,
            include_superseded_distractors=args.include_superseded_distractors,
        )
        result["synthetic_archive"] = safe_diagnostic_path(archive)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
