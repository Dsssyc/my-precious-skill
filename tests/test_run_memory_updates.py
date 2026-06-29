import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RunMemoryUpdatesTests(unittest.TestCase):
    def test_run_memory_updates_bootstraps_empty_project_registry(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir(parents=True)
            project_a.mkdir()
            project_b.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (source_dir / "a.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Need project alpha memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "b.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T11:00:00Z",
                        "cwd": str(project_b),
                        "role": "user",
                        "content": "Need project beta memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Registered new projects: 2", result.stdout)
            registry_rows = [
                json.loads(line)
                for line in (memory_repo / "config/projects.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual({row["project_path"] for row in registry_rows}, {str(project_a.resolve()), str(project_b.resolve())})
            self.assertTrue(all(row["enabled"] for row in registry_rows))

            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual({row["project_path"] for row in session_rows}, {str(project_a.resolve()), str(project_b.resolve())})

            second = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertIn("Registered new projects: 0", second.stdout)
            session_rows_after = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows_after), 2)

    def test_run_memory_updates_respects_disabled_registered_project(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "disabled-project"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (memory_repo / "config/projects.jsonl").write_text(
                json.dumps(
                    {
                        "project_path": str(project_path.resolve()),
                        "source_dir": str(source_dir.resolve()),
                        "enabled": False,
                        "source": "manual",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "disabled.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Disabled project should not be archived.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Projects updated: 0", result.stdout)
            sessions_index = memory_repo / "index/sessions.jsonl"
            self.assertFalse(sessions_index.exists() and sessions_index.read_text(encoding="utf-8").strip())

    def test_run_memory_updates_sanitizes_slugged_paths_in_status_output(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory-cookie_should_not_render"
            source_dir = root / ".codex" / "sessions-cookie_should_not_render"
            project_path = root / "project-cookie_should_not_render"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (source_dir / "sensitive-path.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Runner status output should not expose slugged sensitive path tokens.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertIn("[unsafe-path]", combined)
            self.assertNotIn("cookie_should_not_render", combined)
            self.assertNotIn("cookie", combined.lower())

    def test_run_memory_updates_refuses_symlinked_project_registry_outside_archive(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "project-registry"
            outside_registry = root / "outside-projects.jsonl"
            source_dir.mkdir(parents=True)
            project_path.mkdir()
            outside_registry.write_text("unchanged\n", encoding="utf-8")

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            (memory_repo / "config/projects.jsonl").unlink()
            (memory_repo / "config/projects.jsonl").symlink_to(outside_registry)

            (source_dir / "registry.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Project registry writes must stay inside the archive.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to access unsafe project registry path:", output)
            self.assertEqual(outside_registry.read_text(encoding="utf-8"), "unchanged\n")

    def test_run_memory_updates_uses_custom_patterns_for_discovery_and_update(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "project-custom"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (source_dir / "session.events").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Custom extension source record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--pattern",
                    "*.events",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows), 1)
            self.assertEqual(session_rows[0]["project_path"], str(project_path.resolve()))

    def test_run_memory_updates_passes_registered_archive_scope_to_updater(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "project-scoped"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (memory_repo / "config/projects.jsonl").write_text(
                json.dumps(
                    {
                        "project_path": str(project_path.resolve()),
                        "archive_scope": "domain:runner-scope",
                        "source_dir": str(source_dir.resolve()),
                        "enabled": True,
                        "source": "manual",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "runner-scope.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Decision: registered archive scope should pass through the runner.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Projects updated: 1", result.stdout)
            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows), 1)
            self.assertEqual(session_rows[0]["archive_scope"], "domain:runner-scope")
            scope_rows = [
                json.loads(line)
                for line in (memory_repo / "index/scopes.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(scope_rows[0]["archive_scope"], "domain:runner-scope")

    def test_run_memory_updates_can_rewrite_existing_project_archives(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "project-backfill"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            source = source_dir / "rewrite.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Backfill this project with clean extracted memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stale_dir = memory_repo / "sessions/2026/05/14/stale-backfill"
            stale_dir.mkdir(parents=True)
            (stale_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "session_id": stale_dir.name,
                        "source_agent": "agent",
                        "project": "project-backfill",
                        "project_path": str(project_path.resolve()),
                        "source_record": str(source.resolve()),
                        "source_record_sha256": "oldhash",
                        "source_updated_at": "2026-05-14T09:00:00Z",
                        "summary_path": "sessions/2026/05/14/stale-backfill/summary.md",
                        "evidence_path": "sessions/2026/05/14/stale-backfill/evidence.md",
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
            (stale_dir / "summary.md").write_text("session_meta: stale\n", encoding="utf-8")
            (stale_dir / "evidence.md").write_text("response_item: stale\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--rewrite-existing",
                    "--max-records",
                    "-1",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Existing entries removed: 1", result.stdout)
            self.assertFalse(stale_dir.exists())
            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows), 1)
            self.assertIn("Backfill this project", session_rows[0]["user_intent"])
            self.assertNotIn("session_meta", json.dumps(session_rows[0]))

    def test_run_memory_updates_can_allow_redacted_secret_records(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            project_path = root / "project-secret"
            source_dir.mkdir(parents=True)
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            fake_key = "sk-" + ("notreal" * 4)
            (source_dir / "secret.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": f"Store memory but redact {fake_key}.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--allow-redacted-secrets",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Projects updated: 1", result.stdout)
            summary_paths = list((memory_repo / "sessions").glob("**/summary.md"))
            self.assertEqual(len(summary_paths), 1)
            entry_dir = summary_paths[0].parent
            combined = "\n".join(path.read_text(encoding="utf-8") for path in entry_dir.glob("*"))
            self.assertNotIn(fake_key, combined)
            self.assertIn("openai_key", (entry_dir / "redactions.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
