#!/usr/bin/env python3
"""Safely commit and optionally push generated memory archive changes."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath


ALLOWED_ROOTS = (
    "INDEX.md",
    "config/projects.jsonl",
    "index",
    "daily",
    "memories/explicit.jsonl",
    "sessions",
)
REVIEWED_MEMORY_NODE_FILES = (
    "memories/global.jsonl",
    "memories/domains.jsonl",
    "memories/projects.jsonl",
)
SECRET_PATTERNS = {
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
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


def run_git(
    repo: Path,
    args: list[str],
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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


def is_allowed_path(path: str, *, include_reviewed_memory_nodes: bool = False) -> bool:
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        return False
    text = posix.as_posix()
    if include_reviewed_memory_nodes and text in REVIEWED_MEMORY_NODE_FILES:
        return True
    for root in ALLOWED_ROOTS:
        if text == root or text.startswith(f"{root}/"):
            return True
    return False


def changed_paths_by_policy(
    repo: Path,
    *,
    include_reviewed_memory_nodes: bool = False,
) -> tuple[list[str], list[str]]:
    paths = sorted(set(git_status_paths(repo)))
    allowed = [
        path
        for path in paths
        if is_allowed_path(path, include_reviewed_memory_nodes=include_reviewed_memory_nodes)
    ]
    unexpected = [
        path
        for path in paths
        if not is_allowed_path(path, include_reviewed_memory_nodes=include_reviewed_memory_nodes)
    ]
    return allowed, unexpected


def iter_allowed_files(repo: Path, *, include_reviewed_memory_nodes: bool = False) -> list[Path]:
    files: list[Path] = []
    for root in ALLOWED_ROOTS:
        path = repo / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    if include_reviewed_memory_nodes:
        files.extend(
            path
            for relative in REVIEWED_MEMORY_NODE_FILES
            if (path := repo / relative).is_file()
        )
    return sorted(set(files))


def scan_for_secrets(
    repo: Path,
    *,
    include_reviewed_memory_nodes: bool = False,
) -> list[tuple[str, str, int]]:
    hits: list[tuple[str, str, int]] = []
    for path in iter_allowed_files(
        repo,
        include_reviewed_memory_nodes=include_reviewed_memory_nodes,
    ):
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


def run_archive_audit(repo: Path, *, required: bool = False) -> int:
    audit_script = repo / "tools" / "audit_memory_archive.py"
    if not audit_script.exists():
        if required:
            print("Refusing to sync because archive audit helper is missing.", file=sys.stderr)
            return 1
        return 0
    result = subprocess.run(
        [sys.executable, str(audit_script), "--memory-repo", str(repo)],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        print("Refusing to sync because archive audit failed.", file=sys.stderr)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result.returncode


def run_publish_readiness_audit(repo: Path) -> int:
    audit_script = repo / "tools" / "audit_publish_readiness.py"
    if not audit_script.exists():
        print("Refusing to sync because publish readiness audit helper is missing.", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, str(audit_script), "--memory-repo", str(repo)],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        print("Refusing to sync because publish readiness failed.", file=sys.stderr)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result.returncode


def run_search_health_check(repo: Path) -> int:
    search_script = repo / "tools" / "search_memory.py"
    if not search_script.exists():
        print("Refusing to sync because search health helper is missing.", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, str(search_script), "--repo", str(repo), "--health-check"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        print("Refusing to sync because search health check failed.", file=sys.stderr)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
    return result.returncode


def path_exists_or_is_tracked(repo: Path, relative: str) -> bool:
    if (repo / relative).exists():
        return True
    tracked = run_git(repo, ["ls-files", "--error-unmatch", "--", relative], check=False)
    return tracked.returncode == 0


def existing_allowed_roots(repo: Path, *, include_reviewed_memory_nodes: bool = False) -> list[str]:
    roots = [root for root in ALLOWED_ROOTS if path_exists_or_is_tracked(repo, root)]
    if include_reviewed_memory_nodes:
        roots.extend(
            relative
            for relative in REVIEWED_MEMORY_NODE_FILES
            if path_exists_or_is_tracked(repo, relative)
        )
    return roots


def staged_paths(repo: Path, *, env: dict[str, str] | None = None) -> list[str]:
    result = run_git(repo, ["diff", "--cached", "--name-only", "-z"], env=env)
    return sorted(path for path in result.stdout.split("\0") if path)


def stage_and_validate(
    repo: Path,
    roots: list[str],
    *,
    include_reviewed_memory_nodes: bool,
    env: dict[str, str] | None = None,
) -> int:
    add = run_git(repo, ["add", "--", *roots], check=False, env=env)
    if add.returncode:
        sys.stdout.write(add.stdout)
        sys.stderr.write(add.stderr)
        return add.returncode

    unexpected = [
        path
        for path in staged_paths(repo, env=env)
        if not is_allowed_path(path, include_reviewed_memory_nodes=include_reviewed_memory_nodes)
    ]
    if unexpected:
        print("Refusing to sync because staged files exceed the allowed archive policy:", file=sys.stderr)
        for path in unexpected[:50]:
            print(f"- {path}", file=sys.stderr)
        if len(unexpected) > 50:
            print(f"- ... and {len(unexpected) - 50} more", file=sys.stderr)
        return 1

    check = run_git(repo, ["diff", "--cached", "--check"], check=False, env=env)
    if check.returncode:
        sys.stdout.write(check.stdout)
        sys.stderr.write(check.stderr)
    return check.returncode


def validate_dry_run_stage(
    repo: Path,
    roots: list[str],
    *,
    include_reviewed_memory_nodes: bool,
) -> int:
    index_result = run_git(repo, ["rev-parse", "--git-path", "index"])
    index_path = Path(index_result.stdout.strip())
    if not index_path.is_absolute():
        index_path = (repo / index_path).resolve()
    with tempfile.TemporaryDirectory(prefix="memory-sync-index-") as tmpdir:
        temporary_index = Path(tmpdir) / "index"
        if index_path.is_file():
            shutil.copy2(index_path, temporary_index)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(temporary_index)
        return stage_and_validate(
            repo,
            roots,
            include_reviewed_memory_nodes=include_reviewed_memory_nodes,
            env=env,
        )


def default_message() -> str:
    return f"Update memory archive {date.today().isoformat()}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--message", default=default_message(), help="Commit message")
    parser.add_argument("--push", action="store_true", help="Push after a successful commit")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print actions without committing")
    parser.add_argument(
        "--include-reviewed-memory-nodes",
        action="store_true",
        help="Also publish deterministic-gate-reviewed automatic memory layer files",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = resolve_memory_repo(args.memory_repo)

    include_reviewed = args.include_reviewed_memory_nodes
    allowed, unexpected = changed_paths_by_policy(
        repo,
        include_reviewed_memory_nodes=include_reviewed,
    )
    if unexpected:
        print("Refusing to sync because unexpected files changed:", file=sys.stderr)
        for path in unexpected[:50]:
            print(f"- {path}", file=sys.stderr)
        if len(unexpected) > 50:
            print(f"- ... and {len(unexpected) - 50} more", file=sys.stderr)
        return 1

    secret_hits = scan_for_secrets(
        repo,
        include_reviewed_memory_nodes=include_reviewed,
    )
    if secret_hits:
        print("Refusing to sync because generated archive files contain key-like values:", file=sys.stderr)
        for path, category, line_number in secret_hits[:50]:
            print(f"- {path}:{line_number} category={category}", file=sys.stderr)
        if len(secret_hits) > 50:
            print(f"- ... and {len(secret_hits) - 50} more", file=sys.stderr)
        return 1

    if include_reviewed:
        audit_status = run_archive_audit(repo, required=True)
        if audit_status:
            return audit_status
        publish_status = run_publish_readiness_audit(repo)
        if publish_status:
            return publish_status
        health_status = run_search_health_check(repo)
        if health_status:
            return health_status
    else:
        publish_status = run_publish_readiness_audit(repo)
        if publish_status:
            return publish_status
        audit_status = run_archive_audit(repo)
        if audit_status:
            return audit_status

    if not allowed:
        print("No memory archive changes to sync.")
        return 0

    roots = existing_allowed_roots(
        repo,
        include_reviewed_memory_nodes=include_reviewed,
    )
    if args.dry_run:
        stage_status = validate_dry_run_stage(
            repo,
            roots,
            include_reviewed_memory_nodes=include_reviewed,
        )
        if stage_status:
            return stage_status
        print("Would stage allowed archive roots:")
        for root in roots:
            print(f"- {root}")
        print(f"Would commit: {args.message}")
        if args.push:
            print("Would push after commit.")
        return 0

    stage_status = stage_and_validate(
        repo,
        roots,
        include_reviewed_memory_nodes=include_reviewed,
    )
    if stage_status:
        return stage_status
    staged = run_git(repo, ["diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        print("No staged memory archive changes to commit.")
        return 0
    if staged.returncode not in (0, 1):
        sys.stderr.write(staged.stderr)
        return staged.returncode

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
