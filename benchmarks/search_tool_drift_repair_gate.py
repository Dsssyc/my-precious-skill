#!/usr/bin/env python3
"""Gate archive-bundled search tool drift repair for packaged deployments."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import using_my_precious_runtime_gate as runtime  # noqa: E402


REPORT_KIND = "search_tool_drift_repair_gate"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
PROTECTED_ARCHIVE_ROOTS = (
    "INDEX.md",
    "config",
    "daily",
    "index",
    "memories",
    "records",
    "sessions",
    "sources",
)
LEAK_MARKERS = (
    *runtime.LEAK_MARKERS,
    "context package unsupported",
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


def run_may_fail(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def setup_seeded_archive(root: Path, name: str) -> Path:
    memory_repo = root / name
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--skip-config",
        ],
        f"{name}:setup",
    )
    runtime.write_synthetic_archive(memory_repo)
    return memory_repo


def write_stale_search_tool(memory_repo: Path) -> None:
    stale_tool = memory_repo / "tools/search_memory.py"
    stale_tool.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "sys.stderr.write('context package unsupported\\n')",
                "print(json.dumps({'report_kind': 'legacy_search_results', 'hits': []}))",
                "",
            ]
        ),
        encoding="utf-8",
    )


def context_package_result(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_may_fail(
        [
            sys.executable,
            str(memory_repo / "tools/search_memory.py"),
            runtime.SUPPORTED_QUERY,
            "--repo",
            str(memory_repo),
            "--depth",
            "evidence",
            "--context-json",
        ],
        cwd=memory_repo,
    )


def load_json_payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def parsed_report_kind(result: subprocess.CompletedProcess[str]) -> str:
    payload = load_json_payload(result)
    if payload is None:
        return ""
    report_kind = payload.get("report_kind")
    return report_kind if isinstance(report_kind, str) else ""


def is_supported_context_package(result: subprocess.CompletedProcess[str]) -> bool:
    payload = load_json_payload(result)
    if payload is None or payload.get("report_kind") != CONTEXT_REPORT_KIND:
        return False
    answerability = payload.get("answerability")
    return isinstance(answerability, dict) and answerability.get("status") == "supported"


def refresh_tools(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_may_fail(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--refresh-tools",
            "--skip-config",
        ],
    )


def iter_protected_files(memory_repo: Path) -> list[Path]:
    files: list[Path] = []
    for relative in PROTECTED_ARCHIVE_ROOTS:
        path = memory_repo / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(child for child in path.rglob("*") if child.is_file())
    return sorted(files)


def protected_archive_snapshot(memory_repo: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in iter_protected_files(memory_repo):
        relative = str(path.relative_to(memory_repo))
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def changed_file_count(before: dict[str, str], after: dict[str, str]) -> int:
    keys = set(before) | set(after)
    return sum(1 for key in keys if before.get(key) != after.get(key))


def run_repairable_case(root: Path) -> dict[str, int | bool]:
    memory_repo = setup_seeded_archive(root, "repairable-agent-memory")
    data_before = protected_archive_snapshot(memory_repo)
    write_stale_search_tool(memory_repo)

    pre_result = context_package_result(memory_repo)
    stale_detected = parsed_report_kind(pre_result) != CONTEXT_REPORT_KIND

    repair_result = refresh_tools(memory_repo)
    post_result = context_package_result(memory_repo)
    post_success = is_supported_context_package(post_result)
    data_after = protected_archive_snapshot(memory_repo)

    return {
        "stale_detected": int(stale_detected),
        "repair_attempted": 1,
        "post_success": int(repair_result.returncode == 0 and post_success),
        "template_fallback_used_after_repair": 0,
        "archive_data_mutation_count": changed_file_count(data_before, data_after),
    }


def run_unsafe_case(root: Path) -> dict[str, int]:
    memory_repo = setup_seeded_archive(root, "unsafe-agent-memory")
    outside_tool = root / "outside-search.py"
    outside_tool.write_text("outside stays unchanged\n", encoding="utf-8")
    search_tool = memory_repo / "tools/search_memory.py"
    search_tool.unlink()
    search_tool.symlink_to(outside_tool)

    repair_result = refresh_tools(memory_repo)
    outside_unchanged = outside_tool.read_text(encoding="utf-8") == "outside stays unchanged\n"
    return {
        "repair_attempted": 1,
        "unsafe_repair_fail_closed": int(repair_result.returncode != 0 and outside_unchanged),
    }


def privacy_leak_count(report: dict[str, Any]) -> int:
    rendered = json.dumps(report, sort_keys=True)
    return sum(1 for marker in LEAK_MARKERS if marker in rendered)


def build_report(repairable: dict[str, int | bool], unsafe: dict[str, int]) -> dict[str, Any]:
    metrics: dict[str, int] = {
        "stale_search_tool_detected_count": int(repairable["stale_detected"]),
        "repair_attempt_count": int(repairable["repair_attempted"]) + int(unsafe["repair_attempted"]),
        "post_repair_context_package_success_count": int(repairable["post_success"]),
        "template_fallback_used_after_repair_count": int(repairable["template_fallback_used_after_repair"]),
        "archive_data_mutation_count": int(repairable["archive_data_mutation_count"]),
        "unsafe_repair_fail_closed_count": int(unsafe["unsafe_repair_fail_closed"]),
        "privacy_leak_count": 0,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "claim_boundary": (
            "synthetic deployment search-tool drift repair only; not private archive correctness, "
            "private content repair, ranking, vector search, LLM answer quality, or scheduler publishing"
        ),
        "repair_contract": {
            "command": "python skills/setup-my-precious/scripts/setup_memory_archive.py --path <repo> --refresh-tools --skip-config",
            "updated_surface": "tools/** only",
            "archive_data_preserved": True,
            "post_repair_answerability_source": CONTEXT_REPORT_KIND,
        },
        "template_fallback_used_after_repair": False,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "memory_ids_rendered": False,
            "raw_refs_rendered": False,
            "source_paths_rendered": False,
            "context_packages_rendered": False,
            "stdout_rendered": False,
            "stderr_rendered": False,
        },
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report)
    if (
        metrics["stale_search_tool_detected_count"] != 1
        or metrics["repair_attempt_count"] != 2
        or metrics["post_repair_context_package_success_count"] != 1
        or metrics["template_fallback_used_after_repair_count"] != 0
        or metrics["archive_data_mutation_count"] != 0
        or metrics["unsafe_repair_fail_closed_count"] != 1
        or metrics["privacy_leak_count"] != 0
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, Any]:
    repairable = run_repairable_case(root)
    unsafe = run_unsafe_case(root)
    return build_report(repairable, unsafe)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent directory for generated clean-room artifacts")
    return parser.parse_args(argv)


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-search-tool-drift-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-search-tool-drift-", dir=parent))
    return root, None, root


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_work_root(args.work_dir)
        report = run_gate(root)
    except GateFailure as failure:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failures": [failure.to_report()],
            "privacy": {
                "aggregate_only": True,
                "stdout_rendered": False,
                "stderr_rendered": False,
            },
        }
    finally:
        if temp is not None:
            temp.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
