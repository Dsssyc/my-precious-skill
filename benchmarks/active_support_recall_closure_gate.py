#!/usr/bin/env python3
"""Gate active/current support diagnosis on clean packaged archives.

The gate builds a synthetic packaged memory archive, invokes the archive-bundled
search tool with --depth evidence --context-json, and verifies that the public
active-support diagnosis distinguishes supported hits, wrong active hits,
unsupported active hits, and missing expected nodes. It never uses free-form
search output as answerability evidence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import private_lifecycle_governance_shadow_gate as shadow  # noqa: E402


REPORT_KIND = "active_support_recall_closure_gate"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"

SUPPORTED_CASE = "supported_active_current"
WRONG_ACTIVE_HIT_CASE = "expected_missing_wrong_active_hit"
PACKAGE_UNSUPPORTED_CASE = "expected_hit_package_unsupported"
MISSING_UNSUPPORTED_CASE = "expected_missing_package_unsupported"

SUPPORTED_TEXT = "v225alpha supported durable anchor current answer"
WRONG_ACTIVE_TEXT = "v225wronghit supported alternate current answer"
UNSUPPORTED_TEXT = "v225unsupported active no drilldown marker"
RAW_SOURCE_SENTINEL = "RAW V225 TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=V225_SHOULD_NOT_RENDER"
LEAK_MARKERS = (
    SUPPORTED_TEXT,
    WRONG_ACTIVE_TEXT,
    UNSUPPORTED_TEXT,
    RAW_SOURCE_SENTINEL,
    SECRET_SENTINEL,
)


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def to_report(self) -> dict[str, object]:
        report: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            report["returncode"] = self.returncode
        return report


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    query: str
    expected_node: dict[str, object]
    expected_supported: bool
    required_nonzero_counters: tuple[str, ...] = ()
    required_zero_counters: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseResult:
    spec: CaseSpec
    parse_success: bool
    report_kind: str
    supported: bool
    counters: dict[str, int]
    package_text: str


def run_command(command: list[str], stage: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def setup_packaged_archive(root: Path) -> Path:
    memory_repo = root / "agent-memory"
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--skip-config",
        ],
        "setup_packaged_archive",
    )
    if not (memory_repo / "tools/search_memory.py").is_file():
        raise GateFailure("setup_packaged_archive", "search_tool_missing")
    return memory_repo


def support_paths(slug: str) -> tuple[str, str]:
    base = f"sessions/synthetic/v225-active-support-{slug}"
    return f"{base}/summary.md", f"{base}/evidence.md"


def write_support_file(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n\n"
        "ev_v225_001: Synthetic support file for V2.25 active support gating.\n",
        encoding="utf-8",
    )


def memory_row(
    memory_id: str,
    text: str,
    *,
    topic: str,
    summary_path: str | None = None,
    evidence_path: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": memory_id,
        "layer": "domain",
        "scope": "domain:v225-active-support",
        "topic": topic,
        "text": text,
        "source": "synthetic",
        "confidence": "high",
        "support_count": 2,
        "derived_from": [summary_path] if summary_path else [],
        "evidence_refs": (
            [{"path": evidence_path, "quote_id": "ev_v225_001"}] if evidence_path else []
        ),
        "raw_refs": [{"path": "records/v225-synthetic.jsonl", "anchor": f"message:{memory_id}"}],
        "supersedes": [],
        "superseded_by": None,
    }
    return row


def write_synthetic_archive(memory_repo: Path) -> dict[str, dict[str, object]]:
    supported_summary, supported_evidence = support_paths("supported")
    wrong_summary, wrong_evidence = support_paths("wrong-active")
    write_support_file(memory_repo / supported_summary, "V2.25 supported active summary")
    write_support_file(memory_repo / supported_evidence, "V2.25 supported active evidence")
    write_support_file(memory_repo / wrong_summary, "V2.25 wrong active summary")
    write_support_file(memory_repo / wrong_evidence, "V2.25 wrong active evidence")

    (memory_repo / "records").mkdir(parents=True, exist_ok=True)
    (memory_repo / "records/v225-synthetic.jsonl").write_text(
        json.dumps(
            {
                "message": (
                    "Synthetic raw source anchor for privacy checks; "
                    f"{RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}"
                )
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = [
        memory_row(
            "mem_v225_supported_active",
            SUPPORTED_TEXT,
            topic="v225-supported",
            summary_path=supported_summary,
            evidence_path=supported_evidence,
        ),
        memory_row(
            "mem_v225_wrong_active_hit",
            WRONG_ACTIVE_TEXT,
            topic="v225-wrong-active",
            summary_path=wrong_summary,
            evidence_path=wrong_evidence,
        ),
        memory_row(
            "mem_v225_unsupported_active",
            UNSUPPORTED_TEXT,
            topic="v225-unsupported-active",
        ),
    ]
    (memory_repo / "index").mkdir(parents=True, exist_ok=True)
    (memory_repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {str(row["memory_id"]): row for row in rows}


def missing_node(memory_id: str) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "layer": "domain",
        "scope": "domain:v225-active-support",
        "topic": "v225-expected-missing",
        "text": "synthetic expected node omitted from archive index",
    }


def case_specs(rows_by_id: dict[str, dict[str, object]]) -> list[CaseSpec]:
    return [
        CaseSpec(
            SUPPORTED_CASE,
            "v225alpha supported durable anchor",
            rows_by_id["mem_v225_supported_active"],
            True,
        ),
        CaseSpec(
            WRONG_ACTIVE_HIT_CASE,
            "v225wronghit supported alternate",
            missing_node("mem_v225_expected_missing_wrong_active"),
            False,
            required_nonzero_counters=("active_support_wrong_active_hit_count",),
            required_zero_counters=(
                "active_support_expected_node_missing_count",
                "active_support_package_unsupported_count",
            ),
        ),
        CaseSpec(
            PACKAGE_UNSUPPORTED_CASE,
            "v225unsupported drilldown",
            rows_by_id["mem_v225_unsupported_active"],
            False,
            required_nonzero_counters=("active_support_package_unsupported_count",),
            required_zero_counters=(
                "active_support_expected_node_missing_count",
                "active_support_wrong_active_hit_count",
            ),
        ),
        CaseSpec(
            MISSING_UNSUPPORTED_CASE,
            "v225absent qxmissing nohit",
            missing_node("mem_v225_expected_missing_unsupported"),
            False,
            required_nonzero_counters=(
                "active_support_expected_node_missing_count",
                "active_support_package_unsupported_count",
            ),
            required_zero_counters=("active_support_wrong_active_hit_count",),
        ),
    ]


def run_context_package(memory_repo: Path, spec: CaseSpec) -> str:
    result = run_command(
        [
            sys.executable,
            str(memory_repo / "tools/search_memory.py"),
            spec.query,
            "--repo",
            str(memory_repo),
            "--limit",
            "5",
            "--depth",
            "evidence",
            "--context-json",
        ],
        "search_context_package",
        cwd=memory_repo,
    )
    return result.stdout


def load_context_package(raw_package: str) -> tuple[dict[str, Any] | None, bool, str]:
    try:
        payload = json.loads(raw_package)
    except json.JSONDecodeError:
        return None, False, ""
    if not isinstance(payload, dict):
        return None, False, ""
    report_kind = payload.get("report_kind")
    if not isinstance(report_kind, str):
        return None, False, ""
    return payload, report_kind == CONTEXT_REPORT_KIND, report_kind


def run_case(memory_repo: Path, spec: CaseSpec) -> CaseResult:
    package_text = run_context_package(memory_repo, spec)
    package, parse_success, report_kind = load_context_package(package_text)
    supported, counters = shadow.active_support_diagnosis(package if parse_success else None, spec.expected_node)
    return CaseResult(
        spec=spec,
        parse_success=parse_success,
        report_kind=report_kind,
        supported=supported,
        counters=counters,
        package_text=package_text,
    )


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def case_passed(result: CaseResult) -> bool:
    if not result.parse_success or result.report_kind != CONTEXT_REPORT_KIND:
        return False
    if result.supported != result.spec.expected_supported:
        return False
    for counter in result.spec.required_nonzero_counters:
        if result.counters.get(counter, 0) <= 0:
            return False
    for counter in result.spec.required_zero_counters:
        if result.counters.get(counter, 0) != 0:
            return False
    if result.spec.expected_supported and any(result.counters.values()):
        return False
    return True


def privacy_leak_count(results: list[CaseResult], report: dict[str, object]) -> int:
    rendered_packages = "".join(result.package_text for result in results)
    rendered_report = json.dumps(report, sort_keys=True)
    marker_count = sum(1 for marker in LEAK_MARKERS if marker in rendered_packages or marker in rendered_report)
    memory_id_report_count = 1 if "mem_v225_" in rendered_report else 0
    return marker_count + memory_id_report_count


def build_report(results: list[CaseResult]) -> dict[str, object]:
    case_pass_count = sum(1 for result in results if case_passed(result))
    parse_success_count = sum(1 for result in results if result.parse_success)
    expected_missing_reproductions = sum(
        1 for result in results if result.counters.get("active_support_expected_node_missing_count", 0) > 0
    )
    package_unsupported_reproductions = sum(
        1 for result in results if result.counters.get("active_support_package_unsupported_count", 0) > 0
    )
    wrong_active_reproductions = sum(
        1 for result in results if result.counters.get("active_support_wrong_active_hit_count", 0) > 0
    )
    case_outcomes = {
        result.spec.case_id: {
            "passed": case_passed(result),
            "parse_success": result.parse_success,
            "supported": result.supported,
            "primary_failure_counters": {
                key: result.counters.get(key, 0)
                for key in (
                    "active_support_expected_node_missing_count",
                    "active_support_package_unsupported_count",
                    "active_support_wrong_active_hit_count",
                )
            },
        }
        for result in results
    }
    metrics: dict[str, object] = {
        "active_support_synthetic_case_pass_rate": safe_rate(case_pass_count, len(results)),
        "active_support_expected_node_missing_reproduction_count": expected_missing_reproductions,
        "active_support_package_unsupported_reproduction_count": package_unsupported_reproductions,
        "active_support_wrong_active_hit_reproduction_count": wrong_active_reproductions,
        "active_support_context_package_parse_success_rate": safe_rate(parse_success_count, len(results)),
        "active_support_repair_success_rate": safe_rate(case_pass_count, len(results)),
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "diagnosis_source": "active_support_diagnosis",
        },
        "case_outcomes": case_outcomes,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "context_packages_rendered": False,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "memory_ids_rendered": False,
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "local_private_paths_rendered": False,
        },
        "claim_boundary": (
            "public synthetic active-support diagnosis only; not private archive correctness, "
            "private content repair, ranking overhaul, vector search, ontology discovery, "
            "or live LLM answer quality"
        ),
    }
    metrics["privacy_leak_count"] = privacy_leak_count(results, report)
    if (
        metrics["active_support_synthetic_case_pass_rate"] != 1.0
        or metrics["active_support_context_package_parse_success_rate"] != 1.0
        or metrics["active_support_expected_node_missing_reproduction_count"] != 1
        or metrics["active_support_package_unsupported_reproduction_count"] != 2
        or metrics["active_support_wrong_active_hit_reproduction_count"] != 1
        or metrics["active_support_repair_success_rate"] != 1.0
        or metrics["privacy_leak_count"] != 0
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    memory_repo = setup_packaged_archive(root)
    rows_by_id = write_synthetic_archive(memory_repo)
    return build_report([run_case(memory_repo, spec) for spec in case_specs(rows_by_id)])


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-active-support-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-active-support-", dir=parent))
    return root, None, root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent directory for generated clean-room artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_work_root(args.work_dir)
        report = run_gate(root)
    except GateFailure as failure:
        print(
            json.dumps(
                {
                    "report_kind": REPORT_KIND,
                    "status": "failed",
                    "failures": [failure.to_report()],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if temp is not None:
            temp.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
