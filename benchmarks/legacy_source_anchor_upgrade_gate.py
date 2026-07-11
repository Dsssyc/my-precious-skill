#!/usr/bin/env python3
"""Gate transactional legacy source-anchor upgrades in a packaged archive."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "legacy_source_anchor_upgrade_gate"
UPGRADE_REPORT_KIND = "memory_source_anchor_upgrade_package"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
PREVIEW_REPORT_KIND = "memory_source_preview_package"

TARGET_FACT = "V230 automatic fact binds to a non-first event."
EXPLICIT_FACT = "V230 explicit memory binds to a non-first user event."
PARAPHRASE_ALPHA = "V230 induction memories should preserve source citations during evidence recall."
PARAPHRASE_BETA = "V230 induction memory should keep source refs during evidence retrieval."
OLD_FACT = "V230 layered retrieval should preserve evidence refs and raw source anchors for induced memories."
CURRENT_FACT = "V230 layered retrieval should preserve evidence refs for induced memories."
SECRET = "ghp_" + "V230_SHOULD_NEVER_RENDER_" + "1234567890"


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason

    def to_report(self) -> dict[str, str]:
        return {"stage": self.stage, "reason": self.reason}


@dataclass(frozen=True)
class RecordSpec:
    record_id: str
    project: str
    updated_at: str
    events: tuple[tuple[str, str], ...]
    allow_redacted_secrets: bool = False


@dataclass
class Fixture:
    memory_repo: Path
    source_root: Path
    source_paths: dict[str, Path]


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def record_specs() -> tuple[RecordSpec, ...]:
    return (
        RecordSpec(
            "target",
            "synthetic-v230-target",
            "2026-07-12T10:00:00Z",
            (
                ("user", "Inspect exact legacy provenance."),
                ("assistant", "Decision: The first quote is an unrelated distractor."),
                ("assistant", f"Reusable fact: {TARGET_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "explicit",
            "synthetic-v230-explicit",
            "2026-07-12T10:10:00Z",
            (
                ("user", "I prefer source upgrades to preserve natural user provenance."),
                ("assistant", "Decision: The explicit distractor remains unrelated."),
                ("user", f"Remember this: {EXPLICIT_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "paraphrase-alpha",
            "synthetic-v230-paraphrase-alpha",
            "2026-07-12T10:20:00Z",
            (
                ("user", "Record source-aware induction behavior."),
                ("assistant", "Inspect the deterministic fixture."),
                ("assistant", PARAPHRASE_ALPHA),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "paraphrase-beta",
            "synthetic-v230-paraphrase-beta",
            "2026-07-12T10:30:00Z",
            (
                ("user", "Record equivalent source-aware behavior."),
                ("assistant", "Inspect the deterministic fixture."),
                ("assistant", PARAPHRASE_BETA),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "lifecycle-old",
            "synthetic-v230-lifecycle-old",
            "2026-07-12T10:40:00Z",
            (
                ("user", "Record the earlier lifecycle rule."),
                ("assistant", "The earlier rule retains its own source event."),
                ("assistant", f"Reusable fact: {OLD_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "lifecycle-current-secret",
            "synthetic-v230-lifecycle-current",
            "2026-07-12T10:50:00Z",
            (
                ("user", "Refresh the lifecycle rule."),
                ("assistant", "The replacement retains its own source event."),
                (
                    "assistant",
                    f"Reusable fact: Updated fact: {OLD_FACT} => {CURRENT_FACT} token={SECRET}",
                ),
                ("assistant", "Acknowledged."),
            ),
            allow_redacted_secrets=True,
        ),
    )


def run_command(
    command: list[str],
    stage: str,
    *,
    cwd: Path | None = None,
    require_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if require_success and result.returncode != 0:
        raise GateFailure(stage, "command_failed")
    return result


def parse_package(
    result: subprocess.CompletedProcess[str],
    expected_kind: str,
    stage: str,
) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(stage, "invalid_json") from exc
    if not isinstance(value, dict) or value.get("report_kind") != expected_kind:
        raise GateFailure(stage, "unexpected_report_kind")
    return value


def set_mtime(path: Path, stamp: str) -> None:
    value = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    os.utime(path, (value.timestamp(), value.timestamp()))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def setup_fixture(root: Path) -> Fixture:
    memory_repo = (root / "agent-memory").resolve()
    source_root = (root / "external-source-records").resolve()
    source_root.mkdir(parents=True)
    source_paths: dict[str, Path] = {}
    for spec in record_specs():
        source_dir = source_root / spec.record_id
        source_dir.mkdir()
        source_path = source_dir / f"{spec.record_id}.jsonl"
        source_path.write_text(
            "".join(
                json.dumps({"role": role, "content": content}, sort_keys=True) + "\n"
                for role, content in spec.events
            ),
            encoding="utf-8",
        )
        set_mtime(source_path, spec.updated_at)
        source_paths[spec.record_id] = source_path

    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        "setup",
    )
    for tool in (
        "update_memory_archive.py",
        "search_memory.py",
        "resolve_memory_source.py",
        "upgrade_source_anchors.py",
    ):
        if not (memory_repo / "tools" / tool).is_file():
            raise GateFailure("setup", "packaged_tool_missing")

    projects_root = root / "projects"
    projects_root.mkdir()
    for spec in record_specs():
        project_path = projects_root / spec.project
        project_path.mkdir()
        command = [
            sys.executable,
            str(memory_repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_paths[spec.record_id].parent),
            "--project-path",
            str(project_path),
            "--project",
            spec.project,
            "--source-agent",
            "synthetic-agent",
            "--rewrite-existing",
        ]
        if spec.allow_redacted_secrets:
            command.append("--allow-redacted-secrets")
        run_command(command, f"update_{spec.record_id}", cwd=memory_repo)

    source_maps = list((memory_repo / "sessions").glob("**/source-map.json"))
    event_count = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in source_paths.values())
    if len(source_paths) != 6 or event_count != 24 or len(source_maps) != 6:
        raise GateFailure("fixture", "record_event_cardinality_mismatch")
    return Fixture(memory_repo, source_root, source_paths)


def source_map_entries(repo: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    entries: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted((repo / "sessions").glob("**/source-map.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        source_record = value.get("source_record") if isinstance(value, dict) else None
        if not isinstance(source_record, str):
            raise GateFailure("fixture", "malformed_source_map")
        entries[Path(source_record).stem] = (path, value)
    return entries


def downgrade_provenance(repo: Path) -> None:
    entries = source_map_entries(repo)
    source_map_paths: set[str] = set()
    for path, value in entries.values():
        value.pop("source_anchor_version", None)
        value.pop("evidence_source_anchors", None)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        source_map_paths.add(str(value["source_map_path"]))
        meta_path = path.parent / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("source_anchor_version", None)
        for field in ("reusable_fact_sources", "memory_candidate_sources", "explicit_memory_sources"):
            for row in meta.get(field) or []:
                if isinstance(row, dict):
                    row.pop("source_anchor_id", None)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for relative in (
        "index/memories.jsonl",
        "memories/global.jsonl",
        "memories/domains.jsonl",
        "memories/projects.jsonl",
        "memories/explicit.jsonl",
    ):
        path = repo / relative
        rows = load_jsonl(path)
        changed = False
        for row in rows:
            for raw_ref in row.get("raw_refs") or []:
                if isinstance(raw_ref, dict) and raw_ref.get("path") in source_map_paths:
                    raw_ref["anchor"] = "source_record"
                    changed = True
        if changed:
            write_jsonl(path, rows)


def strip_meta_provenance(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("source_anchor_version", None)
    for field in ("reusable_fact_sources", "memory_candidate_sources", "explicit_memory_sources"):
        for row in result.get(field) or []:
            if isinstance(row, dict):
                row.pop("source_anchor_id", None)
    return result


def semantic_snapshot(repo: Path) -> dict[str, Any]:
    maps: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    content_hashes: list[tuple[str, str]] = []
    for path, value in source_map_entries(repo).values():
        source_map = copy.deepcopy(value)
        source_map.pop("source_anchor_version", None)
        source_map.pop("evidence_source_anchors", None)
        maps.append(source_map)
        metas.append(strip_meta_provenance(json.loads((path.parent / "meta.json").read_text(encoding="utf-8"))))
        for name in ("summary.md", "evidence.md"):
            content_hashes.append((str(value["source_map_path"]).rsplit("/", 1)[0] + "/" + name, hashlib.sha256((path.parent / name).read_bytes()).hexdigest()))
    rows = load_jsonl(repo / "index/memories.jsonl")
    semantic_rows = []
    for row in rows:
        value = copy.deepcopy(row)
        value.pop("raw_refs", None)
        semantic_rows.append(value)
    return {
        "source_maps": sorted(maps, key=lambda value: str(value.get("source_map_path"))),
        "metas": sorted(metas, key=lambda value: str(value.get("source_map_path"))),
        "content_hashes": sorted(content_hashes),
        "memory_rows": sorted(semantic_rows, key=lambda value: str(value.get("memory_id"))),
    }


def parity_counts(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[int, int]]:
    before_rows = {str(row["memory_id"]): row for row in before["memory_rows"]}
    after_rows = {str(row["memory_id"]): row for row in after["memory_rows"]}
    ids = sorted(set(before_rows) | set(after_rows))
    text_matches = sum(
        hashlib.sha256(str(before_rows[memory_id].get("text", "")).encode()).hexdigest()
        == hashlib.sha256(str(after_rows[memory_id].get("text", "")).encode()).hexdigest()
        for memory_id in ids
        if memory_id in before_rows and memory_id in after_rows
    )
    lifecycle_fields = ("supersedes", "superseded_by", "derived_from")
    lifecycle_matches = sum(
        all(before_rows[memory_id].get(key) == after_rows[memory_id].get(key) for key in lifecycle_fields)
        for memory_id in ids
        if memory_id in before_rows and memory_id in after_rows
    )
    support_matches = sum(
        before_rows[memory_id].get("support_count") == after_rows[memory_id].get("support_count")
        for memory_id in ids
        if memory_id in before_rows and memory_id in after_rows
    )
    evidence_matches = sum(
        before_rows[memory_id].get("evidence_refs") == after_rows[memory_id].get("evidence_refs")
        for memory_id in ids
        if memory_id in before_rows and memory_id in after_rows
    )
    return {
        "memory_ids": (len(set(before_rows) & set(after_rows)), len(set(before_rows) | set(after_rows))),
        "memory_text": (text_matches, len(ids)),
        "lifecycle": (lifecycle_matches, len(ids)),
        "support": (support_matches, len(ids)),
        "evidence": (evidence_matches, len(ids)),
    }


def repo_fingerprint(repo: Path) -> dict[str, tuple[str, int]]:
    return {
        path.relative_to(repo).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mode & 0o777,
        )
        for path in sorted(repo.rglob("*"))
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
    }


def run_upgrade(
    fixture: Fixture,
    record_id: str,
    stage: str,
    *,
    apply: bool = False,
    allow_root: Path | None = None,
    allow_secret: bool = False,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    command = [
        sys.executable,
        str(fixture.memory_repo / "tools/upgrade_source_anchors.py"),
        "--memory-repo",
        str(fixture.memory_repo),
        "--source-record",
        str(fixture.source_paths[record_id]),
        "--allow-source-root",
        str(allow_root or fixture.source_root),
        "--apply" if apply else "--dry-run",
        "--report-json",
    ]
    if allow_secret:
        command.append("--allow-redacted-secrets")
    result = run_command(command, stage, cwd=fixture.memory_repo)
    return parse_package(result, UPGRADE_REPORT_KIND, stage), result


def run_search(repo: Path, query: str, stage: str) -> dict[str, Any]:
    result = run_command(
        [
            sys.executable,
            str(repo / "tools/search_memory.py"),
            query,
            "--repo",
            str(repo),
            "--depth",
            "source",
            "--context-json",
        ],
        stage,
        cwd=repo,
    )
    return parse_package(result, CONTEXT_REPORT_KIND, stage)


def source_ref_id(source_map: dict[str, Any], anchor: dict[str, Any]) -> str:
    value = f"{source_map['source_map_path']}#{anchor['source_anchor_id']}"
    return f"src_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def line_three_anchor(source_map: dict[str, Any], *, explicit: bool = False) -> dict[str, Any]:
    matches = [
        row
        for row in source_map.get("evidence_source_anchors") or []
        if isinstance(row, dict)
        and row.get("line_number") == 3
        and (not explicit or str(row.get("quote_id", "")).startswith("ev_explicit_"))
    ]
    if len(matches) != 1:
        raise GateFailure("binding", "expected_line_three_anchor_missing")
    return matches[0]


def run_resolver(
    fixture: Fixture,
    query: str,
    source_map: dict[str, Any],
    anchor: dict[str, Any],
    stage: str,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    ref_id = source_ref_id(source_map, anchor)
    result = run_command(
        [
            sys.executable,
            str(fixture.memory_repo / "tools/resolve_memory_source.py"),
            query,
            "--repo",
            str(fixture.memory_repo),
            "--source-ref-id",
            ref_id,
            "--allow-source-root",
            str(fixture.source_root),
            "--authorize-source-preview",
            "--preview-json",
        ],
        stage,
        cwd=fixture.memory_repo,
    )
    return parse_package(result, PREVIEW_REPORT_KIND, stage), result


def legacy_ref_for_query(repo: Path, query: str) -> str:
    package = run_search(repo, query, "legacy_search")
    for hit in package.get("hits") or []:
        if not isinstance(hit, dict) or hit.get("answerability", {}).get("status") != "supported":
            continue
        refs = hit.get("source_refs")
        if isinstance(refs, list) and refs:
            return str(refs[0]["source_ref_id"])
    raise GateFailure("legacy_search", "supported_ref_missing")


def run_legacy_resolver(fixture: Fixture, query: str, ref_id: str) -> dict[str, Any]:
    result = run_command(
        [
            sys.executable,
            str(fixture.memory_repo / "tools/resolve_memory_source.py"),
            query,
            "--repo",
            str(fixture.memory_repo),
            "--source-ref-id",
            ref_id,
            "--allow-source-root",
            str(fixture.source_root),
            "--authorize-source-preview",
            "--preview-json",
        ],
        "legacy_resolver",
        cwd=fixture.memory_repo,
    )
    return parse_package(result, PREVIEW_REPORT_KIND, "legacy_resolver")


def clone_fixture(fixture: Fixture, root: Path, case_id: str) -> Fixture:
    case_root = root / "negative-cases" / case_id
    memory_repo = (case_root / "agent-memory").resolve()
    source_root = (case_root / "external-source-records").resolve()
    memory_repo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture.memory_repo, memory_repo)
    shutil.copytree(fixture.source_root, source_root)
    source_paths = {
        record_id: source_root / record_id / path.name
        for record_id, path in fixture.source_paths.items()
    }
    for source_map_path, source_map in source_map_entries(memory_repo).values():
        record_id = Path(str(source_map["source_record"])).stem
        source_map["source_record"] = str(source_paths[record_id])
        source_map_path.write_text(json.dumps(source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        meta_path = source_map_path.parent / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["source_record"] = str(source_paths[record_id])
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Fixture(memory_repo, source_root, source_paths)


def replace_archived_hash(fixture: Fixture, record_id: str) -> None:
    digest = hashlib.sha256(fixture.source_paths[record_id].read_bytes()).hexdigest()
    source_map_path, source_map = source_map_entries(fixture.memory_repo)[record_id]
    source_map["source_record_sha256"] = digest
    source_map_path.write_text(json.dumps(source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    meta_path = source_map_path.parent / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["source_record_sha256"] = digest
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_upgrade_module(repo: Path, module_name: str):
    script = repo / "tools/upgrade_source_anchors.py"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise GateFailure("transaction", "module_load_failed")
    sys.path.insert(0, str(script.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def expected_report(package: dict[str, Any], status: str, reason: str) -> bool:
    return package.get("status") == status and package.get("reason") == reason


def run_negative_cases(
    fixture: Fixture,
    root: Path,
) -> tuple[dict[str, bool], list[subprocess.CompletedProcess[str]]]:
    results: dict[str, bool] = {}
    outputs: list[subprocess.CompletedProcess[str]] = []

    missing = clone_fixture(fixture, root, "missing")
    missing.source_paths["target"].unlink()
    package, output = run_upgrade(missing, "target", "missing")
    outputs.append(output)
    results["missing"] = expected_report(package, "blocked", "source_record_unavailable")

    drift = clone_fixture(fixture, root, "drift")
    drift.source_paths["target"].write_text(
        drift.source_paths["target"].read_text(encoding="utf-8") + "{}\n",
        encoding="utf-8",
    )
    package, output = run_upgrade(drift, "target", "drift")
    outputs.append(output)
    results["drift"] = expected_report(package, "blocked", "source_hash_mismatch")

    root_escape = clone_fixture(fixture, root, "root-escape")
    other_root = root_escape.source_root.parent / "other-root"
    other_root.mkdir()
    package, output = run_upgrade(root_escape, "target", "root_escape", allow_root=other_root)
    outputs.append(output)
    results["root_escape"] = expected_report(package, "blocked", "source_root_escape")

    symlink = clone_fixture(fixture, root, "symlink")
    linked = symlink.source_root / "linked.jsonl"
    linked.symlink_to(symlink.source_paths["target"])
    symlink.source_paths["target"] = linked
    package, output = run_upgrade(symlink, "target", "symlink")
    outputs.append(output)
    results["symlink"] = expected_report(package, "blocked", "symlink_escape")

    malformed_map = clone_fixture(fixture, root, "malformed-map")
    source_map_path, _ = source_map_entries(malformed_map.memory_repo)["target"]
    source_map_path.write_text("{not-json\n", encoding="utf-8")
    package, output = run_upgrade(malformed_map, "target", "malformed_map")
    outputs.append(output)
    results["malformed_map"] = expected_report(package, "blocked", "source_map_malformed")

    absent_quote = clone_fixture(fixture, root, "absent-quote")
    source_map_path, source_map = source_map_entries(absent_quote.memory_repo)["target"]
    evidence_path = absent_quote.memory_repo / str(source_map["evidence_path"])
    evidence_path.write_text(
        evidence_path.read_text(encoding="utf-8").replace(
            TARGET_FACT,
            "V230 quote absent from all source events.",
        ),
        encoding="utf-8",
    )
    package, output = run_upgrade(absent_quote, "target", "absent_quote")
    outputs.append(output)
    results["absent_quote"] = expected_report(package, "blocked", "evidence_event_binding_missing")

    ambiguous = clone_fixture(fixture, root, "ambiguous")
    ambiguous.source_paths["target"].write_text(
        ambiguous.source_paths["target"].read_text(encoding="utf-8")
        + json.dumps({"role": "assistant", "content": f"Reusable fact: {TARGET_FACT}"})
        + "\n",
        encoding="utf-8",
    )
    replace_archived_hash(ambiguous, "target")
    package, output = run_upgrade(ambiguous, "target", "ambiguous")
    outputs.append(output)
    results["ambiguous"] = expected_report(package, "blocked", "ambiguous_evidence_event_binding")

    malformed_jsonl = clone_fixture(fixture, root, "malformed-jsonl")
    malformed_jsonl.source_paths["target"].write_text(
        malformed_jsonl.source_paths["target"].read_text(encoding="utf-8") + "{not-json\n",
        encoding="utf-8",
    )
    replace_archived_hash(malformed_jsonl, "target")
    package, output = run_upgrade(malformed_jsonl, "target", "malformed_jsonl")
    outputs.append(output)
    results["malformed_jsonl"] = expected_report(package, "blocked", "source_jsonl_malformed")

    return results, outputs


def build_transaction_plan(module, fixture: Fixture):
    return module.build_plan(
        fixture.memory_repo,
        str(fixture.source_paths["target"]),
        str(fixture.source_root),
        allow_redacted_secrets=False,
    )


def run_transaction_cases(fixture: Fixture, root: Path) -> dict[str, bool]:
    stale = clone_fixture(fixture, root, "transaction-stale")
    module = load_upgrade_module(stale.memory_repo, "v230_upgrade_transaction")
    stale_plan = build_transaction_plan(module, stale)
    if stale_plan is None:
        raise GateFailure("transaction", "stale_plan_missing")
    stale_plan.replacements[0].path.write_bytes(stale_plan.replacements[0].path.read_bytes() + b"\n")
    stale_before = repo_fingerprint(stale.memory_repo)
    try:
        module.apply_upgrade_plan(stale_plan)
        stale_reason = ""
    except module.UpgradeBlocked as exc:
        stale_reason = exc.reason
    stale_ok = stale_reason == "target_fingerprint_changed" and repo_fingerprint(stale.memory_repo) == stale_before

    write_failure = clone_fixture(fixture, root, "transaction-write")
    write_plan = build_transaction_plan(module, write_failure)
    if write_plan is None:
        raise GateFailure("transaction", "write_plan_missing")
    write_before = repo_fingerprint(write_failure.memory_repo)
    replace_calls = 0

    def fail_second(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("injected")
        os.replace(source, destination)

    try:
        module.apply_upgrade_plan(write_plan, replace_func=fail_second)
        write_reason = ""
    except module.UpgradeBlocked as exc:
        write_reason = exc.reason
    write_ok = write_reason == "transaction_write_failed" and repo_fingerprint(write_failure.memory_repo) == write_before

    audit_failure = clone_fixture(fixture, root, "transaction-audit")
    audit_plan = build_transaction_plan(module, audit_failure)
    if audit_plan is None:
        raise GateFailure("transaction", "audit_plan_missing")
    audit_before = repo_fingerprint(audit_failure.memory_repo)
    try:
        module.apply_upgrade_plan(audit_plan, post_validator=lambda _repo: (False, True))
        audit_reason = ""
    except module.UpgradeBlocked as exc:
        audit_reason = exc.reason
    audit_ok = audit_reason == "post_apply_audit_failed" and repo_fingerprint(audit_failure.memory_repo) == audit_before
    return {"stale": stale_ok, "write_rollback": write_ok, "audit_rollback": audit_ok}


def exact_anchor_valid(source_path: Path, source_map: dict[str, Any], anchor: dict[str, Any]) -> bool:
    line_number = anchor.get("line_number")
    if not isinstance(line_number, int) or line_number < 1:
        return False
    lines = source_path.read_text(encoding="utf-8").splitlines()
    if line_number > len(lines):
        return False
    value = json.loads(lines[line_number - 1])
    content = str(value.get("content") or "") if isinstance(value, dict) else ""
    normalized = " ".join(content.split())
    event_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    payload = "\n".join(
        [
            str(source_map.get("source_record_sha256") or ""),
            str(line_number),
            str(anchor.get("event_ordinal") or ""),
            str(anchor.get("event_sha256") or ""),
        ]
    )
    expected_anchor = f"srca_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"
    return (
        anchor.get("event_ordinal") == 1
        and anchor.get("event_sha256") == event_hash
        and anchor.get("source_anchor_id") == expected_anchor
    )


def paraphrase_incremental_state(repo: Path) -> bool:
    entries = source_map_entries(repo)
    alpha_map = entries["paraphrase-alpha"][1]
    beta_map = entries["paraphrase-beta"][1]
    nodes = load_jsonl(repo / "index/memories.jsonl")
    matches = [node for node in nodes if node.get("text") in {PARAPHRASE_ALPHA, PARAPHRASE_BETA}]
    if len(matches) != 1:
        return False
    refs = matches[0].get("raw_refs") or []
    alpha_refs = [ref for ref in refs if isinstance(ref, dict) and ref.get("path") == alpha_map.get("source_map_path")]
    beta_refs = [ref for ref in refs if isinstance(ref, dict) and ref.get("path") == beta_map.get("source_map_path")]
    return (
        len(alpha_refs) == 1
        and str(alpha_refs[0].get("anchor", "")).startswith("srca_")
        and beta_refs == [{"path": beta_map.get("source_map_path"), "anchor": "source_record"}]
    )


def build_report(root: Path, started_at: float) -> dict[str, Any]:
    fixture = setup_fixture(root)
    downgrade_provenance(fixture.memory_repo)
    baseline = semantic_snapshot(fixture.memory_repo)
    command_outputs: list[subprocess.CompletedProcess[str]] = []

    legacy_ref = legacy_ref_for_query(fixture.memory_repo, TARGET_FACT)
    legacy_preview = run_legacy_resolver(fixture, TARGET_FACT, legacy_ref)
    legacy_recall_ok = legacy_preview.get("reason") == "legacy_source_anchor_unavailable"

    eligibility_results: list[bool] = []
    target_dry_run, output = run_upgrade(fixture, "target", "target_dry_run")
    command_outputs.append(output)
    eligibility_results.append(expected_report(target_dry_run, "eligible", "legacy_upgrade_ready"))

    negative_results, negative_outputs = run_negative_cases(fixture, root)
    command_outputs.extend(negative_outputs)
    eligibility_results.extend(negative_results.values())
    transaction = run_transaction_cases(fixture, root)

    secret_blocked, output = run_upgrade(
        fixture,
        "lifecycle-current-secret",
        "secret_default_rejection",
    )
    command_outputs.append(output)
    eligibility_results.append(
        expected_report(secret_blocked, "blocked", "secret_policy_authorization_required")
    )
    secret_allowed, output = run_upgrade(
        fixture,
        "lifecycle-current-secret",
        "secret_explicit_allowance",
        allow_secret=True,
    )
    command_outputs.append(output)
    eligibility_results.append(expected_report(secret_allowed, "eligible", "legacy_upgrade_ready"))

    apply_specs = (
        ("target", False),
        ("explicit", False),
        ("paraphrase-alpha", False),
        ("paraphrase-beta", False),
        ("lifecycle-old", False),
        ("lifecycle-current-secret", True),
    )
    apply_successes = 0
    incremental_cross_source_ok = False
    for record_id, allow_secret in apply_specs:
        package, output = run_upgrade(
            fixture,
            record_id,
            f"apply_{record_id}",
            apply=True,
            allow_secret=allow_secret,
        )
        command_outputs.append(output)
        apply_successes += int(expected_report(package, "applied", "legacy_upgrade_applied"))
        if record_id == "paraphrase-alpha":
            incremental_cross_source_ok = paraphrase_incremental_state(fixture.memory_repo)

    replay, output = run_upgrade(fixture, "target", "idempotent_replay", apply=True)
    command_outputs.append(output)
    replay_ok = (
        expected_report(replay, "noop", "already_current")
        and replay.get("metrics", {}).get("changed_file_count") == 0
    )

    after = semantic_snapshot(fixture.memory_repo)
    parity = parity_counts(baseline, after)
    semantic_equal = baseline == after
    upgraded_entries = source_map_entries(fixture.memory_repo)
    explicit_map_path, explicit_map = upgraded_entries["explicit"]
    explicit_meta = json.loads((explicit_map_path.parent / "meta.json").read_text(encoding="utf-8"))
    natural_rows = [
        row
        for row in explicit_meta.get("reusable_fact_sources") or []
        if isinstance(row, dict) and row.get("source") == "natural_user"
    ]
    natural_user_binding_preserved = len(natural_rows) == 1 and any(
        isinstance(anchor, dict)
        and anchor.get("line_number") == 1
        and anchor.get("source_anchor_id") == natural_rows[0].get("source_anchor_id")
        for anchor in explicit_map.get("evidence_source_anchors") or []
    )
    explicit_nodes = [
        node
        for node in load_jsonl(fixture.memory_repo / "index/memories.jsonl")
        if node.get("text") == EXPLICIT_FACT
    ]
    explicit_sticky_global_preserved = len(explicit_nodes) == 1 and all(
        explicit_nodes[0].get(key) == value
        for key, value in (("layer", "global"), ("scope", "global"), ("persistence", "sticky"))
    )
    binding_checks: list[bool] = []
    for record_id, source_path in fixture.source_paths.items():
        source_map = upgraded_entries[record_id][1]
        anchors = source_map.get("evidence_source_anchors")
        if not isinstance(anchors, list) or not anchors:
            binding_checks.append(False)
            continue
        binding_checks.extend(
            exact_anchor_valid(source_path, source_map, anchor)
            for anchor in anchors
            if isinstance(anchor, dict)
        )

    resolver_specs = (
        ("target", TARGET_FACT, False, TARGET_FACT),
        ("explicit", EXPLICIT_FACT, True, EXPLICIT_FACT),
        ("paraphrase-alpha", PARAPHRASE_BETA, False, PARAPHRASE_ALPHA),
        ("paraphrase-beta", PARAPHRASE_BETA, False, PARAPHRASE_BETA),
        ("lifecycle-current-secret", CURRENT_FACT, False, CURRENT_FACT),
    )
    resolver_successes = 0
    wrong_previews = 0
    for record_id, query, explicit, expected_text in resolver_specs:
        source_map = upgraded_entries[record_id][1]
        anchor = line_three_anchor(source_map, explicit=explicit)
        package, output = run_resolver(
            fixture,
            query,
            source_map,
            anchor,
            f"resolve_{record_id}",
        )
        command_outputs.append(output)
        preview = str(package.get("preview") or "")
        resolved = expected_report(package, "resolved", "original_event_resolved")
        resolver_successes += int(resolved)
        wrong_previews += int(not resolved or expected_text not in preview)

    old_anchor = line_three_anchor(upgraded_entries["lifecycle-old"][1])
    current_anchor = line_three_anchor(upgraded_entries["lifecycle-current-secret"][1])
    lifecycle_event_distinct = (
        old_anchor.get("event_sha256") != current_anchor.get("event_sha256")
        and old_anchor.get("source_anchor_id") != current_anchor.get("source_anchor_id")
    )

    all_output = "".join(result.stdout + result.stderr for result in command_outputs)
    raw_path_leak_count = int(str(root) in all_output)
    raw_ref_leak_count = sum('"raw_refs":' in result.stdout for result in command_outputs)
    unredacted_secret_count = int(SECRET in all_output)
    package_parse_denominator = len(command_outputs) - len(resolver_specs)
    package_parse_numerator = package_parse_denominator
    exact_binding_denominator = len(binding_checks)
    exact_binding_numerator = sum(binding_checks)
    evidence_content_equal = baseline["content_hashes"] == after["content_hashes"]

    metrics: dict[str, int | float] = {
        "source_record_count": 6,
        "source_event_count": 24,
        "legacy_upgrade_package_parse_success_rate": ratio(
            package_parse_numerator,
            package_parse_denominator,
        ),
        "legacy_upgrade_eligibility_accuracy": ratio(sum(eligibility_results), len(eligibility_results)),
        "legacy_exact_binding_accuracy": ratio(exact_binding_numerator, exact_binding_denominator),
        "legacy_memory_id_parity_rate": ratio(*parity["memory_ids"]),
        "legacy_memory_text_hash_parity_rate": ratio(*parity["memory_text"]),
        "legacy_evidence_quote_parity_rate": ratio(*parity["evidence"]) if evidence_content_equal else 0.0,
        "legacy_lifecycle_parity_rate": ratio(*parity["lifecycle"]),
        "legacy_support_count_parity_rate": ratio(*parity["support"]),
        "legacy_safe_apply_success_rate": ratio(apply_successes, len(apply_specs)),
        "legacy_post_upgrade_resolver_success_rate": ratio(resolver_successes, len(resolver_specs)),
        "legacy_transaction_rollback_rate": float(transaction["write_rollback"]),
        "legacy_post_audit_rollback_rate": float(transaction["audit_rollback"]),
        "legacy_optimistic_concurrency_rejection_rate": float(transaction["stale"]),
        "legacy_idempotent_replay_rate": float(replay_ok),
        "legacy_already_current_noop_rate": float(replay_ok),
        "legacy_source_hash_drift_rejection_rate": float(negative_results["drift"]),
        "legacy_missing_source_rejection_rate": float(negative_results["missing"]),
        "legacy_unsafe_path_rejection_rate": ratio(
            int(negative_results["root_escape"]) + int(negative_results["symlink"]),
            2,
        ),
        "legacy_ambiguous_binding_rejection_rate": float(negative_results["ambiguous"]),
        "legacy_secret_policy_accuracy": ratio(
            int(expected_report(secret_blocked, "blocked", "secret_policy_authorization_required"))
            + int(expected_report(secret_allowed, "eligible", "legacy_upgrade_ready")),
            2,
        ),
        "unexpected_semantic_change_count": int(not semantic_equal),
        "partial_upgrade_count": int(not transaction["write_rollback"]) + int(not transaction["audit_rollback"]),
        "wrong_event_preview_count": wrong_previews,
        "unredacted_secret_count": unredacted_secret_count,
        "raw_path_leak_count": raw_path_leak_count,
        "raw_ref_leak_count": raw_ref_leak_count,
        "privacy_leak_count": raw_path_leak_count + raw_ref_leak_count + unredacted_secret_count,
        "runtime_seconds": round(time.monotonic() - started_at, 3),
    }
    rates = [value for key, value in metrics.items() if key.endswith("_rate") or key.endswith("_accuracy")]
    counters = (
        "unexpected_semantic_change_count",
        "partial_upgrade_count",
        "wrong_event_preview_count",
        "unredacted_secret_count",
        "raw_path_leak_count",
        "raw_ref_leak_count",
        "privacy_leak_count",
    )
    passed = (
        legacy_recall_ok
        and incremental_cross_source_ok
        and lifecycle_event_distinct
        and natural_user_binding_preserved
        and explicit_sticky_global_preserved
        and all(value == 1.0 for value in rates)
        and all(metrics[key] == 0 for key in counters)
        and metrics["runtime_seconds"] < 90.0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "synthetic single-record provenance-only legacy JSONL upgrades in a clean packaged repo; "
            "not private migration approval, batch orchestration, arbitrary transcript formats, or public benchmark parity"
        ),
        "metrics": metrics,
        "observations": {
            "legacy_recall_preserved_before_upgrade": legacy_recall_ok,
            "incremental_cross_source_ref_preserved": incremental_cross_source_ok,
            "lifecycle_source_events_distinct": lifecycle_event_distinct,
            "natural_user_binding_preserved": natural_user_binding_preserved,
            "explicit_sticky_global_preserved": explicit_sticky_global_preserved,
            "malformed_source_map_rejection_observed": negative_results["malformed_map"],
            "malformed_jsonl_rejection_observed": negative_results["malformed_jsonl"],
            "absent_quote_rejection_observed": negative_results["absent_quote"],
            "write_rollback_observed": transaction["write_rollback"],
            "post_audit_rollback_observed": transaction["audit_rollback"],
        },
        "privacy": {
            "aggregate_only": True,
            "source_paths_rendered": False,
            "memory_ids_rendered": False,
            "memory_text_rendered": False,
            "quote_text_rendered": False,
            "raw_refs_rendered": False,
            "source_content_rendered": False,
            "secret_values_rendered": False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent for temporary clean-room artifacts")
    return parser.parse_args(argv)


def make_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="my-precious-v230-")
        return Path(temporary.name), temporary, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-v230-", dir=parent))
    return root, None, root


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = time.monotonic()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temporary, cleanup_root = make_root(args.work_dir)
        report = build_report(root, started_at)
    except GateFailure as failure:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failures": [failure.to_report()],
            "privacy": {"aggregate_only": True},
        }
    finally:
        if temporary is not None:
            temporary.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
