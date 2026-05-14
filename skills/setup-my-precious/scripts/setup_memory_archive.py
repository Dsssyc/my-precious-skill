#!/usr/bin/env python3
"""Scaffold a private agent-session memory archive.

This script copies the bundled archive template into a target directory and can
optionally initialize Git and create a private GitHub repository via gh.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_DIR / "assets" / "agent-memory-repo"


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
    shutil.copytree(TEMPLATE_DIR, target, dirs_exist_ok=True)


def init_git(target: Path, dry_run: bool) -> None:
    if (target / ".git").exists():
        return
    run(["git", "init"], cwd=target, dry_run=dry_run)


def initial_commit(target: Path, dry_run: bool) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=target,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    if not result.stdout.strip():
        return
    run(["git", "add", "."], cwd=target, dry_run=dry_run)
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
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = Path(args.path).expanduser().resolve()
    private = not args.public

    if args.mode == "github" and not args.github_repo:
        raise SystemExit("--github-repo is required when --mode github")

    copy_template(target, args.force, args.dry_run)

    if args.mode == "github":
        init_git(target, args.dry_run)
        if not args.dry_run:
            initial_commit(target, args.dry_run)
        create_github_repo(target, args.github_repo, private, args.dry_run)

    print(f"Archive ready: {target}")
    print(f'export AGENT_SESSION_MEMORY_REPO="{target}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
