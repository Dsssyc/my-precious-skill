#!/usr/bin/env python3
"""Gate structure-preserving secret redaction for JSON and JSONL sources."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
REPORT_KIND = "structured_redaction_integrity_gate"
COOKIE_SECRET = "session=synthetic-cookie-marker"
BEARER_SECRET = "synthetic.bearer-token"
GITHUB_SECRET = "ghp_" + "A" * 24
OPENAI_SECRET = "sk-" + "b" * 24
SECRET_MARKERS = (COOKIE_SECRET, BEARER_SECRET, GITHUB_SECRET, OPENAI_SECRET)


def load_updater() -> ModuleType:
    spec = importlib.util.spec_from_file_location("structured_redaction_gate_updater", UPDATER)
    if spec is None or spec.loader is None:
        raise RuntimeError("updater_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(UPDATER.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def parse_structured(path: Path, text: str) -> list[object]:
    if path.suffix == ".json":
        return [json.loads(text)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def rate(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 1.0


def valid_structure_metrics(module: ModuleType) -> tuple[dict[str, float], list[str], int]:
    jsonl_rows = [
        {
            "timestamp": "2026-07-23T01:00:00Z",
            "role": "user",
            "payload": {
                "headers": [
                    (
                        f"Cookie: {COOKIE_SECRET}\n"
                        "Narrative remains with escaped separators: \u0085 \u2028 \u2029."
                    ),
                    f"Authorization: Bearer {BEARER_SECRET}",
                ],
                "credentials": {
                    "github": GITHUB_SECRET,
                    "openai": OPENAI_SECRET,
                },
            },
            "ok": True,
        },
        {
            "timestamp": "2026-07-23T01:00:01Z",
            "role": "assistant",
            "content": "Only the first JSONL record contains synthetic secrets.",
            "ok": True,
        },
    ]
    cases = (
        (
            "json_cookie_trailing_field",
            Path("record.json"),
            json.dumps(
                {
                    "message": f"Cookie: {COOKIE_SECRET}",
                    "nested": {"ok": True},
                },
                indent=2,
            )
            + "\n",
            1,
        ),
        (
            "jsonl_nested_multi_record",
            Path("record.jsonl"),
            json.dumps(jsonl_rows[0], separators=(",", ":"))
            + "\n\n"
            + json.dumps(jsonl_rows[1], separators=(",", ":"))
            + "\n",
            1,
        ),
    )
    source_parse_passes = 0
    redacted_parse_passes = 0
    cookie_passes = 0
    jsonl_boundary_passes = 0
    jsonl_case_count = 0
    leak_count = 0
    failed_cases: list[str] = []

    for case_id, path, source, expected_cookie_count in cases:
        try:
            source_values = parse_structured(path, source)
            source_parse_passes += 1
        except (json.JSONDecodeError, TypeError):
            failed_cases.append(case_id)
            continue
        try:
            redacted, counts = module.redact_source_text(path, source)
            redacted_values = parse_structured(path, redacted)
            redacted_parse_passes += 1
        except (json.JSONDecodeError, TypeError, ValueError):
            failed_cases.append(case_id)
            continue

        secrets_absent = all(secret not in redacted for secret in SECRET_MARKERS)
        cookie_ok = counts.get("cookie", 0) == expected_cookie_count
        if case_id == "jsonl_nested_multi_record":
            cookie_ok = cookie_ok and counts == {
                "bearer_token": 1,
                "cookie": 1,
                "github_token": 1,
                "openai_key": 1,
            }
        if secrets_absent and cookie_ok:
            cookie_passes += 1
        else:
            failed_cases.append(case_id)
        leak_count += sum(redacted.count(secret) for secret in SECRET_MARKERS)

        if path.suffix == ".jsonl":
            jsonl_case_count += 1
            source_lines = source.splitlines()
            redacted_lines = redacted.splitlines()
            boundaries_match = (
                len(source_lines) == len(redacted_lines)
                and [not line.strip() for line in source_lines]
                == [not line.strip() for line in redacted_lines]
                and len(source_values) == len(redacted_values)
            )
            if boundaries_match:
                jsonl_boundary_passes += 1
            else:
                failed_cases.append(case_id)

    return (
        {
            "structured_source_parse_success_rate": rate(source_parse_passes, len(cases)),
            "structured_redaction_parse_success_rate": rate(redacted_parse_passes, len(cases)),
            "cookie_redaction_success_rate": rate(cookie_passes, len(cases)),
            "jsonl_boundary_preservation_rate": rate(jsonl_boundary_passes, jsonl_case_count),
        },
        failed_cases,
        leak_count,
    )


def inventory_payload(source: Path, source_updated_at: str) -> str:
    raw = source.read_bytes()
    stat = source.stat()
    return json.dumps(
        {
            "report_kind": "memory_source_inventory",
            "report_version": 2,
            "records": [
                {
                    "relative_path": source.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "source_updated_at": source_updated_at,
                }
            ],
        },
        sort_keys=True,
    )


def invoke_inventory(memory_repo: Path, source_dir: Path, project_path: Path, payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(UPDATER),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--project-path",
            str(project_path),
            "--require-project-metadata",
            "--source-inventory-stdin",
            "--defer-global-rebuild",
            "--allow-redacted-secrets",
            "--report-json",
        ],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def setup_inventory_root(root: Path) -> tuple[Path, Path, Path]:
    memory_repo = root / "agent-memory"
    source_dir = root / "source-records"
    project_path = root / "project"
    (memory_repo / "index").mkdir(parents=True)
    (memory_repo / "sessions").mkdir()
    source_dir.mkdir()
    project_path.mkdir()
    return memory_repo, source_dir, project_path


def selected_record_case(root: Path) -> tuple[bool, int, int]:
    memory_repo, source_dir, project_path = setup_inventory_root(root)
    source = source_dir / "selected.jsonl"
    source.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-23T01:00:00Z",
                "cwd": str(project_path.resolve()),
                "role": "user",
                "content": (
                    "Decision: selected structured records must materialize after redaction. "
                    f"Cookie: {COOKIE_SECRET}\nPreserve this durable detail."
                ),
                "ok": True,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    result = invoke_inventory(
        memory_repo,
        source_dir,
        project_path,
        inventory_payload(source, "2026-07-23T01:00:00Z"),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {}
    metrics = report.get("metrics", {}) if isinstance(report, dict) else {}
    entry_dirs = [path.parent for path in (memory_repo / "sessions").glob("**/meta.json")]
    required_artifacts = {"summary.md", "evidence.md", "meta.json", "source-map.json"}
    artifacts_ok = len(entry_dirs) == 1 and required_artifacts.issubset(
        {path.name for path in entry_dirs[0].iterdir() if path.is_file()}
    )
    structured_outputs_ok = False
    archive_text = ""
    if artifacts_ok:
        json.loads((entry_dirs[0] / "meta.json").read_text(encoding="utf-8"))
        json.loads((entry_dirs[0] / "source-map.json").read_text(encoding="utf-8"))
        archive_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in entry_dirs[0].iterdir()
            if path.is_file()
        )
        structured_outputs_ok = True
    output = result.stdout + result.stderr
    leak_count = sum((archive_text + output).count(secret) for secret in SECRET_MARKERS)
    leak_count += int(str(root) in output)
    source_inventory_invalid_count = int(report.get("reason") == "source_inventory_invalid")
    passed = (
        result.returncode == 0
        and report.get("status") == "updated"
        and metrics.get("records_selected_count") == 1
        and metrics.get("records_processed_count") == 1
        and artifacts_ok
        and structured_outputs_ok
        and leak_count == 0
    )
    return passed, source_inventory_invalid_count, leak_count


def malformed_case(root: Path) -> tuple[bool, int]:
    memory_repo, source_dir, project_path = setup_inventory_root(root)
    source = source_dir / "malformed.jsonl"
    source.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-23T02:00:00Z",
                "cwd": str(project_path.resolve()),
                "role": "user",
                "content": "Decision: malformed source records must fail closed.",
            }
        )
        + "\n{not-json}\n",
        encoding="utf-8",
    )
    result = invoke_inventory(
        memory_repo,
        source_dir,
        project_path,
        inventory_payload(source, "2026-07-23T02:00:00Z"),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {}
    output = result.stdout + result.stderr
    leak_count = int(str(root) in output)
    passed = (
        result.returncode == 2
        and report.get("status") == "blocked"
        and report.get("reason") == "source_inventory_invalid"
        and not list((memory_repo / "sessions").glob("**/meta.json"))
        and leak_count == 0
    )
    return passed, leak_count


def rejected_inventory_case(root: Path, case_id: str) -> tuple[bool, int]:
    memory_repo, source_dir, project_path = setup_inventory_root(root)
    timestamp = "2026-07-23T03:00:00Z"
    if case_id == "automation_source":
        value = {
            "type": "session_meta",
            "timestamp": timestamp,
            "payload": {
                "cwd": str(project_path.resolve()),
                "thread_source": "automation",
            },
        }
    elif case_id == "target_mismatch":
        other_project = root / "other-project"
        other_project.mkdir()
        value = {
            "timestamp": timestamp,
            "cwd": str(other_project.resolve()),
            "role": "user",
            "content": "Decision: target metadata mismatches must fail closed.",
        }
    else:
        raise ValueError("unknown_synthetic_case")
    source = source_dir / f"{case_id}.jsonl"
    source.write_text(json.dumps(value) + "\n", encoding="utf-8")
    result = invoke_inventory(
        memory_repo,
        source_dir,
        project_path,
        inventory_payload(source, timestamp),
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {}
    output = result.stdout + result.stderr
    leak_count = int(str(root) in output)
    passed = (
        result.returncode == 2
        and report.get("status") == "blocked"
        and report.get("reason") == "source_inventory_invalid"
        and not list((memory_repo / "sessions").glob("**/meta.json"))
        and leak_count == 0
    )
    return passed, leak_count


def main() -> int:
    failed_cases: list[str] = []
    try:
        module = load_updater()
        metrics, structure_failures, privacy_leak_count = valid_structure_metrics(module)
        failed_cases.extend(structure_failures)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected_ok, invalid_count, selected_leaks = selected_record_case(root / "selected")
            malformed_ok, malformed_leaks = malformed_case(root / "malformed")
            rejection_results = [
                rejected_inventory_case(root / case_id, case_id)
                for case_id in ("automation_source", "target_mismatch")
            ]
        rejection_pass_count = sum(int(passed) for passed, _ in rejection_results)
        rejection_leaks = sum(leaks for _, leaks in rejection_results)
        metrics.update(
            {
                "selected_record_materialization_success_rate": 1.0 if selected_ok else 0.0,
                "malformed_source_fail_closed_rate": 1.0 if malformed_ok else 0.0,
                "inventory_rejection_boundary_pass_rate": rate(
                    rejection_pass_count,
                    len(rejection_results),
                ),
                "source_inventory_invalid_count": invalid_count,
                "expected_source_inventory_rejection_count": (
                    int(malformed_ok) + rejection_pass_count
                ),
                "privacy_leak_count": (
                    privacy_leak_count
                    + selected_leaks
                    + malformed_leaks
                    + rejection_leaks
                ),
            }
        )
        if not selected_ok:
            failed_cases.append("selected_record_materialization")
        if not malformed_ok:
            failed_cases.append("malformed_source_fail_closed")
        for case_id, (case_passed, _) in zip(
            ("automation_source", "target_mismatch"),
            rejection_results,
        ):
            if not case_passed:
                failed_cases.append(case_id)
    except Exception:
        metrics = {
            "structured_source_parse_success_rate": 0.0,
            "structured_redaction_parse_success_rate": 0.0,
            "cookie_redaction_success_rate": 0.0,
            "jsonl_boundary_preservation_rate": 0.0,
            "selected_record_materialization_success_rate": 0.0,
            "malformed_source_fail_closed_rate": 0.0,
            "inventory_rejection_boundary_pass_rate": 0.0,
            "source_inventory_invalid_count": 1,
            "expected_source_inventory_rejection_count": 0,
            "privacy_leak_count": 0,
        }
        failed_cases.append("gate_execution")

    passed = (
        all(
            metrics[name] == 1.0
            for name in (
                "structured_source_parse_success_rate",
                "structured_redaction_parse_success_rate",
                "cookie_redaction_success_rate",
                "jsonl_boundary_preservation_rate",
                "selected_record_materialization_success_rate",
                "malformed_source_fail_closed_rate",
                "inventory_rejection_boundary_pass_rate",
            )
        )
        and metrics["source_inventory_invalid_count"] == 0
        and metrics["expected_source_inventory_rejection_count"] == 3
        and metrics["privacy_leak_count"] == 0
    )
    report = {
        "report_kind": REPORT_KIND,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "failed_case_ids": sorted(set(failed_cases)),
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "source_content_rendered": False,
        },
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
