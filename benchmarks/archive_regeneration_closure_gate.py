#!/usr/bin/env python3
"""Gate packaged archive regeneration reference and daily-render closure."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "archive_regeneration_closure_gate"
FACT = "Prefer evidence-bound regeneration over unsupported archive references."
CURRENT_FACT = "Prefer current archive support bundles while preserving lifecycle links."
DAILY_SENTINEL = "Durable regeneration preserves current references"


class GateFailure(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = run(command, cwd=cwd)
    if result.returncode:
        raise GateFailure(f"{stage}: command_failed:{result.returncode}")
    return result


def set_mtime(path: Path, stamp: str) -> None:
    timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    os.utime(path, (timestamp, timestamp))


def setup_archive(root: Path, *, git_backed: bool) -> Path:
    repo = root / "agent-memory"
    require(
        [sys.executable, str(SETUP_SCRIPT), "--path", str(repo), "--mode", "local", "--skip-config"],
        "setup_archive",
    )
    if not git_backed:
        return repo
    remote = root / "remote.git"
    require(["git", "init", "--bare", "--initial-branch=main", str(remote)], "init_remote")
    require(["git", "init", "--initial-branch=main"], "init_repo", cwd=repo)
    require(["git", "config", "user.email", "synthetic@example.invalid"], "git_email", cwd=repo)
    require(["git", "config", "user.name", "Synthetic Gate"], "git_name", cwd=repo)
    require(["git", "add", "."], "initial_stage", cwd=repo)
    require(["git", "commit", "-m", "Initialize synthetic archive"], "initial_commit", cwd=repo)
    require(["git", "remote", "add", "origin", str(remote)], "add_remote", cwd=repo)
    require(["git", "push", "-u", "origin", "main"], "initial_push", cwd=repo)
    return repo


def update_command(repo: Path, source_dir: Path, project_path: Path) -> list[str]:
    return [
        sys.executable,
        str(repo / "tools/update_memory_archive.py"),
        "--memory-repo",
        str(repo),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--project",
        "synthetic-regeneration",
    ]


def read_explicit_nodes(repo: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def node_by_text(repo: Path, text: str) -> dict[str, object]:
    return next(node for node in read_explicit_nodes(repo) if node.get("text") == text)


def ref_paths(node: dict[str, object], field: str) -> list[str]:
    values = node.get(field, [])
    if field == "derived_from":
        return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []
    return [
        str(value.get("path"))
        for value in values
        if isinstance(value, dict) and isinstance(value.get("path"), str)
    ] if isinstance(values, list) else []


def support_bundle_count(node: dict[str, object]) -> int:
    refs = node.get("evidence_refs", [])
    if not isinstance(refs, list):
        return 0
    keys = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        path = str(ref.get("path") or "")
        quote = str(ref.get("quote_id") or "")
        key = Path(path).parent.as_posix() if path.startswith("sessions/") else f"{path}#{quote}"
        keys.add(key)
    return len(keys)


def digest_paths(repo: Path, paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        path = repo / relative
        digest.update(relative.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_source(path: Path, events: list[dict[str, str]], stamp: str) -> None:
    path.write_text("\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n", encoding="utf-8")
    set_mtime(path, stamp)


def add_lifecycle_memory(repo: Path, source_dir: Path, old_id: str) -> None:
    support_dir = repo / "sessions/2026/07/10/lifecycle-support"
    support_dir.mkdir(parents=True, exist_ok=True)
    summary = support_dir / "summary.md"
    evidence = support_dir / "evidence.md"
    summary.write_text("Synthetic lifecycle support summary.\n", encoding="utf-8")
    evidence.write_text(f"ev_lifecycle: {CURRENT_FACT}\n", encoding="utf-8")
    require(
        [
            sys.executable,
            str(repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--source-dir",
            str(source_dir),
            "--explicit-memory",
            CURRENT_FACT,
            "--explicit-layer",
            "global",
            "--explicit-scope",
            "global",
            "--explicit-summary-path",
            summary.relative_to(repo).as_posix(),
            "--explicit-evidence-ref",
            f"{evidence.relative_to(repo).as_posix()}#ev_lifecycle",
            "--explicit-supersedes",
            old_id,
        ],
        "add_lifecycle_memory",
    )


def evaluate_success(root: Path) -> dict[str, object]:
    repo = setup_archive(root, git_backed=True)
    source_dir = root / "records"
    project_path = root / "project"
    source_dir.mkdir()
    project_path.mkdir()
    source = source_dir / "regeneration.jsonl"
    command = update_command(repo, source_dir, project_path)

    write_source(source, [{"role": "user", "content": f"Please remember: {FACT}"}], "2026-07-10T10:00:00Z")
    require(command, "first_update")
    first = node_by_text(repo, FACT)
    old_paths = {
        "derived_from": ref_paths(first, "derived_from"),
        "evidence_refs": ref_paths(first, "evidence_refs"),
        "raw_refs": ref_paths(first, "raw_refs"),
    }
    old_id = str(first["memory_id"])
    add_lifecycle_memory(repo, source_dir, old_id)

    long_decision = (
        "Decision: Durable regeneration preserves current references and "
        + ("stable archive context " * 4)
        + "**supported memory evidence and source anchors remain reachable across replacement**"
    )
    write_source(
        source,
        [
            {"role": "user", "content": f"Please remember: {FACT}"},
            {"role": "assistant", "content": long_decision},
            {"role": "assistant", "content": f"{DAILY_SENTINEL} after source replacement."},
        ],
        "2026-07-11T10:00:00Z",
    )
    require(command, "replacement_update")

    old = node_by_text(repo, FACT)
    current = node_by_text(repo, CURRENT_FACT)
    stale_derived = sum(path in ref_paths(old, "derived_from") for path in old_paths["derived_from"])
    stale_evidence = sum(path in ref_paths(old, "evidence_refs") for path in old_paths["evidence_refs"])
    stale_raw = sum(path in ref_paths(old, "raw_refs") for path in old_paths["raw_refs"])
    support_consistent = all(
        node.get("support_count") == support_bundle_count(node)
        for node in (old, current)
    )
    lifecycle_retained = (
        old.get("superseded_by") == current.get("memory_id")
        and old.get("memory_id") in current.get("supersedes", [])
    )

    daily_text = (repo / "daily/2026/2026-07-11.md").read_text(encoding="utf-8")
    daily_balanced = all(line.count("**") % 2 == 0 for line in daily_text.splitlines())
    daily_retained = DAILY_SENTINEL in daily_text

    audit = run([sys.executable, str(repo / "tools/audit_memory_archive.py"), "--memory-repo", str(repo)])
    search = run([sys.executable, str(repo / "tools/search_memory.py"), "--health-check"] , cwd=repo)

    stable_paths = (
        "memories/explicit.jsonl",
        "index/memories.jsonl",
        "daily/2026/2026-07-11.md",
    )
    before_replay = digest_paths(repo, stable_paths)
    require(command, "idempotent_replay")
    after_replay = digest_paths(repo, stable_paths)
    sync = run(
        [
            sys.executable,
            str(repo / "tools/sync_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--include-reviewed-memory-nodes",
            "--dry-run",
        ],
        cwd=repo,
    )

    return {
        "stale_derived_ref_count": stale_derived,
        "stale_evidence_ref_count": stale_evidence,
        "stale_raw_ref_count": stale_raw,
        "bundle_reconciled": stale_derived == stale_evidence == stale_raw == 0,
        "support_consistent": support_consistent,
        "lifecycle_retained": lifecycle_retained,
        "daily_balanced": daily_balanced,
        "daily_retained": daily_retained,
        "audit_passed": audit.returncode == 0,
        "search_passed": search.returncode == 0,
        "sync_passed": sync.returncode == 0,
        "replay_stable": before_replay == after_replay,
    }


def evaluate_orphan(root: Path) -> bool:
    repo = setup_archive(root, git_backed=False)
    source_dir = root / "records"
    project_path = root / "project"
    source_dir.mkdir()
    project_path.mkdir()
    source = source_dir / "orphan.jsonl"
    command = update_command(repo, source_dir, project_path)
    write_source(source, [{"role": "user", "content": f"Please remember: {FACT}"}], "2026-07-10T10:00:00Z")
    require(command, "orphan_first_update")
    write_source(
        source,
        [{"role": "assistant", "content": "Decision: unrelated durable behavior remains stable."}],
        "2026-07-11T10:00:00Z",
    )
    result = run(command)
    combined = result.stdout + result.stderr
    return (
        result.returncode != 0
        and "Refusing to persist orphaned explicit memory support: count=1" in combined
        and FACT not in combined
        and str(source) not in combined
    )


def evaluate_once(root: Path) -> dict[str, object]:
    success = evaluate_success(root / "success")
    orphan_closed = evaluate_orphan(root / "orphan")
    privacy_probe = json.dumps(
        {"success": success, "orphan_closed": orphan_closed},
        sort_keys=True,
    )
    forbidden_report_fragments = (
        FACT,
        CURRENT_FACT,
        DAILY_SENTINEL,
        "sessions/",
        "/Users/",
        "raw_refs",
        "memory_id",
    )
    privacy_leak_count = sum(fragment in privacy_probe for fragment in forbidden_report_fragments)
    return {
        "regeneration_bundle_reconciliation_accuracy": 1.0 if success["bundle_reconciled"] else 0.0,
        "stale_derived_ref_count": success["stale_derived_ref_count"],
        "stale_evidence_ref_count": success["stale_evidence_ref_count"],
        "stale_raw_ref_count": success["stale_raw_ref_count"],
        "support_count_consistency_rate": 1.0 if success["support_consistent"] else 0.0,
        "lifecycle_link_retention_rate": 1.0 if success["lifecycle_retained"] else 0.0,
        "orphan_explicit_fail_closed_accuracy": 1.0 if orphan_closed else 0.0,
        "daily_structure_safe_clip_accuracy": 1.0 if success["daily_balanced"] else 0.0,
        "daily_durable_fact_retention_rate": 1.0 if success["daily_retained"] else 0.0,
        "post_regeneration_archive_audit_pass_rate": 1.0 if success["audit_passed"] else 0.0,
        "post_regeneration_search_health_pass_rate": 1.0 if success["search_passed"] else 0.0,
        "reviewed_sync_dry_run_pass_rate": 1.0 if success["sync_passed"] else 0.0,
        "idempotent_replay_rate": 1.0 if success["replay_stable"] else 0.0,
        "privacy_leak_count": privacy_leak_count,
    }


def expected_metrics() -> dict[str, object]:
    return {
        "regeneration_bundle_reconciliation_accuracy": 1.0,
        "stale_derived_ref_count": 0,
        "stale_evidence_ref_count": 0,
        "stale_raw_ref_count": 0,
        "support_count_consistency_rate": 1.0,
        "lifecycle_link_retention_rate": 1.0,
        "orphan_explicit_fail_closed_accuracy": 1.0,
        "daily_structure_safe_clip_accuracy": 1.0,
        "daily_durable_fact_retention_rate": 1.0,
        "post_regeneration_archive_audit_pass_rate": 1.0,
        "post_regeneration_search_health_pass_rate": 1.0,
        "reviewed_sync_dry_run_pass_rate": 1.0,
        "idempotent_replay_rate": 1.0,
        "privacy_leak_count": 0,
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = evaluate_once(root / "run-a")
            second = evaluate_once(root / "run-b")
        reports_match = first == second
        passed = reports_match and first == expected_metrics()
        report = {
            "report_kind": REPORT_KIND,
            "status": "passed" if passed else "failed",
            "metrics": first,
            "determinism": {"runs": 2, "reports_match": reports_match},
            "privacy": {
                "synthetic_only": True,
                "private_content_rendered": False,
                "command_output_rendered": False,
            },
            "limits": (
                "Supported packaged synthetic regeneration closure only; not full transaction rollback, "
                "private deployment correctness, LLM quality, ranking, vector search, or ontology discovery."
            ),
        }
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "status": "failed",
            "failure": {"reason": str(exc)},
            "privacy": {"synthetic_only": True, "private_content_rendered": False},
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
