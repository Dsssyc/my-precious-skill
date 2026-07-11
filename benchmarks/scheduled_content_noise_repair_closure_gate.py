#!/usr/bin/env python3
"""Gate search-healthy content-noise repair closure before scheduled publish."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "scheduled_content_noise_repair_closure_gate"

PRIVATE_MARKERS = (
    "PRIVATE_CONTENT_NOISE_SENTINEL",
    "PRIVATE_AMBIGUOUS_CONTENT_SENTINEL",
    "PRIVATE_MALFORMED_CONTENT_SENTINEL",
    "/private/synthetic/content-noise-source.jsonl",
)
RAW_GIT_ACTION = re.compile(r"^\s*(?:\$\s*)?git\s+(?:add|commit|push)\b", re.IGNORECASE)
RAW_GIT_PROSE = re.compile(r"\b(?:run|use|execute)\s+git\s+(?:add|commit|push)\b", re.IGNORECASE)

DURABLE_SUMMARY = "Durable content-noise repair closure remains current."
DURABLE_FACT = "Keep search health separate from content-noise readiness."
DURABLE_TAG = "content-noise-repair"


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
class ClosureCase:
    name: str
    kind: str


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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_searchable_memory(repo: Path) -> None:
    summary_path = "sessions/2026/07/09/content-noise-search/summary.md"
    evidence_path = "sessions/2026/07/09/content-noise-search/evidence.md"
    session_dir = repo / "sessions/2026/07/09/content-noise-search"
    session_dir.mkdir(parents=True, exist_ok=True)
    (repo / summary_path).write_text(
        "# Synthetic Searchable Memory\n\nDurable search health fixture remains current.\n",
        encoding="utf-8",
    )
    (repo / evidence_path).write_text(
        "# Synthetic Searchable Evidence\n\n"
        "ev_001: Durable search health fixture remains current.\n",
        encoding="utf-8",
    )
    node = {
        "memory_id": "mem_scheduled_content_noise_search_health",
        "layer": "global",
        "scope": "global",
        "topic": "scheduled-content-noise-search-health",
        "text": "Durable search health fixture remains current.",
        "rationale": "Synthetic gate requires active drillable memory before content-noise repair.",
        "source": "explicit",
        "confidence": "high",
        "persistence": "sticky",
        "support_count": 1,
        "first_seen": "2026-07-09T00:00:00Z",
        "last_seen": "2026-07-09T00:00:00Z",
        "derived_from": [summary_path],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_001"}],
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": None,
        "tags": ["scheduled-content-noise", "search-health"],
    }
    write_jsonl(repo / "memories/explicit.jsonl", [node])
    write_jsonl(
        repo / "index/memories.jsonl",
        [node],
    )


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
    write_searchable_memory(memory_repo)
    run_command(["git", "init", "-q"], f"{name}:git:init", cwd=memory_repo)
    run_command(["git", "config", "user.email", "synthetic@example.invalid"], f"{name}:git:email", cwd=memory_repo)
    run_command(["git", "config", "user.name", "Synthetic Gate"], f"{name}:git:name", cwd=memory_repo)
    run_command(["git", "add", "."], f"{name}:git:add", cwd=memory_repo)
    run_command(["git", "commit", "-m", "Initial synthetic archive"], f"{name}:git:commit", cwd=memory_repo)
    return memory_repo


def render_agent_native_prompt(memory_repo: Path, root: Path, name: str) -> str:
    source_dir = root / name / "source-records"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = root / name / "agent-native.txt"
    run_command(
        [
            sys.executable,
            str(memory_repo / "tools/render_scheduler.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--backend",
            "agent-native",
            "--allow-redacted-secrets",
            "--push-after-update",
            "--output",
            str(output),
        ],
        f"{name}:render_prompt",
        cwd=memory_repo,
    )
    return output.read_text(encoding="utf-8")


def prompt_contract_result(prompt: str, memory_repo: Path) -> dict[str, bool]:
    health_command = "python tools/search_memory.py --health-check"
    sync_command = "python tools/sync_memory_archive.py --push"
    health_index = prompt.find(health_command)
    sync_index = prompt.find(sync_command)
    raw_git_publish_path = any(
        (RAW_GIT_ACTION.search(line) or RAW_GIT_PROSE.search(line))
        and "do not" not in line.lower()
        and "don't" not in line.lower()
        and "never" not in line.lower()
        for line in prompt.splitlines()
    )
    return {
        "single_working_directory": "Use exactly one working directory:" in prompt and str(memory_repo) in prompt,
        "health_check_before_sync": health_index != -1 and sync_index != -1 and health_index < sync_index,
        "generic_content_query_not_required": "python tools/search_memory.py memory" not in prompt,
        "sync_helper_used": sync_command in prompt,
        "repair_contract": "python tools/repair_publish_surfaces.py --apply" in prompt,
        "no_hand_staging": "Do not hand-stage files" in prompt and not raw_git_publish_path,
    }


def write_session(memory_repo: Path, *, kind: str, name: str) -> dict[str, str]:
    session_dir = memory_repo / f"sessions/2026/07/09/{name}"
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = f"sessions/2026/07/09/{name}/summary.md"
    evidence_path = f"sessions/2026/07/09/{name}/evidence.md"
    source_map_path = f"sessions/2026/07/09/{name}/source-map.json"
    (memory_repo / summary_path).write_text(f"# Synthetic Summary\n\n{DURABLE_SUMMARY}\n", encoding="utf-8")
    (memory_repo / evidence_path).write_text(
        f"# Synthetic Evidence\n\nev_001: {DURABLE_SUMMARY}\n",
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
    meta: dict[str, object] = {
        "session_id": f"synthetic-{name}",
        "source_agent": "synthetic",
        "project": "synthetic-project",
        "project_path": "synthetic-project",
        "archive_scope": "synthetic-project",
        "source_partition": "synthetic-project",
        "source_updated_at": "2026-07-09T00:00:00Z",
        "archive_status": "summarized",
        "redaction_status": "redacted",
        "summary_path": summary_path,
        "evidence_path": evidence_path,
        "source_map_path": source_map_path,
        "user_intent": "Preserve deterministic search-healthy content-noise repair closure.",
        "summary": DURABLE_SUMMARY,
        "facts": [DURABLE_FACT],
        "tags": [DURABLE_TAG],
        "decisions": [],
        "unresolved_tasks": [],
        "explicit_memories": [],
    }
    if kind == "repairable":
        meta["summary"] = (
            f"{DURABLE_SUMMARY} "
            "Command Status: dry-run would push after commit PRIVATE_CONTENT_NOISE_SENTINEL."
        )
        meta["facts"] = [
            DURABLE_FACT,
            "Approval policy is currently never. PRIVATE_CONTENT_NOISE_SENTINEL",
            "raw source path: /private/synthetic/content-noise-source.jsonl",
        ]
        meta["tags"] = [DURABLE_TAG, "unit tests PRIVATE_CONTENT_NOISE_SENTINEL"]
        meta["raw_prompts"] = ["raw prompt: PRIVATE_CONTENT_NOISE_SENTINEL"]
    elif kind == "ambiguous":
        meta["user_intent"] = ""
        meta["summary"] = (
            "Durable content noise closure remains current while command status dry-run would push "
            "PRIVATE_AMBIGUOUS_CONTENT_SENTINEL"
        )
    elif kind != "clean":
        raise AssertionError(f"unexpected session kind: {kind}")
    write_json(session_dir / "meta.json", meta)
    return {
        "meta_path": f"sessions/2026/07/09/{name}/meta.json",
        "summary_path": summary_path,
        "evidence_path": evidence_path,
    }


def write_malformed_meta(memory_repo: Path) -> None:
    meta_path = memory_repo / "sessions/2026/07/09/malformed/meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text('{"summary": "Command Status: dry-run would push PRIVATE_MALFORMED_CONTENT_SENTINEL"', encoding="utf-8")


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


def run_publish_readiness(memory_repo: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = run_command(
        [sys.executable, str(memory_repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(memory_repo)],
        "audit_publish_readiness",
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("audit_publish_readiness", "invalid_json", result.returncode) from exc
    return result, report


def run_archive_audit(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
        "audit_memory_archive",
        cwd=memory_repo,
        check=False,
    )


def run_search_health(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, str(memory_repo / "tools/search_memory.py"), "--health-check", "--repo", str(memory_repo)],
        "search_health",
        cwd=memory_repo,
        check=False,
    )


def run_repair(memory_repo: Path, *, apply: bool) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = run_command(
        [
            sys.executable,
            str(memory_repo / "tools/repair_publish_surfaces.py"),
            "--memory-repo",
            str(memory_repo),
            *(["--apply"] if apply else []),
        ],
        "repair_publish_surfaces",
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("repair_publish_surfaces", "invalid_json", result.returncode) from exc
    return result, report


def run_sync_dry_push(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            sys.executable,
            str(memory_repo / "tools/sync_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--dry-run",
            "--push",
        ],
        "sync_dry_push",
        cwd=memory_repo,
        check=False,
    )


def run_git_commit_all(memory_repo: Path, message: str) -> None:
    run_command(["git", "add", "."], "git_add_repaired_state", cwd=memory_repo)
    result = run_command(["git", "diff", "--cached", "--quiet"], "git_diff_cached", cwd=memory_repo, check=False)
    if result.returncode != 0:
        run_command(["git", "commit", "-m", message], "git_commit_repaired_state", cwd=memory_repo)


def is_sync_publish_intent(result: subprocess.CompletedProcess[str]) -> bool:
    return (
        result.returncode == 0
        and "Would stage allowed archive roots" in result.stdout
        and "Would push after commit." in result.stdout
    )


def is_sync_no_op(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0 and "No memory archive changes to sync." in result.stdout


def contains_private_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_MARKERS)


def privacy_leaks(*results: subprocess.CompletedProcess[str] | str) -> int:
    count = 0
    for result in results:
        text = result if isinstance(result, str) else result.stdout + result.stderr
        count += 1 if contains_private_marker(text) else 0
    return count


def readiness_failed_for_content_noise(report: dict[str, object]) -> bool:
    return report.get("status") == "failed" and int(report.get("blocked_file_count", 0)) > 0


def assert_no_private_markers_in_publish_surfaces(memory_repo: Path) -> None:
    for root in ("daily", "index", "sessions"):
        path = memory_repo / root
        if not path.exists():
            continue
        for file_path in path.rglob("*"):
            if file_path.is_file() and contains_private_marker(file_path.read_text(encoding="utf-8", errors="replace")):
                raise GateFailure("privacy", "private_marker_in_publish_surface")


def durable_content_preserved(memory_repo: Path, paths: dict[str, str]) -> bool:
    meta = json.loads((memory_repo / paths["meta_path"]).read_text(encoding="utf-8"))
    rendered_meta = json.dumps(meta, sort_keys=True)
    rendered_indexes = ""
    for path in (memory_repo / "daily").rglob("*"):
        if path.is_file():
            rendered_indexes += path.read_text(encoding="utf-8", errors="replace")
    for path in (memory_repo / "index").rglob("*.jsonl"):
        rendered_indexes += path.read_text(encoding="utf-8", errors="replace")
    evidence = (memory_repo / paths["evidence_path"]).read_text(encoding="utf-8")
    return (
        DURABLE_SUMMARY in rendered_meta
        and DURABLE_FACT in rendered_meta
        and DURABLE_TAG in rendered_meta
        and DURABLE_SUMMARY in rendered_indexes
        and DURABLE_TAG in rendered_indexes
        and "ev_001" in evidence
        and not contains_private_marker(rendered_meta + rendered_indexes + evidence)
    )


def baseline_case_result(case: ClosureCase, prompt: str, memory_repo: Path) -> dict[str, object]:
    return {
        "case": case.name,
        "prompt_contract_passed": all(prompt_contract_result(prompt, memory_repo).values()),
        "search_health_pre_repair_passed": False,
        "content_noise_blocked": False,
        "repair_apply_success": False,
        "post_repair_archive_audit_passed": False,
        "post_repair_readiness_passed": False,
        "post_repair_search_health_passed": False,
        "post_repair_publish_intent": False,
        "ambiguous_fail_closed": False,
        "malformed_fail_closed": False,
        "no_empty_commit": False,
        "durable_content_preserved": False,
        "hand_stage_bypass_count": 0,
        "free_form_search_output_used": False,
        "privacy_leak_count": privacy_leaks(prompt),
    }


def classify_case(root: Path, case: ClosureCase) -> dict[str, object]:
    memory_repo = setup_archive(root, case.name)
    prompt = render_agent_native_prompt(memory_repo, root, case.name)
    result = baseline_case_result(case, prompt, memory_repo)
    hand_stage_bypass = 0

    if case.kind == "repairable":
        session_paths = write_session(memory_repo, kind="repairable", name=case.name)
        rebuild_indexes(memory_repo, f"{case.name}:rebuild_before_repair")
        search_before = run_search_health(memory_repo)
        readiness_before_result, readiness_before = run_publish_readiness(memory_repo)
        sync_before = run_sync_dry_push(memory_repo)
        repair_result, repair_report = run_repair(memory_repo, apply=True)
        archive_after = run_archive_audit(memory_repo)
        readiness_after_result, _ = run_publish_readiness(memory_repo)
        search_after = run_search_health(memory_repo)
        sync_after = run_sync_dry_push(memory_repo)
        assert_no_private_markers_in_publish_surfaces(memory_repo)
        preserved = durable_content_preserved(memory_repo, session_paths)
        if not preserved:
            raise GateFailure(case.name, "durable_content_not_preserved")
        hand_stage_bypass += 1 if is_sync_publish_intent(sync_before) else 0
        result.update(
            {
                "search_health_pre_repair_passed": search_before.returncode == 0,
                "content_noise_blocked": readiness_failed_for_content_noise(readiness_before),
                "repair_apply_success": repair_result.returncode == 0 and repair_report.get("status") == "repaired",
                "post_repair_archive_audit_passed": archive_after.returncode == 0,
                "post_repair_readiness_passed": readiness_after_result.returncode == 0,
                "post_repair_search_health_passed": search_after.returncode == 0,
                "post_repair_publish_intent": is_sync_publish_intent(sync_after),
                "durable_content_preserved": False,
                "hand_stage_bypass_count": hand_stage_bypass,
                "privacy_leak_count": result["privacy_leak_count"]
                + privacy_leaks(
                    search_before,
                    readiness_before_result,
                    sync_before,
                    repair_result,
                    archive_after,
                    readiness_after_result,
                    search_after,
                    sync_after,
                ),
            }
        )
    elif case.kind == "ambiguous":
        write_session(memory_repo, kind="ambiguous", name=case.name)
        rebuild_indexes(memory_repo, f"{case.name}:rebuild_before_repair")
        search_before = run_search_health(memory_repo)
        readiness_before_result, readiness_before = run_publish_readiness(memory_repo)
        sync_before = run_sync_dry_push(memory_repo)
        repair_result, repair_report = run_repair(memory_repo, apply=True)
        sync_after = run_sync_dry_push(memory_repo)
        hand_stage_bypass += 1 if is_sync_publish_intent(sync_before) or is_sync_publish_intent(sync_after) else 0
        result.update(
            {
                "search_health_pre_repair_passed": search_before.returncode == 0,
                "content_noise_blocked": readiness_failed_for_content_noise(readiness_before),
                "ambiguous_fail_closed": repair_result.returncode != 0 and repair_report.get("status") == "blocked",
                "hand_stage_bypass_count": hand_stage_bypass,
                "privacy_leak_count": result["privacy_leak_count"]
                + privacy_leaks(search_before, readiness_before_result, sync_before, repair_result, sync_after),
            }
        )
    elif case.kind == "malformed":
        write_malformed_meta(memory_repo)
        search_before = run_search_health(memory_repo)
        repair_result, repair_report = run_repair(memory_repo, apply=True)
        sync_after = run_sync_dry_push(memory_repo)
        hand_stage_bypass += 1 if is_sync_publish_intent(sync_after) else 0
        result.update(
            {
                "search_health_pre_repair_passed": search_before.returncode == 0,
                "content_noise_blocked": repair_result.returncode != 0 and repair_report.get("status") == "blocked",
                "malformed_fail_closed": repair_report.get("status") == "blocked"
                and repair_report.get("metrics", {}).get("malformed_meta_count") == 1,
                "hand_stage_bypass_count": hand_stage_bypass,
                "privacy_leak_count": result["privacy_leak_count"]
                + privacy_leaks(search_before, repair_result, sync_after),
            }
        )
    elif case.kind == "clean_no_op":
        write_session(memory_repo, kind="clean", name=case.name)
        rebuild_indexes(memory_repo, f"{case.name}:rebuild_clean")
        run_git_commit_all(memory_repo, "Commit clean repaired state")
        search_before = run_search_health(memory_repo)
        archive_after = run_archive_audit(memory_repo)
        readiness_after_result, _ = run_publish_readiness(memory_repo)
        search_after = run_search_health(memory_repo)
        sync_after = run_sync_dry_push(memory_repo)
        result.update(
            {
                "search_health_pre_repair_passed": search_before.returncode == 0,
                "post_repair_archive_audit_passed": archive_after.returncode == 0,
                "post_repair_readiness_passed": readiness_after_result.returncode == 0,
                "post_repair_search_health_passed": search_after.returncode == 0,
                "no_empty_commit": is_sync_no_op(sync_after),
                "hand_stage_bypass_count": 1 if is_sync_publish_intent(sync_after) else 0,
                "privacy_leak_count": result["privacy_leak_count"]
                + privacy_leaks(search_before, archive_after, readiness_after_result, search_after, sync_after),
            }
        )
    elif case.kind == "durable_preserved":
        session_paths = write_session(memory_repo, kind="repairable", name=case.name)
        rebuild_indexes(memory_repo, f"{case.name}:rebuild_before_repair")
        search_before = run_search_health(memory_repo)
        readiness_before_result, readiness_before = run_publish_readiness(memory_repo)
        repair_result, repair_report = run_repair(memory_repo, apply=True)
        archive_after = run_archive_audit(memory_repo)
        readiness_after_result, _ = run_publish_readiness(memory_repo)
        search_after = run_search_health(memory_repo)
        assert_no_private_markers_in_publish_surfaces(memory_repo)
        preserved = durable_content_preserved(memory_repo, session_paths)
        if not preserved:
            raise GateFailure(case.name, "durable_content_not_preserved")
        result.update(
            {
                "search_health_pre_repair_passed": search_before.returncode == 0,
                "content_noise_blocked": readiness_failed_for_content_noise(readiness_before),
                "repair_apply_success": repair_result.returncode == 0 and repair_report.get("status") == "repaired",
                "post_repair_archive_audit_passed": archive_after.returncode == 0,
                "post_repair_readiness_passed": readiness_after_result.returncode == 0,
                "post_repair_search_health_passed": search_after.returncode == 0,
                "durable_content_preserved": preserved,
                "privacy_leak_count": result["privacy_leak_count"]
                + privacy_leaks(search_before, readiness_before_result, repair_result, archive_after, readiness_after_result, search_after),
            }
        )
    else:
        raise AssertionError(f"unexpected case kind: {case.kind}")

    if result["privacy_leak_count"]:
        raise GateFailure(case.name, "private_marker_rendered")
    if result["free_form_search_output_used"]:
        raise GateFailure(case.name, "free_form_search_output_used")
    return result


def build_report(case_results: list[dict[str, object]]) -> dict[str, object]:
    prompt_pass_count = sum(1 for case in case_results if case["prompt_contract_passed"])
    metrics = {
        "scheduler_prompt_contract_pass_rate": prompt_pass_count / len(case_results) if case_results else 0.0,
        "search_health_pre_repair_pass_rate": (
            sum(1 for case in case_results if case["search_health_pre_repair_passed"]) / len(case_results)
            if case_results
            else 0.0
        ),
        "content_noise_block_count": sum(1 for case in case_results if case["content_noise_blocked"]),
        "repair_apply_success_count": sum(1 for case in case_results if case["repair_apply_success"]),
        "post_repair_readiness_pass_count": sum(1 for case in case_results if case["post_repair_readiness_passed"]),
        "post_repair_search_health_pass_count": sum(
            1 for case in case_results if case["post_repair_search_health_passed"]
        ),
        "post_repair_publish_intent_count": sum(1 for case in case_results if case["post_repair_publish_intent"]),
        "ambiguous_fail_closed_count": sum(1 for case in case_results if case["ambiguous_fail_closed"]),
        "malformed_fail_closed_count": sum(1 for case in case_results if case["malformed_fail_closed"]),
        "no_empty_commit_count": sum(1 for case in case_results if case["no_empty_commit"]),
        "durable_content_preservation_count": sum(1 for case in case_results if case["durable_content_preserved"]),
        "hand_stage_bypass_count": sum(int(case["hand_stage_bypass_count"]) for case in case_results),
        "free_form_search_output_used_count": sum(1 for case in case_results if case["free_form_search_output_used"]),
        "privacy_leak_count": sum(int(case["privacy_leak_count"]) for case in case_results),
    }
    passed = (
        metrics["scheduler_prompt_contract_pass_rate"] == 1.0
        and metrics["search_health_pre_repair_pass_rate"] == 1.0
        and metrics["content_noise_block_count"] == 4
        and metrics["repair_apply_success_count"] == 2
        and metrics["post_repair_readiness_pass_count"] == 3
        and metrics["post_repair_search_health_pass_count"] == 3
        and metrics["post_repair_publish_intent_count"] == 1
        and metrics["ambiguous_fail_closed_count"] == 1
        and metrics["malformed_fail_closed_count"] == 1
        and metrics["no_empty_commit_count"] == 1
        and metrics["durable_content_preservation_count"] == 1
        and metrics["hand_stage_bypass_count"] == 0
        and metrics["free_form_search_output_used_count"] == 0
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "content_noise_contract": {
            "search_health_is_necessary_not_sufficient": True,
            "generic_content_query_required": False,
            "free_form_search_output_used": False,
            "publish_path": (
                "repair -> rebuild -> archive audit -> publish readiness -> search health -> sync dry-run"
            ),
        },
        "claim_boundary": (
            "deterministic search-healthy content-noise repair closure only; not live scheduler reliability, "
            "not live GitHub availability, not live LLM prompt-following quality, not memory quality, "
            "not ranking quality, not vector search, not ontology discovery, not private archive quality, "
            "and not public leaderboard parity"
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
        ClosureCase("search_healthy_noise_repaired_publish_ready", "repairable"),
        ClosureCase("search_healthy_ambiguous_noise_blocked", "ambiguous"),
        ClosureCase("search_healthy_malformed_meta_blocked", "malformed"),
        ClosureCase("clean_after_repair_no_empty_commit", "clean_no_op"),
        ClosureCase("durable_content_preserved", "durable_preserved"),
    ]
    return build_report([classify_case(root, case) for case in cases])


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-content-noise-closure-") as tmpdir:
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
