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
