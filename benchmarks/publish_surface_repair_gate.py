#!/usr/bin/env python3
"""Gate reusable publish-surface repair before archive sync."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "publish_surface_repair_gate"


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
class GateCase:
    name: str
    kind: str
    expect_repair_success: bool


def run_command(
    command: list[str],
    stage: str,
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def setup_archive(parent: Path, name: str) -> Path:
    memory_repo = parent / name / "agent-memory"
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        f"{name}:setup",
    )
    return memory_repo


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_session(memory_repo: Path, case: GateCase) -> dict[str, str]:
    session_dir = memory_repo / "sessions/2026/07/08/synthetic"
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = "sessions/2026/07/08/synthetic/summary.md"
    evidence_path = "sessions/2026/07/08/synthetic/evidence.md"
    source_map_path = "sessions/2026/07/08/synthetic/source-map.json"
    (memory_repo / summary_path).write_text(
        "# Synthetic Summary\n\nDurable launch decision remains current.\n",
        encoding="utf-8",
    )
    (memory_repo / evidence_path).write_text(
        "# Synthetic Evidence\n\n- ev_001: Durable launch decision remains current.\n",
        encoding="utf-8",
    )
    write_json(
        memory_repo / source_map_path,
        {
            "summary_path": summary_path,
            "evidence_path": evidence_path,
            "source_map_path": source_map_path,
        },
    )
    base_meta: dict[str, object] = {
        "session_id": f"synthetic-{case.name}",
        "source_agent": "synthetic",
        "project": "synthetic-project",
        "project_path": "/tmp/synthetic-project",
        "archive_scope": "/tmp/synthetic-project",
        "source_partition": "/tmp/synthetic-project",
        "source_updated_at": "2026-07-08T00:00:00Z",
        "archive_status": "summarized",
        "redaction_status": "redacted",
        "summary_path": summary_path,
        "evidence_path": evidence_path,
        "source_map_path": source_map_path,
        "user_intent": "Preserve durable synthetic publish-surface repair behavior.",
        "decisions": [],
        "unresolved_tasks": [],
        "explicit_memories": [],
    }
    expected_durable_summary = "Durable launch decision remains current."
    if case.kind == "repairable":
        base_meta.update(
            {
                "summary": (
                    "Durable launch decision remains current. "
                    "Command Status: dry-run would push after commit PRIVATE_REPAIR_SENTINEL."
                ),
                "reusable_facts": [
                    "Keep package-first recall as the current durable contract.",
                    "Approval policy is currently never. PRIVATE_FACT_SENTINEL",
                    "raw source path: /Users/example/private/source-record.jsonl",
                ],
                "tags": ["package-first", "unit tests PRIVATE_TAG_SENTINEL"],
                "raw_prompts": ["raw prompt: PRIVATE_RAW_PROMPT_SENTINEL"],
            }
        )
    elif case.kind == "fallback_summary":
        expected_durable_summary = "Preserve durable synthetic publish-surface repair behavior."
        base_meta.update(
            {
                "summary": "Command Status: dry-run would push after commit PRIVATE_SUMMARY_FALLBACK_SENTINEL",
                "reusable_facts": [
                    "Keep package-first recall as the current durable contract.",
                ],
                "tags": ["package-first"],
            }
        )
    elif case.kind == "ambiguous":
        base_meta.update(
            {
                "user_intent": "",
                "summary": (
                    "Durable launch decision remains current while command status dry-run would push after commit"
                ),
                "reusable_facts": [],
                "tags": ["package-first"],
            }
        )
    else:
        raise AssertionError(f"unexpected case kind: {case.kind}")
    write_json(session_dir / "meta.json", base_meta)
    return {
        "meta_path": "sessions/2026/07/08/synthetic/meta.json",
        "durable_summary": expected_durable_summary,
        "durable_fact": "Keep package-first recall as the current durable contract.",
        "durable_tag": "package-first",
    }


def write_malformed_meta(memory_repo: Path) -> None:
    meta = memory_repo / "sessions/2026/07/08/malformed/meta.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text('{"summary": "Command Status: dry-run would push"', encoding="utf-8")


def rebuild_indexes(memory_repo: Path, stage: str) -> None:
    empty_source = memory_repo / ".empty-source"
    empty_source.mkdir(exist_ok=True)
    run_command(
        [
            sys.executable,
            str(memory_repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(empty_source),
            "--project-path",
            str(memory_repo),
            "--max-records",
            "0",
        ],
        stage,
        cwd=memory_repo,
    )


def run_audit(memory_repo: Path, stage: str, *, expect_pass: bool) -> dict[str, object]:
    result = run_command(
        [sys.executable, str(memory_repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(memory_repo)],
        stage,
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(stage, "invalid_json", result.returncode) from exc
    status = report.get("status")
    if expect_pass and result.returncode != 0:
        raise GateFailure(stage, f"expected_pass_got_{status}", result.returncode)
    if not expect_pass and result.returncode == 0:
        raise GateFailure(stage, f"expected_failure_got_{status}", result.returncode)
    return report


def run_repair(memory_repo: Path, stage: str, *, apply: bool, expect_success: bool) -> dict[str, object]:
    script = memory_repo / "tools/repair_publish_surfaces.py"
    result = run_command(
        [
            sys.executable,
            str(script),
            "--memory-repo",
            str(memory_repo),
            *(["--apply"] if apply else []),
        ],
        stage,
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(stage, "invalid_json", result.returncode) from exc
    combined = result.stdout + result.stderr
    private_markers = (
        "PRIVATE_REPAIR_SENTINEL",
        "PRIVATE_SUMMARY_FALLBACK_SENTINEL",
        "PRIVATE_FACT_SENTINEL",
        "PRIVATE_TAG_SENTINEL",
        "PRIVATE_RAW_PROMPT_SENTINEL",
        "/Users/example/private/source-record.jsonl",
    )
    if any(marker in combined for marker in private_markers):
        raise GateFailure(stage, "rendered_private_text", result.returncode)
    if expect_success and result.returncode != 0:
        raise GateFailure(stage, "expected_success", result.returncode)
    if not expect_success and result.returncode == 0:
        raise GateFailure(stage, "expected_fail_closed", result.returncode)
    return report


def assert_meta_preserved(memory_repo: Path, expected: dict[str, str]) -> None:
    meta = json.loads((memory_repo / expected["meta_path"]).read_text(encoding="utf-8"))
    rendered = json.dumps(meta, sort_keys=True)
    for value in ("durable_summary", "durable_fact", "durable_tag"):
        if expected[value] not in rendered:
            raise GateFailure("repairable:meta", f"missing_{value}")
    for marker in (
        "PRIVATE_REPAIR_SENTINEL",
        "PRIVATE_FACT_SENTINEL",
        "PRIVATE_TAG_SENTINEL",
        "PRIVATE_RAW_PROMPT_SENTINEL",
        "/Users/example/private/source-record.jsonl",
        "dry-run",
        "Approval policy",
        "unit tests",
    ):
        if marker in rendered:
            raise GateFailure("repairable:meta", "noise_not_removed")


def run_case(root: Path, case: GateCase) -> dict[str, object]:
    memory_repo = setup_archive(root, case.name)
    if case.kind == "malformed":
        write_malformed_meta(memory_repo)
        report = run_repair(memory_repo, f"{case.name}:dry-run", apply=False, expect_success=False)
        metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
        if int(metrics.get("malformed_meta_count", 0)) != 1:
            raise GateFailure(case.name, "missing_malformed_count")
        return {
            "case": case.name,
            "repair_success": False,
            "fail_closed": True,
            "malformed_fail_closed": True,
            "ambiguous_fail_closed": False,
            "pre_repair_failed": False,
            "post_repair_passed": False,
            "durable_preserved": False,
            "privacy_leak_count": int(report.get("privacy_leak_count", 0) or 0),
        }

    expected = write_session(memory_repo, case)
    rebuild_indexes(memory_repo, f"{case.name}:rebuild-before")
    run_audit(memory_repo, f"{case.name}:pre-audit", expect_pass=False)
    dry_report = run_repair(memory_repo, f"{case.name}:dry-run", apply=False, expect_success=case.expect_repair_success)
    apply_report = run_repair(memory_repo, f"{case.name}:apply", apply=True, expect_success=case.expect_repair_success)
    if case.expect_repair_success:
        run_audit(memory_repo, f"{case.name}:post-audit", expect_pass=True)
        assert_meta_preserved(memory_repo, expected)
    else:
        run_audit(memory_repo, f"{case.name}:post-audit", expect_pass=False)
    metrics = apply_report.get("metrics", {}) if isinstance(apply_report.get("metrics"), dict) else {}
    dry_metrics = dry_report.get("metrics", {}) if isinstance(dry_report.get("metrics"), dict) else {}
    return {
        "case": case.name,
        "repair_success": case.expect_repair_success,
        "fail_closed": not case.expect_repair_success,
        "malformed_fail_closed": False,
        "ambiguous_fail_closed": int(metrics.get("ambiguous_scalar_count", 0)) > 0,
        "pre_repair_failed": True,
        "post_repair_passed": case.expect_repair_success,
        "durable_preserved": case.expect_repair_success,
        "dry_run_repairable_fields": int(dry_metrics.get("fields_with_repair", 0) or 0),
        "privacy_leak_count": int(apply_report.get("privacy_leak_count", 0) or 0),
    }


def build_report(case_results: list[dict[str, object]]) -> dict[str, object]:
    metrics = {
        "pre_repair_readiness_failure_count": sum(1 for case in case_results if case["pre_repair_failed"]),
        "post_repair_readiness_pass_count": sum(1 for case in case_results if case["post_repair_passed"]),
        "repairable_apply_success_count": sum(1 for case in case_results if case["repair_success"]),
        "durable_fact_preservation_count": sum(1 for case in case_results if case["durable_preserved"]),
        "ambiguous_fail_closed_count": sum(1 for case in case_results if case["ambiguous_fail_closed"]),
        "malformed_fail_closed_count": sum(1 for case in case_results if case["malformed_fail_closed"]),
        "privacy_leak_count": sum(int(case["privacy_leak_count"]) for case in case_results),
    }
    passed = (
        metrics["pre_repair_readiness_failure_count"] == 3
        and metrics["post_repair_readiness_pass_count"] == 2
        and metrics["repairable_apply_success_count"] == 2
        and metrics["durable_fact_preservation_count"] == 2
        and metrics["ambiguous_fail_closed_count"] == 1
        and metrics["malformed_fail_closed_count"] == 1
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "synthetic packaged publish-surface repair only; not memory quality, "
            "ranking quality, LLM answer quality, GitHub availability, vector search, or ontology discovery"
        ),
        "metrics": metrics,
        "cases": case_results,
        "privacy": {
            "aggregate_only": True,
            "snippets_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }


def run_gate(root: Path) -> dict[str, object]:
    cases = [
        GateCase("repairable_metadata_noise", "repairable", True),
        GateCase("fallback_summary_metadata_noise", "fallback_summary", True),
        GateCase("ambiguous_scalar_noise", "ambiguous", False),
        GateCase("malformed_metadata", "malformed", False),
    ]
    return build_report([run_case(root, case) for case in cases])


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-publish-repair-") as tmpdir:
            report = run_gate(Path(tmpdir))
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": exc.to_report(),
            "privacy": {
                "aggregate_only": True,
                "snippets_rendered": False,
                "memory_text_rendered": False,
                "source_paths_rendered": False,
                "raw_refs_rendered": False,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
