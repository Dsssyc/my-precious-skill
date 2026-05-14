import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SetupMemoryArchiveTests(unittest.TestCase):
    def test_setup_memory_archive_creates_local_template(self):
        script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            result = subprocess.run(
                [sys.executable, str(script), "--path", str(target), "--mode", "local"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertTrue((target / "README.md").exists())
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / "tools/search_memory.py").exists())
            self.assertTrue((target / "tools/update_memory_archive.py").exists())
            self.assertTrue((target / "tools/render_scheduler.py").exists())
            self.assertTrue((target / "schemas/session_summary.schema.json").exists())
            self.assertIn("Archive ready:", result.stdout)
            self.assertIn("AGENT_SESSION_MEMORY_REPO", result.stdout)

    def test_setup_memory_archive_refuses_non_empty_without_force(self):
        script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            target.mkdir()
            (target / "existing.txt").write_text("do not overwrite silently", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(script), "--path", str(target), "--mode", "local"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("target is not empty", result.stderr)

    def test_setup_memory_archive_github_mode_dry_run(self):
        script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--path",
                    str(target),
                    "--mode",
                    "github",
                    "--github-repo",
                    "owner/agent-memory",
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("dry-run: copy", result.stdout)
            self.assertIn("dry-run: git init", result.stdout)
            self.assertIn("dry-run: gh repo create owner/agent-memory", result.stdout)
            self.assertIn("--private", result.stdout)

    def test_render_scheduler_generates_reviewable_launchd_plist(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(target), "--mode", "local"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rendered = root / "agent-memory.plist"
            subprocess.run(
                [
                    sys.executable,
                    str(target / "tools/render_scheduler.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--backend",
                    "launchd",
                    "--schedule",
                    "hourly",
                    "--output",
                    str(rendered),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = plistlib.loads(rendered.read_bytes())
            self.assertEqual(payload["Label"], "com.agent-memory.update")
            self.assertEqual(payload["StartInterval"], 3600)
            self.assertIn(str((target / "tools/update_memory_archive.py").resolve()), payload["ProgramArguments"])
            self.assertIn(str(source_dir.resolve()), payload["ProgramArguments"])
            self.assertEqual(payload["EnvironmentVariables"]["AGENT_SESSION_MEMORY_REPO"], str(target.resolve()))
            self.assertTrue((target / ".tmp/logs").is_dir())


if __name__ == "__main__":
    unittest.main()
