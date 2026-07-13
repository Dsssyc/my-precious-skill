#!/usr/bin/env python3
"""Gate bounded selected-record preparation in the scheduled updater path."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER_SOURCE = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
V239_GATE = REPO_ROOT / "benchmarks/scheduled_update_throughput_gate.py"
V238_GATE = REPO_ROOT / "benchmarks/scheduled_update_single_writer_gate.py"
BASELINE_COMMIT = "7fec1cec4b04422aae67bfa4cdb62509a37c10a7"
UPDATER_RELATIVE_PATH = "templates/agent-memory-repo/tools/update_memory_archive.py"
CONSOLIDATION_RELATIVE_PATH = "templates/agent-memory-repo/tools/memory_consolidation.py"
REPORT_KIND = "selected_record_materialization_gate"
CONTENT_MARKER = "MATERIALIZATION_OPERATION_SENTINEL"
SECRET_TOKEN = "ghp_" + "SYNTHETICMATERIALIZATIONTOKEN1234567890"
PARITY_ROOTS = ("sessions", "memories", "index", "daily", "INDEX.md")


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load updater module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def baseline_updater(path: Path) -> None:
    for relative_path, target in (
        (UPDATER_RELATIVE_PATH, path),
        (CONSOLIDATION_RELATIVE_PATH, path.parent / "memory_consolidation.py"),
    ):
        result = subprocess.run(
            ["git", "show", f"{BASELINE_COMMIT}:{relative_path}"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError("V2.39 baseline source unavailable")
        target.write_bytes(result.stdout)


def archive_snapshot(memory_repo: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative in PARITY_ROOTS:
        root = memory_repo / relative
        if root.is_file():
            snapshot[relative] = hashlib.sha256(root.read_bytes()).hexdigest()
        elif root.is_dir():
            for path in sorted(child for child in root.rglob("*") if child.is_file()):
                snapshot[path.relative_to(memory_repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def source_anchor_ids(memory_repo: Path) -> list[str]:
    anchors: list[str] = []
    for path in sorted((memory_repo / "sessions").glob("**/source-map.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("evidence_source_anchors", []):
            value = row.get("source_anchor_id") if isinstance(row, dict) else None
            if isinstance(value, str):
                anchors.append(value)
    return anchors


def setup_case(root: Path, *, secret: bool = False, two_records: bool = False) -> tuple[Path, Path, Path]:
    memory_repo = root / "agent-memory"
    source_dir = root / "source-records"
    project_path = root / "project"
    (memory_repo / "index").mkdir(parents=True)
    (memory_repo / "sessions").mkdir()
    source_dir.mkdir()
    project_path.mkdir()
    content = f"Decision: {CONTENT_MARKER} preserves deterministic selected-record output."
    if secret:
        content += f" Authorization: Bearer {SECRET_TOKEN}"
    count = 2 if two_records else 1
    for ordinal in range(count):
        (source_dir / f"record-{ordinal}.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": f"2026-07-13T0{ordinal + 6}:00:00Z",
                    "cwd": str(project_path.resolve()),
                    "role": "user",
                    "content": content,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return memory_repo, source_dir, project_path


def inventory_payload(module: ModuleType, source_dir: Path) -> str:
    rows = []
    for path in sorted(source_dir.glob("*.jsonl")):
        raw = path.read_bytes()
        stat = path.stat()
        row: dict[str, object] = {
            "relative_path": path.relative_to(source_dir).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if int(module.SOURCE_INVENTORY_REPORT_VERSION) >= 2:
            row["source_updated_at"] = json.loads(raw)["timestamp"]
        rows.append(row)
    return json.dumps(
        {
            "report_kind": module.SOURCE_INVENTORY_REPORT_KIND,
            "report_version": module.SOURCE_INVENTORY_REPORT_VERSION,
            "records": rows,
        },
        sort_keys=True,
    )


def invoke(
    module: ModuleType,
    memory_repo: Path,
    source_dir: Path,
    project_path: Path,
    *,
    use_inventory: bool,
    allow_redacted_secrets: bool = False,
    payload: str | None = None,
) -> tuple[int, str]:
    argv = [
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--require-project-metadata",
    ]
    if use_inventory:
        argv.extend(("--source-inventory-stdin", "--defer-global-rebuild"))
    if allow_redacted_secrets:
        argv.append("--allow-redacted-secrets")
    stdout = io.StringIO()
    stderr = io.StringIO()
    original_stdin = sys.stdin
    original_now = module.utc_now
    module.utc_now = lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    sys.stdin = io.StringIO(payload if payload is not None else inventory_payload(module, source_dir))
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = int(module.main(argv))
            if returncode == 0 and use_inventory:
                module.main(["--memory-repo", str(memory_repo), "--finalize-archive"])
    finally:
        sys.stdin = original_stdin
        module.utc_now = original_now
    return returncode, stdout.getvalue() + stderr.getvalue()


def operation_case(module: ModuleType, root: Path) -> tuple[dict[str, float], dict[str, str], list[str], str]:
    memory_repo, source_dir, project_path = setup_case(root)
    source_path = next(source_dir.glob("*.jsonl")).resolve()
    payload = inventory_payload(module, source_dir)
    counters = {"source_reads": 0, "redactions": 0, "json_decodes": 0}
    original_read_bytes = Path.read_bytes
    original_sha256_file = module.sha256_file
    original_redact = module.redact_text
    original_json_loads = module.json.loads

    def counted_read_bytes(path: Path) -> bytes:
        if path.resolve() == source_path:
            counters["source_reads"] += 1
        return original_read_bytes(path)

    def counted_sha256_file(path: Path) -> str:
        if path.resolve() == source_path:
            counters["source_reads"] += 1
        return original_sha256_file(path)

    def counted_redact(text: str):
        if CONTENT_MARKER in text:
            counters["redactions"] += 1
        return original_redact(text)

    def counted_json_loads(value, *args, **kwargs):
        source_decode_callers = {
            "analyze_selected_jsonl",
            "iter_source_json_values",
            "jsonl_contains_value",
            "jsonl_events_with_locators",
        }
        caller = sys._getframe(1).f_code.co_name
        if (
            caller in source_decode_callers
            and isinstance(value, (str, bytes, bytearray))
            and CONTENT_MARKER in str(value)
        ):
            counters["json_decodes"] += 1
        return original_json_loads(value, *args, **kwargs)

    Path.read_bytes = counted_read_bytes
    module.sha256_file = counted_sha256_file
    module.redact_text = counted_redact
    module.json.loads = counted_json_loads
    try:
        returncode, output = invoke(
            module,
            memory_repo,
            source_dir,
            project_path,
            use_inventory=True,
            payload=payload,
        )
    finally:
        Path.read_bytes = original_read_bytes
        module.sha256_file = original_sha256_file
        module.redact_text = original_redact
        module.json.loads = original_json_loads
    if returncode != 0:
        counters = {key: -1 for key in counters}
    return (
        {key: float(value) for key, value in counters.items()},
        archive_snapshot(memory_repo),
        source_anchor_ids(memory_repo),
        output,
    )


def direct_case(module: ModuleType, root: Path) -> tuple[dict[str, str], str]:
    memory_repo, source_dir, project_path = setup_case(root)
    returncode, output = invoke(module, memory_repo, source_dir, project_path, use_inventory=False)
    return (archive_snapshot(memory_repo) if returncode == 0 else {}, output)


def secret_case(module: ModuleType, root: Path) -> tuple[bool, dict[str, str], str]:
    refuse_root = root / "refuse"
    memory_repo, source_dir, project_path = setup_case(refuse_root, secret=True)
    payload = inventory_payload(module, source_dir)
    refused, refused_output = invoke(
        module,
        memory_repo,
        source_dir,
        project_path,
        use_inventory=True,
        payload=payload,
    )
    no_refusal_mutation = not list((memory_repo / "sessions").glob("**/meta.json"))

    allow_root = root / "allow"
    memory_repo, source_dir, project_path = setup_case(allow_root, secret=True)
    allowed, allowed_output = invoke(
        module,
        memory_repo,
        source_dir,
        project_path,
        use_inventory=True,
        allow_redacted_secrets=True,
    )
    return (
        refused != 0 and no_refusal_mutation and allowed == 0,
        archive_snapshot(memory_repo),
        refused_output + allowed_output,
    )


def mutation_case(module: ModuleType, root: Path, *, two_records: bool) -> tuple[bool, str]:
    memory_repo, source_dir, project_path = setup_case(root, two_records=two_records)
    payload = inventory_payload(module, source_dir)
    target = sorted(source_dir.glob("*.jsonl"))[-1]
    target.write_text(target.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    returncode, output = invoke(
        module,
        memory_repo,
        source_dir,
        project_path,
        use_inventory=True,
        payload=payload,
    )
    untouched = not list((memory_repo / "sessions").glob("**/meta.json"))
    return returncode != 0 and untouched, output


def gate_rate(path: Path) -> tuple[float, str]:
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {}
    return (1.0 if result.returncode == 0 and report.get("status") == "passed" else 0.0, result.stdout + result.stderr)


def raw_payload_retention_count(module: ModuleType) -> int:
    prepared_type = getattr(module, "PreparedArchiveRecord", None)
    if prepared_type is None:
        return 1
    forbidden = {"raw", "raw_bytes", "source_bytes", "source_text", "redacted_text", "content"}
    return len(forbidden.intersection(field.name for field in fields(prepared_type)))


def privacy_hits(outputs: list[str], root: Path) -> int:
    markers = (str(root), SECRET_TOKEN)
    return sum(marker in output for output in outputs for marker in markers)


def build_report(root: Path) -> dict[str, object]:
    baseline_path = root / "v239_update_memory_archive.py"
    baseline_updater(baseline_path)
    baseline = load_module(baseline_path, "v239_update_memory_archive")
    candidate = load_module(UPDATER_SOURCE, "v240_update_memory_archive")

    operation_root = root / "operation"
    baseline_ops, baseline_snapshot, baseline_anchors, baseline_output = operation_case(baseline, operation_root)
    shutil.rmtree(operation_root)
    candidate_ops, candidate_snapshot, candidate_anchors, candidate_output = operation_case(candidate, operation_root)

    direct_root = root / "direct"
    baseline_direct, baseline_direct_output = direct_case(baseline, direct_root)
    shutil.rmtree(direct_root)
    candidate_direct, candidate_direct_output = direct_case(candidate, direct_root)

    secret_root = root / "secret"
    baseline_secret_ok, baseline_secret_snapshot, baseline_secret_output = secret_case(baseline, secret_root)
    shutil.rmtree(secret_root)
    candidate_secret_ok, candidate_secret_snapshot, candidate_secret_output = secret_case(candidate, secret_root)
    mutation_ok, mutation_output = mutation_case(candidate, root / "candidate-mutation", two_records=False)
    prepare_before_mutation, prepare_output = mutation_case(candidate, root / "candidate-prepare", two_records=True)
    v239_rate, v239_output = gate_rate(V239_GATE)
    v238_rate, v238_output = gate_rate(V238_GATE)
    outputs = [
        baseline_output,
        candidate_output,
        baseline_direct_output,
        candidate_direct_output,
        baseline_secret_output,
        candidate_secret_output,
        mutation_output,
        prepare_output,
        v239_output,
        v238_output,
    ]
    baseline_work = sum(baseline_ops.values())
    candidate_work = sum(candidate_ops.values())
    work_reduction = 1.0 - (candidate_work / baseline_work) if baseline_work > 0 else -1.0
    metrics: dict[str, int | float] = {
        "selected_record_source_read_amplification": candidate_ops["source_reads"],
        "selected_record_redaction_amplification": candidate_ops["redactions"],
        "selected_record_json_decode_amplification": candidate_ops["json_decodes"],
        "selected_record_preparation_before_mutation_rate": 1.0 if prepare_before_mutation else 0.0,
        "selected_record_raw_payload_retention_count": raw_payload_retention_count(candidate),
        "selected_record_output_parity_rate": 1.0 if baseline_snapshot == candidate_snapshot else 0.0,
        "selected_record_source_anchor_parity_rate": 1.0 if baseline_anchors == candidate_anchors else 0.0,
        "selected_record_secret_policy_parity_rate": 1.0
        if baseline_secret_ok and candidate_secret_ok and baseline_secret_snapshot == candidate_secret_snapshot
        else 0.0,
        "selected_record_mutation_rejection_rate": 1.0 if mutation_ok else 0.0,
        "direct_cli_regression_pass_rate": 1.0 if baseline_direct == candidate_direct else 0.0,
        "v239_throughput_regression_pass_rate": v239_rate,
        "v238_single_writer_regression_pass_rate": v238_rate,
        "synthetic_materialization_work_reduction_rate": work_reduction,
        "privacy_leak_count": privacy_hits(outputs, root),
    }
    passed = (
        metrics["selected_record_source_read_amplification"] == 1.0
        and metrics["selected_record_redaction_amplification"] == 1.0
        and metrics["selected_record_json_decode_amplification"] <= 2.0
        and metrics["selected_record_preparation_before_mutation_rate"] == 1.0
        and metrics["selected_record_raw_payload_retention_count"] == 0
        and metrics["selected_record_output_parity_rate"] == 1.0
        and metrics["selected_record_source_anchor_parity_rate"] == 1.0
        and metrics["selected_record_secret_policy_parity_rate"] == 1.0
        and metrics["selected_record_mutation_rejection_rate"] == 1.0
        and metrics["direct_cli_regression_pass_rate"] == 1.0
        and metrics["v239_throughput_regression_pass_rate"] == 1.0
        and metrics["v238_single_writer_regression_pass_rate"] == 1.0
        and metrics["synthetic_materialization_work_reduction_rate"] >= 0.60
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "baseline_metrics": {
            "selected_record_source_read_amplification": baseline_ops["source_reads"],
            "selected_record_redaction_amplification": baseline_ops["redactions"],
            "selected_record_json_decode_amplification": baseline_ops["json_decodes"],
        },
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "source_content_rendered": False,
            "project_names_rendered": False,
            "child_output_rendered": False,
        },
        "claim_boundary": (
            "selected-record scheduled materialization operation counts, output/source-anchor parity, "
            "secret and mutation safety, and V2.38/V2.39 regression only; not private wall-clock "
            "performance, deployment approval, memory quality, ranking, or LLM quality"
        ),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_report(Path(tmpdir))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
