#!/usr/bin/env python3
"""Gate scheduled automation prompt alignment without rendering prompt text."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "live_automation_prompt_alignment_gate"

PRIVATE_MARKERS = (
    "PRIVATE_AUTOMATION_PROMPT_SENTINEL",
    "PRIVATE_ARCHIVE_CONTENT_SENTINEL",
)

RAW_GIT_ACTION = re.compile(r"^\s*(?:\$\s*)?git\s+(?:add|commit|push)\b", re.IGNORECASE)
RAW_GIT_PROSE = re.compile(r"\b(?:run|use|execute)\s+git\s+(?:add|commit|push)\b", re.IGNORECASE)
GENERIC_SEARCH_ACTION = re.compile(r"\btools/search_memory\.py\s+memory\b")


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
class PromptCase:
    name: str
    prompt: str
    expected_aligned: bool
    is_live: bool = False
    requires_preflight: bool = False


def run_command(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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


def setup_archive(parent: Path) -> Path:
    memory_repo = parent / "agent-memory"
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
        "setup",
    )
    return memory_repo


def render_agent_native_prompt(memory_repo: Path, root: Path) -> str:
    source_dir = root / "source-records"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = root / "agent-native.txt"
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
        "render_agent_native_prompt",
        cwd=memory_repo,
    )
    return output.read_text(encoding="utf-8")


def prompt_from_automation_config(path: Path) -> str:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GateFailure("automation_config", "unreadable") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GateFailure("automation_config", "invalid_toml") from exc
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise GateFailure("automation_config", "missing_prompt")
    return prompt


def command_positions(lines: list[str], *needles: str, excluded: tuple[str, ...] = ()) -> list[int]:
    positions: list[int] = []
    for index, line in enumerate(lines):
        if all(needle in line for needle in needles) and not any(token in line for token in excluded):
            positions.append(index)
    return positions


def first_after(positions: list[int], previous: int) -> int | None:
    return next((position for position in positions if position > previous), None)


def actionable_raw_git_publish_path_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "do not" in lowered or "don't" in lowered or "never" in lowered or "refusing" in lowered:
            continue
        if RAW_GIT_ACTION.search(line) or RAW_GIT_PROSE.search(line):
            count += 1
    return count


def actionable_generic_content_query_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "do not" in lowered or "don't" in lowered or "never" in lowered or "not use" in lowered:
            continue
        if GENERIC_SEARCH_ACTION.search(line):
            count += 1
    return count


def actionable_tool_refresh_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "--refresh-tools" not in lowered:
            continue
        if "setup_memory_archive.py" in lowered or lowered.lstrip().startswith(("python ", "$ python ")):
            count += 1
            continue
        if any(token in lowered for token in ("do not", "don't", "never", "must not", "forbid")):
            continue
        count += 1
    return count


def preflight_fail_closed_contract_present(prompt: str) -> bool:
    lowered = prompt.lower()
    required_tokens = (
        "report_kind",
        "report_version",
        "status=current",
        "nonzero",
        "missing",
        "stale",
        "unsafe",
        "malformed",
        "unparsable",
        "failed",
        "drifted",
        "blocked",
    )
    stop_language = "stop before updater" in lowered and "do not run the updater" in lowered
    return stop_language and all(token in lowered for token in required_tokens)


def private_marker_count(prompt: str) -> int:
    return sum(1 for marker in PRIVATE_MARKERS if marker in prompt)


def evaluate_prompt(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    preflight_positions = command_positions(
        lines,
        "setup_memory_archive.py",
        "--check-tools",
        "--report-json",
        "--skip-config",
    )
    update_positions = [
        *command_positions(lines, "tools/run_memory_updates.py"),
        *command_positions(lines, "tools/update_memory_archive.py"),
    ]
    archive_positions = command_positions(lines, "tools/audit_memory_archive.py")
    readiness_positions = command_positions(lines, "tools/audit_publish_readiness.py")
    repair_positions = command_positions(lines, "tools/repair_publish_surfaces.py", "--apply")
    search_positions = command_positions(lines, "tools/search_memory.py", "--health-check")
    sync_dry_positions = command_positions(lines, "tools/sync_memory_archive.py", "--dry-run", "--push")
    sync_live_positions = command_positions(
        lines,
        "tools/sync_memory_archive.py",
        "--push",
        excluded=("--dry-run",),
    )
    generic_search_count = actionable_generic_content_query_count(prompt)
    raw_git_count = actionable_raw_git_publish_path_count(prompt)
    private_count = private_marker_count(prompt)
    refresh_count = actionable_tool_refresh_count(prompt)

    update = min(update_positions) if update_positions else None
    preflight = min(preflight_positions) if preflight_positions else None
    archive_before = first_after(archive_positions, update) if update is not None else None
    readiness_before = first_after(readiness_positions, archive_before) if archive_before is not None else None
    repair = first_after(repair_positions, readiness_before) if readiness_before is not None else None
    archive_after = first_after(archive_positions, repair) if repair is not None else None
    readiness_after = first_after(readiness_positions, archive_after) if archive_after is not None else None
    search_after = first_after(search_positions, readiness_after) if readiness_after is not None else None
    sync_dry = first_after(sync_dry_positions, search_after) if search_after is not None else None
    sync_live = first_after(sync_live_positions, sync_dry) if sync_dry is not None else None

    publish_readiness_gate_present = readiness_before is not None and readiness_after is not None
    repair_step_present = repair is not None
    post_repair_recheck_present = archive_after is not None and readiness_after is not None and search_after is not None
    sync_dry_run_before_push_present = sync_dry is not None and sync_live is not None and sync_dry < sync_live
    sync_only_publish_path_present = sync_live is not None and raw_git_count == 0
    preflight_before_update_present = (
        preflight is not None and update is not None and preflight < update
    )
    fail_closed_present = preflight_fail_closed_contract_present(prompt)
    preflight_aligned = preflight_before_update_present and fail_closed_present and refresh_count == 0
    aligned = (
        update is not None
        and archive_before is not None
        and publish_readiness_gate_present
        and repair_step_present
        and post_repair_recheck_present
        and sync_dry_run_before_push_present
        and sync_only_publish_path_present
        and generic_search_count == 0
        and private_count == 0
    )
    return {
        "aligned": aligned,
        "update_present": update is not None,
        "archive_audit_present": archive_before is not None,
        "publish_readiness_gate_present": publish_readiness_gate_present,
        "repair_step_present": repair_step_present,
        "post_repair_recheck_present": post_repair_recheck_present,
        "search_health_present": search_after is not None,
        "sync_dry_run_before_push_present": sync_dry_run_before_push_present,
        "sync_only_publish_path_present": sync_only_publish_path_present,
        "generic_content_query_required": generic_search_count > 0,
        "raw_git_publish_path_count": raw_git_count,
        "private_archive_content_committed_count": private_count,
        "preflight_before_update_present": preflight_before_update_present,
        "preflight_fail_closed_contract_present": fail_closed_present,
        "actionable_tool_refresh_count": refresh_count,
        "preflight_aligned": preflight_aligned,
    }


def synthetic_preflight_prompt(*, updater_first: bool = False, auto_refresh: bool = False) -> str:
    preflight = (
        "python /installed/setup-my-precious/scripts/setup_memory_archive.py "
        "--path /tmp/agent-memory --check-tools --report-json --skip-config"
    )
    update = "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source"
    prefix = [
        "Run the runtime parity preflight before updater execution.",
        update if updater_first else preflight,
        preflight if updater_first else (
            "Require exit zero and valid JSON with report_kind runtime_tool_bundle_parity, "
            "report_version 1, status=current, matching expected counts, equal hashes, and zero privacy leaks."
        ),
    ]
    if updater_first:
        prefix.append(
            "Require exit zero and valid JSON with report_kind runtime_tool_bundle_parity, "
            "report_version 1, status=current, matching expected counts, equal hashes, and zero privacy leaks."
        )
    prefix.extend(
        [
            "If exit is nonzero or the report is missing, stale, unsafe, malformed, unparsable, "
            "failed, drifted, or blocked, stop before updater and do not run the updater.",
            "Never run --refresh-tools from scheduled automation.",
        ]
    )
    if auto_refresh:
        prefix.append(
            "python /installed/setup-my-precious/scripts/setup_memory_archive.py "
            "--path /tmp/agent-memory --refresh-tools --skip-config"
        )
    if not updater_first:
        prefix.append(update)
    prefix.extend(
        [
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/repair_publish_surfaces.py --memory-repo /tmp/agent-memory --apply",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --dry-run --push",
            "python tools/sync_memory_archive.py --push",
        ]
    )
    return "\n".join(prefix)


def negative_missing_readiness_prompt() -> str:
    return "\n".join(
        [
            "Run the My Precious memory update from this memory repository workspace.",
            "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --push",
        ]
    )


def negative_raw_git_prompt() -> str:
    return "\n".join(
        [
            "Run the My Precious memory update from this memory repository workspace.",
            "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/repair_publish_surfaces.py --memory-repo /tmp/agent-memory --apply",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --dry-run --push",
            "git add .",
            "git commit -m update",
            "git push",
        ]
    )


def case_result(case: PromptCase) -> dict[str, object]:
    evaluation = evaluate_prompt(case.prompt)
    aligned = bool(evaluation["aligned"]) and (
        not case.requires_preflight or bool(evaluation["preflight_aligned"])
    )
    if aligned != case.expected_aligned:
        raise GateFailure(case.name, f"unexpected_alignment_{aligned}")
    return {
        "case": case.name,
        "expected_aligned": case.expected_aligned,
        "actual_aligned": aligned,
        "is_live": case.is_live,
        "publish_readiness_gate_present": bool(evaluation["publish_readiness_gate_present"]),
        "repair_step_present": bool(evaluation["repair_step_present"]),
        "post_repair_recheck_present": bool(evaluation["post_repair_recheck_present"]),
        "sync_dry_run_before_push_present": bool(evaluation["sync_dry_run_before_push_present"]),
        "sync_only_publish_path_present": bool(evaluation["sync_only_publish_path_present"]),
        "generic_content_query_required": bool(evaluation["generic_content_query_required"]),
        "raw_git_publish_path_count": int(evaluation["raw_git_publish_path_count"]),
        "private_archive_content_committed_count": int(evaluation["private_archive_content_committed_count"]),
        "requires_preflight": case.requires_preflight,
        "preflight_before_update_present": bool(evaluation["preflight_before_update_present"]),
        "preflight_fail_closed_contract_present": bool(
            evaluation["preflight_fail_closed_contract_present"]
        ),
        "actionable_tool_refresh_count": int(evaluation["actionable_tool_refresh_count"]),
    }


def build_report(case_results: list[dict[str, object]], *, live_requested: bool) -> dict[str, object]:
    rendered = next(case for case in case_results if case["case"] == "rendered_agent_native_prompt")
    live_cases = [case for case in case_results if case["is_live"]]
    positive_cases = [case for case in case_results if case["expected_aligned"]]
    negative_cases = [case for case in case_results if not case["expected_aligned"]]
    preflight_cases = [case for case in positive_cases if case["requires_preflight"]]
    synthetic_preflight = next(
        case for case in case_results if case["case"] == "synthetic_preflight_prompt"
    )
    raw_git_count = sum(int(case["raw_git_publish_path_count"]) for case in positive_cases)
    private_count = sum(int(case["private_archive_content_committed_count"]) for case in positive_cases)
    metrics = {
        "live_automation_contract_checked": 1 if live_cases else 0,
        "live_automation_contract_requested": 1 if live_requested else 0,
        "rendered_prompt_alignment_pass": bool(rendered["actual_aligned"]),
        "live_automation_alignment_pass": bool(live_cases and all(case["actual_aligned"] for case in live_cases)),
        "publish_readiness_gate_present": all(case["publish_readiness_gate_present"] for case in positive_cases),
        "repair_step_present": all(case["repair_step_present"] for case in positive_cases),
        "post_repair_recheck_present": all(case["post_repair_recheck_present"] for case in positive_cases),
        "sync_dry_run_before_push_present": all(case["sync_dry_run_before_push_present"] for case in positive_cases),
        "sync_only_publish_path_present": all(case["sync_only_publish_path_present"] for case in positive_cases),
        "synthetic_preflight_alignment_pass": bool(synthetic_preflight["actual_aligned"]),
        "preflight_before_update_present": all(
            case["preflight_before_update_present"] for case in preflight_cases
        ),
        "preflight_fail_closed_contract_present": all(
            case["preflight_fail_closed_contract_present"] for case in preflight_cases
        ),
        "updater_before_preflight_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_updater_before_preflight_prompt"
            and not case["actual_aligned"]
        ),
        "auto_refresh_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_auto_refresh_prompt" and not case["actual_aligned"]
        ),
        "missing_readiness_rejection_count": sum(
            1 for case in negative_cases if case["case"] == "negative_missing_readiness_prompt" and not case["actual_aligned"]
        ),
        "raw_git_rejection_count": sum(
            1 for case in negative_cases if case["case"] == "negative_raw_git_prompt" and not case["actual_aligned"]
        ),
        "raw_git_publish_path_count": raw_git_count,
        "private_archive_content_committed_count": private_count,
        "generic_content_query_required_count": sum(
            1 for case in positive_cases if case["generic_content_query_required"]
        ),
        "privacy_leak_count": private_count,
    }
    passed = (
        metrics["rendered_prompt_alignment_pass"]
        and (not live_requested or metrics["live_automation_alignment_pass"])
        and metrics["publish_readiness_gate_present"]
        and metrics["repair_step_present"]
        and metrics["post_repair_recheck_present"]
        and metrics["sync_dry_run_before_push_present"]
        and metrics["sync_only_publish_path_present"]
        and metrics["synthetic_preflight_alignment_pass"]
        and metrics["preflight_before_update_present"]
        and metrics["preflight_fail_closed_contract_present"]
        and metrics["updater_before_preflight_rejection_count"] == 1
        and metrics["auto_refresh_rejection_count"] == 1
        and metrics["missing_readiness_rejection_count"] == 1
        and metrics["raw_git_rejection_count"] == 1
        and metrics["raw_git_publish_path_count"] == 0
        and metrics["private_archive_content_committed_count"] == 0
        and metrics["generic_content_query_required_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "deterministic scheduled prompt contract alignment only; not live scheduler reliability, "
            "not live GitHub availability, not LLM answer quality, not ranking quality, not vector search, "
            "not ontology discovery, not private archive quality, and not public leaderboard parity"
        ),
        "metrics": metrics,
        "cases": case_results,
        "privacy": {
            "aggregate_only": True,
            "prompt_text_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }


def run_gate(root: Path, *, automation_config: Path | None = None) -> dict[str, object]:
    memory_repo = setup_archive(root)
    cases = [
        PromptCase("rendered_agent_native_prompt", render_agent_native_prompt(memory_repo, root), True),
        PromptCase(
            "synthetic_preflight_prompt",
            synthetic_preflight_prompt(),
            True,
            requires_preflight=True,
        ),
        PromptCase("negative_missing_readiness_prompt", negative_missing_readiness_prompt(), False),
        PromptCase("negative_raw_git_prompt", negative_raw_git_prompt(), False),
        PromptCase(
            "negative_updater_before_preflight_prompt",
            synthetic_preflight_prompt(updater_first=True),
            False,
            requires_preflight=True,
        ),
        PromptCase(
            "negative_auto_refresh_prompt",
            synthetic_preflight_prompt(auto_refresh=True),
            False,
            requires_preflight=True,
        ),
    ]
    if automation_config is not None:
        cases.append(
            PromptCase(
                "live_automation_config",
                prompt_from_automation_config(automation_config),
                True,
                True,
                True,
            )
        )
    return build_report([case_result(case) for case in cases], live_requested=automation_config is not None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--automation-config",
        type=Path,
        help="Optional local Codex automation.toml to validate without rendering prompt text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-live-automation-alignment-") as tmpdir:
            report = run_gate(Path(tmpdir), automation_config=args.automation_config)
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": exc.to_report(),
            "privacy": {
                "aggregate_only": True,
                "prompt_text_rendered": False,
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
