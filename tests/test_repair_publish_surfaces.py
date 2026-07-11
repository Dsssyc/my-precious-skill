import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SETUP_SCRIPT = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()


def run(command: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result


def setup_archive(root: Path) -> Path:
    repo = root / "agent-memory"
    run(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(repo),
            "--mode",
            "local",
            "--skip-config",
        ]
    )
    return repo


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_session(repo: Path, *, summary: str) -> Path:
    session_dir = repo / "sessions/2026/07/08/synthetic"
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = "sessions/2026/07/08/synthetic/summary.md"
    evidence_path = "sessions/2026/07/08/synthetic/evidence.md"
    source_map_path = "sessions/2026/07/08/synthetic/source-map.json"
    (repo / summary_path).write_text("# Summary\n\nDurable package-first recall remains current.\n", encoding="utf-8")
    (repo / evidence_path).write_text("# Evidence\n\n- ev_001: Durable evidence.\n", encoding="utf-8")
    write_json(
        repo / source_map_path,
        {"summary_path": summary_path, "evidence_path": evidence_path, "source_map_path": source_map_path},
    )
    meta_path = session_dir / "meta.json"
    write_json(
        meta_path,
        {
            "session_id": "synthetic-repair",
            "source_agent": "synthetic",
            "project": "synthetic",
            "project_path": "/tmp/synthetic",
            "archive_scope": "/tmp/synthetic",
            "source_partition": "/tmp/synthetic",
            "source_updated_at": "2026-07-08T00:00:00Z",
            "archive_status": "summarized",
            "redaction_status": "redacted",
            "summary_path": summary_path,
            "evidence_path": evidence_path,
            "source_map_path": source_map_path,
            "summary": summary,
            "reusable_facts": [
                "Durable package-first recall remains current.",
                "Approval policy is currently never PRIVATE_FACT_SENTINEL.",
                "raw source path: /Users/example/private/source-record.jsonl",
            ],
            "tags": ["package-first", "unit tests PRIVATE_TAG_SENTINEL"],
            "raw_prompts": ["raw prompt: PRIVATE_RAW_SENTINEL"],
            "decisions": [],
            "unresolved_tasks": [],
            "explicit_memories": [],
        },
    )
    return meta_path


def rebuild(repo: Path) -> None:
    empty = repo / ".empty-source"
    empty.mkdir(exist_ok=True)
    run(
        [
            sys.executable,
            str(repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(repo),
            "--source-dir",
            str(empty),
            "--project-path",
            str(repo),
            "--max-records",
            "0",
        ],
        cwd=repo,
    )


def audit(repo: Path) -> subprocess.CompletedProcess[str]:
    return run(
        [sys.executable, str(repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(repo)],
        cwd=repo,
        check=False,
    )


def repair(repo: Path, *, apply: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(repo / "tools/repair_publish_surfaces.py"), "--memory-repo", str(repo)]
    if apply:
        command.append("--apply")
    return run(command, cwd=repo, check=False)


class RepairPublishSurfacesTests(unittest.TestCase):
    def test_dry_run_is_aggregate_and_apply_repairs_derived_publish_surfaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = setup_archive(Path(tmpdir))
            meta_path = write_session(
                repo,
                summary=(
                    "Durable package-first recall remains current. "
                    "Command Status: dry-run would push after commit PRIVATE_SUMMARY_SENTINEL."
                ),
            )
            rebuild(repo)
            self.assertNotEqual(audit(repo).returncode, 0)

            dry = repair(repo)

            self.assertEqual(dry.returncode, 0, dry.stderr)
            dry_report = json.loads(dry.stdout)
            self.assertEqual(dry_report["status"], "repairable")
            self.assertTrue(dry_report["privacy"]["aggregate_only"])
            self.assertEqual(dry_report["privacy_leak_count"], 0)
            combined = dry.stdout + dry.stderr
            for marker in (
                "PRIVATE_SUMMARY_SENTINEL",
                "PRIVATE_FACT_SENTINEL",
                "PRIVATE_TAG_SENTINEL",
                "PRIVATE_RAW_SENTINEL",
                "/Users/example/private/source-record.jsonl",
                str(meta_path),
            ):
                self.assertNotIn(marker, combined)

            applied = repair(repo, apply=True)

            self.assertEqual(applied.returncode, 0, applied.stderr)
            report = json.loads(applied.stdout)
            self.assertEqual(report["status"], "repaired")
            self.assertTrue(report["metrics"]["rebuild_performed"])
            self.assertEqual(audit(repo).returncode, 0)
            repaired_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rendered = json.dumps(repaired_meta, sort_keys=True)
            self.assertIn("Durable package-first recall remains current.", rendered)
            self.assertIn("package-first", rendered)
            self.assertNotIn("dry-run", rendered)
            self.assertNotIn("Approval policy", rendered)
            self.assertNotIn("unit tests", rendered)
            self.assertNotIn("/Users/example/private/source-record.jsonl", rendered)

    def test_ambiguous_scalar_fails_closed_without_rebuild(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = setup_archive(Path(tmpdir))
            meta_path = write_session(
                repo,
                summary="Durable package-first recall remains current while command status dry-run would push",
            )
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["user_intent"] = ""
            meta["reusable_facts"] = []
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rebuild(repo)

            result = repair(repo, apply=True)

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["metrics"]["ambiguous_scalar_count"], 1)
            self.assertFalse(report["metrics"]["rebuild_performed"])
            repaired_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertIn("dry-run", repaired_meta["summary"])

    def test_ambiguous_summary_uses_clean_metadata_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = setup_archive(Path(tmpdir))
            meta_path = write_session(
                repo,
                summary="Command Status: dry-run would push PRIVATE_SUMMARY_SENTINEL",
            )
            rebuild(repo)
            self.assertNotEqual(audit(repo).returncode, 0)

            result = repair(repo, apply=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "repaired")
            self.assertEqual(report["metrics"]["ambiguous_scalar_count"], 0)
            self.assertGreaterEqual(report["metrics"]["scalar_fields_rewritten"], 1)
            self.assertTrue(report["metrics"]["rebuild_performed"])
            self.assertEqual(audit(repo).returncode, 0)
            repaired_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertNotIn("PRIVATE_SUMMARY_SENTINEL", repaired_meta["summary"])
            self.assertNotIn("dry-run", repaired_meta["summary"])
            rendered = json.dumps(repaired_meta, sort_keys=True)
            self.assertIn("Durable package-first recall remains current.", rendered)

    def test_malformed_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = setup_archive(Path(tmpdir))
            meta_path = repo / "sessions/2026/07/08/malformed/meta.json"
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text('{"summary": "Command Status: dry-run would push"', encoding="utf-8")

            result = repair(repo)

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["metrics"]["malformed_meta_count"], 1)
            self.assertEqual(report["privacy_leak_count"], 0)

    def test_nested_strings_under_text_bearing_fields_are_repaired(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = setup_archive(Path(tmpdir))
            meta_path = write_session(
                repo,
                summary="Durable package-first recall remains current.",
            )
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["reusable_facts"] = [
                {"kind": "durable", "value": "Nested durable fact remains current."},
                {"kind": "noisy", "value": "Command Status: dry-run would push PRIVATE_NESTED_SENTINEL."},
            ]
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rebuild(repo)
            self.assertNotEqual(audit(repo).returncode, 0)

            result = repair(repo, apply=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(audit(repo).returncode, 0)
            repaired_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            rendered = json.dumps(repaired_meta, sort_keys=True)
            self.assertIn("Nested durable fact remains current.", rendered)
            self.assertNotIn("PRIVATE_NESTED_SENTINEL", rendered)


if __name__ == "__main__":
    unittest.main()
