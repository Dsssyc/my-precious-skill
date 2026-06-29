#!/usr/bin/env python3
"""Run a synthetic benchmark for explicit non-project source streams.

The runner creates a temporary deployment archive, registers
``config/source_streams.jsonl`` without project registry rows, runs the real
global update runner, then scores the induced memory through the real layered
recall scorer. It prints aggregate-only JSON and never renders source content,
memory text, source paths, raw refs, or case-level details.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import e2e_induction_recall_benchmark as e2e_benchmark
import layered_recall_benchmark as recall_benchmark
import updater_induction_benchmark as induction_benchmark


DEFAULT_SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
PROJECT_METADATA_KEYS = {
    "cwd",
    "project_path",
    "working_directory",
    "current_working_directory",
    "workspace",
    "repo_path",
    "repository_path",
}


@dataclass
class SourceStreamRun:
    case_id: str
    category: str
    source_records: int
    metadata_free_records: int
    recall_cases: int
    recall_details: list[dict[str, Any]]
    update_hit: bool
    project_registry_independent: bool
    archive_scope_hit: bool
    source_partition_hit: bool
    failed: bool
    leaked: bool


def ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def validate_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        raise SystemExit("no benchmark cases found")
    seen: set[str] = set()
    for case in cases:
        case_id = induction_benchmark.safe_id(case.get("case_id"), "case_id")
        if case_id in seen:
            raise SystemExit("duplicate case_id")
        seen.add(case_id)
        induction_benchmark.safe_category(case.get("category"))
        induction_benchmark.safe_id(case.get("stream_id"), "stream_id")
        induction_benchmark.safe_id(case.get("archive_scope"), "archive_scope")
        induction_benchmark.safe_id(case.get("source_partition"), "source_partition")
        induction_benchmark.safe_id(case.get("project"), "project")
        records = case.get("records")
        if not isinstance(records, list) or not records:
            raise SystemExit("benchmark case records must be a non-empty list")
        for record in records:
            if not isinstance(record, dict):
                raise SystemExit("benchmark record must be an object")
            induction_benchmark.safe_id(record.get("record_id"), "record_id")
            if not isinstance(record.get("events"), list) or not record["events"]:
                raise SystemExit("benchmark record events must be a non-empty list")
        for expected in case.get("expected_memories") or []:
            if not isinstance(expected, dict):
                raise SystemExit("expected_memories entries must be objects")
            if not isinstance(expected.get("recall_query"), str) or not expected["recall_query"].strip():
                raise SystemExit("expected memory must include non-empty recall_query")
            if expected.get("expect_evidence_drilldown") is not True:
                raise SystemExit("expected memory must include expect_evidence_drilldown=true")
            if expected.get("expect_source_policy") is not True:
                raise SystemExit("expected memory must include expect_source_policy=true")


def prepare_work_dir(work_dir: str | None):
    if work_dir:
        path = Path(work_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise SystemExit("--work-dir must be empty")
        return path, None
    temp = tempfile.TemporaryDirectory(prefix="my-precious-source-stream-registry-")
    return Path(temp.name), temp


def write_source_stream_record(case_root: Path, record: dict[str, Any]) -> Path:
    record_id = induction_benchmark.safe_id(record.get("record_id"), "record_id")
    source_dir = case_root / "source-records"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{record_id}.jsonl"
    lines: list[str] = []
    for event in record["events"]:
        payload = {
            "role": str(event["role"]),
            "content": induction_benchmark.expand_synthetic_placeholders(str(event["content"])),
        }
        lines.append(json.dumps(payload, sort_keys=True))
    source_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    epoch = induction_benchmark.timestamp_to_epoch(str(record["updated_at"]))
    os.utime(source_path, (epoch, epoch))
    return source_path


def source_record_has_project_metadata(path: Path) -> bool:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return any(value_contains_project_metadata(value) for value in values)


def value_contains_project_metadata(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in PROJECT_METADATA_KEYS and isinstance(child, str) and child.strip():
                return True
            if value_contains_project_metadata(child):
                return True
    elif isinstance(value, list):
        return any(value_contains_project_metadata(item) for item in value)
    return False


def write_source_stream_registry(memory_repo: Path, case: dict[str, Any], source_dir: Path) -> None:
    row = {
        "stream_id": induction_benchmark.safe_id(case.get("stream_id"), "stream_id"),
        "source_dir": str(source_dir),
        "archive_scope": induction_benchmark.safe_id(case.get("archive_scope"), "archive_scope"),
        "source_partition": induction_benchmark.safe_id(case.get("source_partition"), "source_partition"),
        "project": induction_benchmark.safe_id(case.get("project"), "project"),
        "enabled": True,
        "source": "benchmark",
    }
    (memory_repo / "config/projects.jsonl").write_text("", encoding="utf-8")
    (memory_repo / "config/source_streams.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def run_global_source_stream_update(memory_repo: Path, discovery_dir: Path) -> induction_benchmark.CommandResult:
    return induction_benchmark.run_command(
        [
            sys.executable,
            str(memory_repo / "tools/run_memory_updates.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(discovery_dir),
        ]
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return induction_benchmark.load_jsonl(path)


def project_registry_empty(memory_repo: Path) -> bool:
    rows = load_jsonl(memory_repo / "config/projects.jsonl")
    return not rows


def assignment_hit(rows: list[dict[str, Any]], field: str, expected: object) -> bool:
    expected_text = str(expected)
    return bool(rows) and all(str(row.get(field) or "") == expected_text for row in rows)


def build_source_stream_recall_case(
    case: dict[str, Any],
    expected: dict[str, Any],
    node: dict[str, Any],
) -> dict[str, Any]:
    recall_case = e2e_benchmark.build_recall_case(case, expected, node, {})
    recall_case["source_benchmark"] = "MyPrecious-source-stream-registry-synthetic"
    return recall_case


def score_source_stream_case(
    case: dict[str, Any],
    run_root: Path,
    setup_script: Path,
    search_timeout_s: float,
) -> SourceStreamRun:
    case_id = induction_benchmark.safe_id(case.get("case_id"), "case_id")
    category = induction_benchmark.safe_category(case.get("category"))
    case_root = run_root / induction_benchmark.safe_case_slug(case_id)
    case_root.mkdir(parents=True, exist_ok=True)
    memory_repo = case_root / "synthetic-memory-archive"
    induction_benchmark.setup_archive(memory_repo, setup_script)
    discovery_dir = case_root / "empty-project-discovery"
    discovery_dir.mkdir()

    source_paths = [write_source_stream_record(case_root, record) for record in case["records"]]
    source_dir = source_paths[0].parent
    metadata_free_records = sum(int(not source_record_has_project_metadata(path)) for path in source_paths)
    write_source_stream_registry(memory_repo, case, source_dir)
    update_result = run_global_source_stream_update(memory_repo, discovery_dir)
    command_outputs = [update_result]

    session_rows = load_jsonl(memory_repo / "index/sessions.jsonl")
    update_hit = update_result.returncode == 0 and "Source streams updated: 1" in update_result.stdout
    archive_scope_hit = assignment_hit(session_rows, "archive_scope", case.get("archive_scope"))
    source_partition_hit = assignment_hit(session_rows, "source_partition", case.get("source_partition"))
    project_independent = project_registry_empty(memory_repo)

    nodes = induction_benchmark.load_nodes(memory_repo)
    recall_cases: list[dict[str, Any]] = []
    failed = update_result.returncode != 0
    for expected in case.get("expected_memories") or []:
        expected_text = str(expected.get("text") or "")
        expected_source = str(expected.get("source") or "")
        node = induction_benchmark.node_by_text(nodes, expected_text, expected_source)
        if node is None:
            failed = True
            continue
        try:
            recall_cases.append(build_source_stream_recall_case(case, expected, node))
        except ValueError:
            failed = True

    details: list[dict[str, Any]] = []
    leaked = induction_benchmark.privacy_leaked(case, command_outputs, memory_repo)
    if recall_cases:
        recall_cases_path = case_root / "source-stream-recall-cases.jsonl"
        e2e_benchmark.write_recall_cases(recall_cases_path, recall_cases)
        loaded_cases = recall_benchmark.load_cases(recall_cases_path)
        _, details = recall_benchmark.score_cases(
            memory_repo,
            loaded_cases,
            memory_repo / "tools/search_memory.py",
            search_timeout_s,
        )
        failed = failed or any(not detail.get("case_pass") for detail in details)
        leaked = leaked or any(not detail.get("privacy_boundary_pass") for detail in details)
    elif case.get("expected_memories"):
        failed = True

    failed = failed or leaked or not update_hit or not project_independent or not archive_scope_hit or not source_partition_hit
    return SourceStreamRun(
        case_id=case_id,
        category=category,
        source_records=len(source_paths),
        metadata_free_records=metadata_free_records,
        recall_cases=len(recall_cases),
        recall_details=details,
        update_hit=update_hit,
        project_registry_independent=project_independent,
        archive_scope_hit=archive_scope_hit,
        source_partition_hit=source_partition_hit,
        failed=failed,
        leaked=leaked,
    )


def detail_hit(detail: dict[str, Any], key: str) -> int:
    return int(detail.get(key) is True)


def build_report(cases: list[dict[str, Any]], runs: list[SourceStreamRun], fingerprint: str) -> dict[str, Any]:
    details = [detail for run in runs for detail in run.recall_details]
    recall_cases = len(details)
    evidence_cases = sum(1 for detail in details if detail.get("required_evidence_paths"))
    source_policy_cases = sum(1 for detail in details if detail.get("expected_source_anchor"))
    source_records = sum(run.source_records for run in runs)
    metadata_free_records = sum(run.metadata_free_records for run in runs)
    return {
        "report_version": 1,
        "report_kind": "source_stream_registry_benchmark",
        "cases_sha256": fingerprint,
        "privacy": {
            "aggregate_only": True,
            "case_details_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "cases": len(cases),
        "source_records": source_records,
        "source_records_without_project_metadata": metadata_free_records,
        "recall_cases": recall_cases,
        "category_counts": dict(sorted(Counter(run.category for run in runs).items())),
        "source_stream_update_rate": ratio(sum(int(run.update_hit) for run in runs), len(runs)),
        "project_registry_independence_rate": ratio(
            sum(int(run.project_registry_independent) for run in runs),
            len(runs),
        ),
        "metadata_free_source_record_rate": ratio(metadata_free_records, source_records),
        "archive_scope_assignment_rate": ratio(sum(int(run.archive_scope_hit) for run in runs), len(runs)),
        "source_partition_assignment_rate": ratio(
            sum(int(run.source_partition_hit) for run in runs),
            len(runs),
        ),
        "source_stream_memory_recall_at_5": ratio(
            sum(detail_hit(detail, "memory_recall_at_5") for detail in details),
            recall_cases,
        ),
        "source_stream_session_drilldown_rate": ratio(
            sum(detail_hit(detail, "session_drilldown_hit") for detail in details),
            recall_cases,
        ),
        "source_stream_evidence_reachability_rate": ratio(
            sum(
                int(
                    detail.get("evidence_reachability_hit") is True
                    and detail.get("memory_evidence_ref_reachability_hit") is True
                )
                for detail in details
            ),
            evidence_cases,
        ),
        "source_stream_source_policy_pass_rate": ratio(
            sum(detail_hit(detail, "source_depth_policy_pass") for detail in details),
            source_policy_cases,
        ),
        "privacy_leak_count": sum(int(run.leaked) for run in runs),
        "failed_case_count": sum(int(run.failed) for run in runs),
        "case_pass_rate": ratio(sum(int(not run.failed) for run in runs), len(runs)),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Synthetic source stream registry benchmark JSONL")
    parser.add_argument("--work-dir", help="Empty directory for temporary synthetic archives")
    parser.add_argument("--setup-script", default=str(DEFAULT_SETUP_SCRIPT), help="Archive setup script to run")
    parser.add_argument(
        "--search-timeout-s",
        type=float,
        default=recall_benchmark.DEFAULT_SEARCH_TIMEOUT_S,
        help="Per-depth search subprocess timeout in seconds",
    )
    parser.add_argument("--fail-under", action="append", default=[], help="Require metric >= value")
    parser.add_argument("--fail-over", action="append", default=[], help="Require metric <= value")
    parser.add_argument("--fail-under-file", help="JSON object of lower-bound metric thresholds")
    parser.add_argument("--fail-over-file", help="JSON object of upper-bound metric thresholds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases_path = Path(args.cases).expanduser().resolve()
    setup_script = Path(args.setup_script).expanduser().resolve()
    if not setup_script.is_file():
        raise SystemExit("setup script not found")
    cases = list(induction_benchmark.iter_jsonl(cases_path))
    validate_cases(cases)
    run_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        runs = [
            score_source_stream_case(case, run_root, setup_script, args.search_timeout_s)
            for case in cases
        ]
        report = build_report(cases, runs, induction_benchmark.cases_fingerprint(cases_path))
        fail_under = {
            **e2e_benchmark.load_threshold_file(args.fail_under_file),
            **e2e_benchmark.parse_thresholds(args.fail_under),
        }
        fail_over = {
            **e2e_benchmark.load_threshold_file(args.fail_over_file),
            **e2e_benchmark.parse_thresholds(args.fail_over),
        }
        failures = e2e_benchmark.apply_quality_gates(report, fail_under, fail_over)
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
