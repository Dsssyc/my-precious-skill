#!/usr/bin/env python3
"""Build a synthetic memory archive for packaged layered recall cases."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


UNSAFE_PATH = "[unsafe-path]"
MEMORY_LAYER_FILES = {
    "global": "global.jsonl",
    "domain": "domains.jsonl",
    "project": "projects.jsonl",
}
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
    if (
        any(ord(char) < 32 or ord(char) == 127 for char in text)
        or SENSITIVE_PATH_PATTERN.search(text)
        or has_sensitive_identifier_token(text)
    ):
        return UNSAFE_PATH
    return text


def safe_diagnostic_path(path: Path) -> str:
    return safe_diagnostic_text(path)


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
            }
        )
        or token_pairs.intersection(
            {
                ("api", "key"),
                ("auth", "token"),
                ("bearer", "token"),
                ("private", "key"),
                ("secret", "key"),
                ("session", "id"),
            }
        )
    )


def has_unsafe_identifier_path_reference(text: str) -> bool:
    if text.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    return any(part == ".." for part in re.split(r"[\\/]+", text))


def is_safe_memory_identifier(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return not (
        any(ord(char) < 32 or ord(char) == 127 for char in value)
        or has_sensitive_identifier_token(value)
        or has_unsafe_identifier_path_reference(value)
    )


def iter_jsonl(path: Path) -> Iterable[dict]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"unable to read cases JSONL {safe_diagnostic_path(path)}: {safe_diagnostic_text(exc)}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON at {safe_diagnostic_path(path)}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"{safe_diagnostic_path(path)}:{line_no}: expected object case")
            yield value


def positive_case(case: dict) -> bool:
    return case.get("expected_abstain") is not True


def text_list(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def raw_ref_from_anchor(anchor: str) -> dict:
    if "#" not in anchor:
        return {"path": anchor, "anchor": ""}
    path, raw_anchor = anchor.split("#", 1)
    return {"path": path, "anchor": raw_anchor}


def archive_relative_path_text(value: object, field: str) -> str:
    text = str(value).strip()
    if (
        not text
        or text.startswith(("~", "/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", text)
        or any(part == ".." for part in re.split(r"[\\/]+", text))
    ):
        raise SystemExit(f"unsafe archive path in benchmark case field: {field}")
    return text


def validate_case_archive_paths(case: dict) -> None:
    archive_relative_path_text(case["expected_summary_path"], "expected_summary_path")
    for summary_path in text_list(case.get("derived_from_paths")):
        archive_relative_path_text(summary_path, "derived_from_paths")
    for evidence_path in text_list(case.get("required_evidence_paths")):
        archive_relative_path_text(evidence_path, "required_evidence_paths")
    source_path = str(case["expected_source_anchor"]).split("#", 1)[0]
    archive_relative_path_text(source_path, "expected_source_anchor")


def validate_case_memory_identifier(value: object, field: str) -> None:
    if not is_safe_memory_identifier(value):
        raise SystemExit(f"unsafe benchmark memory identifier in case field: {field}")


def validate_case_memory_identifiers(case: dict) -> None:
    if positive_case(case):
        validate_case_memory_identifier(case.get("expected_memory_id"), "expected_memory_id")
    for support_id in text_list(case.get("derived_from_memory_ids")):
        validate_case_memory_identifier(support_id, "derived_from_memory_ids")
    for field in (
        "self_cycle_derived_from_memory_id",
        "missing_derived_from_memory_id",
        "superseded_derived_from_memory_id",
        "deprecated_derived_from_memory_id",
    ):
        for memory_id in text_list(case.get(field)):
            validate_case_memory_identifier(memory_id, field)
    for stale_id in text_list(case.get("stale_memory_id")):
        validate_case_memory_identifier(stale_id, "stale_memory_id")
    for contradicted_id in text_list(case.get("contradicted_memory_id")):
        validate_case_memory_identifier(contradicted_id, "contradicted_memory_id")
    for deprecated_id in text_list(case.get("deprecated_memory_id")):
        validate_case_memory_identifier(deprecated_id, "deprecated_memory_id")
    for false_merge_id in text_list(case.get("semantic_false_merge_memory_id")):
        validate_case_memory_identifier(false_merge_id, "semantic_false_merge_memory_id")


def memory_layer(case: dict) -> str:
    expected_layer = str(case.get("expected_layer") or "").strip()
    if expected_layer:
        if expected_layer not in {"global", "domain", "project"}:
            raise SystemExit("benchmark case expected_layer must be global, domain, or project")
        return expected_layer
    category = str(case.get("category") or "uncategorized")
    if category == "scope_calibration":
        return "domain"
    if category == "cross_project_recall":
        return "global"
    return "project"


def evidence_paths_for_case(case: dict) -> list[str]:
    evidence_paths = text_list(case.get("required_evidence_paths"))
    if evidence_paths:
        return evidence_paths
    summary_path = str(case["expected_summary_path"])
    return [summary_path.replace("/summary.md", "/evidence.md")]


def summary_paths_for_case(case: dict) -> list[str]:
    summary_paths = text_list(case.get("derived_from_paths"))
    if summary_paths:
        return summary_paths
    return [str(case["expected_summary_path"])]


def memory_graph_source_ids(case: dict) -> list[str]:
    ids = []
    ids.extend(text_list(case.get("derived_from_memory_ids")))
    for field in (
        "self_cycle_derived_from_memory_id",
        "missing_derived_from_memory_id",
        "superseded_derived_from_memory_id",
        "deprecated_derived_from_memory_id",
    ):
        ids.extend(text_list(case.get(field)))
    return ids


def build_memory_record(case: dict, *, include_superseded_refs: bool = False) -> dict:
    category = str(case.get("category") or "uncategorized")
    summary_paths = summary_paths_for_case(case)
    evidence_paths = evidence_paths_for_case(case)
    query = str(case["query"])
    memory_id = str(case["expected_memory_id"])
    reference_answers = text_list(case.get("reference_answer"))
    answer_text = " ".join(f"Reference answer: {answer}." for answer in reference_answers)
    text_parts = [f"Synthetic answer target: {memory_id}."]
    if answer_text:
        text_parts.append(answer_text)
    text_parts.append(f"{query} {query} {query}.")
    is_explicit_memory = category == "explicit_memory"
    graph_source_ids = memory_graph_source_ids(case)
    record = {
        "memory_id": memory_id,
        "layer": memory_layer(case),
        "scope": "synthetic",
        "topic": category.replace("_", "-"),
        "text": " ".join(text_parts),
        "rationale": f"Exact synthetic benchmark query match for: {query}.",
        "source": "explicit" if is_explicit_memory else "automatic",
        "confidence": "high",
        "persistence": "sticky" if is_explicit_memory else "normal",
        "support_count": max(1, len(summary_paths), len(evidence_paths)),
        "first_seen": "2026-06-19",
        "last_seen": "2026-06-19",
        "derived_from": graph_source_ids or summary_paths,
        "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
        "raw_refs": [] if graph_source_ids else [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
        "supersedes": text_list(case.get("stale_memory_id")) if include_superseded_refs else [],
        "superseded_by": None,
        "tags": [category, "synthetic-benchmark", str(case.get("source_benchmark") or "synthetic")],
    }
    contradicted_ids = text_list(case.get("contradicted_memory_id"))
    if include_superseded_refs and contradicted_ids:
        record["contradicts"] = contradicted_ids
    return record


def build_memory_graph_support_records(case: dict) -> list[dict]:
    summary_paths = summary_paths_for_case(case)
    evidence_paths = evidence_paths_for_case(case)
    raw_refs = [raw_ref_from_anchor(str(case["expected_source_anchor"]))]
    category = str(case.get("category") or "uncategorized")
    records = []

    def graph_support_paths(memory_id: str) -> tuple[list[str], list[str]]:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", memory_id).strip("._") or "memory-graph-support"
        base = f"sessions/synthetic/2027/05/graph-invalid/{slug}"
        return [f"{base}/summary.md"], [f"{base}/evidence.md"]

    def support_record(
        memory_id: str,
        *,
        derived_from: list[str] | None = None,
        evidence_ref_paths: list[str] | None = None,
    ) -> dict:
        record_evidence_paths = evidence_ref_paths if evidence_ref_paths is not None else evidence_paths
        return {
            "memory_id": memory_id,
            "layer": "domain",
            "scope": "synthetic",
            "topic": f"{category.replace('_', '-')}-support",
            "text": f"Synthetic memory graph support node: {memory_id}.",
            "rationale": "Synthetic support node for memory graph drilldown.",
            "source": "automatic",
            "confidence": "high",
            "persistence": "normal",
            "support_count": max(1, len(summary_paths), len(evidence_paths)),
            "first_seen": "2026-06-19",
            "last_seen": "2026-06-19",
            "derived_from": derived_from if derived_from is not None else summary_paths,
            "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in record_evidence_paths],
            "raw_refs": raw_refs,
            "supersedes": [],
            "superseded_by": None,
            "tags": [category, "synthetic-benchmark", "memory-graph-support"],
        }

    for support_id in text_list(case.get("derived_from_memory_ids")):
        records.append(support_record(support_id))

    for self_cycle_id in text_list(case.get("self_cycle_derived_from_memory_id")):
        invalid_summary_paths, invalid_evidence_paths = graph_support_paths(self_cycle_id)
        records.append(
            support_record(
                self_cycle_id,
                derived_from=[self_cycle_id, *invalid_summary_paths],
                evidence_ref_paths=invalid_evidence_paths,
            )
        )

    for superseded_id in text_list(case.get("superseded_derived_from_memory_id")):
        invalid_summary_paths, invalid_evidence_paths = graph_support_paths(superseded_id)
        replacement_id = f"{superseded_id}_replacement"
        superseded = support_record(
            superseded_id,
            derived_from=invalid_summary_paths,
            evidence_ref_paths=invalid_evidence_paths,
        )
        superseded["superseded_by"] = replacement_id
        replacement = support_record(replacement_id)
        replacement["supersedes"] = [superseded_id]
        records.extend([superseded, replacement])

    for deprecated_id in text_list(case.get("deprecated_derived_from_memory_id")):
        invalid_summary_paths, invalid_evidence_paths = graph_support_paths(deprecated_id)
        marker_id = f"{deprecated_id}_deprecation"
        deprecated = support_record(
            deprecated_id,
            derived_from=invalid_summary_paths,
            evidence_ref_paths=invalid_evidence_paths,
        )
        deprecated["confidence"] = "low"
        deprecated["deprecated_by"] = marker_id
        marker = support_record(marker_id)
        marker["deprecates"] = [deprecated_id]
        records.extend([deprecated, marker])

    return records


def build_superseded_distractor_records(case: dict) -> list[dict]:
    category = str(case.get("category") or "uncategorized")
    query = str(case["query"])
    expected_memory_id = str(case["expected_memory_id"])
    summary_paths = summary_paths_for_case(case)
    evidence_paths = evidence_paths_for_case(case)
    records = []
    for stale_id in text_list(case.get("stale_memory_id")):
        if stale_id == expected_memory_id:
            continue
        records.append(
            {
                "memory_id": stale_id,
                "layer": memory_layer(case),
                "scope": "synthetic",
                "topic": category.replace("_", "-"),
                "text": f"Synthetic superseded distractor target: {stale_id}. {query} {query} {query}.",
                "rationale": f"Superseded synthetic distractor for: {query}.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "normal",
                "support_count": max(1, len(summary_paths), len(evidence_paths)),
                "first_seen": "2026-06-18",
                "last_seen": "2026-06-18",
                "derived_from": summary_paths,
                "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
                "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
                "supersedes": [],
                "superseded_by": expected_memory_id,
                "tags": [
                    category,
                    "synthetic-benchmark",
                    "superseded-distractor",
                    str(case.get("source_benchmark") or "synthetic"),
                ],
            }
        )
    for contradicted_id in text_list(case.get("contradicted_memory_id")):
        if contradicted_id == expected_memory_id:
            continue
        records.append(
            {
                "memory_id": contradicted_id,
                "layer": memory_layer(case),
                "scope": "synthetic",
                "topic": category.replace("_", "-"),
                "text": f"Synthetic contradicted distractor target: {contradicted_id}. {query} {query} {query}.",
                "rationale": f"Contradicted synthetic distractor for: {query}.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "normal",
                "support_count": max(1, len(summary_paths), len(evidence_paths)),
                "first_seen": "2026-06-18",
                "last_seen": "2026-06-18",
                "derived_from": summary_paths,
                "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
                "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
                "supersedes": [],
                "superseded_by": None,
                "contradicted_by": [expected_memory_id],
                "tags": [
                    category,
                    "synthetic-benchmark",
                    "contradicted-distractor",
                    str(case.get("source_benchmark") or "synthetic"),
                ],
            }
        )
    for deprecated_id in text_list(case.get("deprecated_memory_id")):
        if deprecated_id == expected_memory_id:
            continue
        marker_id = f"{expected_memory_id}_deprecation"
        records.append(
            {
                "memory_id": deprecated_id,
                "layer": memory_layer(case),
                "scope": "synthetic",
                "topic": category.replace("_", "-"),
                "text": f"Synthetic deprecated distractor target: {deprecated_id}. {query} {query} {query}.",
                "rationale": f"Deprecated synthetic distractor for: {query}.",
                "source": "automatic",
                "confidence": "low",
                "persistence": "normal",
                "support_count": max(1, len(summary_paths), len(evidence_paths)),
                "first_seen": "2026-05-18",
                "last_seen": "2026-05-18",
                "derived_from": summary_paths,
                "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
                "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
                "supersedes": [],
                "superseded_by": None,
                "deprecated_by": marker_id,
                "tags": [
                    category,
                    "synthetic-benchmark",
                    "deprecated-distractor",
                    str(case.get("source_benchmark") or "synthetic"),
                ],
            }
        )
        records.append(
            {
                "memory_id": marker_id,
                "layer": memory_layer(case),
                "scope": "synthetic",
                "topic": category.replace("_", "-"),
                "text": f"Synthetic deprecation marker for: {deprecated_id}. {query}.",
                "rationale": f"Deprecation marker for: {query}.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "normal",
                "support_count": max(1, len(summary_paths), len(evidence_paths)),
                "first_seen": "2026-06-19",
                "last_seen": "2026-06-19",
                "derived_from": summary_paths,
                "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
                "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
                "supersedes": [],
                "superseded_by": None,
                "deprecates": [deprecated_id],
                "tags": [
                    category,
                    "synthetic-benchmark",
                    "deprecation-marker",
                    str(case.get("source_benchmark") or "synthetic"),
                ],
            }
        )
    for false_merge_id in text_list(case.get("semantic_false_merge_memory_id")):
        if false_merge_id == expected_memory_id:
            continue
        records.append(
            {
                "memory_id": false_merge_id,
                "layer": memory_layer(case),
                "scope": "synthetic",
                "topic": category.replace("_", "-"),
                "text": f"Synthetic near-miss false merge distractor target: {false_merge_id}. {query}.",
                "rationale": f"Near-miss false merge distractor for: {query}.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "normal",
                "support_count": 1,
                "first_seen": "2026-06-18",
                "last_seen": "2026-06-18",
                "derived_from": summary_paths,
                "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
                "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
                "supersedes": [],
                "superseded_by": None,
                "tags": [
                    category,
                    "synthetic-benchmark",
                    "false-merge-distractor",
                    str(case.get("source_benchmark") or "synthetic"),
                ],
            }
        )
    return records


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def write_positive_case_files(repo: Path, case: dict, record: dict) -> None:
    reference_answers = text_list(case.get("reference_answer"))
    reference_evidence = text_list(case.get("reference_evidence"))
    answer_section = ""
    if reference_answers:
        answer_section = "Reference answers:\n" + "".join(f"- {answer}\n" for answer in reference_answers) + "\n"
    for summary_path in summary_paths_for_case(case):
        write_text(
            repo / str(summary_path),
            "# Synthetic Layered Recall Session\n\n"
            f"Query: {case['query']}\n\n"
            f"Expected memory: {case['expected_memory_id']}\n\n"
            f"{answer_section}"
            "This file is generated synthetic benchmark data only.\n",
        )
    for evidence_path in evidence_paths_for_case(case):
        answer_evidence = " ".join(f"Reference answer: {answer}." for answer in reference_answers)
        evidence_text = " ".join(f"Reference evidence: {snippet}." for snippet in reference_evidence)
        write_text(
            repo / evidence_path,
            "# Synthetic Evidence\n\n"
            f"syn_ev_001: Evidence supporting {case['expected_memory_id']} for query {case['query']}. "
            f"{answer_evidence} {evidence_text}\n",
        )
    raw_refs = record["raw_refs"] or [raw_ref_from_anchor(str(case["expected_source_anchor"]))]
    for raw_ref in raw_refs:
        raw_path = repo / raw_ref["path"]
        append_text(
            raw_path,
            json.dumps(
                {
                    "anchor": raw_ref.get("anchor", ""),
                    "note": "Synthetic source anchor placeholder. No raw private transcript.",
                },
                sort_keys=True,
            )
            + "\n",
        )


def write_memory_record_support_files(repo: Path, case: dict, record: dict) -> None:
    for summary_path in text_list(record.get("derived_from")):
        if "/" not in summary_path or not summary_path.endswith("summary.md"):
            continue
        write_text(
            repo / summary_path,
            "# Synthetic Memory Graph Support\n\n"
            f"Query: {case['query']}\n\n"
            f"Support memory: {record.get('memory_id', '')}\n\n"
            "This file is generated synthetic benchmark data only.\n",
        )
    for evidence_ref in record.get("evidence_refs", []):
        if not isinstance(evidence_ref, dict):
            continue
        evidence_path = evidence_ref.get("path")
        if not isinstance(evidence_path, str) or not evidence_path.strip():
            continue
        write_text(
            repo / evidence_path,
            "# Synthetic Evidence\n\n"
            f"syn_ev_001: Evidence supporting {record.get('memory_id', '')} for query {case['query']}.\n",
        )
    for raw_ref in record.get("raw_refs", []):
        if not isinstance(raw_ref, dict):
            continue
        raw_path_value = raw_ref.get("path")
        if not isinstance(raw_path_value, str) or not raw_path_value.strip():
            continue
        append_text(
            repo / raw_path_value,
            json.dumps(
                {
                    "anchor": raw_ref.get("anchor", ""),
                    "note": "Synthetic source anchor placeholder. No raw private transcript.",
                },
                sort_keys=True,
            )
            + "\n",
        )


def write_memory_root_files(repo: Path, records: list[dict]) -> None:
    memories_dir = repo / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    by_layer: dict[str, list[dict]] = {layer: [] for layer in MEMORY_LAYER_FILES}
    explicit_records: list[dict] = []
    for record in records:
        layer = str(record.get("layer") or "project")
        if record.get("source") == "explicit":
            explicit_records.append(record)
            continue
        if layer in by_layer:
            by_layer[layer].append(record)
    for layer, file_name in MEMORY_LAYER_FILES.items():
        write_text(
            memories_dir / file_name,
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in by_layer[layer]),
        )
    write_text(
        memories_dir / "explicit.jsonl",
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in explicit_records),
    )


def write_archive(repo: Path, cases: list[dict], *, include_superseded_distractors: bool = False) -> None:
    try:
        (repo / "index").mkdir(parents=True, exist_ok=True)
        (repo / "sessions").mkdir(parents=True, exist_ok=True)
        (repo / "records").mkdir(parents=True, exist_ok=True)
        write_text(repo / "INDEX.md", "# Synthetic Layered Recall Archive\n")

        records = []
        for case in cases:
            if not positive_case(case):
                continue
            validate_case_memory_identifiers(case)
            validate_case_archive_paths(case)
            record = build_memory_record(case, include_superseded_refs=include_superseded_distractors)
            if include_superseded_distractors:
                records.extend(build_superseded_distractor_records(case))
            graph_support_records = build_memory_graph_support_records(case)
            records.extend(graph_support_records)
            records.append(record)
            write_positive_case_files(repo, case, record)
            for support_record in graph_support_records:
                write_memory_record_support_files(repo, case, support_record)

        (repo / "index" / "memories.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        write_memory_root_files(repo, records)
    except OSError as exc:
        display_repo = safe_diagnostic_path(repo)
        display_error = safe_diagnostic_text(exc)
        raise SystemExit(f"unable to write synthetic archive {display_repo}: {display_error}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Output synthetic archive path")
    parser.add_argument("--cases", required=True, help="Packaged benchmark JSONL cases")
    parser.add_argument(
        "--include-superseded-distractors",
        action="store_true",
        help="Add superseded stale memories with strong query matches to stress stale suppression",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    cases = list(iter_jsonl(Path(args.cases).expanduser().resolve()))
    write_archive(repo, cases, include_superseded_distractors=args.include_superseded_distractors)
    print(json.dumps({"repo": safe_diagnostic_path(repo), "cases": len(cases)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
