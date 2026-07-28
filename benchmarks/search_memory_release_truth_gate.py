#!/usr/bin/env python3
"""Gate the approved search runtime across every installable surface."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_KIND = "search_memory_release_truth_gate"
APPROVED_SOURCE_COMMIT = "b076f5585ee3bfe0a8b2db07718ec9b32a3e03dd"
APPROVED_SEARCH_SHA256 = "e73b7b6600db8a147d667f91f08eef0562b5029e487950a7fa228c4903f8d248"
REJECTED_SEARCH_SHA256 = {
    "3e0715d25cf0d59703774c5e9d41a19155e92ce85fa8f11549516449d3c15875",
    "29e20ef5f63570d37d09eb878916d66de57ff44e9f8e794bd5f1ec33e25eefed",
}
REJECTED_RUNTIME_SYMBOLS = (
    "scoped_global_preference_applicability",
    "normalized_subject_candidate_v1",
    "source_bound_subject_preference_support_v1",
)
RELEASE_SURFACES = (
    REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py",
    REPO_ROOT / "skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py",
    REPO_ROOT / "skills/using-my-precious/scripts/search_memory.py",
)
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
SYNTHETIC_FACT = "Release truth health marker stays synthetic."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def seed_health_memory(memory_repo: Path) -> None:
    summary = memory_repo / "sessions/synthetic/release-truth/summary.md"
    evidence = memory_repo / "sessions/synthetic/release-truth/evidence.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("# Synthetic release truth\n", encoding="utf-8")
    evidence.write_text("ev_release_truth_001: synthetic gate evidence\n", encoding="utf-8")
    row = {
        "memory_id": "release_truth_synthetic_memory",
        "layer": "global",
        "scope": "global",
        "topic": "release truth",
        "text": SYNTHETIC_FACT,
        "source": "synthetic",
        "confidence": "high",
        "support_count": 1,
        "derived_from": ["sessions/synthetic/release-truth/summary.md"],
        "evidence_refs": [
            {
                "path": "sessions/synthetic/release-truth/evidence.md",
                "quote_id": "ev_release_truth_001",
            }
        ],
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": None,
    }
    index_path = memory_repo / "index/memories.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def packaged_probe(root: Path) -> tuple[str, bool, bool]:
    memory_repo = root / "agent-memory"
    try:
        setup = run(
            [
                sys.executable,
                str(SETUP_SCRIPT),
                "--path",
                str(memory_repo),
                "--skip-config",
            ]
        )
    except OSError:
        return "", False, True
    if setup.returncode:
        return "", False, False
    packaged_search = memory_repo / "tools/search_memory.py"
    if not packaged_search.is_file():
        return "", False, False
    seed_health_memory(memory_repo)
    try:
        packaged_hash = sha256(packaged_search)
        health = run(
            [
                sys.executable,
                str(packaged_search),
                "--repo",
                str(memory_repo),
                "--health-check",
            ],
            cwd=memory_repo,
        )
    except OSError:
        return "", False, True
    return packaged_hash, health.returncode == 0, False


def privacy_leak_count(report: dict[str, Any], root: Path) -> int:
    rendered = json.dumps(report, sort_keys=True)
    return sum(
        marker in rendered
        for marker in (
            str(REPO_ROOT),
            str(root),
            SYNTHETIC_FACT,
            *REJECTED_RUNTIME_SYMBOLS,
        )
    )


def build_report(root: Path) -> dict[str, Any]:
    surface_hashes: list[str | None] = []
    surface_texts: list[str | None] = []
    failure_counts = {
        "missing_surface_count": 0,
        "unreadable_surface_count": 0,
        "invalid_utf8_surface_count": 0,
        "packaged_probe_error_count": 0,
    }
    for path in RELEASE_SURFACES:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            failure_counts["missing_surface_count"] += 1
            surface_hashes.append(None)
            surface_texts.append(None)
            continue
        except OSError:
            failure_counts["unreadable_surface_count"] += 1
            surface_hashes.append(None)
            surface_texts.append(None)
            continue
        surface_hashes.append(hashlib.sha256(content).hexdigest())
        try:
            surface_texts.append(content.decode("utf-8"))
        except UnicodeDecodeError:
            failure_counts["invalid_utf8_surface_count"] += 1
            surface_texts.append(None)

    packaged_hash, packaged_health, packaged_probe_error = packaged_probe(root)
    failure_counts["packaged_probe_error_count"] = int(packaged_probe_error)
    surface_count = len(RELEASE_SURFACES)
    readable_count = sum(value is not None for value in surface_hashes)
    utf8_count = sum(value is not None for value in surface_texts)
    metrics: dict[str, float | int] = {
        "release_surface_read_rate": readable_count / surface_count,
        "release_surface_utf8_rate": utf8_count / surface_count,
        "release_surface_parity_rate": 1.0
        if readable_count == surface_count and len(set(surface_hashes)) == 1
        else 0.0,
        "approved_runtime_match_rate": (
            sum(value == APPROVED_SEARCH_SHA256 for value in surface_hashes)
            / surface_count
        ),
        "rejected_runtime_absence_rate": 1.0
        if readable_count == surface_count
        and utf8_count == surface_count
        and all(
            value not in REJECTED_SEARCH_SHA256
            and text is not None
            and not any(symbol in text for symbol in REJECTED_RUNTIME_SYMBOLS)
            for value, text in zip(surface_hashes, surface_texts, strict=True)
        )
        else 0.0,
        "packaged_runtime_match_rate": 1.0
        if packaged_hash == APPROVED_SEARCH_SHA256
        else 0.0,
        "packaged_health_check_rate": 1.0 if packaged_health else 0.0,
        "privacy_leak_count": 0,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "claim_boundary": (
            "approved packaged search-runtime truth only; not semantic recall quality, "
            "ranking quality, private deployment parity, or LLM answer quality"
        ),
        "approved_runtime": {
            "source_commit": APPROVED_SOURCE_COMMIT,
            "sha256": APPROVED_SEARCH_SHA256,
        },
        "release_surface_count": surface_count,
        "failure_counts": failure_counts,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "paths_rendered": False,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "memory_ids_rendered": False,
            "context_packages_rendered": False,
        },
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report, root)
    required = (
        "release_surface_read_rate",
        "release_surface_utf8_rate",
        "release_surface_parity_rate",
        "approved_runtime_match_rate",
        "rejected_runtime_absence_rate",
        "packaged_runtime_match_rate",
        "packaged_health_check_rate",
    )
    if any(metrics[name] != 1.0 for name in required) or metrics["privacy_leak_count"]:
        report["status"] = "failed"
    return report


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-release-truth-") as tmpdir:
            report = build_report(Path(tmpdir))
    except Exception:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure_stage": "unexpected_gate_failure",
            "privacy": {"aggregate_only": True, "paths_rendered": False},
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
