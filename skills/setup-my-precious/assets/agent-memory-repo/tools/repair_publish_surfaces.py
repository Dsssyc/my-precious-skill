#!/usr/bin/env python3
"""Repair publish-surface noise at structured metadata sources."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import audit_publish_readiness as readiness
import update_memory_archive as updater


REPORT_KIND = "publish_surface_repair_report"
SEGMENT_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")
SUMMARY_FALLBACK_FIELDS = (
    "user_intent",
    "reusable_facts",
    "decisions",
    "unresolved_tasks",
    "title",
)


@dataclass
class RepairStats:
    meta_files_scanned: int = 0
    malformed_meta_count: int = 0
    meta_files_with_repair: int = 0
    fields_with_repair: int = 0
    list_items_removed: int = 0
    scalar_segments_removed: int = 0
    scalar_fields_rewritten: int = 0
    raw_source_fields_cleared: int = 0
    ambiguous_scalar_count: int = 0
    rebuild_performed: bool = False
    category_counts: Counter[str] = field(default_factory=Counter)

    @property
    def blocked(self) -> bool:
        return self.malformed_meta_count > 0 or self.ambiguous_scalar_count > 0

    @property
    def repair_count(self) -> int:
        return (
            self.list_items_removed
            + self.scalar_segments_removed
            + self.scalar_fields_rewritten
            + self.raw_source_fields_cleared
        )


@dataclass
class CleanResult:
    value: object
    changed: bool = False
    ambiguous_count: int = 0
    list_items_removed: int = 0
    scalar_segments_removed: int = 0
    scalar_fields_rewritten: int = 0
    raw_source_fields_cleared: int = 0
    category_counts: Counter[str] = field(default_factory=Counter)

    def absorb(self, other: "CleanResult") -> None:
        self.changed = self.changed or other.changed
        self.ambiguous_count += other.ambiguous_count
        self.list_items_removed += other.list_items_removed
        self.scalar_segments_removed += other.scalar_segments_removed
        self.scalar_fields_rewritten += other.scalar_fields_rewritten
        self.raw_source_fields_cleared += other.raw_source_fields_cleared
        self.category_counts.update(other.category_counts)


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
        if repo.exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def repairable_field(name: object) -> bool:
    normalized = str(name).lower()
    return normalized in readiness.TEXT_FIELDS or normalized in readiness.RAW_SOURCE_FIELDS


def force_raw_source(name: object) -> bool:
    return str(name).lower() in readiness.RAW_SOURCE_FIELDS


def text_counts(text: str, *, force_raw: bool) -> Counter[str]:
    return readiness.category_counts_for_text(text, force_raw_source=force_raw)


def split_segments(text: str) -> list[str]:
    return [segment.strip() for segment in SEGMENT_BOUNDARY.split(text) if segment.strip()]


def nested_counts(value: object, *, force_raw: bool) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in readiness.iter_strings(value):
        counts.update(text_counts(text, force_raw=force_raw))
    return counts


def clean_scalar(text: str, *, force_raw: bool) -> CleanResult:
    counts = text_counts(text, force_raw=force_raw)
    result = CleanResult(value=text)
    if not counts:
        return result
    result.category_counts.update(counts)
    if force_raw:
        result.value = ""
        result.changed = True
        result.raw_source_fields_cleared = 1
        return result

    segments = split_segments(text)
    if len(segments) <= 1:
        result.ambiguous_count = 1
        return result

    kept: list[str] = []
    removed = 0
    for segment in segments:
        segment_counts = text_counts(segment, force_raw=False)
        if segment_counts:
            removed += 1
            continue
        kept.append(segment)
    if not kept:
        result.ambiguous_count = 1
        return result
    result.value = " ".join(kept)
    result.changed = True
    result.scalar_segments_removed = removed
    result.scalar_fields_rewritten = 1
    return result


def clean_value(value: object, field_name: object) -> CleanResult:
    force_raw = force_raw_source(field_name)
    if isinstance(value, str):
        return clean_scalar(value, force_raw=force_raw)
    if isinstance(value, list):
        result = CleanResult(value=[])
        cleaned_items: list[object] = []
        for item in value:
            if isinstance(item, str):
                counts = text_counts(item, force_raw=force_raw)
                if counts:
                    result.category_counts.update(counts)
                    result.changed = True
                    result.list_items_removed += 1
                    if force_raw:
                        result.raw_source_fields_cleared += 1
                    continue
                cleaned_items.append(item)
                continue
            if isinstance(item, (list, dict)):
                counts = nested_counts(item, force_raw=force_raw)
                if counts:
                    result.category_counts.update(counts)
                    result.changed = True
                    result.list_items_removed += 1
                    if force_raw:
                        result.raw_source_fields_cleared += 1
                    continue
            cleaned_items.append(item)
        result.value = cleaned_items
        return result
    if isinstance(value, dict):
        result = CleanResult(value={})
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            child = clean_value(item, field_name)
            result.absorb(child)
            cleaned[str(key)] = child.value
        result.value = cleaned
        return result
    return CleanResult(value=value)


def clean_summary_fallback_text(value: object) -> str:
    for text in readiness.iter_strings(value):
        durable = updater.durable_memory_text(text)
        if durable and not text_counts(durable, force_raw=False):
            return durable
    return ""


def summary_fallback_from_metadata(
    payload: dict[str, object],
    field_results: dict[str, tuple[object, CleanResult]],
) -> str:
    results_by_normalized_key = {key.lower(): result for key, result in field_results.items()}
    payload_by_normalized_key = {str(key).lower(): value for key, value in payload.items()}
    for field_name in SUMMARY_FALLBACK_FIELDS:
        if field_name in results_by_normalized_key:
            value = results_by_normalized_key[field_name][1].value
        else:
            value = payload_by_normalized_key.get(field_name)
        fallback = clean_summary_fallback_text(value)
        if fallback:
            return fallback
    return ""


def iter_meta_paths(memory_repo: Path) -> list[Path]:
    sessions = memory_repo / "sessions"
    if not sessions.exists():
        return []
    return sorted(
        path
        for path in sessions.glob("**/meta.json")
        if not path.is_symlink() and updater.is_safe_repo_path(memory_repo, path)
    )


def load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def scan_repairs(memory_repo: Path) -> tuple[RepairStats, list[tuple[Path, dict[str, object]]]]:
    stats = RepairStats()
    replacements: list[tuple[Path, dict[str, object]]] = []
    for meta_path in iter_meta_paths(memory_repo):
        stats.meta_files_scanned += 1
        payload = load_json(meta_path)
        if payload is None:
            stats.malformed_meta_count += 1
            continue
        cleaned = dict(payload)
        field_results: dict[str, tuple[object, CleanResult]] = {}
        for key, value in payload.items():
            if not repairable_field(key):
                continue
            result = clean_value(value, key)
            field_results[str(key)] = (key, result)

        for key_text, (key, result) in list(field_results.items()):
            if str(key).lower() != "summary" or result.ambiguous_count == 0:
                continue
            fallback = summary_fallback_from_metadata(payload, field_results)
            if not fallback:
                continue
            replacement = CleanResult(value=fallback, changed=True, scalar_fields_rewritten=1)
            replacement.category_counts.update(result.category_counts)
            field_results[key_text] = (key, replacement)

        file_changed = False
        for key, result in field_results.values():
            stats.category_counts.update(result.category_counts)
            stats.ambiguous_scalar_count += result.ambiguous_count
            stats.list_items_removed += result.list_items_removed
            stats.scalar_segments_removed += result.scalar_segments_removed
            stats.scalar_fields_rewritten += result.scalar_fields_rewritten
            stats.raw_source_fields_cleared += result.raw_source_fields_cleared
            if result.changed:
                stats.fields_with_repair += 1
                cleaned[key] = result.value
                file_changed = True
        if file_changed:
            stats.meta_files_with_repair += 1
            replacements.append((meta_path, cleaned))
    return stats, replacements


def apply_repairs(memory_repo: Path, replacements: list[tuple[Path, dict[str, object]]]) -> None:
    for path, payload in replacements:
        updater.write_safe_archive_text(
            memory_repo,
            path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            "session metadata file",
        )
    if replacements:
        updater.rebuild_indexes(memory_repo)


def report_status(stats: RepairStats, apply: bool) -> str:
    if stats.blocked:
        return "blocked"
    if stats.repair_count == 0:
        return "clean"
    return "repaired" if apply else "repairable"


def build_report(stats: RepairStats, *, apply: bool) -> dict[str, object]:
    category_counts = {category: 0 for category in readiness.ALL_CATEGORIES}
    for category, count in stats.category_counts.items():
        category_counts[category] = count
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": report_status(stats, apply),
        "mode": "apply" if apply else "dry_run",
        "metrics": {
            "meta_files_scanned": stats.meta_files_scanned,
            "malformed_meta_count": stats.malformed_meta_count,
            "meta_files_with_repair": stats.meta_files_with_repair,
            "fields_with_repair": stats.fields_with_repair,
            "list_items_removed": stats.list_items_removed,
            "scalar_segments_removed": stats.scalar_segments_removed,
            "scalar_fields_rewritten": stats.scalar_fields_rewritten,
            "raw_source_fields_cleared": stats.raw_source_fields_cleared,
            "ambiguous_scalar_count": stats.ambiguous_scalar_count,
            "rebuild_performed": stats.rebuild_performed,
        },
        "category_counts": category_counts,
        "privacy_leak_count": 0,
        "privacy": {
            "aggregate_only": True,
            "snippets_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
            "metadata_paths_rendered": False,
        },
        "claim_boundary": (
            "structured metadata publish-surface repair only; not memory quality, ranking quality, "
            "LLM answer quality, GitHub availability, vector search, or ontology discovery"
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the memory repository")
    parser.add_argument("--apply", action="store_true", help="Apply repair and rebuild derived publish surfaces")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    stats, replacements = scan_repairs(memory_repo)
    if args.apply and not stats.blocked:
        apply_repairs(memory_repo, replacements)
        stats.rebuild_performed = bool(replacements)
    report = build_report(stats, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if stats.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
