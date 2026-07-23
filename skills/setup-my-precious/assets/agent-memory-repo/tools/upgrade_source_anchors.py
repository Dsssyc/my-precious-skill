#!/usr/bin/env python3
"""Upgrade legacy source-map provenance without rewriting memory content."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import update_memory_archive as updater
from resolve_memory_source import allowed_source_path, lexical_absolute_path


REPORT_KIND = "memory_source_anchor_upgrade_package"
SOURCE_ANCHOR_VERSION = 1
EVIDENCE_QUOTE_PATTERN = re.compile(r"^(ev_(?:explicit_)?[0-9]{3}):\s*(.+)$")
MEMORY_PATHS = (
    "memories/global.jsonl",
    "memories/domains.jsonl",
    "memories/projects.jsonl",
    "memories/explicit.jsonl",
    "index/memories.jsonl",
)


class UpgradeBlocked(Exception):
    def __init__(self, reason: str, *, rollback_count: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.rollback_count = rollback_count


@dataclass(frozen=True)
class FileReplacement:
    path: Path
    original: bytes
    replacement: bytes
    mode: int
    fingerprint: str


@dataclass(frozen=True)
class InputFingerprint:
    path: Path
    fingerprint: str
    scope: str
    changed_reason: str


@dataclass(frozen=True)
class UpgradePlan:
    repo: Path
    source_path: Path
    source_root: Path
    replacements: tuple[FileReplacement, ...]
    inputs: tuple[InputFingerprint, ...]
    quote_count: int
    affected_memory_count: int
    redaction_count: int


@dataclass(frozen=True)
class ApplyResult:
    applied_file_count: int
    audit_passed: bool
    search_health_passed: bool


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_fingerprint(path: Path, reason: str) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise UpgradeBlocked(reason) from exc


def base_report(mode: str) -> dict[str, Any]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "blocked",
        "reason": "fail_closed",
        "mode": mode,
        "metrics": {
            "source_records_scanned": 0,
            "eligible_source_record_count": 0,
            "already_current_count": 0,
            "blocked_source_record_count": 0,
            "changed_file_count": 0,
            "evidence_quote_count": 0,
            "exact_event_binding_count": 0,
            "affected_memory_count": 0,
            "redaction_category_count": 0,
            "applied_file_count": 0,
            "rollback_file_count": 0,
        },
        "validation": {
            "source_root_allowed": False,
            "source_format_supported": False,
            "source_hash_verified": False,
            "archive_paths_verified": False,
            "evidence_quotes_verified": False,
            "memory_semantics_preserved": False,
            "target_fingerprints_verified": False,
            "post_apply_audit_passed": False,
            "post_apply_search_health_passed": False,
            "aggregate_scan_bounded": False,
            "read_only": False,
        },
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "project_paths_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "quote_text_rendered": False,
            "raw_refs_rendered": False,
            "source_content_rendered": False,
            "secret_values_rendered": False,
            "scheduler_state_rendered": False,
        },
        "claim_boundary": (
            "single-record provenance-only legacy source-anchor upgrade; "
            "not batch migration, semantic rewriting, arbitrary formats, or private deployment approval"
        ),
    }


def blocked_report(mode: str, reason: str, *, scanned: int = 1) -> dict[str, Any]:
    report = base_report(mode)
    report["reason"] = reason
    report["metrics"]["source_records_scanned"] = scanned
    report["metrics"]["blocked_source_record_count"] = scanned
    return report


def load_json_object(path: Path, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpgradeBlocked(reason) from exc
    if not isinstance(value, dict):
        raise UpgradeBlocked(reason)
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise UpgradeBlocked("memory_index_unavailable") from exc
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UpgradeBlocked("memory_index_malformed") from exc
        if not isinstance(value, dict):
            raise UpgradeBlocked("memory_index_malformed")
        rows.append(value)
    return rows


def render_jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")


def safe_repo_file(repo: Path, path_text: object, expected_name: str = "") -> Path:
    if not isinstance(path_text, str) or not path_text.strip():
        raise UpgradeBlocked("archive_path_missing")
    pure = PurePosixPath(path_text)
    if pure.is_absolute() or ".." in pure.parts:
        raise UpgradeBlocked("unsafe_archive_path")
    candidate = repo / pure.as_posix()
    current = repo
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise UpgradeBlocked("unsafe_archive_path")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UpgradeBlocked("unsafe_archive_path") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise UpgradeBlocked("unsafe_archive_path")
    if expected_name and resolved.name != expected_name:
        raise UpgradeBlocked("archive_path_kind_mismatch")
    return resolved


def safe_optional_repo_file(repo: Path, relative: str) -> Path | None:
    candidate = repo / relative
    current = repo
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise UpgradeBlocked("unsafe_archive_path")
    if not candidate.exists():
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UpgradeBlocked("unsafe_archive_path") from exc
    if not resolved.is_file():
        raise UpgradeBlocked("unsafe_archive_path")
    return resolved


def source_maps(repo: Path) -> list[tuple[Path, dict[str, Any]]]:
    values: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((repo / "sessions").glob("**/source-map.json")):
        if path.is_symlink() or not path.is_file():
            continue
        values.append((path.resolve(), load_json_object(path, "source_map_malformed")))
    return values


def matching_source_map(repo: Path, source_path: Path) -> tuple[Path, dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path, value in source_maps(repo):
        source_record = value.get("source_record")
        if not isinstance(source_record, str) or not source_record:
            continue
        if lexical_absolute_path(source_record) == source_path:
            matches.append((path, value))
    if not matches:
        raise UpgradeBlocked("source_record_not_archived")
    if len(matches) != 1:
        raise UpgradeBlocked("multiple_archive_entries_for_source")
    return matches[0]


def parse_evidence_quotes(path: Path) -> tuple[dict[str, str], str]:
    try:
        content = path.read_bytes()
        lines = content.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise UpgradeBlocked("evidence_unavailable") from exc
    quotes: dict[str, str] = {}
    for line in lines:
        match = EVIDENCE_QUOTE_PATTERN.match(line)
        if not match:
            continue
        quote_id, text = match.groups()
        if quote_id in quotes:
            raise UpgradeBlocked("duplicate_evidence_quote_id")
        quotes[quote_id] = text.strip()
    if not quotes:
        raise UpgradeBlocked("evidence_quotes_missing")
    return quotes, sha256_bytes(content)


def read_strict_jsonl(path: Path) -> tuple[str, str]:
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UpgradeBlocked("source_jsonl_malformed") from exc
    parsed_any = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            raise UpgradeBlocked("source_jsonl_malformed") from exc
        parsed_any = True
    if not parsed_any:
        raise UpgradeBlocked("source_jsonl_malformed")
    return text, sha256_bytes(content)


def event_matches_quote(event: updater.MemoryEvent, quote_id: str, quote_text: str) -> bool:
    target = updater.source_text_key(quote_text)
    candidates = {
        updater.source_text_key(event.text),
        updater.source_text_key(updater.durable_memory_text(event.text)),
    }
    if event.kind == "user":
        candidates.add(updater.source_text_key(updater.natural_user_memory_fact(event.text)))
        if quote_id.startswith("ev_explicit_") and updater.explicit_source_event([event], quote_text) is event:
            return True
    return bool(target and target in candidates)


def build_anchor_rows(
    quotes: dict[str, str],
    events: list[updater.MemoryEvent],
    source_hash: str,
) -> list[dict[str, object]]:
    anchors: list[dict[str, object]] = []
    for quote_id, quote_text in quotes.items():
        matches = [event for event in events if event_matches_quote(event, quote_id, quote_text)]
        if not matches:
            raise UpgradeBlocked("evidence_event_binding_missing")
        locators = {
            (event.line_number, event.event_ordinal, event.event_sha256)
            for event in matches
        }
        if len(locators) != 1:
            raise UpgradeBlocked("ambiguous_evidence_event_binding")
        line_number, event_ordinal, event_sha256 = next(iter(locators))
        if line_number <= 0 or event_ordinal <= 0 or not event_sha256:
            raise UpgradeBlocked("evidence_event_locator_missing")
        row: dict[str, object] = {
            "quote_id": quote_id,
            "line_number": line_number,
            "event_ordinal": event_ordinal,
            "event_sha256": event_sha256,
        }
        row["source_anchor_id"] = updater.source_anchor_id(source_hash, row)
        anchors.append(row)
    return anchors


def quote_for_text(quotes: dict[str, str], text: object) -> str:
    target = updater.source_text_key(str(text or ""))
    matches = [quote_id for quote_id, value in quotes.items() if updater.source_text_key(value) == target]
    return matches[0] if len(matches) == 1 else ""


def upgraded_meta(
    meta: dict[str, Any],
    quotes: dict[str, str],
    anchor_by_quote: dict[str, str],
) -> dict[str, Any]:
    value = copy.deepcopy(meta)
    value["source_anchor_version"] = SOURCE_ANCHOR_VERSION
    for field in ("reusable_fact_sources", "memory_candidate_sources"):
        rows = value.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            quote_id = str(row.get("evidence_quote_id") or "") or quote_for_text(quotes, row.get("text"))
            if not quote_id or quote_id not in anchor_by_quote:
                raise UpgradeBlocked("meta_quote_binding_missing")
            row["evidence_quote_id"] = quote_id
            row["source_anchor_id"] = anchor_by_quote[quote_id]
    explicit_rows = value.get("explicit_memory_sources")
    if not isinstance(explicit_rows, list):
        explicit_rows = []
        value["explicit_memory_sources"] = explicit_rows
    if not explicit_rows:
        for index, text in enumerate(value.get("explicit_memories") or [], 1):
            quote_id = f"ev_explicit_{index:03d}"
            if quote_id not in anchor_by_quote:
                raise UpgradeBlocked("meta_quote_binding_missing")
            explicit_rows.append(
                {
                    "text": text,
                    "quote_id": quote_id,
                    "source_anchor_id": anchor_by_quote[quote_id],
                }
            )
    else:
        for row in explicit_rows:
            if not isinstance(row, dict):
                raise UpgradeBlocked("meta_quote_binding_missing")
            quote_id = str(row.get("quote_id") or "")
            if not quote_id or quote_id not in anchor_by_quote:
                raise UpgradeBlocked("meta_quote_binding_missing")
            row["source_anchor_id"] = anchor_by_quote[quote_id]
    return value


def upgraded_memory_rows(
    rows: list[dict[str, Any]],
    source_map_path: str,
    evidence_path: str,
    anchor_by_quote: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    upgraded = copy.deepcopy(rows)
    affected = 0
    for row in upgraded:
        evidence_refs = row.get("evidence_refs")
        raw_refs = row.get("raw_refs")
        relevant_evidence = [
            ref
            for ref in (evidence_refs if isinstance(evidence_refs, list) else [])
            if isinstance(ref, dict) and ref.get("path") == evidence_path
        ]
        relevant_raw = [
            ref
            for ref in (raw_refs if isinstance(raw_refs, list) else [])
            if isinstance(ref, dict) and ref.get("path") == source_map_path
        ]
        if not relevant_evidence and not relevant_raw:
            continue
        if not isinstance(evidence_refs, list) or not relevant_evidence:
            raise UpgradeBlocked("memory_evidence_binding_missing")
        if len(relevant_evidence) != 1:
            raise UpgradeBlocked("ambiguous_memory_evidence_binding")
        quote_id = relevant_evidence[0].get("quote_id")
        if not isinstance(quote_id, str) or quote_id not in anchor_by_quote:
            raise UpgradeBlocked("memory_evidence_binding_missing")
        if not isinstance(raw_refs, list) or not relevant_raw:
            raise UpgradeBlocked("memory_source_ref_missing")
        if len(relevant_raw) != 1:
            raise UpgradeBlocked("ambiguous_memory_source_binding")
        relevant_raw[0]["anchor"] = anchor_by_quote[quote_id]
        affected += 1
    return upgraded, affected


def replacement(path: Path, content: bytes) -> FileReplacement | None:
    original = path.read_bytes()
    if original == content:
        return None
    return FileReplacement(
        path=path,
        original=original,
        replacement=content,
        mode=path.stat().st_mode & 0o777,
        fingerprint=sha256_bytes(original),
    )


def build_plan(
    repo: Path,
    source_record: str,
    allow_source_root: str,
    *,
    allow_redacted_secrets: bool,
    selected_source_map: tuple[Path, dict[str, Any]] | None = None,
) -> UpgradePlan | None:
    try:
        allow_root = lexical_absolute_path(allow_source_root)
        allow_root.resolve(strict=True)
    except OSError as exc:
        raise UpgradeBlocked("source_root_unavailable") from exc
    if not allow_root.is_dir():
        raise UpgradeBlocked("source_root_unavailable")
    source_path, source_error = allowed_source_path(source_record, allow_root)
    if source_path is None:
        raise UpgradeBlocked(source_error)
    if source_path.suffix.lower() != ".jsonl":
        raise UpgradeBlocked("unsupported_source_format")

    if selected_source_map is None:
        source_map_file, source_map = matching_source_map(repo, source_path)
    else:
        source_map_file, source_map = selected_source_map
        archived_source = source_map.get("source_record")
        if not isinstance(archived_source, str) or lexical_absolute_path(archived_source).resolve() != source_path:
            raise UpgradeBlocked("source_map_source_mismatch")
    if source_map.get("source_anchor_version") == SOURCE_ANCHOR_VERSION:
        anchors = source_map.get("evidence_source_anchors")
        if isinstance(anchors, list):
            return None
        raise UpgradeBlocked("source_map_malformed")
    source_map_rel = source_map_file.relative_to(repo).as_posix()
    if source_map.get("source_map_path") != source_map_rel:
        raise UpgradeBlocked("source_map_self_path_mismatch")
    summary_file = safe_repo_file(repo, source_map.get("summary_path"), "summary.md")
    evidence_file = safe_repo_file(repo, source_map.get("evidence_path"), "evidence.md")
    if summary_file.parent != source_map_file.parent or evidence_file.parent != source_map_file.parent:
        raise UpgradeBlocked("archive_entry_path_mismatch")
    meta_file = source_map_file.parent / "meta.json"
    if meta_file.is_symlink() or not meta_file.is_file():
        raise UpgradeBlocked("meta_unavailable")
    meta = load_json_object(meta_file, "meta_malformed")

    expected_hash = source_map.get("source_record_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise UpgradeBlocked("source_hash_unavailable")
    if meta.get("source_record_sha256") != expected_hash:
        raise UpgradeBlocked("source_hash_metadata_mismatch")
    source_text, actual_hash = read_strict_jsonl(source_path)
    if actual_hash != expected_hash:
        raise UpgradeBlocked("source_hash_mismatch")
    redacted_text, redaction_counts = updater.redact_source_text(source_path, source_text)
    if redaction_counts and not allow_redacted_secrets:
        raise UpgradeBlocked("secret_policy_authorization_required")
    events = updater.extract_source_events(source_path, redacted_text, source_text)
    quotes, evidence_fingerprint = parse_evidence_quotes(evidence_file)
    anchors = build_anchor_rows(quotes, events, expected_hash)
    anchor_by_quote = {
        str(row["quote_id"]): str(row["source_anchor_id"])
        for row in anchors
    }

    new_source_map = copy.deepcopy(source_map)
    new_source_map["source_anchor_version"] = SOURCE_ANCHOR_VERSION
    new_source_map["evidence_source_anchors"] = anchors
    new_meta = upgraded_meta(meta, quotes, anchor_by_quote)
    replacements: list[FileReplacement] = []
    for path, content in (
        (source_map_file, (json.dumps(new_source_map, indent=2, sort_keys=True) + "\n").encode("utf-8")),
        (meta_file, (json.dumps(new_meta, indent=2, sort_keys=True) + "\n").encode("utf-8")),
    ):
        item = replacement(path, content)
        if item is not None:
            replacements.append(item)

    affected_memory_ids: set[str] = set()
    for relative in MEMORY_PATHS:
        path = safe_optional_repo_file(repo, relative)
        if path is None:
            continue
        rows = load_jsonl(path)
        upgraded_rows, affected = upgraded_memory_rows(
            rows,
            source_map_rel,
            str(source_map["evidence_path"]),
            anchor_by_quote,
        )
        if affected:
            for before, after in zip(rows, upgraded_rows):
                if before != after:
                    before_semantics = {key: value for key, value in before.items() if key != "raw_refs"}
                    after_semantics = {key: value for key, value in after.items() if key != "raw_refs"}
                    if before_semantics != after_semantics:
                        raise UpgradeBlocked("memory_semantic_drift")
                    memory_id = after.get("memory_id")
                    if isinstance(memory_id, str):
                        affected_memory_ids.add(memory_id)
            item = replacement(path, render_jsonl(upgraded_rows))
            if item is not None:
                replacements.append(item)
    if not affected_memory_ids:
        raise UpgradeBlocked("affected_memory_missing")
    return UpgradePlan(
        repo=repo,
        source_path=source_path,
        source_root=allow_root.resolve(strict=True),
        replacements=tuple(sorted(replacements, key=lambda item: item.path.as_posix())),
        inputs=(
            InputFingerprint(source_path, actual_hash, "source", "source_hash_mismatch"),
            InputFingerprint(
                summary_file,
                file_fingerprint(summary_file, "archive_dependency_changed"),
                "archive",
                "archive_dependency_changed",
            ),
            InputFingerprint(
                evidence_file,
                evidence_fingerprint,
                "archive",
                "archive_dependency_changed",
            ),
        ),
        quote_count=len(quotes),
        affected_memory_count=len(affected_memory_ids),
        redaction_count=len(redaction_counts),
    )


def write_sibling_temp(path: Path, content: bytes, mode: int, label: str) -> Path:
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.{label}-",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), mode)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def target_matches_fingerprint(item: FileReplacement) -> bool:
    try:
        if item.path.is_symlink() or not item.path.is_file():
            return False
        return sha256_bytes(item.path.read_bytes()) == item.fingerprint
    except OSError:
        return False


def input_matches_fingerprint(plan: UpgradePlan, item: InputFingerprint) -> bool:
    try:
        if item.scope == "source":
            safe_path, _ = allowed_source_path(str(item.path), plan.source_root)
            if safe_path != item.path:
                return False
        else:
            relative = item.path.relative_to(plan.repo).as_posix()
            if safe_repo_file(plan.repo, relative) != item.path:
                return False
        return sha256_bytes(item.path.read_bytes()) == item.fingerprint
    except (OSError, ValueError, UpgradeBlocked):
        return False


def run_post_validation(repo: Path) -> tuple[bool, bool]:
    try:
        audit_script = safe_repo_file(repo, "tools/audit_memory_archive.py", "audit_memory_archive.py")
        search_script = safe_repo_file(repo, "tools/search_memory.py", "search_memory.py")
    except UpgradeBlocked:
        return False, False
    audit = subprocess.run(
        [sys.executable, str(audit_script), "--memory-repo", str(repo)],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if audit.returncode:
        return False, False
    search = subprocess.run(
        [sys.executable, str(search_script), "--repo", str(repo), "--health-check"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return True, search.returncode == 0


def restore_replacements(replaced: list[FileReplacement]) -> int:
    restored = 0
    try:
        for item in reversed(replaced):
            temp_path = write_sibling_temp(item.path, item.original, item.mode, "rollback")
            try:
                os.replace(temp_path, item.path)
            finally:
                temp_path.unlink(missing_ok=True)
            restored += 1
    except OSError as exc:
        raise UpgradeBlocked("rollback_failed", rollback_count=restored) from exc
    return restored


def apply_upgrade_plan(
    plan: UpgradePlan,
    *,
    replace_func: Callable[[Path, Path], object] = os.replace,
    post_validator: Callable[[Path], tuple[bool, bool]] = run_post_validation,
) -> ApplyResult:
    prepared: dict[Path, Path] = {}
    replaced: list[FileReplacement] = []
    failure_reason = "transaction_write_failed"
    try:
        for item in plan.replacements:
            prepared[item.path] = write_sibling_temp(
                item.path,
                item.replacement,
                item.mode,
                "upgrade",
            )
        for item in plan.inputs:
            if not input_matches_fingerprint(plan, item):
                raise UpgradeBlocked(item.changed_reason)
        if not all(target_matches_fingerprint(item) for item in plan.replacements):
            raise UpgradeBlocked("target_fingerprint_changed")
        for item in plan.replacements:
            if not target_matches_fingerprint(item):
                raise UpgradeBlocked("target_fingerprint_changed")
            replace_func(prepared[item.path], item.path)
            prepared.pop(item.path, None)
            replaced.append(item)
        failure_reason = "post_apply_validation_failed"
        audit_passed, search_passed = post_validator(plan.repo)
        if not audit_passed:
            failure_reason = "post_apply_audit_failed"
            raise UpgradeBlocked(failure_reason)
        if not search_passed:
            failure_reason = "post_apply_search_health_failed"
            raise UpgradeBlocked(failure_reason)
        return ApplyResult(
            applied_file_count=len(replaced),
            audit_passed=True,
            search_health_passed=True,
        )
    except UpgradeBlocked as exc:
        if not replaced:
            raise
        rollback_count = restore_replacements(replaced)
        raise UpgradeBlocked(exc.reason, rollback_count=rollback_count) from exc
    except Exception as exc:
        rollback_count = restore_replacements(replaced) if replaced else 0
        raise UpgradeBlocked(failure_reason, rollback_count=rollback_count) from exc
    finally:
        for temp_path in prepared.values():
            temp_path.unlink(missing_ok=True)


def eligible_report(plan: UpgradePlan, mode: str) -> dict[str, Any]:
    report = base_report(mode)
    report["status"] = "eligible"
    report["reason"] = "legacy_upgrade_ready"
    metrics = report["metrics"]
    metrics["source_records_scanned"] = 1
    metrics["eligible_source_record_count"] = 1
    metrics["changed_file_count"] = len(plan.replacements)
    metrics["evidence_quote_count"] = plan.quote_count
    metrics["exact_event_binding_count"] = plan.quote_count
    metrics["affected_memory_count"] = plan.affected_memory_count
    metrics["redaction_category_count"] = plan.redaction_count
    for key in (
        "source_root_allowed",
        "source_format_supported",
        "source_hash_verified",
        "archive_paths_verified",
        "evidence_quotes_verified",
        "memory_semantics_preserved",
        "target_fingerprints_verified",
    ):
        report["validation"][key] = True
    return report


def applied_report(plan: UpgradePlan, result: ApplyResult) -> dict[str, Any]:
    report = eligible_report(plan, "apply")
    report["status"] = "applied"
    report["reason"] = "legacy_upgrade_applied"
    report["metrics"]["applied_file_count"] = result.applied_file_count
    report["validation"]["post_apply_audit_passed"] = result.audit_passed
    report["validation"]["post_apply_search_health_passed"] = result.search_health_passed
    return report


def failed_apply_report(plan: UpgradePlan, exc: UpgradeBlocked) -> dict[str, Any]:
    report = eligible_report(plan, "apply")
    report["status"] = "blocked"
    report["reason"] = exc.reason
    report["metrics"]["eligible_source_record_count"] = 0
    report["metrics"]["blocked_source_record_count"] = 1
    report["metrics"]["rollback_file_count"] = exc.rollback_count
    if exc.reason == "target_fingerprint_changed":
        report["validation"]["target_fingerprints_verified"] = False
    elif exc.reason == "source_hash_mismatch":
        report["validation"]["source_hash_verified"] = False
    elif exc.reason == "archive_dependency_changed":
        report["validation"]["evidence_quotes_verified"] = False
    return report


def aggregate_readiness_scan(
    repo: Path,
    allow_source_root: str,
    *,
    scan_limit: int,
    allow_redacted_secrets: bool,
) -> dict[str, Any]:
    report = base_report("aggregate_scan")
    report["status"] = "scanned"
    report["reason"] = "aggregate_readiness_scan_complete"
    report["validation"]["aggregate_scan_bounded"] = True
    report["validation"]["read_only"] = True
    reason_counts: dict[str, int] = {}
    try:
        canonical_source_root = lexical_absolute_path(allow_source_root).resolve(strict=True)
    except OSError:
        report["status"] = "blocked"
        report["reason"] = "source_root_unavailable"
        return report
    for source_map_file in sorted((repo / "sessions").glob("**/source-map.json")):
        if report["metrics"]["source_records_scanned"] >= scan_limit:
            break
        try:
            source_map = load_json_object(source_map_file, "source_map_malformed")
        except UpgradeBlocked as exc:
            report["metrics"]["source_records_scanned"] += 1
            report["metrics"]["blocked_source_record_count"] += 1
            reason_counts[exc.reason] = reason_counts.get(exc.reason, 0) + 1
            continue
        if source_map.get("source_anchor_version") == SOURCE_ANCHOR_VERSION:
            continue
        report["metrics"]["source_records_scanned"] += 1
        source_record = source_map.get("source_record")
        if not isinstance(source_record, str) or not source_record:
            reason = "source_record_unavailable"
            report["metrics"]["blocked_source_record_count"] += 1
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            continue
        try:
            plan = build_plan(
                repo,
                source_record,
                str(canonical_source_root),
                allow_redacted_secrets=allow_redacted_secrets,
                selected_source_map=(source_map_file.resolve(), source_map),
            )
        except UpgradeBlocked as exc:
            report["metrics"]["blocked_source_record_count"] += 1
            reason_counts[exc.reason] = reason_counts.get(exc.reason, 0) + 1
            continue
        if plan is None:
            report["metrics"]["already_current_count"] += 1
            continue
        report["metrics"]["eligible_source_record_count"] += 1
        report["metrics"]["changed_file_count"] += len(plan.replacements)
        report["metrics"]["evidence_quote_count"] += plan.quote_count
        report["metrics"]["exact_event_binding_count"] += plan.quote_count
        report["metrics"]["affected_memory_count"] += plan.affected_memory_count
        report["metrics"]["redaction_category_count"] += plan.redaction_count
    report["blocked_reason_counts"] = dict(sorted(reason_counts.items()))
    if report["metrics"]["source_records_scanned"] == 0:
        report["reason"] = "no_legacy_source_records"
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", required=True)
    parser.add_argument("--source-record")
    parser.add_argument("--allow-source-root", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--scan-limit", type=int, default=24)
    parser.add_argument("--allow-redacted-secrets", action="store_true")
    parser.add_argument("--report-json", action="store_true")
    args = parser.parse_args(argv)
    if not args.report_json:
        parser.error("--report-json is required")
    if args.apply and not args.source_record:
        parser.error("--apply requires exactly one --source-record")
    if args.scan_limit <= 0:
        parser.error("--scan-limit must be greater than 0")
    return args


def command_report(args: argparse.Namespace) -> dict[str, Any]:
    mode = "apply" if args.apply else "dry_run"
    repo = Path(args.memory_repo).expanduser().resolve()
    if not (repo / "sessions").is_dir():
        report = blocked_report(mode, "memory_repo_unavailable", scanned=0)
    elif not args.source_record:
        report = aggregate_readiness_scan(
            repo,
            args.allow_source_root,
            scan_limit=args.scan_limit,
            allow_redacted_secrets=args.allow_redacted_secrets,
        )
    else:
        plan: UpgradePlan | None = None
        try:
            plan = build_plan(
                repo,
                args.source_record,
                args.allow_source_root,
                allow_redacted_secrets=args.allow_redacted_secrets,
            )
            if plan is None:
                report = base_report(mode)
                report["status"] = "noop"
                report["reason"] = "already_current"
                report["metrics"]["source_records_scanned"] = 1
                report["metrics"]["already_current_count"] = 1
            elif args.apply:
                try:
                    report = applied_report(plan, apply_upgrade_plan(plan))
                except UpgradeBlocked as exc:
                    report = failed_apply_report(plan, exc)
            else:
                report = eligible_report(plan, mode)
        except UpgradeBlocked as exc:
            report = failed_apply_report(plan, exc) if args.apply and plan is not None else blocked_report(mode, exc.reason)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "apply" if args.apply else "dry_run"
    try:
        report = command_report(args)
    except Exception:
        report = blocked_report(mode, "unexpected_internal_error", scanned=0)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
