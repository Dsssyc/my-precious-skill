import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BackfillMemoryArchiveTests(unittest.TestCase):
    def test_backfill_memory_archive_removes_collected_group_entries_directly(self):
        script_dir = Path("templates/agent-memory-repo/tools").resolve()
        sys.path.insert(0, str(script_dir))
        try:
            import backfill_memory_archive as backfill
        finally:
            sys.path.remove(str(script_dir))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            project_path = root / "project"
            source_record = root / "records" / "rollout.jsonl"
            entry_a = memory_repo / "sessions/2026/05/14/stale-a"
            entry_b = memory_repo / "sessions/2026/05/14/stale-b"
            untouched = memory_repo / "sessions/2026/05/14/untouched"
            for entry in (entry_a, entry_b, untouched):
                entry.mkdir(parents=True)
                (entry / "meta.json").write_text("{}", encoding="utf-8")

            group = backfill.BackfillGroup(
                project_path=project_path,
                project_name="project",
                source_agent="agent",
                source_record=source_record,
                entries=[entry_a, entry_b],
            )

            removed = backfill.remove_group_entries(memory_repo, group)

            self.assertEqual(removed, 2)
            self.assertFalse(entry_a.exists())
            self.assertFalse(entry_b.exists())
            self.assertTrue(untouched.exists())

    def test_backfill_memory_archive_rewrites_existing_meta_source_groups(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "rollout.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Backfill the stale memory entry from existing archive metadata.",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:01Z",
                        "cwd": str(project_path),
                        "role": "assistant",
                        "content": "Decision: meta-driven backfill should remove wrapper-field summaries.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            for name, stamp in (("stale-a", "2026-05-14T09:00:00Z"), ("stale-b", "2026-05-14T09:30:00Z")):
                entry_dir = memory_repo / "sessions/2026/05/14" / name
                entry_dir.mkdir(parents=True)
                (entry_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "session_id": name,
                            "source_agent": "agent",
                            "project": "project",
                            "project_path": str(project_path.resolve()),
                            "source_record": str(source.resolve()),
                            "source_record_sha256": name,
                            "source_updated_at": stamp,
                            "summary_path": f"sessions/2026/05/14/{name}/summary.md",
                            "evidence_path": f"sessions/2026/05/14/{name}/evidence.md",
                            "archive_status": "summarized",
                            "redaction_status": "none",
                            "contains_raw_transcript": False,
                            "evidence_policy": "short_redacted_snippets",
                            "user_intent": "session_meta: stale",
                            "summary": "response_item: stale",
                            "reusable_facts": ["base_instructions"],
                            "tags": ["session_meta"],
                            "decisions": [],
                            "unresolved_tasks": [],
                            "redaction_counts": {},
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (entry_dir / "summary.md").write_text("session_meta: stale\n", encoding="utf-8")
                (entry_dir / "evidence.md").write_text("response_item: stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/backfill_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--project-path",
                    str(project_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Source records selected: 1", result.stdout)
            self.assertIn("Existing entries removed: 2", result.stdout)
            self.assertFalse((memory_repo / "sessions/2026/05/14/stale-a").exists())
            self.assertFalse((memory_repo / "sessions/2026/05/14/stale-b").exists())
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("Backfill the stale memory", rows[0]["user_intent"])
            self.assertNotIn("session_meta", json.dumps(rows[0]))

    def test_backfill_memory_archive_can_prune_noisy_entries_with_missing_sources(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            project_path = root / "project"
            missing_source = root / "missing" / "rollout.jsonl"
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/missing-noisy"
            entry_dir.mkdir(parents=True)
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "session_id": entry_dir.name,
                        "source_agent": "agent",
                        "project": "project",
                        "project_path": str(project_path.resolve()),
                        "source_record": str(missing_source.resolve()),
                        "source_record_sha256": "oldhash",
                        "source_updated_at": "2026-05-14T09:00:00Z",
                        "summary_path": "sessions/2026/05/14/missing-noisy/summary.md",
                        "evidence_path": "sessions/2026/05/14/missing-noisy/evidence.md",
                        "archive_status": "summarized",
                        "redaction_status": "none",
                        "contains_raw_transcript": False,
                        "evidence_policy": "short_redacted_snippets",
                        "user_intent": "session_meta: stale",
                        "summary": "response_item: stale",
                        "reusable_facts": [],
                        "tags": ["session_meta"],
                        "decisions": [],
                        "unresolved_tasks": [],
                        "redaction_counts": {},
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (entry_dir / "summary.md").write_text("session_meta: stale\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("response_item: stale\n", encoding="utf-8")
            stale_daily = memory_repo / "daily/2026/2026-05-13.md"
            stale_daily.parent.mkdir(parents=True)
            stale_daily.write_text("session_meta: stale daily entry\n", encoding="utf-8")

            live_source = root / "records" / "live.jsonl"
            live_source.parent.mkdir()
            live_source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "This valid entry should not be rewritten during prune-only.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            live_dir = memory_repo / "sessions/2026/05/14/live-valid"
            live_dir.mkdir(parents=True)
            (live_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "session_id": live_dir.name,
                        "source_agent": "agent",
                        "project": "project",
                        "project_path": str(project_path.resolve()),
                        "source_record": str(live_source.resolve()),
                        "source_record_sha256": "livehash",
                        "source_updated_at": "2026-05-14T10:00:00Z",
                        "summary_path": "sessions/2026/05/14/live-valid/summary.md",
                        "evidence_path": "sessions/2026/05/14/live-valid/evidence.md",
                        "archive_status": "summarized",
                        "redaction_status": "none",
                        "contains_raw_transcript": False,
                        "evidence_policy": "short_redacted_snippets",
                        "user_intent": "Clean existing entry.",
                        "summary": "Clean existing entry.",
                        "reusable_facts": [],
                        "tags": ["agent-memory"],
                        "decisions": [],
                        "unresolved_tasks": [],
                        "redaction_counts": {},
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (live_dir / "summary.md").write_text("Clean existing entry.\n", encoding="utf-8")
            (live_dir / "evidence.md").write_text("Clean existing evidence.\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/backfill_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--prune-missing-source-noise",
                    "--prune-only",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Missing-source noisy entries pruned: 1", result.stdout)
            self.assertNotIn("Rewritten:", result.stdout)
            self.assertFalse(entry_dir.exists())
            self.assertFalse(stale_daily.exists())
            self.assertTrue(live_dir.exists())
            sessions_index = memory_repo / "index/sessions.jsonl"
            self.assertTrue(sessions_index.exists() and sessions_index.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
