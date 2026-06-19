#!/usr/bin/env python3
"""Scaffold a private agent-session memory archive.

This script copies the bundled archive template into a target directory and can
optionally initialize Git and create a private GitHub repository via gh.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_DIR / "assets" / "agent-memory-repo"
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
TEMPLATE_SKIP_DIRS = {"__pycache__"}
TEMPLATE_SKIP_SUFFIXES = {".pyc"}


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
    config_path = config_path.expanduser().resolve()
    if dry_run:
        print(f"dry-run: write config {config_path} memory_repo={target}")
        return

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
