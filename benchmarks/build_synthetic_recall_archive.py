#!/usr/bin/env python3
"""Build a synthetic memory archive for packaged layered recall cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise SystemExit(f"{path}:{line_no}: expected object case")
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


def memory_layer(category: str) -> str:
    if category == "scope_calibration":
        return "domain"
    if category == "cross_project_recall":
        return "global"
    return "project"


def build_memory_record(case: dict) -> dict:
    category = str(case.get("category") or "uncategorized")
    summary_path = str(case["expected_summary_path"])
    evidence_paths = text_list(case.get("required_evidence_paths"))
    if not evidence_paths:
        evidence_paths = [summary_path.replace("/summary.md", "/evidence.md")]
    query = str(case["query"])
    memory_id = str(case["expected_memory_id"])
    return {
        "memory_id": memory_id,
        "layer": memory_layer(category),
        "scope": "synthetic",
        "topic": category.replace("_", "-"),
        "text": f"{query} {query} {query} Synthetic answer target: {memory_id}.",
        "rationale": f"Exact synthetic benchmark query match for: {query}.",
        "source": "synthetic",
        "confidence": "high",
        "persistence": "normal",
        "support_count": max(1, len(evidence_paths)),
        "first_seen": "2026-06-19",
        "last_seen": "2026-06-19",
        "derived_from": [summary_path],
        "evidence_refs": [{"path": path, "quote_id": "syn_ev_001"} for path in evidence_paths],
        "raw_refs": [raw_ref_from_anchor(str(case["expected_source_anchor"]))],
        "supersedes": text_list(case.get("stale_memory_id")),
        "superseded_by": None,
        "tags": [category, "synthetic-benchmark", str(case.get("source_benchmark") or "synthetic")],
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_positive_case_files(repo: Path, case: dict, record: dict) -> None:
    summary_path = repo / str(case["expected_summary_path"])
    write_text(
        summary_path,
        "# Synthetic Layered Recall Session\n\n"
        f"Query: {case['query']}\n\n"
        f"Expected memory: {case['expected_memory_id']}\n\n"
        "This file is generated synthetic benchmark data only.\n",
    )
    for evidence_path in text_list(case.get("required_evidence_paths")):
        write_text(
            repo / evidence_path,
            "# Synthetic Evidence\n\n"
            f"syn_ev_001: Evidence supporting {case['expected_memory_id']} for query {case['query']}.\n",
        )
    for raw_ref in record["raw_refs"]:
        raw_path = repo / raw_ref["path"]
        write_text(
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


def write_archive(repo: Path, cases: list[dict]) -> None:
    (repo / "index").mkdir(parents=True, exist_ok=True)
    (repo / "sessions").mkdir(parents=True, exist_ok=True)
    (repo / "records").mkdir(parents=True, exist_ok=True)
    write_text(repo / "INDEX.md", "# Synthetic Layered Recall Archive\n")

    records = []
    for case in cases:
        if not positive_case(case):
            continue
        record = build_memory_record(case)
        records.append(record)
        write_positive_case_files(repo, case, record)

    (repo / "index" / "memories.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Output synthetic archive path")
    parser.add_argument("--cases", required=True, help="Packaged benchmark JSONL cases")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    cases = list(iter_jsonl(Path(args.cases).expanduser().resolve()))
    write_archive(repo, cases)
    print(json.dumps({"repo": str(repo), "cases": len(cases)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
