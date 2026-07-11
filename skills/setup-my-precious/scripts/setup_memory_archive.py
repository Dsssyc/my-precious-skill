#!/usr/bin/env python3
"""Scaffold a private agent-session memory archive.

This script copies the bundled archive template into a target directory and can
optionally initialize Git and create a private GitHub repository via gh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_DIR / "assets" / "agent-memory-repo"
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
TEMPLATE_SKIP_DIRS = {"__pycache__"}
TEMPLATE_SKIP_SUFFIXES = {".pyc"}
TOOL_BUNDLE_REPORT_KIND = "runtime_tool_bundle_parity"
TOOL_BUNDLE_REPORT_VERSION = 1


class ToolBundleInspection(NamedTuple):
    report: dict[str, object]
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    unsafe: tuple[str, ...]


def run(command: list[str], cwd: Path | None = None, dry_run: bool = False) -> None:
    printable = " ".join(command)
    if dry_run:
        print(f"dry-run: {printable}")
        return
    subprocess.run(command, cwd=cwd, check=True)


def ensure_template() -> None:
    if not TEMPLATE_DIR.exists():
        raise SystemExit(f"template directory not found: {TEMPLATE_DIR}")


def is_effectively_empty(path: Path) -> bool:
    if not path.exists():
        return True
    return not any(path.iterdir())


def copy_template(target: Path, force: bool, dry_run: bool) -> None:
    ensure_template()
    if target.exists() and not is_effectively_empty(target) and not force:
        raise SystemExit(
            f"target is not empty: {target}\n"
            "Re-run with --force to merge the template into this directory."
        )
    if dry_run:
        print(f"dry-run: copy {TEMPLATE_DIR} -> {target}")
        return
    target.mkdir(parents=True, exist_ok=True)
    ensure_safe_template_destinations(target)
    shutil.copytree(
        TEMPLATE_DIR,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def init_git(target: Path, dry_run: bool) -> None:
    if (target / ".git").exists():
        return
    run(["git", "init"], cwd=target, dry_run=dry_run)


def has_git_history(target: Path) -> bool:
    if not (target / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=target,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode == 0


def ensure_safe_github_history(target: Path, allow_existing_history: bool) -> None:
    if allow_existing_history or not has_git_history(target):
        return
    raise SystemExit(
        "Refusing GitHub setup because the target already has existing Git history. "
        "Creating a hosted repository with --push would publish that history. "
        "Review it first, then rerun with --allow-existing-history if this is intentional."
    )


def template_files() -> list[str]:
    return sorted(
        str(path.relative_to(TEMPLATE_DIR))
        for path in TEMPLATE_DIR.rglob("*")
        if path.is_file()
        and not TEMPLATE_SKIP_DIRS.intersection(path.relative_to(TEMPLATE_DIR).parts)
        and path.suffix not in TEMPLATE_SKIP_SUFFIXES
    )


def tool_template_files() -> list[str]:
    tools_dir = TEMPLATE_DIR / "tools"
    if not tools_dir.exists():
        return []
    return sorted(
        str(path.relative_to(TEMPLATE_DIR))
        for path in tools_dir.rglob("*")
        if path.is_file()
        and not TEMPLATE_SKIP_DIRS.intersection(path.relative_to(TEMPLATE_DIR).parts)
        and path.suffix not in TEMPLATE_SKIP_SUFFIXES
    )


def is_safe_target_path(target: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(target.resolve())
    except (OSError, ValueError):
        return False
    return True


def ensure_safe_template_destinations(target: Path) -> None:
    for relative in template_files():
        destination = target / relative
        if not is_safe_target_path(target, destination):
            raise SystemExit(f"Refusing to write unsafe template path: {destination}")


def ensure_safe_tool_destinations(target: Path) -> None:
    for relative in tool_template_files():
        destination = target / relative
        if not is_safe_target_path(target, destination):
            raise SystemExit(f"Refusing to write unsafe tool path: {destination}")


def has_symlink_component(target: Path, destination: Path) -> bool:
    try:
        relative = destination.relative_to(target)
    except ValueError:
        return True
    current = target
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def bundle_sha256(entries: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def extra_target_tool_count(target: Path, expected: set[str]) -> int:
    tools_dir = target / "tools"
    if not tools_dir.is_dir() or tools_dir.is_symlink():
        return 0
    extras = 0
    for path in tools_dir.rglob("*"):
        relative = path.relative_to(target)
        if TEMPLATE_SKIP_DIRS.intersection(relative.parts) or path.suffix in TEMPLATE_SKIP_SUFFIXES:
            continue
        if (path.is_file() or path.is_symlink()) and relative.as_posix() not in expected:
            extras += 1
    return extras


def inspect_tool_bundle(target: Path, *, action: str, changed_tool_count: int = 0) -> ToolBundleInspection:
    ensure_template()
    if not target.is_dir():
        raise SystemExit(f"target archive does not exist: {target}")
    files = tool_template_files()
    if not files:
        raise SystemExit(f"template tools directory is empty: {TEMPLATE_DIR / 'tools'}")

    source_entries: list[tuple[str, bytes]] = []
    target_entries: list[tuple[str, bytes]] = []
    matching: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    unsafe: list[str] = []
    expected = set(files)

    for relative in files:
        source = TEMPLATE_DIR / relative
        source_content = source.read_bytes()
        source_entries.append((relative, source_content))
        destination = target / relative
        destination_exists = destination.exists() or destination.is_symlink()
        destination_unsafe = (
            has_symlink_component(target, destination)
            or not is_safe_target_path(target, destination)
            or (destination_exists and not destination.is_file())
        )
        if destination_unsafe:
            unsafe.append(relative)
            target_entries.append((relative, b"<unsafe>"))
            continue
        if not destination.is_file():
            missing.append(relative)
            target_entries.append((relative, b"<missing>"))
            continue
        target_content = destination.read_bytes()
        target_entries.append((relative, target_content))
        if target_content == source_content:
            matching.append(relative)
        else:
            stale.append(relative)

    status = "blocked" if unsafe else ("current" if not missing and not stale else "drifted")
    report: dict[str, object] = {
        "report_kind": TOOL_BUNDLE_REPORT_KIND,
        "report_version": TOOL_BUNDLE_REPORT_VERSION,
        "action": action,
        "status": status,
        "source_bundle_sha256": bundle_sha256(source_entries),
        "target_bundle_sha256": bundle_sha256(target_entries),
        "expected_tool_count": len(files),
        "matching_tool_count": len(matching),
        "missing_tool_count": len(missing),
        "stale_tool_count": len(stale),
        "changed_tool_count": changed_tool_count,
        "unsafe_target_count": len(unsafe),
        "extra_target_tool_count": extra_target_tool_count(target, expected),
        "privacy_leak_count": 0,
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "file_contents_rendered": False,
            "archive_text_rendered": False,
        },
        "claim_boundary": (
            "tool parity against this setup skill's bundled reusable runtime only; "
            "not latest-release discovery, live deployment correctness, or automatic code publishing"
        ),
    }
    return ToolBundleInspection(
        report=report,
        missing=tuple(missing),
        stale=tuple(stale),
        unsafe=tuple(unsafe),
    )


def prepare_tool_copy(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def replace_tool_files_transactionally(target: Path, changed: tuple[str, ...]) -> tuple[bool, bool]:
    prepared: dict[str, Path] = {}
    backups: dict[str, Path | None] = {}
    applied: list[str] = []
    try:
        for relative in changed:
            destination = target / relative
            prepared[relative] = prepare_tool_copy(TEMPLATE_DIR / relative, destination)
            if destination.exists():
                backups[relative] = prepare_tool_copy(destination, destination)
            else:
                backups[relative] = None

        for relative in changed:
            destination = target / relative
            os.replace(prepared[relative], destination)
            applied.append(relative)
        return True, True
    except OSError:
        rollback_succeeded = True
        for relative in reversed(applied):
            destination = target / relative
            backup = backups.get(relative)
            try:
                if backup is None:
                    destination.unlink(missing_ok=True)
                else:
                    os.replace(backup, destination)
            except OSError:
                rollback_succeeded = False
        return False, rollback_succeeded
    finally:
        for temp_path in (*prepared.values(), *(path for path in backups.values() if path is not None)):
            temp_path.unlink(missing_ok=True)


def refresh_tool_files(target: Path, dry_run: bool) -> tuple[dict[str, object], int]:
    action = "refresh_dry_run" if dry_run else "refresh"
    before = inspect_tool_bundle(target, action=action)
    if before.unsafe:
        return before.report, 1
    if not before.missing and not before.stale:
        return before.report, 0
    if dry_run:
        report = dict(before.report)
        report["status"] = "repairable"
        return report, 0

    changed = (*before.missing, *before.stale)
    replaced, rollback_succeeded = replace_tool_files_transactionally(target, changed)
    if not replaced:
        failed = inspect_tool_bundle(target, action=action)
        report = dict(failed.report)
        report["status"] = "blocked"
        remaining_drift = len(failed.missing) + len(failed.stale)
        report["changed_tool_count"] = (
            0 if rollback_succeeded else max(0, len(changed) - remaining_drift)
        )
        report["reason"] = "tool_replace_failed" if rollback_succeeded else "tool_rollback_failed"
        return report, 1

    after = inspect_tool_bundle(target, action=action, changed_tool_count=len(changed))
    report = dict(after.report)
    if after.unsafe or after.missing or after.stale:
        report["status"] = "blocked"
        return report, 1
    report["status"] = "refreshed"
    return report, 0


def print_tool_bundle_report(report: dict[str, object], *, report_json: bool) -> None:
    if report_json:
        print(json.dumps(report, sort_keys=True))
        return
    status = str(report["status"])
    if status == "blocked":
        unsafe_count = int(report["unsafe_target_count"])
        if unsafe_count:
            print(f"Refusing to write unsafe tool path: count={unsafe_count}", file=sys.stderr)
        else:
            print(f"Tool bundle repair blocked: {report.get('reason', 'post_refresh_parity_failed')}", file=sys.stderr)
        return
    if status == "refreshed":
        print(f"Tool files refreshed: {report['changed_tool_count']}")
    elif status == "repairable":
        print(
            "dry-run: tool bundle repairable "
            f"missing={report['missing_tool_count']} stale={report['stale_tool_count']}"
        )
    else:
        print(
            f"Tool bundle status: {status} "
            f"matching={report['matching_tool_count']}/{report['expected_tool_count']}"
        )


def stage_template_files(target: Path, dry_run: bool) -> None:
    files = template_files()
    if not files:
        return
    run(["git", "add", "--", *files], cwd=target, dry_run=dry_run)


def staged_files(target: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=target,
        check=True,
        stdout=subprocess.PIPE,
    )
    return sorted(name for name in result.stdout.decode("utf-8", errors="replace").split("\0") if name)


def initial_commit(target: Path, dry_run: bool) -> None:
    preexisting_staged = staged_files(target)
    if preexisting_staged:
        listed = "\n".join(f"- {name}" for name in preexisting_staged[:20])
        if len(preexisting_staged) > 20:
            listed += f"\n- ... and {len(preexisting_staged) - 20} more"
        raise SystemExit(
            "Refusing to create the initial archive commit because the Git index "
            f"already contains preexisting staged changes:\n{listed}\n"
            "Commit, stash, or unstage those changes before rerunning Git-backed setup."
        )

    stage_template_files(target, dry_run)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=target,
        stderr=subprocess.PIPE,
    )
    if staged.returncode == 0:
        return
    if staged.returncode not in (0, 1):
        raise subprocess.CalledProcessError(staged.returncode, staged.args, stderr=staged.stderr)
    run(["git", "commit", "-m", "Initialize agent memory archive"], cwd=target, dry_run=dry_run)


def ensure_gh_available() -> None:
    if shutil.which("gh") is None:
        raise SystemExit(
            "GitHub repository creation requested, but gh was not found. "
            "Create the remote manually or install/authenticate gh."
        )


def create_github_repo(target: Path, repo: str, private: bool, dry_run: bool) -> None:
    if dry_run:
        visibility = "--private" if private else "--public"
        print(f"dry-run: gh repo create {repo} --source {target} --remote origin --push {visibility}")
        return
    ensure_gh_available()
    command = ["gh", "repo", "create", repo, "--source", str(target), "--remote", "origin", "--push"]
    command.append("--private" if private else "--public")
    run(command, cwd=target, dry_run=dry_run)


def write_config(target: Path, config_path: Path, dry_run: bool) -> None:
    config_path = config_path.expanduser()
    if dry_run:
        print(f"dry-run: write config {config_path} memory_repo={target}")
        return
    if config_path.is_symlink():
        raise SystemExit(f"Refusing to write symlinked config path: {config_path}")
    config_path = config_path.resolve()

    payload: dict[str, object] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict):
            payload.update(existing)

    payload["version"] = 1
    payload["memory_repo"] = str(target)
    parent_existed = config_path.parent.exists()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not parent_existed:
        config_path.parent.chmod(0o700)
    config_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    config_path.chmod(0o600)
    print(f"Config written: {config_path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="Archive directory to create or update")
    parser.add_argument(
        "--mode",
        choices=("local", "github"),
        default="local",
        help="local creates a folder; github also initializes Git and creates/pushes a remote via gh",
    )
    parser.add_argument("--github-repo", help="GitHub repository name, either name or owner/name")
    parser.add_argument("--private", action="store_true", default=True, help="Create a private GitHub repo")
    parser.add_argument("--public", action="store_true", help="Create a public GitHub repo instead")
    parser.add_argument("--force", action="store_true", help="Merge template files into a non-empty directory")
    tool_action = parser.add_mutually_exclusive_group()
    tool_action.add_argument(
        "--refresh-tools",
        action="store_true",
        help="Refresh only bundled reusable tool files in an existing archive",
    )
    tool_action.add_argument(
        "--check-tools",
        action="store_true",
        help="Check whether an existing archive has the complete bundled runtime tool set",
    )
    parser.add_argument(
        "--report-json",
        action="store_true",
        help="Emit a structured aggregate report for --check-tools or --refresh-tools",
    )
    parser.add_argument(
        "--allow-existing-history",
        action="store_true",
        help="Allow GitHub mode to push preexisting Git history after manual review",
    )
    parser.add_argument("--config-path", default=str(DEFAULT_CONFIG_PATH), help="Config file that records the archive path")
    parser.add_argument("--skip-config", action="store_true", help="Do not write a local archive-location config file")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = Path(args.path).expanduser().resolve()
    private = not args.public

    if args.mode == "github" and not args.github_repo:
        raise SystemExit("--github-repo is required when --mode github")
    if (args.refresh_tools or args.check_tools) and args.mode == "github":
        raise SystemExit("--check-tools and --refresh-tools only support --mode local")
    if args.report_json and not (args.refresh_tools or args.check_tools):
        raise SystemExit("--report-json requires --check-tools or --refresh-tools")
    if args.check_tools:
        inspection = inspect_tool_bundle(target, action="check")
        print_tool_bundle_report(inspection.report, report_json=args.report_json)
        return 0 if inspection.report["status"] == "current" else 1
    if args.refresh_tools:
        report, returncode = refresh_tool_files(target, args.dry_run)
        print_tool_bundle_report(report, report_json=args.report_json)
        if not args.report_json and returncode == 0:
            print(f"Archive tools ready: {target}")
        return returncode
    if args.mode == "github":
        ensure_safe_github_history(target, args.allow_existing_history)

    copy_template(target, args.force, args.dry_run)

    if args.mode == "github":
        init_git(target, args.dry_run)
        if not args.dry_run:
            initial_commit(target, args.dry_run)
        create_github_repo(target, args.github_repo, private, args.dry_run)

    if not args.skip_config:
        write_config(target, Path(args.config_path), args.dry_run)

    print(f"Archive ready: {target}")
    print(f'Current shell override: export AGENT_SESSION_MEMORY_REPO="{target}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
