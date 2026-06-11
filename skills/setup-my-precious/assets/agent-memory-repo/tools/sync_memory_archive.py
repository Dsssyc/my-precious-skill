#!/usr/bin/env python3
"""Safely commit and optionally push generated memory archive changes."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath


ALLOWED_ROOTS = (
    "INDEX.md",
    "config/projects.jsonl",
    "index",
    "daily",
    "sessions",
)
SECRET_PATTERNS = {
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
}


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates: list[str] = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.append(os.getcwd())
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_status_paths(repo: Path) -> list[str]:
    result = run_git(repo, ["status", "--porcelain=v1", "-uall", "-z"])
    paths: list[str] = []
    entries = result.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:]
        if path:
            paths.append(path)
        if status[0] in "RC" or status[1] in "RC":
            if index < len(entries) and entries[index]:
                paths.append(entries[index])
                index += 1
    return paths


def is_allowed_path(path: str) -> bool:
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        return False
    text = posix.as_posix()
    for root in ALLOWED_ROOTS:
        if text == root or text.startswith(f"{root}/"):
            return True
    return False


def changed_paths_by_policy(repo: Path) -> tuple[list[str], list[str]]:
    paths = sorted(set(git_status_paths(repo)))
    allowed = [path for path in paths if is_allowed_path(path)]
    unexpected = [path for path in paths if not is_allowed_path(path)]
    return allowed, unexpected


def iter_allowed_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in ALLOWED_ROOTS:
        path = repo / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return sorted(files)


def scan_for_secrets(repo: Path) -> list[tuple[str, str, int]]:
    hits: list[tuple[str, str, int]] = []
    for path in iter_allowed_files(repo):
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(repo).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for category, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    hits.append((relative, category, line_number))
    return hits


def existing_allowed_roots(repo: Path) -> list[str]:
    return [root for root in ALLOWED_ROOTS if (repo / root).exists()]


def default_message() -> str:
    return f"Update memory archive {date.today().isoformat()}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--message", default=default_message(), help="Commit message")
    parser.add_argument("--push", action="store_true", help="Push after a successful commit")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print actions without committing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_memory_repo(args.memory_repo)

    allowed, unexpected = changed_paths_by_policy(repo)
    if unexpected:
        print("Refusing to sync because unexpected files changed:", file=sys.stderr)
        for path in unexpected[:50]:
            print(f"- {path}", file=sys.stderr)
        if len(unexpected) > 50:
            print(f"- ... and {len(unexpected) - 50} more", file=sys.stderr)
        return 1

    secret_hits = scan_for_secrets(repo)
    if secret_hits:
        print("Refusing to sync because generated archive files contain key-like values:", file=sys.stderr)
        for path, category, line_number in secret_hits[:50]:
            print(f"- {path}:{line_number} category={category}", file=sys.stderr)
        if len(secret_hits) > 50:
            print(f"- ... and {len(secret_hits) - 50} more", file=sys.stderr)
        return 1

    if not allowed:
        print("No memory archive changes to sync.")
        return 0

    roots = existing_allowed_roots(repo)
    if args.dry_run:
        print("Would stage allowed archive roots:")
        for root in roots:
            print(f"- {root}")
        print(f"Would commit: {args.message}")
        if args.push:
            print("Would push after commit.")
        return 0

    run_git(repo, ["add", "--", *roots])
    staged = run_git(repo, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        print("No staged memory archive changes to commit.")
        return 0
    if staged.returncode not in (0, 1):
        sys.stderr.write(staged.stderr)
        return staged.returncode

    check = run_git(repo, ["diff", "--cached", "--check"], check=False)
    if check.returncode:
        sys.stdout.write(check.stdout)
        sys.stderr.write(check.stderr)
        return check.returncode

    commit = run_git(repo, ["commit", "-m", args.message], check=False)
    sys.stdout.write(commit.stdout)
    sys.stderr.write(commit.stderr)
    if commit.returncode:
        return commit.returncode

    if args.push:
        push = run_git(repo, ["push"], check=False)
        sys.stdout.write(push.stdout)
        sys.stderr.write(push.stderr)
        if push.returncode:
            return push.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
