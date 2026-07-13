#!/usr/bin/env python3
"""Gate single-inventory scheduled ingestion and single archive finalization."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "templates/agent-memory-repo"
RUNNER_SOURCE = TEMPLATE_ROOT / "tools/run_memory_updates.py"
UPDATER_SOURCE = TEMPLATE_ROOT / "tools/update_memory_archive.py"
SINGLE_WRITER_GATE = REPO_ROOT / "benchmarks/scheduled_update_single_writer_gate.py"
BASELINE_COMMIT = "e25c5bc29ddf1ace05b46e808c4b506860a35b61"
REPORT_KIND = "scheduled_update_throughput_gate"
PRIVATE_SENTINEL = "PRIVATE_THROUGHPUT_SENTINEL"
PARITY_ROOTS = ("sessions", "memories", "index", "daily", "INDEX.md")


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def output_count(output: str, label: str) -> int | None:
    prefix = f"{label}: "
    for line in output.splitlines():
        if line.startswith(prefix):
            try:
                return int(line.removeprefix(prefix))
            except ValueError:
                return None
    return None


def runner_command(memory_repo: Path, source_dir: Path, *extra: str) -> list[str]:
    return [
        sys.executable,
        str(memory_repo / "tools/run_memory_updates.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        *extra,
    ]


def write_fake_updater(memory_repo: Path) -> None:
    (memory_repo / "tools/update_memory_archive.py").write_text(
        f"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
is_finalize = '--finalize-archive' in args
project = ''
if '--project-path' in args:
    project = Path(args[args.index('--project-path') + 1]).name
records = []
if '--source-inventory-stdin' in args:
    payload = json.loads(sys.stdin.read())
    records = [row['relative_path'] for row in payload['records']]
row = {{
    'kind': 'finalize' if is_finalize else 'ingestion',
    'project': project,
    'records': records,
    'inventory_stdin': '--source-inventory-stdin' in args,
    'defer_global_rebuild': '--defer-global-rebuild' in args,
}}
with Path(os.environ['MY_PRECIOUS_THROUGHPUT_LOG']).open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(row, sort_keys=True) + '\\n')
if project and project == os.environ.get('MY_PRECIOUS_FAIL_PROJECT'):
    print('{PRIVATE_SENTINEL}', file=sys.stderr)
    raise SystemExit(9)
if is_finalize and os.environ.get('MY_PRECIOUS_FAIL_FINALIZER') == '1':
    print('{PRIVATE_SENTINEL}', file=sys.stderr)
    raise SystemExit(10)
""",
        encoding="utf-8",
    )


def setup_schedule_repo(root: Path, name: str, project_count: int) -> tuple[Path, Path, Path]:
    case_root = root / name
    memory_repo = case_root / "agent-memory"
    source_dir = case_root / "source-records"
    tools_dir = memory_repo / "tools"
    config_dir = memory_repo / "config"
    tools_dir.mkdir(parents=True)
    config_dir.mkdir()
    source_dir.mkdir()
    shutil.copyfile(RUNNER_SOURCE, tools_dir / "run_memory_updates.py")
    write_fake_updater(memory_repo)
    projects = []
    for ordinal in range(project_count):
        project_path = case_root / f"project-{ordinal:03d}"
        project_path.mkdir()
        projects.append(
            {
                "project_path": str(project_path.resolve()),
                "source_dir": str(source_dir.resolve()),
                "enabled": True,
                "source": "synthetic",
            }
        )
        (source_dir / f"record-{ordinal:03d}.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": f"2026-07-13T00:{ordinal % 60:02d}:00Z",
                    "cwd": str(project_path.resolve()),
                    "role": "user",
                    "content": f"Synthetic throughput record {ordinal:03d}.",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    (config_dir / "projects.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in projects),
        encoding="utf-8",
    )
    (config_dir / "source_streams.jsonl").write_text("", encoding="utf-8")
    return memory_repo, source_dir, case_root


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def run_schedule_success(root: Path) -> tuple[dict[str, int | float], list[str]]:
    project_count = 71
    memory_repo, source_dir, case_root = setup_schedule_repo(root, "schedule-success", project_count)
    log = case_root / "calls.jsonl"
    env = {**os.environ, "MY_PRECIOUS_THROUGHPUT_LOG": str(log)}
    result = run(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    rows = read_log(log)
    ingestion = [row for row in rows if row.get("kind") == "ingestion"]
    finalizers = [row for row in rows if row.get("kind") == "finalize"]
    dispatch_matches = sum(
        row.get("project") == f"project-{ordinal:03d}"
        and row.get("records") == [f"record-{ordinal:03d}.jsonl"]
        and row.get("inventory_stdin") is True
        and row.get("defer_global_rebuild") is True
        for ordinal, row in enumerate(ingestion)
    )
    inventory_count = output_count(result.stdout, "Source inventories built")
    root_rescans = output_count(result.stdout, "Source root rescans")
    finalization_count = output_count(result.stdout, "Archive finalizations")
    nonselected_reparse_count = sum(max(0, len(row.get("records", [])) - 1) for row in ingestion)
    baseline_operations = (project_count + 1) + project_count
    candidate_operations = (inventory_count or 0) + (finalization_count or 0)
    return {
        "source_inventory_count": inventory_count if inventory_count is not None else -1,
        "source_root_rescan_count": root_rescans if root_rescans is not None else -1,
        "nonselected_record_reparse_count": nonselected_reparse_count,
        "target_dispatch_accuracy": dispatch_matches / project_count,
        "successful_run_finalization_count": len(finalizers) if result.returncode == 0 else 0,
        "synthetic_redundant_work_reduction_rate": 1 - (candidate_operations / baseline_operations),
        "success": int(
            result.returncode == 0
            and len(ingestion) == project_count
            and len(finalizers) == 1
            and finalization_count == 1
        ),
    }, [result.stdout + result.stderr]


def run_schedule_failure(root: Path) -> tuple[int, list[str]]:
    memory_repo, source_dir, case_root = setup_schedule_repo(root, "schedule-failure", 3)
    log = case_root / "calls.jsonl"
    env = {
        **os.environ,
        "MY_PRECIOUS_THROUGHPUT_LOG": str(log),
        "MY_PRECIOUS_FAIL_PROJECT": "project-000",
    }
    result = run(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    rows = read_log(log)
    finalizers = [row for row in rows if row.get("kind") == "finalize"]
    passed = (
        result.returncode != 0
        and len(rows) == 1
        and rows[0].get("project") == "project-000"
        and not finalizers
        and output_count(result.stdout, "Archive finalizations") == 0
    )
    return len(finalizers) if passed else -1, [result.stdout + result.stderr]


def run_finalizer_failure(root: Path) -> tuple[float, list[str]]:
    memory_repo, source_dir, case_root = setup_schedule_repo(root, "finalizer-failure", 1)
    log = case_root / "calls.jsonl"
    env = {
        **os.environ,
        "MY_PRECIOUS_THROUGHPUT_LOG": str(log),
        "MY_PRECIOUS_FAIL_FINALIZER": "1",
    }
    result = run(runner_command(memory_repo, source_dir), cwd=memory_repo, env=env)
    rows = read_log(log)
    passed = (
        result.returncode != 0
        and [row.get("kind") for row in rows] == ["ingestion", "finalize"]
        and "update_status=failed reason=archive_finalization_failed" in result.stderr
    )
    return 1.0 if passed else 0.0, [result.stdout + result.stderr]


def run_dry_run(root: Path) -> tuple[int, list[str]]:
    memory_repo, source_dir, case_root = setup_schedule_repo(root, "dry-run", 1)
    log = case_root / "calls.jsonl"
    env = {**os.environ, "MY_PRECIOUS_THROUGHPUT_LOG": str(log)}
    result = run(runner_command(memory_repo, source_dir, "--dry-run"), cwd=memory_repo, env=env)
    finalizers = [row for row in read_log(log) if row.get("kind") == "finalize"]
    passed = result.returncode == 0 and not finalizers and output_count(result.stdout, "Archive finalizations") == 0
    return len(finalizers) if passed else -1, [result.stdout + result.stderr]


def inventory_row(path: Path, source_root: Path, *, relative_path: str | None = None) -> dict[str, object]:
    raw = path.read_bytes()
    stat = path.stat()
    source_value = json.loads(raw)
    return {
        "relative_path": relative_path or path.relative_to(source_root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "source_updated_at": source_value["timestamp"],
    }


def inventory_payload(rows: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "report_kind": "memory_source_inventory",
            "report_version": 2,
            "records": rows,
        },
        sort_keys=True,
    )


def run_inventory_rejection_cases(root: Path) -> tuple[float, list[str]]:
    outputs: list[str] = []
    passed = 0
    for case in ("malformed", "duplicate", "outside", "symlink", "mutated"):
        case_root = root / f"inventory-{case}"
        memory_repo = case_root / "agent-memory"
        source_dir = case_root / "source-records"
        project_path = case_root / "project"
        (memory_repo / "index").mkdir(parents=True)
        (memory_repo / "sessions").mkdir()
        source_dir.mkdir()
        project_path.mkdir()
        source = source_dir / f"{PRIVATE_SENTINEL}.jsonl"
        source.write_text(
            json.dumps(
                {
                    "timestamp": "2026-07-13T11:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "Synthetic fail-closed inventory record.",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if case == "malformed":
            payload = "{"
        elif case == "duplicate":
            row = inventory_row(source, source_dir)
            payload = inventory_payload([row, row])
        elif case == "outside":
            outside = case_root / "outside.jsonl"
            outside.write_bytes(source.read_bytes())
            payload = inventory_payload([inventory_row(outside, case_root, relative_path="../outside.jsonl")])
        elif case == "symlink":
            outside = case_root / "outside.jsonl"
            outside.write_bytes(source.read_bytes())
            link = source_dir / "escape.jsonl"
            link.symlink_to(outside)
            payload = inventory_payload([inventory_row(link, source_dir)])
        else:
            payload = inventory_payload([inventory_row(source, source_dir)])
            source.write_text(source.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
        result = run(
            [
                sys.executable,
                str(UPDATER_SOURCE),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(source_dir),
                "--project-path",
                str(project_path),
                "--require-project-metadata",
                "--source-inventory-stdin",
                "--defer-global-rebuild",
            ],
            input_text=payload,
        )
        output = result.stdout + result.stderr
        outputs.append(output)
        passed += int(
            result.returncode != 0
            and "update_status=blocked reason=source_inventory_invalid" in result.stderr
            and not list((memory_repo / "sessions").glob("**/meta.json"))
            and PRIVATE_SENTINEL not in output
            and str(case_root) not in output
        )
    return passed / 5, outputs


def copy_template(target: Path) -> None:
    shutil.copytree(
        TEMPLATE_ROOT,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def baseline_file(relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{relative_path}"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError("baseline source unavailable")
    return result.stdout


def write_frozen_datetime_hook(root: Path) -> Path:
    hook_dir = root / "python-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        """import datetime as _datetime

class FrozenDateTime(_datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 13, 12, 0, 0, tzinfo=_datetime.UTC)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)

_datetime.datetime = FrozenDateTime
""",
        encoding="utf-8",
    )
    return hook_dir


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


def run_output_parity_case(root: Path) -> tuple[float, int, list[str]]:
    case_root = root / "output-parity"
    source_dir = case_root / "source-records"
    source_dir.mkdir(parents=True)
    projects = []
    for ordinal in range(3):
        project_path = case_root / f"project-{ordinal}"
        project_path.mkdir()
        projects.append(project_path)
        for record_ordinal in range(2):
            hour = ordinal * 2 + record_ordinal + 1
            (source_dir / f"project-{ordinal}-{record_ordinal}.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": f"2026-07-13T{hour:02d}:00:00Z",
                        "cwd": str(project_path.resolve()),
                        "role": "user",
                        "content": (
                            f"Decision: synthetic parity project {ordinal} record "
                            f"{record_ordinal} keeps deterministic archive output."
                        ),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
    stream_path = case_root / "source-stream"
    stream_path.mkdir()
    (source_dir / "stream.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-13T04:00:00Z",
                "role": "user",
                "content": "Decision: synthetic stream parity remains project-independent.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "custom.memory").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-13T08:00:00Z",
                "cwd": str(projects[0].resolve()),
                "role": "user",
                "content": "Decision: synthetic custom-pattern parity remains deterministic.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "stream.memory").write_text(
        json.dumps(
            {
                "timestamp": "2026-07-13T09:00:00Z",
                "role": "user",
                "content": "Decision: synthetic custom-pattern stream parity remains deterministic.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    baseline_repo = case_root / "baseline-memory"
    candidate_repo = case_root / "candidate-memory"
    copy_template(baseline_repo)
    copy_template(candidate_repo)
    for memory_repo in (baseline_repo, candidate_repo):
        (memory_repo / "config/projects.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "project_path": str(project.resolve()),
                        "source_dir": str(source_dir.resolve()),
                        "enabled": True,
                        "source": "synthetic",
                        **(
                            {
                                "archive_scope": "domain:shared-parity",
                                "source_partition": f"source:project-{ordinal}",
                            }
                            if ordinal < 2
                            else {}
                        ),
                    },
                    sort_keys=True,
                )
                + "\n"
                for ordinal, project in enumerate(projects)
            ),
            encoding="utf-8",
        )
        (memory_repo / "config/source_streams.jsonl").write_text(
            json.dumps(
                {
                    "stream_id": "synthetic-stream",
                    "source_dir": str(source_dir.resolve()),
                    "project_path": str(stream_path.resolve()),
                    "archive_scope": "domain:synthetic",
                    "source_partition": "source:synthetic",
                    "project": "synthetic-stream",
                    "enabled": True,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    for relative in (
        "templates/agent-memory-repo/tools/run_memory_updates.py",
        "templates/agent-memory-repo/tools/update_memory_archive.py",
    ):
        (baseline_repo / "tools" / Path(relative).name).write_bytes(baseline_file(relative))
    hook_dir = write_frozen_datetime_hook(case_root)
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            part for part in (str(hook_dir), os.environ.get("PYTHONPATH", "")) if part
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    scenarios: tuple[tuple[str, ...], ...] = (
        (),
        (),
        ("--pattern", "*.memory"),
        ("--rewrite-existing", "--max-records", "1"),
    )
    passed = 0
    outputs: list[str] = []
    for extra in scenarios:
        baseline = run(runner_command(baseline_repo, source_dir, *extra), cwd=baseline_repo, env=env)
        candidate = run(runner_command(candidate_repo, source_dir, *extra), cwd=candidate_repo, env=env)
        outputs.extend((baseline.stdout + baseline.stderr, candidate.stdout + candidate.stderr))
        passed += int(
            baseline.returncode == 0
            and candidate.returncode == 0
            and archive_snapshot(baseline_repo) == archive_snapshot(candidate_repo)
        )
    return passed / len(scenarios), len(scenarios), outputs


def run_single_writer_regression() -> tuple[float, list[str]]:
    result = run([sys.executable, str(SINGLE_WRITER_GATE)], cwd=REPO_ROOT)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    passed = result.returncode == 0 and payload.get("status") == "passed"
    return 1.0 if passed else 0.0, [result.stdout + result.stderr]


def privacy_hits(outputs: list[str], root: Path) -> int:
    markers = (PRIVATE_SENTINEL, str(root))
    return sum(marker in output for output in outputs for marker in markers)


def build_report(root: Path) -> dict[str, object]:
    schedule, schedule_outputs = run_schedule_success(root)
    failed_finalizations, failure_outputs = run_schedule_failure(root)
    finalizer_failure_rate, finalizer_outputs = run_finalizer_failure(root)
    dry_finalizations, dry_outputs = run_dry_run(root)
    rejection_rate, rejection_outputs = run_inventory_rejection_cases(root)
    output_parity_rate, output_parity_scenario_count, parity_outputs = run_output_parity_case(root)
    single_writer_rate, single_writer_outputs = run_single_writer_regression()
    outputs = [
        *schedule_outputs,
        *failure_outputs,
        *finalizer_outputs,
        *dry_outputs,
        *rejection_outputs,
        *parity_outputs,
        *single_writer_outputs,
    ]
    metrics: dict[str, int | float] = {
        "source_inventory_amplification": float(schedule["source_inventory_count"]),
        "source_root_rescan_count": int(schedule["source_root_rescan_count"]),
        "nonselected_record_reparse_count": int(schedule["nonselected_record_reparse_count"]),
        "target_dispatch_accuracy": float(schedule["target_dispatch_accuracy"]),
        "successful_run_finalization_count": int(schedule["successful_run_finalization_count"]),
        "failed_run_finalization_count": failed_finalizations,
        "dry_run_finalization_count": dry_finalizations,
        "finalizer_failure_propagation_rate": finalizer_failure_rate,
        "output_parity_rate": output_parity_rate,
        "output_parity_scenario_count": output_parity_scenario_count,
        "fail_closed_inventory_rejection_rate": rejection_rate,
        "single_writer_regression_pass_rate": single_writer_rate,
        "synthetic_redundant_work_reduction_rate": float(schedule["synthetic_redundant_work_reduction_rate"]),
        "privacy_leak_count": privacy_hits(outputs, root),
    }
    passed = (
        schedule["success"] == 1
        and metrics["source_inventory_amplification"] == 1.0
        and metrics["source_root_rescan_count"] == 0
        and metrics["nonselected_record_reparse_count"] == 0
        and metrics["target_dispatch_accuracy"] == 1.0
        and metrics["successful_run_finalization_count"] == 1
        and metrics["failed_run_finalization_count"] == 0
        and metrics["dry_run_finalization_count"] == 0
        and metrics["finalizer_failure_propagation_rate"] == 1.0
        and metrics["output_parity_rate"] == 1.0
        and metrics["output_parity_scenario_count"] == 4
        and metrics["fail_closed_inventory_rejection_rate"] == 1.0
        and metrics["single_writer_regression_pass_rate"] == 1.0
        and metrics["synthetic_redundant_work_reduction_rate"] >= 0.95
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "source_content_rendered": False,
            "project_names_rendered": False,
            "child_output_rendered": False,
        },
        "claim_boundary": (
            "single-host scheduled source inventory reuse, target dispatch, one final rebuild, "
            "fail-closed inventory validation, and V2.38 output parity only; not whole-run rollback, "
            "distributed locking, private wall-clock performance, memory quality, ranking, or LLM quality"
        ),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_report(Path(tmpdir))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
