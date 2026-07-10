#!/usr/bin/env python3
"""Gate exact, authorized evidence-to-original-JSONL-event resolution."""

from __future__ import annotations

import argparse
import copy
import hashlib
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
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "authorized_original_source_gate"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
PREVIEW_REPORT_KIND = "memory_source_preview_package"

TARGET_FACT = "V229 exact original event binding must select the supporting event."
PARAPHRASE_ALPHA = "V229 induction memories should preserve source citations during evidence recall."
PARAPHRASE_BETA = "V229 induction memory should keep source refs during evidence retrieval."
EXPLICIT_FACT = "V229 explicit exact source event must remain addressable."
OLD_FACT = "V229 layered retrieval should preserve evidence refs and raw source anchors for induced memories."
CURRENT_FACT = "V229 layered retrieval should preserve evidence refs for induced memories."
SECRET_SAFE_TEXT = "V229 safe secret-bearing source remains inspectable after redaction."
DISTRACTOR = "V229_UNRELATED_DISTRACTOR"
SECRET = "ghp_" + "V229_SHOULD_NEVER_RENDER_" + "1234567890"
NO_HIT_QUERY = "absent unsupported quasar mnemonic"
INACTIVE_QUERY = TARGET_FACT


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


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
    nodes: list[dict[str, Any]]
    source_maps: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class PreviewRun:
    case_id: str
    package: dict[str, Any]
    stdout: str
    stderr: str


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def run_command(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise GateFailure(stage, "command_failed")
    return result


def parse_json_package(result: subprocess.CompletedProcess[str], report_kind: str, stage: str) -> dict[str, Any]:
    try:
        package = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure(stage, "invalid_json") from exc
    if not isinstance(package, dict) or package.get("report_kind") != report_kind:
        raise GateFailure(stage, "unexpected_report_kind")
    return package


def set_mtime(path: Path, stamp: str) -> None:
    timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    os.utime(path, (timestamp, timestamp))


def record_specs() -> tuple[RecordSpec, ...]:
    return (
        RecordSpec(
            "target-later-event",
            "synthetic-v229-target",
            "2026-07-11T10:00:00Z",
            (
                ("user", "Inspect exact original-event provenance."),
                ("assistant", f"Decision: {DISTRACTOR} must not support the target fact."),
                ("assistant", f"Reusable fact: {TARGET_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "paraphrase-alpha",
            "synthetic-v229-paraphrase-alpha",
            "2026-07-11T10:10:00Z",
            (
                ("user", "Record source-aware induction behavior."),
                ("assistant", "I will inspect the deterministic fixture."),
                ("assistant", PARAPHRASE_ALPHA),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "paraphrase-beta",
            "synthetic-v229-paraphrase-beta",
            "2026-07-11T10:20:00Z",
            (
                ("user", "Record equivalent source-aware behavior."),
                ("assistant", "I will inspect the deterministic fixture."),
                ("assistant", PARAPHRASE_BETA),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "explicit-later-event",
            "synthetic-v229-explicit",
            "2026-07-11T10:30:00Z",
            (
                ("user", "Review explicit source provenance."),
                ("assistant", f"Decision: {DISTRACTOR} remains unrelated to explicit memory."),
                ("user", f"Remember this: {EXPLICIT_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "lifecycle-old",
            "synthetic-v229-lifecycle-old",
            "2026-07-11T10:40:00Z",
            (
                ("user", "Record the earlier lifecycle rule."),
                ("assistant", "The earlier rule will retain its own source event."),
                ("assistant", f"Reusable fact: {OLD_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "lifecycle-current",
            "synthetic-v229-lifecycle-current",
            "2026-07-11T10:50:00Z",
            (
                ("user", "Refresh the lifecycle rule."),
                ("assistant", "The replacement will retain its own source event."),
                ("assistant", f"Reusable fact: Updated fact: {OLD_FACT} => {CURRENT_FACT}"),
                ("assistant", "Acknowledged."),
            ),
        ),
        RecordSpec(
            "secret-bearing",
            "synthetic-v229-secret",
            "2026-07-11T11:00:00Z",
            (
                ("user", "Record a source event that requires preview redaction."),
                ("assistant", "Only the safe fact may remain visible."),
                ("assistant", f"Reusable fact: {SECRET_SAFE_TEXT} token={SECRET}"),
                ("assistant", "Acknowledged."),
            ),
            allow_redacted_secrets=True,
        ),
        RecordSpec(
            "noise-control",
            "synthetic-v229-noise",
            "2026-07-11T11:10:00Z",
            (
                ("user", "Run the synthetic control."),
                ("assistant", "I checked the source fixture."),
                ("user", "Continue the synthetic control."),
                ("assistant", "The command completed."),
            ),
        ),
    )


def write_source_records(root: Path) -> tuple[Path, dict[str, Path]]:
    source_root = (root / "external-source-records").resolve()
    source_root.mkdir(parents=True)
    source_paths: dict[str, Path] = {}
    for spec in record_specs():
        record_dir = source_root / spec.record_id
        record_dir.mkdir()
        source_path = record_dir / f"{spec.record_id}.jsonl"
        source_path.write_text(
            "".join(
                json.dumps({"role": role, "content": content}, sort_keys=True) + "\n"
                for role, content in spec.events
            ),
            encoding="utf-8",
        )
        set_mtime(source_path, spec.updated_at)
        source_paths[spec.record_id] = source_path
    return source_root, source_paths


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def setup_fixture(root: Path) -> Fixture:
    memory_repo = (root / "agent-memory").resolve()
    source_root, source_paths = write_source_records(root)
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
    for tool in ("update_memory_archive.py", "search_memory.py", "resolve_memory_source.py"):
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

    nodes = load_jsonl(memory_repo / "index/memories.jsonl")
    source_maps: dict[str, dict[str, Any]] = {}
    for path in sorted((memory_repo / "sessions").glob("**/source-map.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise GateFailure("fixture", "malformed_source_map")
        source_record = value.get("source_record")
        if isinstance(source_record, str):
            source_maps[Path(source_record).stem] = value
    if set(source_maps) != set(source_paths):
        raise GateFailure("fixture", "source_map_coverage_mismatch")
    return Fixture(memory_repo, source_root, source_paths, nodes, source_maps)


def node_by_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any]:
    matches = [node for node in nodes if node.get("text") == text]
    if len(matches) != 1:
        raise GateFailure("fixture", "expected_memory_node_missing")
    return matches[0]


def node_with_prefix(nodes: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    matches = [node for node in nodes if str(node.get("text") or "").startswith(prefix)]
    if len(matches) != 1:
        raise GateFailure("fixture", "expected_memory_node_missing")
    return matches[0]


def paraphrase_node(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [node for node in nodes if node.get("text") in {PARAPHRASE_ALPHA, PARAPHRASE_BETA}]
    if len(matches) != 1:
        raise GateFailure("fixture", "paraphrase_not_consolidated")
    return matches[0]


def anchor_binding(
    node: dict[str, Any],
    source_map: dict[str, Any],
    *,
    line_number: int,
    explicit: bool = False,
) -> dict[str, Any] | None:
    raw_refs = node.get("raw_refs") if isinstance(node.get("raw_refs"), list) else []
    evidence_refs = node.get("evidence_refs") if isinstance(node.get("evidence_refs"), list) else []
    anchors = source_map.get("evidence_source_anchors")
    if not isinstance(anchors, list):
        return None
    for anchor in anchors:
        if not isinstance(anchor, dict) or anchor.get("line_number") != line_number:
            continue
        quote_id = anchor.get("quote_id")
        source_anchor_id = anchor.get("source_anchor_id")
        if explicit and not str(quote_id or "").startswith("ev_explicit_"):
            continue
        raw_match = {
            "path": source_map.get("source_map_path"),
            "anchor": source_anchor_id,
        } in raw_refs
        evidence_match = {
            "path": source_map.get("evidence_path"),
            "quote_id": quote_id,
        } in evidence_refs
        if raw_match and evidence_match:
            return anchor
    return None


def source_ref_id(source_map: dict[str, Any], anchor: dict[str, Any]) -> str:
    value = f"{source_map['source_map_path']}#{anchor['source_anchor_id']}"
    return f"src_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


def run_search(fixture: Fixture, query: str, case_id: str) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    return run_search_repo(fixture.memory_repo, query, case_id)


def run_search_repo(repo: Path, query: str, case_id: str) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
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
        f"search_{case_id}",
        cwd=repo,
    )
    return parse_json_package(result, CONTEXT_REPORT_KIND, f"search_{case_id}"), result


def context_has_ref(package: dict[str, Any], memory_id: str, ref_id: str, *, active: bool = True) -> bool:
    hits = package.get("hits")
    if not isinstance(hits, list):
        return False
    return any(
        isinstance(hit, dict)
        and hit.get("memory_id") == memory_id
        and hit.get("active_current") is active
        and any(
            isinstance(ref, dict)
            and ref.get("source_ref_id") == ref_id
            and ref.get("status") == "available"
            for ref in (hit.get("source_refs") if isinstance(hit.get("source_refs"), list) else [])
        )
        for hit in hits
    )


def run_resolver(
    repo: Path,
    source_root: Path,
    query: str,
    ref_id: str,
    case_id: str,
    *,
    authorize: bool = True,
) -> PreviewRun:
    command = [
        sys.executable,
        str(repo / "tools/resolve_memory_source.py"),
        query,
        "--repo",
        str(repo),
        "--source-ref-id",
        ref_id,
        "--allow-source-root",
        str(source_root),
    ]
    if authorize:
        command.append("--authorize-source-preview")
    command.append("--preview-json")
    result = run_command(command, f"resolve_{case_id}", cwd=repo)
    package = parse_json_package(result, PREVIEW_REPORT_KIND, f"resolve_{case_id}")
    return PreviewRun(case_id, package, result.stdout, result.stderr)


def clone_archive(fixture: Fixture, root: Path, case_id: str) -> Path:
    destination = root / "negative-cases" / case_id / "agent-memory"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture.memory_repo, destination)
    return destination.resolve()


def cloned_source_map_path(repo: Path, source_map: dict[str, Any]) -> Path:
    return repo / str(source_map["source_map_path"])


def write_source_map(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def report_reason(run: PreviewRun, status: str, reason: str) -> bool:
    return run.package.get("status") == status and run.package.get("reason") == reason and run.package.get("preview") == ""


def build_report(root: Path, started_at: float) -> dict[str, Any]:
    fixture = setup_fixture(root)
    source_record_count = len(fixture.source_paths)
    source_event_count = sum(
        len(path.read_text(encoding="utf-8").splitlines()) for path in fixture.source_paths.values()
    )
    if source_record_count != 8 or source_event_count != 32:
        raise GateFailure("fixture", "record_event_cardinality_mismatch")
    if any(path.is_relative_to(fixture.memory_repo) for path in fixture.source_paths.values()):
        raise GateFailure("fixture", "source_record_inside_archive")

    target = node_by_text(fixture.nodes, TARGET_FACT)
    explicit = node_by_text(fixture.nodes, EXPLICIT_FACT)
    paraphrase = paraphrase_node(fixture.nodes)
    old = node_by_text(fixture.nodes, OLD_FACT)
    current = node_by_text(fixture.nodes, CURRENT_FACT)
    secret = node_with_prefix(fixture.nodes, SECRET_SAFE_TEXT)

    binding_specs = (
        (target, "target-later-event", False),
        (paraphrase, "paraphrase-alpha", False),
        (paraphrase, "paraphrase-beta", False),
        (explicit, "explicit-later-event", True),
        (old, "lifecycle-old", False),
        (current, "lifecycle-current", False),
        (secret, "secret-bearing", False),
    )
    bindings: dict[str, dict[str, Any]] = {}
    anchor_hits = 0
    quote_hits = 0
    for node, record_id, explicit_quote in binding_specs:
        source_map = fixture.source_maps[record_id]
        anchor = anchor_binding(node, source_map, line_number=3, explicit=explicit_quote)
        if anchor is not None:
            quote_hits += 1
            source_path = fixture.source_paths[record_id]
            source_value = json.loads(source_path.read_text(encoding="utf-8").splitlines()[2])
            expected_hash = hashlib.sha256(str(source_value["content"]).encode("utf-8")).hexdigest()
            if (
                anchor.get("event_ordinal") == 1
                and anchor.get("event_sha256") == expected_hash
                and source_map.get("source_record_sha256") == hashlib.sha256(source_path.read_bytes()).hexdigest()
            ):
                anchor_hits += 1
            bindings[record_id] = anchor

    target_ref = source_ref_id(fixture.source_maps["target-later-event"], bindings["target-later-event"])
    explicit_ref = source_ref_id(fixture.source_maps["explicit-later-event"], bindings["explicit-later-event"])
    paraphrase_alpha_ref = source_ref_id(fixture.source_maps["paraphrase-alpha"], bindings["paraphrase-alpha"])
    paraphrase_beta_ref = source_ref_id(fixture.source_maps["paraphrase-beta"], bindings["paraphrase-beta"])
    current_ref = source_ref_id(fixture.source_maps["lifecycle-current"], bindings["lifecycle-current"])
    secret_ref = source_ref_id(fixture.source_maps["secret-bearing"], bindings["secret-bearing"])

    context_runs: list[subprocess.CompletedProcess[str]] = []
    target_context, result = run_search(fixture, TARGET_FACT, "target")
    context_runs.append(result)
    paraphrase_context, result = run_search(fixture, str(paraphrase["text"]), "paraphrase")
    context_runs.append(result)
    explicit_context, result = run_search(fixture, EXPLICIT_FACT, "explicit")
    context_runs.append(result)
    current_context, result = run_search(fixture, CURRENT_FACT, "current")
    context_runs.append(result)
    secret_context, result = run_search(fixture, SECRET_SAFE_TEXT, "secret")
    context_runs.append(result)
    no_hit_context, result = run_search(fixture, NO_HIT_QUERY, "no_hit")
    context_runs.append(result)
    context_membership = (
        context_has_ref(target_context, str(target["memory_id"]), target_ref),
        context_has_ref(paraphrase_context, str(paraphrase["memory_id"]), paraphrase_alpha_ref),
        context_has_ref(paraphrase_context, str(paraphrase["memory_id"]), paraphrase_beta_ref),
        context_has_ref(explicit_context, str(explicit["memory_id"]), explicit_ref),
        context_has_ref(current_context, str(current["memory_id"]), current_ref),
        context_has_ref(secret_context, str(secret["memory_id"]), secret_ref),
    )

    preview_runs: list[PreviewRun] = []
    expected_previews: dict[str, str] = {}

    def resolve_success(case_id: str, query: str, ref_id: str, expected: str) -> PreviewRun:
        run = run_resolver(fixture.memory_repo, fixture.source_root, query, ref_id, case_id)
        preview_runs.append(run)
        expected_previews[case_id] = expected
        return run

    authorized_target = resolve_success("authorized_target", TARGET_FACT, target_ref, TARGET_FACT)
    authorized_paraphrase_alpha = resolve_success(
        "authorized_paraphrase_alpha", str(paraphrase["text"]), paraphrase_alpha_ref, PARAPHRASE_ALPHA
    )
    authorized_paraphrase_beta = resolve_success(
        "authorized_paraphrase_beta", str(paraphrase["text"]), paraphrase_beta_ref, PARAPHRASE_BETA
    )
    authorized_explicit = resolve_success("authorized_explicit", EXPLICIT_FACT, explicit_ref, EXPLICIT_FACT)
    authorized_current = resolve_success("authorized_current", CURRENT_FACT, current_ref, CURRENT_FACT)
    authorized_secret = resolve_success("authorized_secret", SECRET_SAFE_TEXT, secret_ref, SECRET_SAFE_TEXT)

    unauthorized = run_resolver(
        fixture.memory_repo,
        fixture.source_root,
        TARGET_FACT,
        target_ref,
        "unauthorized",
        authorize=False,
    )
    preview_runs.append(unauthorized)
    no_hit = run_resolver(fixture.memory_repo, fixture.source_root, NO_HIT_QUERY, target_ref, "no_hit")
    preview_runs.append(no_hit)
    inactive_repo = clone_archive(fixture, root, "inactive_source_only")
    inactive_index = inactive_repo / "index/memories.jsonl"
    inactive_rows = load_jsonl(inactive_index)
    inactive_target = next(row for row in inactive_rows if row.get("memory_id") == target.get("memory_id"))
    inactive_current = next(row for row in inactive_rows if row.get("memory_id") == explicit.get("memory_id"))
    inactive_target["superseded_by"] = inactive_current["memory_id"]
    inactive_current["supersedes"] = [
        *list(inactive_current.get("supersedes") or []),
        inactive_target["memory_id"],
    ]
    inactive_index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in inactive_rows),
        encoding="utf-8",
    )
    inactive_context, result = run_search_repo(inactive_repo, INACTIVE_QUERY, "inactive")
    context_runs.append(result)
    inactive = run_resolver(inactive_repo, fixture.source_root, INACTIVE_QUERY, target_ref, "inactive")
    preview_runs.append(inactive)
    wrong_ref = run_resolver(
        fixture.memory_repo, fixture.source_root, TARGET_FACT, "src_000000000000", "wrong_ref"
    )
    preview_runs.append(wrong_ref)

    disallowed_root = (root / "disallowed-source-root").resolve()
    disallowed_root.mkdir()
    root_escape = run_resolver(fixture.memory_repo, disallowed_root, TARGET_FACT, target_ref, "root_escape")
    preview_runs.append(root_escape)

    target_source_map = fixture.source_maps["target-later-event"]
    target_source = fixture.source_paths["target-later-event"]

    symlink_repo = clone_archive(fixture, root, "symlink_escape")
    outside_source = root / "outside-symlink-target.jsonl"
    outside_source.write_bytes(target_source.read_bytes())
    symlink_path = fixture.source_root / "escaped-source-link"
    symlink_path.symlink_to(outside_source)
    symlink_map = copy.deepcopy(target_source_map)
    symlink_map["source_record"] = str(symlink_path)
    symlink_map["source_record_sha256"] = hashlib.sha256(outside_source.read_bytes()).hexdigest()
    write_source_map(cloned_source_map_path(symlink_repo, target_source_map), symlink_map)
    symlink_escape = run_resolver(symlink_repo, fixture.source_root, TARGET_FACT, target_ref, "symlink_escape")
    preview_runs.append(symlink_escape)

    hash_repo = clone_archive(fixture, root, "source_hash_mismatch")
    original_source_bytes = target_source.read_bytes()
    try:
        target_source.write_bytes(original_source_bytes + b'{"role":"assistant","content":"mutation"}\n')
        source_hash_mismatch = run_resolver(
            hash_repo, fixture.source_root, TARGET_FACT, target_ref, "source_hash_mismatch"
        )
    finally:
        target_source.write_bytes(original_source_bytes)
    preview_runs.append(source_hash_mismatch)

    anchor_repo = clone_archive(fixture, root, "source_anchor_mismatch")
    anchor_map = copy.deepcopy(target_source_map)
    target_anchor_id = bindings["target-later-event"]["source_anchor_id"]
    for row in anchor_map["evidence_source_anchors"]:
        if row.get("source_anchor_id") == target_anchor_id:
            row["event_sha256"] = "0" * 64
    write_source_map(cloned_source_map_path(anchor_repo, target_source_map), anchor_map)
    source_anchor_mismatch = run_resolver(
        anchor_repo, fixture.source_root, TARGET_FACT, target_ref, "source_anchor_mismatch"
    )
    preview_runs.append(source_anchor_mismatch)

    format_repo = clone_archive(fixture, root, "unsupported_source_format")
    unsupported_path = fixture.source_root / "unsupported-source.txt"
    unsupported_path.write_bytes(target_source.read_bytes())
    format_map = copy.deepcopy(target_source_map)
    format_map["source_record"] = str(unsupported_path)
    format_map["source_record_sha256"] = hashlib.sha256(unsupported_path.read_bytes()).hexdigest()
    write_source_map(cloned_source_map_path(format_repo, target_source_map), format_map)
    unsupported_format = run_resolver(
        format_repo, fixture.source_root, TARGET_FACT, target_ref, "unsupported_source_format"
    )
    preview_runs.append(unsupported_format)

    malformed_repo = clone_archive(fixture, root, "malformed_context_package")
    (malformed_repo / "tools/search_memory.py").write_text(
        "#!/usr/bin/env python3\nprint('{not-json')\n",
        encoding="utf-8",
    )
    malformed_package = run_resolver(
        malformed_repo, fixture.source_root, TARGET_FACT, target_ref, "malformed_context_package"
    )
    preview_runs.append(malformed_package)

    legacy_repo = clone_archive(fixture, root, "legacy_source_map")
    legacy_map = copy.deepcopy(target_source_map)
    legacy_map.pop("source_anchor_version", None)
    write_source_map(cloned_source_map_path(legacy_repo, target_source_map), legacy_map)
    legacy = run_resolver(legacy_repo, fixture.source_root, TARGET_FACT, target_ref, "legacy_source_map")
    preview_runs.append(legacy)

    successful_runs = (
        authorized_target,
        authorized_paraphrase_alpha,
        authorized_paraphrase_beta,
        authorized_explicit,
        authorized_current,
        authorized_secret,
    )
    successful_hits = sum(
        int(
            run.package.get("status") == "resolved"
            and run.package.get("reason") == "original_event_resolved"
            and expected_previews[run.case_id] in str(run.package.get("preview") or "")
        )
        for run in successful_runs
    )
    wrong_event_preview_count = sum(
        int(
            expected_previews[run.case_id] not in str(run.package.get("preview") or "")
            or DISTRACTOR in str(run.package.get("preview") or "")
        )
        for run in successful_runs
    )
    all_runtime_output = "\n".join(
        [
            *(result.stdout + "\n" + result.stderr for result in context_runs),
            *(run.stdout + "\n" + run.stderr for run in preview_runs),
        ]
    )
    raw_path_markers = [str(fixture.source_root), *(str(path) for path in fixture.source_paths.values())]
    raw_path_leak_count = sum(int(marker in all_runtime_output) for marker in raw_path_markers)
    raw_ref_leak_count = sum(
        int(marker in all_runtime_output)
        for marker in ("srca_", "source-map.json", str(target_source_map.get("source_map_path") or ""))
    )
    unredacted_secret_count = int(SECRET in all_runtime_output)
    redaction_ok = bool(
        authorized_secret.package.get("status") == "resolved"
        and SECRET_SAFE_TEXT in str(authorized_secret.package.get("preview") or "")
        and "[REDACTED_" in str(authorized_secret.package.get("preview") or "")
        and SECRET not in str(authorized_secret.package.get("preview") or "")
        and authorized_secret.package.get("redaction", {}).get("applied") is True
    )

    lifecycle_ok = bool(
        old.get("superseded_by") == current.get("memory_id")
        and old.get("memory_id") in (current.get("supersedes") or [])
        and bindings.get("lifecycle-old")
        and bindings.get("lifecycle-current")
        and bindings["lifecycle-old"].get("source_anchor_id")
        != bindings["lifecycle-current"].get("source_anchor_id")
    )
    paraphrase_ok = bool(
        int(paraphrase.get("support_count") or 0) >= 2
        and bindings.get("paraphrase-alpha")
        and bindings.get("paraphrase-beta")
        and bindings["paraphrase-alpha"].get("source_anchor_id")
        != bindings["paraphrase-beta"].get("source_anchor_id")
    )
    cases = {
        "non_first_supporting_event": bindings.get("target-later-event", {}).get("line_number") == 3,
        "cross_project_paraphrase_sources": paraphrase_ok,
        "explicit_non_first_event": bool(
            explicit.get("source") == "explicit"
            and bindings.get("explicit-later-event", {}).get("line_number") == 3
        ),
        "current_and_superseded_sources": lifecycle_ok,
        "authorized_exact_ref": successful_hits == len(successful_runs) and all(context_membership[:6]),
        "default_unauthorized": report_reason(unauthorized, "blocked", "authorization_required"),
        "unsupported_no_hit": report_reason(no_hit, "unsupported", "source_ref_not_supported")
        and no_hit_context.get("answerability", {}).get("status") == "unsupported",
        "inactive_source_only": report_reason(inactive, "unsupported", "inactive_source_only")
        and inactive_context.get("answerability", {}).get("reason") == "no_active_current_support",
        "wrong_source_ref": report_reason(wrong_ref, "unsupported", "source_ref_not_supported"),
        "root_escape": report_reason(root_escape, "blocked", "source_root_escape"),
        "symlink_escape": report_reason(symlink_escape, "blocked", "symlink_escape"),
        "source_hash_mismatch": report_reason(source_hash_mismatch, "blocked", "source_hash_mismatch"),
        "source_anchor_mismatch": report_reason(source_anchor_mismatch, "blocked", "source_anchor_mismatch"),
        "unsupported_source_format": report_reason(unsupported_format, "unavailable", "unsupported_source_format"),
        "malformed_context_package": report_reason(
            malformed_package, "unsupported", "malformed_context_package"
        ),
        "legacy_source_map": report_reason(legacy, "unavailable", "legacy_source_anchor_unavailable"),
        "secret_redaction": redaction_ok,
    }

    integrity_runs = (root_escape, symlink_escape, source_hash_mismatch, source_anchor_mismatch, unsupported_format)
    integrity_hits = sum(
        int(
            run.package.get("preview") == ""
            and run.package.get("reason")
            in {
                "source_root_escape",
                "symlink_escape",
                "source_hash_mismatch",
                "source_anchor_mismatch",
                "unsupported_source_format",
            }
        )
        for run in integrity_runs
    )
    privacy_leak_count = raw_path_leak_count + raw_ref_leak_count + unredacted_secret_count
    runtime_seconds = round(time.monotonic() - started_at, 3)
    metrics = {
        "source_context_package_parse_success_rate": ratio(len(context_runs), len(context_runs)),
        "source_preview_package_parse_success_rate": ratio(len(preview_runs), len(preview_runs)),
        "source_anchor_assignment_accuracy": ratio(anchor_hits, len(binding_specs)),
        "memory_evidence_quote_fidelity_rate": ratio(quote_hits, len(binding_specs)),
        "authorized_original_event_resolution_rate": ratio(successful_hits, len(successful_runs)),
        "default_source_content_block_rate": 1.0 if cases["default_unauthorized"] else 0.0,
        "unsupported_source_rejection_rate": ratio(
            int(cases["unsupported_no_hit"]) + int(cases["wrong_source_ref"]), 2
        ),
        "inactive_source_rejection_rate": 1.0 if cases["inactive_source_only"] else 0.0,
        "source_integrity_failure_block_rate": ratio(integrity_hits, len(integrity_runs)),
        "legacy_source_map_fail_closed_rate": 1.0 if cases["legacy_source_map"] else 0.0,
        "source_preview_redaction_accuracy": 1.0 if redaction_ok else 0.0,
        "wrong_event_preview_count": wrong_event_preview_count,
        "unredacted_secret_count": unredacted_secret_count,
        "raw_path_leak_count": raw_path_leak_count,
        "raw_ref_leak_count": raw_ref_leak_count,
        "privacy_leak_count": privacy_leak_count,
        "runtime_seconds": runtime_seconds,
    }
    diagnostics = {
        "unauthorized_block_count": int(cases["default_unauthorized"]),
        "unsupported_block_count": int(cases["unsupported_no_hit"]),
        "inactive_block_count": int(cases["inactive_source_only"]),
        "wrong_ref_block_count": int(cases["wrong_source_ref"]),
        "root_escape_block_count": int(cases["root_escape"]),
        "symlink_escape_block_count": int(cases["symlink_escape"]),
        "source_hash_mismatch_block_count": int(cases["source_hash_mismatch"]),
        "source_anchor_mismatch_block_count": int(cases["source_anchor_mismatch"]),
        "unsupported_format_block_count": int(cases["unsupported_source_format"]),
        "malformed_package_block_count": int(cases["malformed_context_package"]),
        "legacy_source_map_block_count": int(cases["legacy_source_map"]),
    }
    deterministic_rates = [
        value
        for name, value in metrics.items()
        if name.endswith("_rate") or name.endswith("_accuracy")
    ]
    failed = bool(
        not all(cases.values())
        or any(value != 1.0 for value in deterministic_rates)
        or any(metrics[name] != 0 for name in (
            "wrong_event_preview_count",
            "unredacted_secret_count",
            "raw_path_leak_count",
            "raw_ref_leak_count",
            "privacy_leak_count",
        ))
        or runtime_seconds >= 90.0
    )
    return {
        "report_kind": REPORT_KIND,
        "overall_status": "fail" if failed else "pass",
        "package_source": "clean_packaged_deployment_repo",
        "fixture": {
            "source_record_count": source_record_count,
            "source_event_count": source_event_count,
            "source_format": "jsonl",
            "source_records_external_to_archive": True,
        },
        "command_contract": {
            "search_report_kind": CONTEXT_REPORT_KIND,
            "resolver_report_kind": PREVIEW_REPORT_KIND,
            "search_depth": "source",
            "context_json": True,
            "exact_source_ref_only": True,
            "explicit_authorization_required": True,
            "free_form_search_used": False,
        },
        "cases": cases,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "privacy": {
            "aggregate_only": True,
            "context_packages_rendered": False,
            "source_previews_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "claim_boundary": (
            "bounded generic JSONL event resolution after package-first support validation; "
            "not arbitrary transcript formats, private production correctness, or bulk source access"
        ),
    }


def prepare_work_dir(path_text: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path_text:
        root = Path(path_text).expanduser().resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return root, None
    temp_handle = tempfile.TemporaryDirectory(prefix="my-precious-v229-")
    return Path(temp_handle.name).resolve(), temp_handle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional deterministic work directory to keep for inspection")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root, temp_handle = prepare_work_dir(args.work_dir)
    started_at = time.monotonic()
    try:
        report = build_report(root, started_at)
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "overall_status": "fail",
            "failure": {"stage": exc.stage, "reason": exc.reason},
        }
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("overall_status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
