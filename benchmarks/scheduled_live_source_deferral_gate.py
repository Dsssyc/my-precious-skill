#!/usr/bin/env python3
"""Gate deterministic live-source deferral and retry closure."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "templates/agent-memory-repo"
REPORT_KIND = "scheduled_live_source_deferral_gate"
PRIVATE_SENTINEL = "PRIVATE_LIVE_SOURCE_SENTINEL"
MANIFEST_CONTENT_SENTINEL = "MANIFEST_PRIVATE_CONTENT_SENTINEL"


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )


def copy_template(target: Path) -> None:
    shutil.copytree(
        TEMPLATE_ROOT,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def write_source(path: Path, timestamp: str, project_path: Path, content: str) -> bytes:
    raw = (
        json.dumps(
            {
                "timestamp": timestamp,
                "cwd": str(project_path.resolve()),
                "role": "user",
                "content": content,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    path.write_bytes(raw)
    return raw


def configure_project(memory_repo: Path, source_dir: Path, project_path: Path) -> None:
    (memory_repo / "config/projects.jsonl").write_text(
        json.dumps(
            {
                "project_path": str(project_path.resolve()),
                "source_dir": str(source_dir.resolve()),
                "enabled": True,
                "source": "synthetic",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def invoke_runner(
    memory_repo: Path,
    source_dir: Path,
    *,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = run(
        [
            sys.executable,
            str(memory_repo / "tools/run_memory_updates.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--report-json",
        ],
        cwd=memory_repo,
        env=env,
    )
    lines = [line for line in result.stdout.splitlines() if line]
    try:
        payload = json.loads(lines[0]) if len(lines) == 1 else {}
    except json.JSONDecodeError:
        payload = {}
    return result, payload if isinstance(payload, dict) else {}


def meta_rows(memory_repo: Path) -> list[tuple[Path, dict[str, Any]]]:
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append((path, payload))
    return rows


def rows_for_source(memory_repo: Path, source: Path) -> list[tuple[Path, dict[str, Any]]]:
    source_key = str(source.resolve())
    return [row for row in meta_rows(memory_repo) if row[1].get("source_record") == source_key]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_artifact_snapshot(memory_repo: Path, source: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for meta_path, _ in rows_for_source(memory_repo, source):
        entry = meta_path.parent
        for path in sorted(item for item in entry.rglob("*") if item.is_file()):
            snapshot[path.relative_to(entry).as_posix()] = digest(path.read_bytes())
    return snapshot


def install_live_mutation_wrapper(
    memory_repo: Path,
    changed: Path,
    unavailable: Path,
    never_archived: Path,
    marker: Path,
) -> None:
    updater = memory_repo / "tools/update_memory_archive.py"
    implementation = memory_repo / "tools/update_memory_archive_impl.py"
    shutil.copyfile(updater, implementation)
    updater.write_text(
        """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
marker = Path(os.environ['MY_PRECIOUS_LIVE_MUTATION_MARKER'])
if '--finalize-archive' not in args and not marker.exists():
    changed = Path(os.environ['MY_PRECIOUS_CHANGED_SOURCE'])
    changed.write_text(changed.read_text(encoding='utf-8') + '{}\\n', encoding='utf-8')
    never_archived = Path(os.environ['MY_PRECIOUS_NEVER_ARCHIVED_SOURCE'])
    never_archived.write_text(never_archived.read_text(encoding='utf-8') + '{}\\n', encoding='utf-8')
    Path(os.environ['MY_PRECIOUS_UNAVAILABLE_SOURCE']).unlink()
    marker.write_text('mutated\\n', encoding='utf-8')
implementation = Path(__file__).with_name('update_memory_archive_impl.py')
os.execv(sys.executable, [sys.executable, str(implementation), *args])
""",
        encoding="utf-8",
    )
    os.environ.pop("MY_PRECIOUS_LIVE_MUTATION_MARKER", None)


def run_live_deferral_case(root: Path) -> tuple[dict[str, int | float], list[str]]:
    case_root = root / "live-deferral"
    memory_repo = case_root / "agent-memory"
    source_dir = case_root / "source-records"
    project_path = case_root / "project"
    source_dir.mkdir(parents=True)
    project_path.mkdir()
    copy_template(memory_repo)
    configure_project(memory_repo, source_dir, project_path)

    changed = source_dir / "changed.jsonl"
    unavailable = source_dir / "unavailable.jsonl"
    never_archived = source_dir / "never-archived-older.jsonl"
    stable = source_dir / "stable.jsonl"
    write_source(changed, "2026-07-21T06:00:00Z", project_path, "Decision: retain prior changed-source memory.")
    write_source(unavailable, "2026-07-21T07:00:00Z", project_path, "Decision: retain prior unavailable-source memory.")
    initial_result, initial_report = invoke_runner(memory_repo, source_dir)

    prior: dict[Path, tuple[dict[str, str], str]] = {}
    for source in (changed, unavailable):
        rows = rows_for_source(memory_repo, source)
        if len(rows) == 1:
            _, payload = rows[0]
            prior[source] = (
                source_artifact_snapshot(memory_repo, source),
                str(payload.get("source_record_sha256") or ""),
            )

    write_source(
        changed,
        "2026-07-21T13:00:00Z",
        project_path,
        "Decision: changed source should defer until a stable retry.",
    )
    unavailable_v2 = write_source(
        unavailable,
        "2026-07-21T12:00:00Z",
        project_path,
        "Decision: unavailable source should defer until a stable retry.",
    )
    write_source(
        never_archived,
        "2026-07-21T08:00:00Z",
        project_path,
        "Decision: an older never-archived source must survive high-water advancement.",
    )
    stable_raw = write_source(
        stable,
        "2026-07-21T11:00:00Z",
        project_path,
        "Decision: stable sibling must publish during partial source deferral.",
    )
    marker = case_root / "mutation-applied"
    install_live_mutation_wrapper(memory_repo, changed, unavailable, never_archived, marker)
    env = {
        **os.environ,
        "MY_PRECIOUS_LIVE_MUTATION_MARKER": str(marker),
        "MY_PRECIOUS_CHANGED_SOURCE": str(changed),
        "MY_PRECIOUS_UNAVAILABLE_SOURCE": str(unavailable),
        "MY_PRECIOUS_NEVER_ARCHIVED_SOURCE": str(never_archived),
    }
    deferred_result, deferred_report = invoke_runner(memory_repo, source_dir, env=env)

    partial_mutations = 0
    for source in (changed, unavailable):
        prior_entry = prior.get(source)
        current_rows = rows_for_source(memory_repo, source)
        if prior_entry is None:
            partial_mutations += 1
            continue
        prior_snapshot, prior_hash = prior_entry
        current_hashes = {str(payload.get("source_record_sha256") or "") for _, payload in current_rows}
        if source_artifact_snapshot(memory_repo, source) != prior_snapshot or current_hashes != {prior_hash}:
            partial_mutations += 1
    if rows_for_source(memory_repo, never_archived):
        partial_mutations += 1

    deferred_timestamps = {
        str(payload.get("source_updated_at") or "")
        for _, payload in meta_rows(memory_repo)
    }
    freshness_advances = sum(
        timestamp in deferred_timestamps
        for timestamp in (
            "2026-07-21T08:00:00Z",
            "2026-07-21T12:00:00Z",
            "2026-07-21T13:00:00Z",
        )
    )
    stable_rows = rows_for_source(memory_repo, stable)
    stable_published = any(
        payload.get("source_record_sha256") == digest(stable_raw)
        for _, payload in stable_rows
    )

    unavailable.write_bytes(unavailable_v2)
    retry_result, retry_report = invoke_runner(memory_repo, source_dir, env=env)
    retry_expected = {
        changed: digest(changed.read_bytes()),
        unavailable: digest(unavailable_v2),
        never_archived: digest(never_archived.read_bytes()),
    }
    retry_recalled = sum(
        any(
            payload.get("source_record_sha256") == expected_hash
            for _, payload in rows_for_source(memory_repo, source)
        )
        for source, expected_hash in retry_expected.items()
    )

    deferred_metrics = deferred_report.get("metrics") if isinstance(deferred_report.get("metrics"), dict) else {}
    live_source_defer_accuracy = (
        1.0
        if deferred_result.returncode == 0
        and deferred_report.get("status") == "deferred"
        and deferred_report.get("reason") == "source_records_deferred"
        and deferred_report.get("source_batch_complete") is False
        and deferred_metrics.get("records_deferred_count") == 3
        else 0.0
    )
    stable_sibling_accuracy = (
        1.0
        if stable_published and deferred_metrics.get("archive_finalization_count") == 1
        else 0.0
    )
    deferred_retry_recall = (
        retry_recalled / 3
        if retry_result.returncode == 0
        and retry_report.get("status") == "updated"
        and retry_report.get("reason") == "updated"
        else 0.0
    )
    inventory_worker_accuracy = (
        1.0
        if initial_result.returncode == 0
        and initial_report.get("status") == "updated"
        and deferred_metrics.get("inventory_worker_count") == 1
        else 0.0
    )
    return {
        "live_source_defer_accuracy": live_source_defer_accuracy,
        "stable_sibling_publish_accuracy": stable_sibling_accuracy,
        "deferred_retry_recall": deferred_retry_recall,
        "changed_source_partial_mutation_count": partial_mutations,
        "changed_source_freshness_advance_count": freshness_advances,
        "inventory_worker_isolation_accuracy": inventory_worker_accuracy,
        "deferred_reason_covered": int(
            deferred_report.get("status") == "deferred"
            and deferred_report.get("reason") == "source_records_deferred"
        ),
        "retry_reason_covered": int(
            retry_report.get("status") == "updated" and retry_report.get("reason") == "updated"
        ),
    }, [
        initial_result.stdout + initial_result.stderr,
        deferred_result.stdout + deferred_result.stderr,
        retry_result.stdout + retry_result.stderr,
    ]


def run_unknown_failure_case(root: Path) -> tuple[float, int, list[str]]:
    case_root = root / "unknown-failure"
    memory_repo = case_root / "agent-memory"
    source_dir = case_root / "source-records"
    project_path = case_root / "project"
    source_dir.mkdir(parents=True)
    project_path.mkdir()
    copy_template(memory_repo)
    configure_project(memory_repo, source_dir, project_path)
    write_source(
        source_dir / "record.jsonl",
        "2026-07-21T14:00:00Z",
        project_path,
        "Decision: unknown child failure must remain aggregate-only.",
    )
    (memory_repo / "tools/update_memory_archive.py").write_text(
        f"import sys\nprint('{PRIVATE_SENTINEL}', file=sys.stderr)\nraise SystemExit(9)\n",
        encoding="utf-8",
    )

    result, report = invoke_runner(memory_repo, source_dir)
    passed = (
        result.returncode != 0
        and report.get("status") == "blocked"
        and report.get("reason") == "child_failure_unclassified"
        and isinstance(report.get("metrics"), dict)
        and report["metrics"].get("child_failure_count") == 1
    )
    return 1.0 if passed else 0.0, int(passed), [result.stdout + result.stderr]


def run_manifest_case(root: Path) -> tuple[float, list[str]]:
    case_root = root / "manifest"
    source_dir = case_root / "source-records"
    project_path = case_root / "project"
    manifest_dir = case_root / "private-manifest"
    source_dir.mkdir(parents=True)
    project_path.mkdir()
    manifest_dir.mkdir(mode=0o700)
    write_source(
        source_dir / "record.jsonl",
        "2026-07-21T15:00:00Z",
        project_path,
        MANIFEST_CONTENT_SENTINEL,
    )
    manifest = manifest_dir / "inventory.json"
    result = run(
        [
            sys.executable,
            str(TEMPLATE_ROOT / "tools/run_memory_updates.py"),
            "--source-dir",
            str(source_dir),
            "--inventory-worker-manifest",
            str(manifest),
        ],
        cwd=REPO_ROOT,
    )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    rows = payload.get("records") if isinstance(payload, dict) else None
    allowed_row_keys = {
        "relative_path",
        "sha256",
        "size",
        "mtime_ns",
        "source_updated_at",
        "project_paths",
    }
    passed = (
        result.returncode == 0
        and isinstance(rows, list)
        and len(rows) == 1
        and isinstance(rows[0], dict)
        and set(rows[0]) == allowed_row_keys
        and MANIFEST_CONTENT_SENTINEL not in manifest.read_text(encoding="utf-8")
        and stat.S_IMODE(manifest.stat().st_mode) == 0o600
    )
    return 1.0 if passed else 0.0, [result.stdout + result.stderr]


def privacy_leak_count(outputs: list[str], root: Path) -> int:
    markers = (PRIVATE_SENTINEL, MANIFEST_CONTENT_SENTINEL, str(root))
    return sum(marker in output for output in outputs for marker in markers)


def build_report(root: Path) -> dict[str, object]:
    live, live_outputs = run_live_deferral_case(root)
    unknown_accuracy, unknown_covered, unknown_outputs = run_unknown_failure_case(root)
    manifest_accuracy, manifest_outputs = run_manifest_case(root)
    outputs = [*live_outputs, *unknown_outputs, *manifest_outputs]
    reason_coverage = (
        live["deferred_reason_covered"]
        + live["retry_reason_covered"]
        + unknown_covered
    ) / 3
    metrics: dict[str, int | float] = {
        "live_source_defer_accuracy": float(live["live_source_defer_accuracy"]),
        "stable_sibling_publish_accuracy": float(live["stable_sibling_publish_accuracy"]),
        "deferred_retry_recall": float(live["deferred_retry_recall"]),
        "changed_source_partial_mutation_count": int(live["changed_source_partial_mutation_count"]),
        "changed_source_freshness_advance_count": int(live["changed_source_freshness_advance_count"]),
        "unknown_failure_block_accuracy": unknown_accuracy,
        "aggregate_failure_reason_coverage": reason_coverage,
        "inventory_worker_isolation_accuracy": float(live["inventory_worker_isolation_accuracy"]),
        "manifest_metadata_only_accuracy": manifest_accuracy,
        "privacy_leak_count": privacy_leak_count(outputs, root),
    }
    passed = (
        metrics["live_source_defer_accuracy"] == 1.0
        and metrics["stable_sibling_publish_accuracy"] == 1.0
        and metrics["deferred_retry_recall"] == 1.0
        and metrics["changed_source_partial_mutation_count"] == 0
        and metrics["changed_source_freshness_advance_count"] == 0
        and metrics["unknown_failure_block_accuracy"] == 1.0
        and metrics["aggregate_failure_reason_coverage"] == 1.0
        and metrics["inventory_worker_isolation_accuracy"] == 1.0
        and metrics["manifest_metadata_only_accuracy"] == 1.0
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "source_content_rendered": False,
            "child_output_rendered": False,
        },
        "claim_boundary": (
            "synthetic single-host live-source deferral, stable-sibling progress, deterministic retry, "
            "metadata-only inventory isolation, and aggregate failure classification only; not private "
            "archive performance, retrieval quality, ranking quality, vector search, or LLM answer quality"
        ),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_report(Path(tmpdir))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
