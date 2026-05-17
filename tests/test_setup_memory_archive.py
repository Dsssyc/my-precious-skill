import plistlib
import json
import importlib.util
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def load_setup_module():
    script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
    spec = importlib.util.spec_from_file_location("setup_memory_archive", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SetupMemoryArchiveTests(unittest.TestCase):
    def test_setup_memory_archive_creates_local_template(self):
        script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            config_path = Path(tmpdir) / "my-precious-config.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--path",
                    str(target),
                    "--mode",
                    "local",
                    "--config-path",
                    str(config_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertTrue((target / "README.md").exists())
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / "config/projects.jsonl").exists())
            self.assertTrue((target / "tools/search_memory.py").exists())
            self.assertTrue((target / "tools/update_memory_archive.py").exists())
            self.assertTrue((target / "tools/run_memory_updates.py").exists())
            self.assertTrue((target / "tools/render_scheduler.py").exists())
            self.assertTrue((target / "tools/sync_memory_archive.py").exists())
            self.assertTrue((target / "schemas/session_summary.schema.json").exists())
            self.assertIn("Archive ready:", result.stdout)
            self.assertIn("AGENT_SESSION_MEMORY_REPO", result.stdout)
            self.assertIn("Config written:", result.stdout)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["memory_repo"], str(target.resolve()))
            self.assertEqual(config["version"], 1)

    def test_write_config_uses_private_permissions(self):
        module = load_setup_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            target.mkdir()
            config_path = Path(tmpdir) / "config" / "my-precious.json"

            module.write_config(target, config_path, dry_run=False)

            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(config_path.parent.stat().st_mode), 0o700)

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

    def test_github_mode_refuses_to_push_existing_git_history_without_explicit_flag(self):
        script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            target.mkdir()
            subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=target, check=True)
            (target / "already-committed.secret").write_text("local secret", encoding="utf-8")
            subprocess.run(["git", "add", "already-committed.secret"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "commit", "-m", "Existing private history"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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
                    "--force",
                    "--dry-run",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing Git history", result.stderr)
            self.assertIn("--allow-existing-history", result.stderr)

    def test_initial_commit_stages_only_template_files(self):
        module = load_setup_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            target.mkdir()
            (target / "do-not-publish.secret").write_text("local secret", encoding="utf-8")

            module.copy_template(target, force=True, dry_run=False)
            subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            module.stage_template_files(target, dry_run=False)

            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=target,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.splitlines()

            self.assertIn("?? do-not-publish.secret", status)
            self.assertTrue(any(line.endswith("README.md") and line.startswith("A") for line in status))

    def test_initial_commit_refuses_preexisting_staged_files(self):
        module = load_setup_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent-memory"
            target.mkdir()
            (target / "pre-staged.secret").write_text("local secret", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "pre-staged.secret"], cwd=target, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            module.copy_template(target, force=True, dry_run=False)

            with self.assertRaises(SystemExit) as caught:
                module.initial_commit(target, dry_run=False)

            self.assertIn("preexisting staged changes", str(caught.exception))
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=target,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.splitlines()
            self.assertIn("A  pre-staged.secret", status)
            head_check = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=target,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(head_check.returncode, 0)

    def test_template_copy_and_staging_ignore_generated_python_caches(self):
        module = load_setup_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            template = root / "template"
            template.mkdir()
            (template / "tools/__pycache__").mkdir(parents=True)
            (template / "README.md").write_text("template", encoding="utf-8")
            (template / "tools/search_memory.py").write_text("print('search')\n", encoding="utf-8")
            (template / "tools/__pycache__/search_memory.pyc").write_bytes(b"cache")
            old_template = module.TEMPLATE_DIR
            module.TEMPLATE_DIR = template
            try:
                self.assertEqual(module.template_files(), ["README.md", "tools/search_memory.py"])

                target = root / "agent-memory"
                module.copy_template(target, force=False, dry_run=False)

                self.assertTrue((target / "README.md").exists())
                self.assertTrue((target / "tools/search_memory.py").exists())
                self.assertFalse((target / "tools/__pycache__/search_memory.pyc").exists())
            finally:
                module.TEMPLATE_DIR = old_template

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
                [sys.executable, str(setup_script), "--path", str(target), "--mode", "local", "--skip-config"],
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

    def test_render_scheduler_defaults_to_global_runner(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            source_dir.mkdir(parents=True)

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(target), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rendered = root / "agent-memory-global.plist"
            subprocess.run(
                [
                    sys.executable,
                    str(target / "tools/render_scheduler.py"),
                    "--source-dir",
                    str(source_dir),
                    "--backend",
                    "launchd",
                    "--schedule",
                    "daily",
                    "--allow-redacted-secrets",
                    "--output",
                    str(rendered),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = plistlib.loads(rendered.read_bytes())
            self.assertIn(str((target / "tools/run_memory_updates.py").resolve()), payload["ProgramArguments"])
            self.assertIn(str(source_dir.resolve()), payload["ProgramArguments"])
            self.assertIn("--allow-redacted-secrets", payload["ProgramArguments"])
            self.assertNotIn("--project-path", payload["ProgramArguments"])
            self.assertNotIn(str((target / "tools/update_memory_archive.py").resolve()), payload["ProgramArguments"])

    def test_render_scheduler_can_render_agent_native_prompt(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            source_dir.mkdir(parents=True)

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(target), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rendered = root / "agent-native.txt"
            subprocess.run(
                [
                    sys.executable,
                    str(target / "tools/render_scheduler.py"),
                    "--source-dir",
                    str(source_dir),
                    "--backend",
                    "agent-native",
                    "--allow-redacted-secrets",
                    "--push-after-update",
                    "--output",
                    str(rendered),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            prompt = rendered.read_text(encoding="utf-8")
            self.assertIn("Use exactly one working directory", prompt)
            self.assertIn(str(target.resolve()), prompt)
            self.assertIn("--allow-redacted-secrets", prompt)
            self.assertIn("tools/sync_memory_archive.py --push", prompt)

    def test_render_scheduler_refuses_global_schedule_without_runner(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "agent-memory"
            source_dir = root / ".codex" / "sessions"
            source_dir.mkdir(parents=True)

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(target), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            (target / "tools/run_memory_updates.py").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(target / "tools/render_scheduler.py"),
                    "--source-dir",
                    str(source_dir),
                    "--backend",
                    "launchd",
                    "--schedule",
                    "daily",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run_memory_updates.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
