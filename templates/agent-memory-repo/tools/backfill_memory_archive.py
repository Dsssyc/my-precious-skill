#!/usr/bin/env python3
"""Rewrite existing archive entries from their recorded source records."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from update_memory_archive import (
    SourceRecord,
    archive_scope_for_row,
    isoformat,
    project_name_from_path,
    read_record_text,
    rebuild_indexes,
    redact_text,
    is_safe_archive_entry_dir,
    prune_empty_session_dirs,
    sha256_file,
    source_timestamp,
    write_record,
)

from audit_memory_archive import NOISE_PATTERNS


@dataclass
class BackfillGroup:
    project_path: Path
    archive_scope: str
    project_name: str
    source_agent: str
    source_record: Path
    entries: list[Path]


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
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "sessions").exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def load_meta(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def collect_groups(memory_repo: Path, project_path: Path | None, source_record: Path | None) -> list[BackfillGroup]:
    grouped: dict[tuple[str, str], BackfillGroup] = {}
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        meta = load_meta(meta_path)
        if not meta:
            continue
        meta_project = meta.get("project_path")
        meta_source = meta.get("source_record")
        if not isinstance(meta_project, str) or not isinstance(meta_source, str):
            continue
        resolved_project = Path(meta_project).expanduser().resolve()
        resolved_source = Path(meta_source).expanduser().resolve()
        if project_path and resolved_project != project_path.resolve():
            continue
        if source_record and resolved_source != source_record.resolve():
            continue
        if not resolved_source.exists() or not resolved_source.is_file():
            continue
        archive_scope = archive_scope_for_row(meta) or str(resolved_project)
        key = (archive_scope, str(resolved_source))
        group = grouped.get(key)
        if group is None:
            project_name = str(meta.get("project") or "") or project_name_from_path(resolved_project)
            source_agent = str(meta.get("source_agent") or "") or "agent"
            group = BackfillGroup(
                project_path=resolved_project,
                archive_scope=archive_scope,
                project_name=project_name,
                source_agent=source_agent,
                source_record=resolved_source,
                entries=[],
            )
            grouped[key] = group
        group.entries.append(meta_path.parent)
    return sorted(grouped.values(), key=lambda item: (item.archive_scope, item.source_record.as_posix()))


def entry_has_noise(entry_dir: Path) -> bool:
    entry_root = entry_dir.resolve()
    for path in sorted(entry_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.resolve(strict=False).relative_to(entry_root)
        except (OSError, ValueError):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in NOISE_PATTERNS.values():
            if pattern.search(text):
                return True
    return False


def prune_missing_source_noise(memory_repo: Path, project_path: Path | None, source_record: Path | None, dry_run: bool) -> int:
    pruned = 0
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        meta = load_meta(meta_path)
        if not meta:
            continue
        meta_project = meta.get("project_path")
        meta_source = meta.get("source_record")
        if not isinstance(meta_project, str) or not isinstance(meta_source, str):
            continue
        resolved_project = Path(meta_project).expanduser().resolve()
        resolved_source = Path(meta_source).expanduser().resolve()
        if project_path and resolved_project != project_path.resolve():
            continue
        if source_record and resolved_source != source_record.resolve():
            continue
        if resolved_source.exists():
            continue
        entry_dir = meta_path.parent
        if not entry_has_noise(entry_dir):
            continue
        if not is_safe_archive_entry_dir(memory_repo, entry_dir):
            raise SystemExit(f"Refusing to remove unsafe archive entry path: {entry_dir}")
        print(f"Prune missing-source noisy entry: {entry_dir.relative_to(memory_repo)}")
        if not dry_run:
            shutil.rmtree(entry_dir)
        pruned += 1
    if pruned and not dry_run:
        prune_empty_session_dirs(memory_repo / "sessions")
    return pruned


def record_from_source(path: Path) -> SourceRecord:
    text = read_record_text(path)
    return SourceRecord(path=path, updated_at=source_timestamp(path, text), sha256=sha256_file(path))


def remove_group_entries(memory_repo: Path, group: BackfillGroup) -> int:
    removed = 0
    for entry_dir in group.entries:
        if not entry_dir.exists():
            continue
        if not is_safe_archive_entry_dir(memory_repo, entry_dir):
            raise SystemExit(f"Refusing to remove unsafe archive entry path: {entry_dir}")
        shutil.rmtree(entry_dir)
        removed += 1
    if removed:
        prune_empty_session_dirs(memory_repo / "sessions")
    return removed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--project-path", help="Only rewrite entries for this project path")
    parser.add_argument("--source-record", help="Only rewrite entries for this source record")
    parser.add_argument("--source-agent", help="Override source agent label in rewritten entries")
    parser.add_argument("--project", help="Override project name in rewritten entries")
    parser.add_argument("--max-records", type=int, default=-1, help="Maximum source records to rewrite; negative means no limit")
    parser.add_argument("--dry-run", action="store_true", help="Show selected source records without changing the archive")
    parser.add_argument("--allow-redacted-secrets", action="store_true", help="Rewrite records with detected secrets after redaction")
    parser.add_argument(
        "--prune-missing-source-noise",
        action="store_true",
        help="Remove generated entries whose source record is missing and whose archive text contains wrapper-field noise",
    )
    parser.add_argument(
        "--prune-only",
        action="store_true",
        help="Only prune missing-source noisy entries; do not rewrite available source records",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.prune_only and not args.prune_missing_source_noise:
        raise SystemExit("--prune-only requires --prune-missing-source-noise")
    memory_repo = resolve_memory_repo(args.memory_repo)
    project_path = Path(args.project_path).expanduser().resolve() if args.project_path else None
    source_record = Path(args.source_record).expanduser().resolve() if args.source_record else None
    groups = [] if args.prune_only else collect_groups(memory_repo, project_path, source_record)
    if args.max_records >= 0:
        groups = groups[: args.max_records]

    print(f"Memory repo: {memory_repo}")
    print(f"Source records selected: {len(groups)}")
    for group in groups:
        print(f"- {group.project_path} :: {group.source_record} ({len(group.entries)} existing entries)")

    pruned = 0
    if args.prune_missing_source_noise:
        pruned = prune_missing_source_noise(memory_repo, project_path, source_record, args.dry_run)
        print(f"Missing-source noisy entries pruned: {pruned}")
    if args.prune_only:
        if not args.dry_run:
            rebuild_indexes(memory_repo)
        print("Backfill complete.")
        return 0

    if args.dry_run:
        return 0

    sensitive: list[tuple[BackfillGroup, dict[str, int]]] = []
    records: list[tuple[BackfillGroup, SourceRecord]] = []
    for group in groups:
        record = record_from_source(group.source_record)
        records.append((group, record))
        _, counts = redact_text(read_record_text(group.source_record))
        if counts:
            sensitive.append((group, counts))
    if sensitive and not args.allow_redacted_secrets:
        print("Refusing to rewrite records that match secret redaction patterns.", file=sys.stderr)
        for group, counts in sensitive:
            labels = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
            print(f"- {group.source_record}: {labels}", file=sys.stderr)
        print("Review the source records or rerun with --allow-redacted-secrets to store redacted snippets.", file=sys.stderr)
        return 2

    removed = 0
    skipped = 0
    for group, record in records:
        removed += remove_group_entries(memory_repo, group)
        written = write_record(
            memory_repo=memory_repo,
            project_path=group.project_path,
            archive_scope=group.archive_scope,
            project_name=args.project or group.project_name,
            source_agent=args.source_agent or group.source_agent,
            record=record,
        )
        if written is None:
            skipped += 1
            print(f"Skipped low-signal: {isoformat(record.updated_at)} {group.source_record}")
        else:
            print(f"Rewritten: {isoformat(record.updated_at)} {group.source_record}")
    rebuild_indexes(memory_repo)
    print(f"Existing entries removed: {removed}")
    print(f"Records skipped as low-signal: {skipped}")
    print("Backfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
