#!/usr/bin/env python3
"""Resolve one authorized memory source ref to a bounded redacted event preview."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable


REPORT_KIND = "memory_source_preview_package"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SOURCE_REF_ID_PATTERN = re.compile(r"^src_[0-9a-f]{12}$")
SOURCE_ANCHOR_ID_PATTERN = re.compile(r"^srca_[0-9a-f]{16}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_JSONL_LINE_BYTES = 1024 * 1024


def load_tool_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("tool_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    tools_dir = str(path.parent)
    inserted = tools_dir not in sys.path
    if inserted:
        sys.path.insert(0, tools_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(tools_dir)
    return module


def source_anchor_id(
    source_record_sha256: str,
    line_number: int,
    event_ordinal: int,
    event_sha256: str,
) -> str:
    payload = "\n".join(
        [
            source_record_sha256,
            str(line_number),
            str(event_ordinal),
            event_sha256,
        ]
    )
    return f"srca_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def base_report(source_ref_id: str) -> dict[str, Any]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "blocked",
        "reason": "fail_closed",
        "source_ref_id": source_ref_id,
        "support_validation": {
            "context_package_valid": False,
            "active_current_query_supported": False,
            "exact_source_ref_selected": False,
        },
        "integrity": {
            "source_root_allowed": False,
            "source_hash_verified": False,
            "source_anchor_verified": False,
        },
        "redaction": {
            "applied": False,
            "bounded": True,
        },
        "preview": "",
        "privacy": {
            "full_query_rendered": False,
            "source_path_rendered": False,
            "raw_ref_rendered": False,
            "unrestricted_source_content_rendered": False,
            "bounded_redacted_preview_rendered": False,
        },
        "claim_boundary": (
            "one explicitly authorized JSONL event preview after package-first support validation; "
            "not bulk transcript access, private archive correctness, or multi-principal authorization"
        ),
    }


def fail(report: dict[str, Any], reason: str, status: str = "blocked") -> dict[str, Any]:
    report["status"] = status
    report["reason"] = reason
    report["preview"] = ""
    report["privacy"]["bounded_redacted_preview_rendered"] = False
    return report


def run_context_package(repo: Path, query: str) -> tuple[dict[str, Any] | None, str]:
    search_script = repo / "tools/search_memory.py"
    if not search_script.is_file():
        return None, "search_tool_missing"
    result = subprocess.run(
        [
            sys.executable,
            str(search_script),
            query,
            "--repo",
            str(repo),
            "--depth",
            "source",
            "--context-json",
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None, "search_context_unavailable"
    try:
        package = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "malformed_context_package"
    if not isinstance(package, dict) or package.get("report_kind") != CONTEXT_REPORT_KIND:
        return None, "malformed_context_package"
    return package, ""


def supported_source_ref(package: dict[str, Any], source_ref_id: str) -> bool:
    answerability = package.get("answerability")
    if not isinstance(answerability, dict) or answerability.get("status") != "supported":
        return False
    hits = package.get("hits")
    if not isinstance(hits, list):
        return False
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("active_current") is not True:
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            not isinstance(hit_answerability, dict)
            or hit_answerability.get("status") != "supported"
            or not isinstance(query_support, dict)
            or query_support.get("status") != "supported"
        ):
            continue
        source_refs = hit.get("source_refs")
        if not isinstance(source_refs, list):
            continue
        if any(
            isinstance(ref, dict)
            and ref.get("source_ref_id") == source_ref_id
            and ref.get("status") == "available"
            and ref.get("unsafe_ref") is False
            for ref in source_refs
        ):
            return True
    return False


def source_ref_text(search: ModuleType, repo: Path, raw_ref: object) -> tuple[str, str] | None:
    sanitized = search.sanitize_raw_ref(repo, raw_ref)
    parsed = search.parse_sanitized_source_ref(sanitized)
    if parsed is None:
        return None
    return parsed


def locate_raw_ref(
    search: ModuleType,
    repo: Path,
    source_ref_id: str,
) -> tuple[str, str] | None:
    matches: set[tuple[str, str]] = set()
    for row in iter_jsonl(repo / "index/memories.jsonl"):
        raw_refs = row.get("raw_refs")
        if not isinstance(raw_refs, list):
            continue
        for raw_ref in raw_refs:
            parsed = source_ref_text(search, repo, raw_ref)
            if parsed is None:
                continue
            path_text, anchor_text = parsed
            if search.stable_source_ref_id(path_text, anchor_text) == source_ref_id:
                matches.add((path_text, anchor_text))
    return next(iter(matches)) if len(matches) == 1 else None


def load_source_map(repo: Path, path_text: str) -> dict[str, Any] | None:
    candidate = repo / path_text
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if resolved.name != "source-map.json" or not resolved.is_file():
        return None
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def source_anchor_row(source_map: dict[str, Any], anchor_text: str) -> dict[str, Any] | None:
    if source_map.get("source_anchor_version") != 1:
        return None
    anchors = source_map.get("evidence_source_anchors")
    if not isinstance(anchors, list):
        return None
    matches = [
        row
        for row in anchors
        if isinstance(row, dict) and row.get("source_anchor_id") == anchor_text
    ]
    if not matches:
        return None
    locator = tuple(matches[0].get(key) for key in ("line_number", "event_ordinal", "event_sha256"))
    if any(
        tuple(row.get(key) for key in ("line_number", "event_ordinal", "event_sha256")) != locator
        for row in matches[1:]
    ):
        return None
    return matches[0]


def lexical_absolute_path(value: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(value)))


def has_symlink_component(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def allowed_source_path(source_record: str, allow_root: Path) -> tuple[Path | None, str]:
    lexical = lexical_absolute_path(source_record)
    try:
        relative = lexical.relative_to(allow_root)
    except ValueError:
        return None, "source_root_escape"
    if has_symlink_component(allow_root, relative):
        return None, "symlink_escape"
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(allow_root)
    except (OSError, ValueError):
        return None, "source_root_escape"
    if not resolved.is_file():
        return None, "source_record_unavailable"
    return resolved, ""


def read_jsonl_value_and_hash(path: Path, line_number: int) -> tuple[object | None, str, str]:
    if path.suffix.lower() != ".jsonl":
        return None, "unsupported_source_format", ""
    digest = hashlib.sha256()
    target_line: bytes | None = None
    target_error = ""
    try:
        with path.open("rb") as handle:
            for current_line, raw_line in enumerate(handle, 1):
                digest.update(raw_line)
                if current_line == line_number:
                    if len(raw_line) > MAX_JSONL_LINE_BYTES:
                        target_error = "source_event_too_large"
                    else:
                        target_line = raw_line
    except OSError:
        return None, "source_record_unavailable", ""
    source_hash = digest.hexdigest()
    if target_error:
        return None, target_error, source_hash
    if target_line is None:
        return None, "source_anchor_missing", source_hash
    try:
        return json.loads(target_line.decode("utf-8")), "", source_hash
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "source_event_malformed", source_hash


def resolve_preview(
    *,
    repo: Path,
    query: str,
    source_ref_id: str,
    allow_source_root: str,
    authorized: bool,
) -> dict[str, Any]:
    report = base_report(source_ref_id)
    package, package_error = run_context_package(repo, query)
    if package is None:
        return fail(report, package_error, "unsupported")
    report["support_validation"]["context_package_valid"] = True
    if not supported_source_ref(package, source_ref_id):
        answerability = package.get("answerability")
        reason = (
            "inactive_source_only"
            if isinstance(answerability, dict) and answerability.get("reason") == "no_active_current_support"
            else "source_ref_not_supported"
        )
        return fail(report, reason, "unsupported")
    report["support_validation"]["active_current_query_supported"] = True
    report["support_validation"]["exact_source_ref_selected"] = True
    if not authorized:
        return fail(report, "authorization_required")

    search_script = repo / "tools/search_memory.py"
    updater_script = repo / "tools/update_memory_archive.py"
    try:
        search = load_tool_module(search_script, "_my_precious_search_for_source_resolution")
        updater = load_tool_module(updater_script, "_my_precious_updater_for_source_resolution")
    except (OSError, RuntimeError, ImportError):
        return fail(report, "resolver_dependency_unavailable", "unavailable")

    raw_ref = locate_raw_ref(search, repo, source_ref_id)
    if raw_ref is None:
        return fail(report, "source_ref_not_unique", "unsupported")
    path_text, anchor_text = raw_ref
    if not SOURCE_ANCHOR_ID_PATTERN.fullmatch(anchor_text):
        return fail(report, "legacy_source_anchor_unavailable", "unavailable")
    source_map = load_source_map(repo, path_text)
    if source_map is None:
        return fail(report, "source_map_unavailable", "unavailable")
    if source_map.get("source_anchor_version") != 1:
        return fail(report, "legacy_source_anchor_unavailable", "unavailable")
    anchor = source_anchor_row(source_map, anchor_text)
    if anchor is None:
        return fail(report, "source_anchor_unavailable", "unavailable")

    try:
        allow_root = Path(allow_source_root).expanduser().resolve(strict=True)
    except OSError:
        return fail(report, "source_root_unavailable", "unavailable")
    if not allow_root.is_dir():
        return fail(report, "source_root_unavailable", "unavailable")
    source_record = source_map.get("source_record")
    if not isinstance(source_record, str) or not source_record:
        return fail(report, "source_record_unavailable", "unavailable")
    source_path, source_error = allowed_source_path(source_record, allow_root)
    if source_path is None:
        return fail(report, source_error)
    report["integrity"]["source_root_allowed"] = True

    expected_source_hash = source_map.get("source_record_sha256")
    if not isinstance(expected_source_hash, str) or not SHA256_PATTERN.fullmatch(expected_source_hash):
        return fail(report, "source_hash_unavailable", "unavailable")
    line_number = anchor.get("line_number")
    event_ordinal = anchor.get("event_ordinal")
    expected_event_hash = anchor.get("event_sha256")
    if (
        not isinstance(line_number, int)
        or isinstance(line_number, bool)
        or line_number <= 0
        or not isinstance(event_ordinal, int)
        or isinstance(event_ordinal, bool)
        or event_ordinal <= 0
        or not isinstance(expected_event_hash, str)
        or not SHA256_PATTERN.fullmatch(expected_event_hash)
    ):
        return fail(report, "source_anchor_malformed", "unavailable")
    if source_anchor_id(expected_source_hash, line_number, event_ordinal, expected_event_hash) != anchor_text:
        return fail(report, "source_anchor_mismatch")
    value, value_error, actual_source_hash = read_jsonl_value_and_hash(source_path, line_number)
    if actual_source_hash and actual_source_hash != expected_source_hash:
        return fail(report, "source_hash_mismatch")
    if not actual_source_hash and value_error != "unsupported_source_format":
        return fail(report, value_error or "source_record_unavailable", "unavailable")
    if actual_source_hash == expected_source_hash:
        report["integrity"]["source_hash_verified"] = True
    if value_error:
        return fail(report, value_error, "unavailable")
    events = updater.events_from_value(value)
    if event_ordinal > len(events):
        return fail(report, "source_anchor_missing", "unavailable")
    event = events[event_ordinal - 1]
    if updater.source_event_sha256(event.text) != expected_event_hash:
        return fail(report, "source_anchor_mismatch")
    report["integrity"]["source_anchor_verified"] = True

    preview = search.redact_source_preview_text(event.text)
    if not preview or search.has_sensitive_display_text(preview):
        return fail(report, "source_preview_redaction_failed")
    report["status"] = "resolved"
    report["reason"] = "original_event_resolved"
    report["preview"] = preview
    report["redaction"]["applied"] = "[REDACTED_" in preview
    report["privacy"]["bounded_redacted_preview_rendered"] = True
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Memory query used to validate active/current support")
    parser.add_argument("--repo", required=True, help="Path to the agent memory archive")
    parser.add_argument("--source-ref-id", required=True, help="Exact source_ref_id from source-depth context JSON")
    parser.add_argument("--allow-source-root", required=True, help="Explicit root allowed for this source preview")
    parser.add_argument("--authorize-source-preview", action="store_true", help="Confirm authorization for one preview")
    parser.add_argument("--preview-json", action="store_true", help="Emit memory_source_preview_package JSON")
    args = parser.parse_args(argv)
    if not args.preview_json:
        parser.error("--preview-json is required")
    if not SOURCE_REF_ID_PATTERN.fullmatch(args.source_ref_id):
        parser.error("--source-ref-id must be one exact source_ref_id")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()
    report = resolve_preview(
        repo=repo,
        query=args.query,
        source_ref_id=args.source_ref_id,
        allow_source_root=args.allow_source_root,
        authorized=args.authorize_source_preview,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
