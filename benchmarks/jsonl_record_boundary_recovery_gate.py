#!/usr/bin/env python3
"""Gate LF/CRLF JSONL boundaries across inventory, materialization, and replay."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from scheduled_reboot_replay_gate import SyntheticArchive, git, kill_process_group


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "templates/agent-memory-repo/tools/run_memory_updates.py"
UPDATER = REPO_ROOT / "templates/agent-memory-repo/tools/update_memory_archive.py"
REPORT_KIND = "jsonl_record_boundary_recovery_gate"
COOKIE_SECRET = "session=synthetic-jsonl-boundary"
SEPARATORS = ("\u0085", "\u2028", "\u2029")


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def rate(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 1.0


def source_rows(project_path: Path) -> list[dict[str, object]]:
    return [
        {
            "timestamp": "2026-07-23T01:00:00Z",
            "cwd": str(project_path.resolve()),
            "role": "user",
            "content": (
                f"Decision: physical JSONL records retain A{SEPARATORS[0]}B"
                f"{SEPARATORS[1]}C{SEPARATORS[2]}D. Cookie: {COOKIE_SECRET}"
            ),
        },
        {
            "timestamp": "2026-07-23T01:00:01Z",
            "cwd": str(project_path.resolve()),
            "role": "assistant",
            "content": "Second synthetic physical record.",
        },
    ]


def render_jsonl(rows: list[dict[str, object]], newline: str) -> str:
    encoded = [
        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ]
    return encoded[0] + newline + newline + encoded[1] + newline


def inventory_payload(source: Path, source_updated_at: str) -> str:
    raw = source.read_bytes()
    file_stat = source.stat()
    return json.dumps(
        {
            "report_kind": "memory_source_inventory",
            "report_version": 2,
            "records": [
                {
                    "relative_path": source.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "size": file_stat.st_size,
                    "mtime_ns": file_stat.st_mtime_ns,
                    "source_updated_at": source_updated_at,
                }
            ],
        },
        sort_keys=True,
    )


def parse_report(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def direct_inventory_cases(
    root: Path,
    runner: ModuleType,
    updater: ModuleType,
) -> tuple[int, int, int, int, int]:
    accepted = 0
    physical_counts = 0
    crlf_passes = 0
    invalid_count = 0
    privacy_leaks = 0
    for case_id, newline in (("lf", "\n"), ("crlf", "\r\n")):
        case_root = root / case_id
        source_dir = case_root / "source"
        project_path = case_root / "project"
        source_dir.mkdir(parents=True)
        project_path.mkdir()
        rows = source_rows(project_path)
        source_text = render_jsonl(rows, newline)
        source = source_dir / "records.jsonl"
        source.write_text(source_text, encoding="utf-8")
        try:
            inventory = runner.build_source_inventory(source_dir, ("*.jsonl",))
            runner_values = list(runner.iter_json_values(source, source_text))
            updater_values = list(updater.iter_source_json_values(source, source_text))
            redacted, counts = updater.redact_source_text(source, source_text)
            events, selected_values = updater.analyze_selected_jsonl(source_text, redacted)
            user_events = [event for event in events if event.kind == "user"]
            assistant_events = [event for event in events if event.kind == "assistant"]
            valid = (
                len(inventory) == 1
                and inventory[0].source_updated_at == "2026-07-23T01:00:01Z"
                and runner_values == rows
                and updater_values == rows
                and selected_values == rows
                and bool(user_events)
                and bool(assistant_events)
                and all(event.line_number == 1 for event in user_events)
                and all(event.line_number == 3 for event in assistant_events)
                and counts == {"cookie": 1}
                and all(separator in rows[0]["content"] for separator in SEPARATORS)
                and COOKIE_SECRET not in redacted
            )
            accepted += int(valid)
            physical_counts += int(
                len(runner.jsonl_physical_lines(source_text)) == 3
                and len(updater.jsonl_physical_lines(source_text)) == 3
                and len([line for line in source_text.split("\n") if line.strip()]) == 2
            )
            if case_id == "crlf":
                crlf_passes += int(valid)
            privacy_leaks += redacted.count(COOKIE_SECRET)
        except runner.SourceInventoryError:
            invalid_count += 1
        except updater.SourceInventoryError:
            invalid_count += 1
    return accepted, physical_counts, crlf_passes, invalid_count, privacy_leaks


def inventory_worker_case(root: Path) -> tuple[bool, int, int]:
    source_dir = root / "source"
    project_path = root / "project"
    manifest_dir = root / "manifest"
    source_dir.mkdir(parents=True)
    project_path.mkdir()
    manifest_dir.mkdir(mode=0o700)
    source = source_dir / "records.jsonl"
    source.write_text(render_jsonl(source_rows(project_path), "\r\n"), encoding="utf-8")
    manifest = manifest_dir / "inventory.json"
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--source-dir",
            str(source_dir),
            "--inventory-worker-manifest",
            str(manifest),
            "--pattern",
            "*.jsonl",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    output = result.stdout + result.stderr
    passed = (
        result.returncode == 0
        and payload.get("report_kind") == "memory_source_inventory_manifest"
        and isinstance(payload.get("records"), list)
        and len(payload["records"]) == 1
    )
    invalid_count = int("source_inventory_invalid" in output)
    privacy_leaks = output.count(COOKIE_SECRET) + int(str(root) in output)
    return passed, invalid_count, privacy_leaks


def materialization_case(root: Path) -> tuple[bool, int, int]:
    memory_repo = root / "agent-memory"
    source_dir = root / "source"
    project_path = root / "project"
    (memory_repo / "index").mkdir(parents=True)
    (memory_repo / "sessions").mkdir()
    source_dir.mkdir()
    project_path.mkdir()
    source = source_dir / "selected.jsonl"
    source.write_text(render_jsonl(source_rows(project_path), "\r\n"), encoding="utf-8")
    result = subprocess.run(
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
        input=inventory_payload(source, "2026-07-23T01:00:01Z"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    report = parse_report(result)
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    entry_dirs = [path.parent for path in (memory_repo / "sessions").glob("**/meta.json")]
    artifacts_ok = len(entry_dirs) == 1
    archive_text = ""
    if artifacts_ok:
        required = {"summary.md", "evidence.md", "meta.json", "source-map.json"}
        files = {path.name for path in entry_dirs[0].iterdir() if path.is_file()}
        artifacts_ok = required.issubset(files)
        archive_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in entry_dirs[0].iterdir()
            if path.is_file()
        )
    output = result.stdout + result.stderr
    privacy_leaks = (
        (archive_text + output).count(COOKIE_SECRET)
        + int(str(root) in output)
    )
    invalid_count = int(report.get("reason") == "source_inventory_invalid")
    passed = (
        result.returncode == 0
        and report.get("status") == "updated"
        and metrics.get("records_selected_count") == 1
        and metrics.get("records_processed_count") == 1
        and artifacts_ok
        and privacy_leaks == 0
    )
    return passed, invalid_count, privacy_leaks


def malformed_case(root: Path, runner: ModuleType) -> tuple[bool, int]:
    source_dir = root / "source"
    project_path = root / "project"
    memory_repo = root / "agent-memory"
    manifest_dir = root / "manifest"
    source_dir.mkdir(parents=True)
    project_path.mkdir()
    (memory_repo / "index").mkdir(parents=True)
    (memory_repo / "sessions").mkdir()
    manifest_dir.mkdir(mode=0o700)
    source = source_dir / "malformed.jsonl"
    source.write_text(
        json.dumps(source_rows(project_path)[0], ensure_ascii=False)
        + "\r\n{not-json}\r\n",
        encoding="utf-8",
    )
    direct_rejected = False
    try:
        runner.build_source_inventory(source_dir, ("*.jsonl",))
    except runner.SourceInventoryError:
        direct_rejected = True
    worker = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--source-dir",
            str(source_dir),
            "--inventory-worker-manifest",
            str(manifest_dir / "inventory.json"),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    updater = subprocess.run(
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
        input=inventory_payload(source, "2026-07-23T01:00:00Z"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    report = parse_report(updater)
    output = worker.stdout + worker.stderr + updater.stdout + updater.stderr
    privacy_leaks = output.count(COOKIE_SECRET) + int(str(root) in output)
    passed = (
        direct_rejected
        and worker.returncode != 0
        and "source_inventory_invalid" in worker.stderr
        and updater.returncode == 2
        and report.get("status") == "blocked"
        and report.get("reason") == "source_inventory_invalid"
        and not list((memory_repo / "sessions").glob("**/meta.json"))
        and privacy_leaks == 0
    )
    return passed, privacy_leaks


def install_replay_runtime(fixture: SyntheticArchive) -> None:
    runtime_copy = fixture.canonical / "tools/jsonl_inventory_runtime.py"
    shutil.copyfile(RUNNER, runtime_copy)
    (fixture.canonical / "tools/run_memory_updates.py").write_text(
        """#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

args = sys.argv[1:]
repo = Path(args[args.index('--memory-repo') + 1])
source_dir = Path(args[args.index('--source-dir') + 1])
runtime_path = Path(__file__).with_name('jsonl_inventory_runtime.py')
with tempfile.TemporaryDirectory(prefix='synthetic-jsonl-inventory-') as manifest_dir_text:
    manifest_dir = Path(manifest_dir_text)
    manifest_dir.chmod(0o700)
    inventory_result = subprocess.run(
        [
            sys.executable,
            str(runtime_path),
            '--source-dir',
            str(source_dir),
            '--inventory-worker-manifest',
            str(manifest_dir / 'inventory.json'),
            '--pattern',
            '*.jsonl',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
if inventory_result.returncode != 0:
    print(json.dumps({
        'report_kind': 'memory_update_batch_report',
        'report_version': 1,
        'status': 'blocked',
        'reason': 'source_inventory_invalid',
        'failure_stage': 'source_inventory',
        'source_batch_complete': False,
        'metrics': {
            'inventory_worker_count': 1,
            'projects_updated_count': 0,
            'source_streams_updated_count': 0,
            'archive_finalization_count': 0,
            'records_deferred_count': 0,
            'targets_deferred_count': 0,
            'child_failure_count': 0,
        },
        'privacy': {
            'aggregate_only': True,
            'paths_rendered': False,
            'source_content_rendered': False,
            'child_output_rendered': False,
        },
    }, sort_keys=True, separators=(',', ':')), flush=True)
    raise SystemExit(1)
(repo / 'INDEX.md').write_text('synthetic JSONL replay update\\n', encoding='utf-8')
print(json.dumps({
    'report_kind': 'memory_update_batch_report',
    'report_version': 1,
    'status': 'updated',
    'reason': 'updated',
    'failure_stage': 'none',
    'source_batch_complete': True,
    'metrics': {
        'inventory_worker_count': 1,
        'projects_updated_count': 1,
        'source_streams_updated_count': 0,
        'archive_finalization_count': 1,
        'records_deferred_count': 0,
        'targets_deferred_count': 0,
        'child_failure_count': 0,
    },
    'privacy': {
        'aggregate_only': True,
        'paths_rendered': False,
        'source_content_rendered': False,
        'child_output_rendered': False,
    },
}, sort_keys=True, separators=(',', ':')), flush=True)
marker = os.environ.get('SYNTHETIC_UPDATE_STARTED')
if marker:
    Path(marker).write_text('started\\n', encoding='utf-8')
    release = Path(os.environ['SYNTHETIC_UPDATE_RELEASE'])
    while not release.exists():
        time.sleep(0.02)
""",
        encoding="utf-8",
    )
    git(fixture.canonical, "add", "tools")
    git(fixture.canonical, "commit", "-m", "Synthetic JSONL physical-line runtime")
    git(fixture.canonical, "push", "origin", "main")
    fixture.base_sha = fixture.canonical_head()
    fixture.tool_hashes = fixture.current_tool_hashes()


def stale_replay_case(root: Path) -> tuple[bool, int, int]:
    root.mkdir(parents=True)
    fixture = SyntheticArchive(root, "stale-replay")
    project_path = fixture.root / "project"
    project_path.mkdir()
    (fixture.source / "raw-record.jsonl").write_text(
        render_jsonl(source_rows(project_path), "\n"),
        encoding="utf-8",
    )
    install_replay_runtime(fixture)
    marker = fixture.root / "update-started"
    release = fixture.root / "update-release"
    process = fixture.start(
        SYNTHETIC_UPDATE_STARTED=str(marker),
        SYNTHETIC_UPDATE_RELEASE=str(release),
    )
    fixture.wait_for_file(marker, "jsonl_replay:marker")
    fixture.wait_for_phase("updating", "jsonl_replay:phase")
    kill_process_group(process, "jsonl_replay:kill")
    transaction = json.loads(
        (fixture.state / "transaction.json").read_text(encoding="utf-8")
    )
    result, report = fixture.invoke()
    metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
    rendered = result.stdout + result.stderr + json.dumps(report, sort_keys=True)
    privacy_leaks = rendered.count(COOKIE_SECRET) + int(str(root) in rendered)
    invalid_count = int(report.get("reason") == "source_inventory_invalid")
    passed = (
        transaction.get("phase") == "updating"
        and result.returncode == 0
        and report.get("status") == "published"
        and report.get("recovery_action") == "stale_staging_replayed"
        and metrics.get("update_inventory_worker_count") == 1
        and fixture.canonical_clean()
        and fixture.canonical_head() == fixture.remote_head()
        and privacy_leaks == 0
    )
    return passed, invalid_count, privacy_leaks


def main() -> int:
    failed_cases: list[str] = []
    metrics = {
        "unicode_separator_inventory_acceptance_rate": 0.0,
        "unicode_separator_materialization_rate": 0.0,
        "physical_record_count_accuracy": 0.0,
        "crlf_compatibility_rate": 0.0,
        "malformed_jsonl_fail_closed_rate": 0.0,
        "stale_replay_recovery_rate": 0.0,
        "valid_case_source_inventory_invalid_count": 0,
        "privacy_leak_count": 0,
    }
    try:
        runner = load_module("jsonl_boundary_gate_runner", RUNNER)
        updater = load_module("jsonl_boundary_gate_updater", UPDATER)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            accepted, counts, crlf_passes, direct_invalid, direct_leaks = (
                direct_inventory_cases(root / "direct", runner, updater)
            )
            worker_ok, worker_invalid, worker_leaks = inventory_worker_case(
                root / "worker"
            )
            materialized, materialized_invalid, materialized_leaks = (
                materialization_case(root / "materialization")
            )
            malformed_ok, malformed_leaks = malformed_case(
                root / "malformed",
                runner,
            )
            replayed, replay_invalid, replay_leaks = stale_replay_case(
                root / "replay"
            )

        metrics = {
            "unicode_separator_inventory_acceptance_rate": rate(
                accepted + int(worker_ok),
                3,
            ),
            "unicode_separator_materialization_rate": rate(
                int(materialized) + int(replayed),
                2,
            ),
            "physical_record_count_accuracy": rate(counts, 2),
            "crlf_compatibility_rate": rate(
                crlf_passes + int(worker_ok) + int(materialized),
                3,
            ),
            "malformed_jsonl_fail_closed_rate": 1.0 if malformed_ok else 0.0,
            "stale_replay_recovery_rate": 1.0 if replayed else 0.0,
            "valid_case_source_inventory_invalid_count": (
                direct_invalid
                + worker_invalid
                + materialized_invalid
                + replay_invalid
            ),
            "privacy_leak_count": (
                direct_leaks
                + worker_leaks
                + materialized_leaks
                + malformed_leaks
                + replay_leaks
            ),
        }
        case_results = {
            "direct_inventory": accepted == 2 and counts == 2,
            "inventory_worker": worker_ok,
            "selected_record_materialization": materialized,
            "malformed_fail_closed": malformed_ok,
            "stale_updating_replay": replayed,
        }
        failed_cases.extend(
            case_id for case_id, passed in case_results.items() if not passed
        )
    except Exception:
        failed_cases.append("gate_execution")

    passed = (
        all(
            metrics[name] == 1.0
            for name in (
                "unicode_separator_inventory_acceptance_rate",
                "unicode_separator_materialization_rate",
                "physical_record_count_accuracy",
                "crlf_compatibility_rate",
                "malformed_jsonl_fail_closed_rate",
                "stale_replay_recovery_rate",
            )
        )
        and metrics["valid_case_source_inventory_invalid_count"] == 0
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
