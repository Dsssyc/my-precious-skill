#!/usr/bin/env python3
"""Audit source, installed skills, deployed tools, and automation release identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


REPORT_KIND = "my_precious_release_convergence"
REPORT_VERSION = 1
PARITY_REPORT_KIND = "runtime_tool_bundle_parity"
AUTOMATION_REPORT_KIND = "live_automation_prompt_alignment_gate"
SKILL_NAMES = ("setup-my-precious", "update-my-precious", "using-my-precious")
SKIPPED_DIRS = {"__pycache__"}
SKIPPED_SUFFIXES = {".pyc"}


class AuditFailure(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def git_value(repo: Path, *arguments: str) -> str:
    result = run(["git", *arguments], cwd=repo)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        raise AuditFailure("source_git", "source_git_evidence_unavailable")
    return value


def source_git_evidence(
    source_repo: Path,
    approved_ref: str,
    integration_ref: str,
) -> dict[str, object]:
    if not source_repo.is_dir() or source_repo.is_symlink():
        raise AuditFailure("source_repository", "source_repository_unavailable")
    root = git_value(source_repo, "rev-parse", "--show-toplevel")
    try:
        root_matches = Path(root).resolve() == source_repo.resolve()
    except OSError as exc:
        raise AuditFailure("source_repository", "source_repository_unavailable") from exc
    if not root_matches:
        raise AuditFailure("source_repository", "source_repository_not_root")
    status = run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=source_repo,
    )
    if status.returncode != 0:
        raise AuditFailure("source_git", "source_git_evidence_unavailable")
    if status.stdout:
        raise AuditFailure("source_git", "source_worktree_dirty")
    head = git_value(source_repo, "rev-parse", "HEAD")
    approved = git_value(source_repo, "rev-parse", approved_ref)
    integration = git_value(source_repo, "rev-parse", integration_ref)
    return {
        "source_commit": head,
        "approved_commit": approved,
        "integration_commit": integration,
        "source_head_matches_approved_ref": head == approved,
        "approved_integration_refs_converged": approved == integration,
    }


def skipped(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return bool(SKIPPED_DIRS.intersection(relative.parts)) or path.suffix in SKIPPED_SUFFIXES


def tree_entries(root: Path, *, unavailable_reason: str) -> list[tuple[str, bytes]]:
    if not root.is_dir() or root.is_symlink():
        raise AuditFailure("skill_bundle", unavailable_reason)
    entries: list[tuple[str, bytes]] = []
    try:
        for path in sorted(root.rglob("*")):
            if skipped(path, root):
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append((relative, b"symlink\0" + os.readlink(path).encode("utf-8")))
            elif path.is_file():
                entries.append((relative, b"file\0" + path.read_bytes()))
    except OSError as exc:
        raise AuditFailure("skill_bundle", unavailable_reason) from exc
    return entries


def bundle_sha256(entries: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def skill_bundle(root: Path, *, source: bool) -> tuple[str, dict[str, str]]:
    unavailable = "source_skill_bundle_unavailable" if source else "installed_skill_bundle_unavailable"
    all_entries: list[tuple[str, bytes]] = []
    per_skill: dict[str, str] = {}
    for skill_name in SKILL_NAMES:
        entries = tree_entries(root / skill_name, unavailable_reason=unavailable)
        per_skill[skill_name] = bundle_sha256(entries)
        all_entries.extend(
            (f"{skill_name}/{relative}", content)
            for relative, content in entries
        )
    return bundle_sha256(all_entries), per_skill


def valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and value >= 0


def parse_json_object(output: str, *, stage: str, reason: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AuditFailure(stage, reason) from exc
    if not isinstance(payload, dict):
        raise AuditFailure(stage, reason)
    return payload


def tool_parity(source_repo: Path, deployment_repo: Path) -> dict[str, object]:
    setup_script = (
        source_repo
        / "skills"
        / "setup-my-precious"
        / "scripts"
        / "setup_memory_archive.py"
    )
    if not setup_script.is_file() or setup_script.is_symlink():
        raise AuditFailure("tool_parity", "source_setup_tool_unavailable")
    if not deployment_repo.is_dir() or deployment_repo.is_symlink():
        raise AuditFailure("tool_parity", "deployment_repository_unavailable")
    result = run(
        [
            sys.executable,
            str(setup_script),
            "--path",
            str(deployment_repo),
            "--check-tools",
            "--report-json",
            "--skip-config",
        ],
        cwd=source_repo,
    )
    report = parse_json_object(
        result.stdout,
        stage="tool_parity",
        reason="malformed_tool_parity_report",
    )
    counts = (
        "expected_tool_count",
        "matching_tool_count",
        "missing_tool_count",
        "stale_tool_count",
        "unsafe_target_count",
        "changed_tool_count",
        "extra_target_tool_count",
        "privacy_leak_count",
    )
    privacy = report.get("privacy")
    valid = (
        report.get("report_kind") == PARITY_REPORT_KIND
        and report.get("report_version") == 1
        and report.get("action") == "check"
        and report.get("status") in {"current", "drifted", "blocked"}
        and all(nonnegative_int(report.get(name)) for name in counts)
        and valid_sha256(report.get("source_bundle_sha256"))
        and valid_sha256(report.get("target_bundle_sha256"))
        and isinstance(privacy, dict)
        and privacy.get("aggregate_only") is True
        and privacy.get("absolute_paths_rendered") is False
        and privacy.get("file_contents_rendered") is False
        and privacy.get("archive_text_rendered") is False
        and report.get("privacy_leak_count") == 0
    )
    expected_returncode = 0 if report.get("status") == "current" else 1
    if not valid or result.returncode != expected_returncode:
        raise AuditFailure("tool_parity", "malformed_tool_parity_report")
    return report


def python_script_command_count(prompt: str, expected_script: Path) -> int:
    count = 0
    expected = str(expected_script)
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("$ "):
            stripped = stripped[2:].lstrip()
        try:
            parts = shlex.split(stripped)
        except ValueError:
            continue
        if len(parts) >= 2 and parts[0] in {"python", "python3"} and parts[1] == expected:
            count += 1
    return count


def actionable_self_update_count(prompt: str) -> int:
    count = 0
    negations = ("do not", "don't", "never", "must not", "refus", "forbid")
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("$ "):
            stripped = stripped[2:].lstrip()
        lowered = stripped.lower()
        if not stripped or any(token in lowered for token in negations):
            continue
        try:
            parts = shlex.split(stripped)
        except ValueError:
            parts = []
        command = [part.lower() for part in parts]
        command_is_self_update = (
            command[:2] == ["git", "pull"]
            or command[:2] in (["pip", "install"], ["pip3", "install"])
            or command[:3] == ["uv", "pip", "install"]
            or command[:2] == ["poetry", "install"]
            or (
                len(command) >= 2
                and command[0] in {"python", "python3"}
                and command[1].endswith("setup_memory_archive.py")
                and "--refresh-tools" in command
            )
        )
        prose_is_self_update = (
            lowered.startswith(("install skills", "pull source code", "refresh tools"))
        )
        if command_is_self_update or prose_is_self_update:
            count += 1
    return count


def automation_alignment(
    source_repo: Path,
    installed_root: Path,
    automation_config: Path,
) -> dict[str, object]:
    if not automation_config.is_file() or automation_config.is_symlink():
        raise AuditFailure("automation", "automation_configuration_unavailable")
    try:
        config = tomllib.loads(automation_config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AuditFailure("automation", "malformed_automation_configuration") from exc
    prompt = config.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AuditFailure("automation", "malformed_automation_configuration")
    gate = source_repo / "benchmarks" / "live_automation_prompt_alignment_gate.py"
    if not gate.is_file() or gate.is_symlink():
        raise AuditFailure("automation", "automation_alignment_gate_unavailable")
    result = run(
        [
            sys.executable,
            str(gate),
            "--automation-config",
            str(automation_config),
        ],
        cwd=source_repo,
    )
    report = parse_json_object(
        result.stdout,
        stage="automation",
        reason="malformed_automation_alignment_report",
    )
    metrics = report.get("metrics")
    report_valid = (
        report.get("report_kind") == AUTOMATION_REPORT_KIND
        and report.get("report_version") == 1
        and report.get("status") in {"passed", "failed"}
        and isinstance(metrics, dict)
        and isinstance(report.get("privacy"), dict)
        and report["privacy"].get("aggregate_only") is True
        and report["privacy"].get("prompt_text_rendered") is False
    )
    expected_returncode = 0 if report.get("status") == "passed" else 1
    if not report_valid or result.returncode != expected_returncode:
        raise AuditFailure("automation", "malformed_automation_alignment_report")

    setup_script = (
        installed_root
        / "setup-my-precious"
        / "scripts"
        / "setup_memory_archive.py"
    )
    adapter_script = (
        installed_root
        / "update-my-precious"
        / "scripts"
        / "run_scheduled_memory_transaction.py"
    )
    setup_count = python_script_command_count(prompt, setup_script)
    adapter_count = python_script_command_count(prompt, adapter_script)
    self_update_count = actionable_self_update_count(prompt)
    contract_aligned = (
        report.get("status") == "passed"
        and metrics.get("live_automation_alignment_pass") is True
        and config.get("status") == "ACTIVE"
        and config.get("execution_environment") == "local"
        and setup_count == 1
        and adapter_count == 1
        and self_update_count == 0
    )
    return {
        "automation_contract_aligned": contract_aligned,
        "automation_setup_command_count": setup_count,
        "automation_adapter_command_count": adapter_count,
        "automation_self_update_command_count": self_update_count,
    }


def audit(args: argparse.Namespace) -> dict[str, object]:
    source_repo = args.source_repo.expanduser().resolve()
    installed_root = args.installed_root.expanduser().resolve()
    deployment_repo = args.deployment_repo.expanduser().resolve()
    automation_config = args.automation_config.expanduser().resolve()

    git_evidence = source_git_evidence(
        source_repo,
        args.approved_ref,
        args.integration_ref,
    )
    source_skill_hash, source_skills = skill_bundle(
        source_repo / "skills",
        source=True,
    )
    installed_skill_hash, installed_skills = skill_bundle(
        installed_root,
        source=False,
    )
    skill_mismatch_count = sum(
        source_skills[name] != installed_skills[name]
        for name in SKILL_NAMES
    )
    parity = tool_parity(source_repo, deployment_repo)
    automation = automation_alignment(source_repo, installed_root, automation_config)

    parity_status = parity["status"]
    parity_current = (
        parity_status == "current"
        and parity["source_bundle_sha256"] == parity["target_bundle_sha256"]
        and parity["expected_tool_count"] == parity["matching_tool_count"]
        and parity["missing_tool_count"] == 0
        and parity["stale_tool_count"] == 0
        and parity["unsafe_target_count"] == 0
        and parity["changed_tool_count"] == 0
    )
    current = (
        git_evidence["source_head_matches_approved_ref"]
        and git_evidence["approved_integration_refs_converged"]
        and source_skill_hash == installed_skill_hash
        and parity_current
        and automation["automation_contract_aligned"]
    )
    status = "blocked" if parity_status == "blocked" else ("current" if current else "drifted")
    report: dict[str, object] = {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "status": status,
        "source_commit": git_evidence["source_commit"],
        "approved_commit": git_evidence["approved_commit"],
        "integration_commit": git_evidence["integration_commit"],
        "source_skill_bundle_sha256": source_skill_hash,
        "installed_skill_bundle_sha256": installed_skill_hash,
        "source_tool_bundle_sha256": parity["source_bundle_sha256"],
        "deployed_tool_bundle_sha256": parity["target_bundle_sha256"],
        "checks": {
            "source_worktree_clean": True,
            "source_head_matches_approved_ref": git_evidence[
                "source_head_matches_approved_ref"
            ],
            "approved_integration_refs_converged": git_evidence[
                "approved_integration_refs_converged"
            ],
            "source_installed_skills_match": source_skill_hash == installed_skill_hash,
            "source_deployed_tools_match": parity_current,
            "automation_contract_checked": True,
            "automation_contract_aligned": automation[
                "automation_contract_aligned"
            ],
        },
        "mismatch_counts": {
            "skill_tree_mismatch_count": skill_mismatch_count,
            "missing_tool_count": parity["missing_tool_count"],
            "stale_tool_count": parity["stale_tool_count"],
            "unsafe_target_count": parity["unsafe_target_count"],
            "automation_contract_mismatch_count": int(
                not automation["automation_contract_aligned"]
            ),
            "automation_self_update_command_count": automation[
                "automation_self_update_command_count"
            ],
        },
        "metrics": {
            "audit_mutation_count": 0,
            "privacy_leak_count": 0,
        },
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "automation_prompt_rendered": False,
            "archive_content_rendered": False,
            "file_contents_rendered": False,
            "raw_refs_rendered": False,
        },
        "claim_boundary": (
            "read-only approved-source-to-installed-skills-to-deployed-tools and "
            "automation-path identity only; not scheduled self-update, scheduler or network "
            "reliability, archive quality, recall quality, ranking quality, or LLM answer quality"
        ),
    }
    if status == "blocked":
        report["failure"] = {
            "stage": "tool_parity",
            "reason": "unsafe_runtime_tool_bundle",
        }
    return report


def blocked_report(failure: AuditFailure) -> dict[str, object]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "status": "blocked",
        "failure": {
            "stage": failure.stage,
            "reason": failure.reason,
        },
        "metrics": {
            "audit_mutation_count": 0,
            "privacy_leak_count": 0,
        },
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "automation_prompt_rendered": False,
            "archive_content_rendered": False,
            "file_contents_rendered": False,
            "raw_refs_rendered": False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--approved-ref", default="origin/main")
    parser.add_argument("--integration-ref", default="origin/dev-feature")
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--deployment-repo", type=Path, required=True)
    parser.add_argument("--automation-config", type=Path, required=True)
    parser.add_argument(
        "--report-json",
        action="store_true",
        help="Emit the aggregate JSON report (the only supported output format)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
    except AuditFailure as failure:
        report = blocked_report(failure)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "current" else 1


if __name__ == "__main__":
    raise SystemExit(main())
