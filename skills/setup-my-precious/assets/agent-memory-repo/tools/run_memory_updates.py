#!/usr/bin/env python3
"""Run memory archive updates for registered and discovered projects.

This runner bootstraps an empty deployment repository by scanning a shared
source-record directory, discovering project paths from record metadata, and
then invoking the per-project updater for each enabled project.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


CONFIG_CANDIDATES = (
    "MY_PRECIOUS_CONFIG",
    "AGENT_SESSION_MEMORY_CONFIG",
)
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
DEFAULT_PATTERNS = ("*.jsonl", "*.json")
PROJECT_PATH_KEYS = {
    "cwd",
    "project_path",
    "working_directory",
    "current_working_directory",
    "workspace",
    "repo_path",
    "repository_path",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env"}
PROJECT_REGISTRY = Path("config/projects.jsonl")


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def configured_memory_repos() -> list[str]:
    config_paths: list[str] = []
    for name in CONFIG_CANDIDATES:
        value = os.environ.get(name)
        if value:
            config_paths.append(value)
    config_paths.append(str(DEFAULT_CONFIG_PATH))

    repos: list[str] = []
    for candidate in config_paths:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        value = payload.get("memory_repo")
        if isinstance(value, str) and value.strip():
            repos.append(value)
    return repos


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates: list[str] = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(configured_memory_repos())
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit(
        "No memory repository found. Run setup-my-precious, pass --memory-repo, "
        "or set AGENT_SESSION_MEMORY_REPO."
    )


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def iter_candidate_files(source_dir: Path, patterns: tuple[str, ...]) -> Iterable[Path]:
    for pattern in patterns:
        for path in source_dir.rglob(pattern):
            if path.is_file() and not should_skip(path.relative_to(source_dir)):
                yield path


def iter_json_values(path: Path, text: str) -> Iterable[object]:
    if path.suffix == ".jsonl":
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                continue
        return

    if path.suffix == ".json":
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            return
        return

    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            yield json.loads(raw_line)
        except json.JSONDecodeError:
            continue


def walk_json_values(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_values(child)


def discover_projects(source_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    discovered: set[Path] = set()
    if not source_dir.exists() or not source_dir.is_dir():
        return []
    for path in iter_candidate_files(source_dir, patterns):
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        for value in iter_json_values(path, text):
            for key, child in walk_json_values(value):
                if key in PROJECT_PATH_KEYS and isinstance(child, str) and child.strip():
                    candidate = Path(child).expanduser()
                    if candidate.is_absolute():
                        discovered.add(candidate.resolve())
    return sorted(discovered, key=lambda item: item.as_posix())


def registry_path(memory_repo: Path) -> Path:
    return memory_repo / PROJECT_REGISTRY


def load_registry(memory_repo: Path) -> dict[str, dict[str, object]]:
    projects: dict[str, dict[str, object]] = {}
    path = registry_path(memory_repo)
    if not path.exists():
        return projects
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            project_path = row.get("project_path")
            if not isinstance(project_path, str) or not project_path.strip():
                continue
            resolved = Path(project_path).expanduser()
            if resolved.is_absolute():
                key = str(resolved.resolve())
            else:
                key = str(resolved)
            normalized = dict(row)
            normalized["project_path"] = key
            projects[key] = normalized
    return projects


def merge_discovered_projects(
    registered: dict[str, dict[str, object]],
    discovered: Iterable[Path],
    source_dir: Path,
) -> tuple[dict[str, dict[str, object]], int]:
    merged = dict(registered)
    now = utc_now_text()
    added = 0
    for project_path in discovered:
        key = str(project_path.resolve())
        if key in merged:
            continue
        merged[key] = {
            "project_path": key,
            "source_dir": str(source_dir),
            "enabled": True,
            "source": "discovered",
            "discovered_at": now,
        }
        added += 1
    return merged, added


def write_registry(memory_repo: Path, projects: dict[str, dict[str, object]], dry_run: bool) -> None:
    path = registry_path(memory_repo)
    if dry_run:
        print(f"dry-run: write project registry {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(projects[key], sort_keys=True) for key in sorted(projects)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def enabled_projects(projects: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(projects):
        row = projects[key]
        if row.get("enabled", True) is False:
            continue
        rows.append(row)
    return rows


def run_project_update(
    memory_repo: Path,
    project: dict[str, object],
    default_source_dir: Path,
    dry_run: bool,
    max_records: int | None,
    patterns: tuple[str, ...],
    allow_redacted_secrets: bool,
) -> int:
    project_path = str(project["project_path"])
    source_dir = Path(str(project.get("source_dir") or default_source_dir)).expanduser().resolve()
    command = [
        sys.executable,
        str(memory_repo / "tools" / "update_memory_archive.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        project_path,
        "--require-project-metadata",
    ]
    project_name = project.get("project")
    if isinstance(project_name, str) and project_name.strip():
        command.extend(["--project", project_name])
    if max_records is not None:
        command.extend(["--max-records", str(max_records)])
    for pattern in patterns:
        command.extend(["--pattern", pattern])
    if allow_redacted_secrets:
        command.append("--allow-redacted-secrets")
    if dry_run:
        command.append("--dry-run")

    print(f"Updating project: {project_path}")
    result = subprocess.run(command, cwd=memory_repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--source-dir", required=True, help="Shared source record directory to scan")
    parser.add_argument("--pattern", action="append", help="Discovery glob pattern; may be repeated")
    parser.add_argument("--max-records", type=int, help="Maximum records to archive per project")
    parser.add_argument(
        "--allow-redacted-secrets",
        action="store_true",
        help="Allow per-project updates to archive records with detected secrets after redaction",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover and run project updates without writing records")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    source_dir = Path(args.source_dir).expanduser().resolve()
    patterns = tuple(args.pattern or DEFAULT_PATTERNS)

    registered = load_registry(memory_repo)
    discovered = discover_projects(source_dir, patterns)
    projects, added = merge_discovered_projects(registered, discovered, source_dir)
    write_registry(memory_repo, projects, args.dry_run)

    runnable = enabled_projects(projects)
    print(f"Memory repo: {memory_repo}")
    print(f"Source dir: {source_dir}")
    print(f"Discovered projects: {len(discovered)}")
    print(f"Registered new projects: {added}")
    print(f"Enabled projects: {len(runnable)}")

    if not runnable:
        print("Projects updated: 0")
        if not discovered and not registered:
            print("No registered projects and no project paths discovered from source records.")
        return 0

    failures = 0
    updated = 0
    for project in runnable:
        returncode = run_project_update(
            memory_repo,
            project,
            source_dir,
            args.dry_run,
            args.max_records,
            patterns,
            args.allow_redacted_secrets,
        )
        if returncode:
            failures += 1
        else:
            updated += 1

    print(f"Projects updated: {updated}")
    if failures:
        print(f"Projects failed: {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
