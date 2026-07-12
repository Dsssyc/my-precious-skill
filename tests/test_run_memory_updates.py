import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


def load_runner_module():
    path = Path("templates/agent-memory-repo/tools/run_memory_updates.py").resolve()
    spec = importlib.util.spec_from_file_location("run_memory_updates_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RunMemoryUpdatesTests(unittest.TestCase):
    def test_source_inventory_reads_each_candidate_once_and_preserves_dispatch_semantics(self):
        module = load_runner_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "records"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir()
            project_a.mkdir()
            project_b.mkdir()

            fixtures = {
                "a.jsonl": {
                    "timestamp": "2026-07-13T01:00:00Z",
                    "cwd": str(project_a),
                    "role": "user",
                    "content": "Synthetic project A inventory record.",
                },
                "b.jsonl": {
                    "timestamp": "2026-07-13T02:00:00Z",
                    "cwd": str(project_b),
                    "role": "user",
                    "content": "Synthetic project B inventory record.",
                },
                "stream.jsonl": {
                    "timestamp": "2026-07-13T03:00:00Z",
                    "role": "user",
                    "content": "Synthetic source stream record without project metadata.",
                },
            }
            for name, payload in fixtures.items():
                (source_dir / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            (source_dir / "automation.jsonl").write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "cwd": str(project_a),
                            "thread_source": "automation",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            original_read_bytes = Path.read_bytes
            read_counts: dict[Path, int] = {}

            def counted_read_bytes(path: Path) -> bytes:
                resolved = path.resolve()
                read_counts[resolved] = read_counts.get(resolved, 0) + 1
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", counted_read_bytes):
                inventory = module.build_source_inventory(
                    source_dir,
                    ("*.jsonl", "a*.jsonl"),
                )

            self.assertEqual(set(read_counts.values()), {1})
            self.assertEqual(len(read_counts), 4)
            self.assertEqual(
                [record.relative_path for record in inventory],
                ["a.jsonl", "b.jsonl", "stream.jsonl"],
            )
            self.assertEqual(
                module.discover_projects_from_inventory(inventory),
                [project_a.resolve(), project_b.resolve()],
            )
            self.assertEqual(
                [
                    record.relative_path
                    for record in module.inventory_records_for_target(
                        inventory,
                        project_a,
                        require_project_metadata=True,
                    )
                ],
                ["a.jsonl"],
            )
            self.assertEqual(
                [
                    record.relative_path
                    for record in module.inventory_records_for_target(
                        inventory,
                        root / "source-stream",
                        require_project_metadata=False,
                    )
                ],
                ["stream.jsonl"],
            )

    def test_source_inventory_fails_closed_on_symlink_escape_without_rendering_paths(self):
        module = load_runner_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "records"
            source_dir.mkdir()
            outside = root / "PRIVATE_INVENTORY_ESCAPE.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            (source_dir / "escape.jsonl").symlink_to(outside)

            with self.assertRaises(module.SourceInventoryError) as raised:
                module.build_source_inventory(source_dir, ("*.jsonl",))

            self.assertEqual(str(raised.exception), "source_inventory_unsafe")
            self.assertNotIn(str(root), str(raised.exception))
            self.assertNotIn(outside.name, str(raised.exception))

    def test_runner_classifies_unsafe_source_inventory_before_child_launch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            tools_dir = memory_repo / "tools"
            config_dir = memory_repo / "config"
            tools_dir.mkdir(parents=True)
            config_dir.mkdir()
            source_dir.mkdir()
            shutil.copyfile(
                Path("templates/agent-memory-repo/tools/run_memory_updates.py"),
                tools_dir / "run_memory_updates.py",
            )
            marker = root / "child-launched"
            (tools_dir / "update_memory_archive.py").write_text(
                "from pathlib import Path\nPath('" + str(marker) + "').touch()\n",
                encoding="utf-8",
            )
            (config_dir / "projects.jsonl").write_text("", encoding="utf-8")
            outside = root / "PRIVATE_RUNNER_ESCAPE.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            (source_dir / "escape.jsonl").symlink_to(outside)

            result = subprocess.run(
                [
                    sys.executable,
                    str(tools_dir / "run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("update_status=blocked reason=source_inventory_invalid", result.stderr)
            self.assertFalse(marker.exists())
            self.assertNotIn(str(root), result.stdout + result.stderr)
            self.assertNotIn(outside.name, result.stdout + result.stderr)

    def test_run_memory_updates_runs_registered_source_stream_without_project_registry(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "agent-source-stream"
            runner_source_dir = root / "empty-project-discovery"
            source_dir.mkdir(parents=True)
            runner_source_dir.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            (memory_repo / "config/projects.jsonl").write_text("", encoding="utf-8")
            (memory_repo / "config/source_streams.jsonl").write_text(
                json.dumps(
                    {
                        "stream_id": "domain-agent-memory",
                        "source_dir": str(source_dir.resolve()),
                        "archive_scope": "domain:agent-memory",
                        "source_partition": "source:agent-memory",
                        "project": "agent-memory-domain",
                        "enabled": True,
                        "source": "manual",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "domain.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "role": "user",
                        "content": "Decision: domain source streams should update without project metadata.",
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
                    str(runner_source_dir),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Enabled source streams: 1", result.stdout)
            self.assertIn("Source streams updated: 1", result.stdout)
            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows), 1)
            self.assertEqual(session_rows[0]["archive_scope"], "domain:agent-memory")
            self.assertEqual(session_rows[0]["source_partition"], "source:agent-memory")
            self.assertEqual(session_rows[0]["project"], "agent-memory-domain")
            self.assertEqual(session_rows[0]["project_path"], str(source_dir.resolve()))
            scope_rows = [
                json.loads(line)
                for line in (memory_repo / "index/scopes.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(scope_rows[0]["archive_scope"], "domain:agent-memory")

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

    def test_run_memory_updates_does_not_render_paths_in_status_output(self):
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
            self.assertIn("Memory repo: configured", combined)
            self.assertIn("Source dir: configured", combined)
            self.assertNotIn("cookie_should_not_render", combined)
            self.assertNotIn("cookie", combined.lower())
            self.assertNotIn(str(root), combined)

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
            self.assertNotIn(str(root), output)
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
                        "source_partition": "source:runner-scope",
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
            self.assertEqual(session_rows[0]["source_partition"], "source:runner-scope")
            scope_rows = [
                json.loads(line)
                for line in (memory_repo / "index/scopes.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(scope_rows[0]["archive_scope"], "domain:runner-scope")

    def test_run_memory_updates_keeps_shared_archive_scope_project_partitions_independent(self):
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

            (memory_repo / "config/projects.jsonl").write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True)
                    for row in (
                        {
                            "project_path": str(project_a.resolve()),
                            "archive_scope": "domain:runner-shared",
                            "source_dir": str(source_dir.resolve()),
                            "enabled": True,
                            "source": "manual",
                        },
                        {
                            "project_path": str(project_b.resolve()),
                            "archive_scope": "domain:runner-shared",
                            "source_dir": str(source_dir.resolve()),
                            "enabled": True,
                            "source": "manual",
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "a-newer.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T11:00:00Z",
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Project alpha newer runner record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (source_dir / "b-older.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_b),
                        "role": "user",
                        "content": "Project beta older runner record must still be archived.",
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

            self.assertIn("Projects updated: 2", result.stdout)
            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(session_rows), 2)
            self.assertEqual({row["project_path"] for row in session_rows}, {str(project_a.resolve()), str(project_b.resolve())})
            self.assertEqual({row["archive_scope"] for row in session_rows}, {"domain:runner-shared"})

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

            self.assertIn("Projects updated: 1", result.stdout)
            self.assertNotIn("Existing entries removed:", result.stdout)
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


class RunMemoryUpdatesReliabilityTests(unittest.TestCase):
    runner_source = Path("templates/agent-memory-repo/tools/run_memory_updates.py").resolve()

    def make_fake_repo(self, root: Path, *, project_count: int = 1, include_stream: bool = False) -> tuple[Path, Path]:
        memory_repo = root / "agent-memory"
        source_dir = root / "source-records"
        tools_dir = memory_repo / "tools"
        config_dir = memory_repo / "config"
        tools_dir.mkdir(parents=True)
        config_dir.mkdir()
        source_dir.mkdir()
        shutil.copyfile(self.runner_source, tools_dir / "run_memory_updates.py")

        projects = []
        for ordinal in range(project_count):
            project_path = root / f"project-{chr(ord('a') + ordinal)}"
            project_path.mkdir()
            projects.append(
                {
                    "project_path": str(project_path.resolve()),
                    "source_dir": str(source_dir.resolve()),
                    "enabled": True,
                    "source": "manual",
                }
            )
        (config_dir / "projects.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in projects),
            encoding="utf-8",
        )
        stream_rows = []
        if include_stream:
            stream_path = root / "source-stream"
            stream_path.mkdir()
            stream_rows.append(
                {
                    "stream_id": "synthetic-stream",
                    "source_dir": str(source_dir.resolve()),
                    "project_path": str(stream_path.resolve()),
                    "archive_scope": "domain:synthetic",
                    "source_partition": "source:synthetic",
                    "enabled": True,
                }
            )
        (config_dir / "source_streams.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in stream_rows),
            encoding="utf-8",
        )
        return memory_repo, source_dir

    @staticmethod
    def install_failing_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
project_path = args[args.index('--project-path') + 1]
marker = Path(os.environ['MY_PRECIOUS_TEST_LAUNCH_MARKER'])
with marker.open('a', encoding='utf-8') as handle:
    handle.write(Path(project_path).name + '\\n')
if Path(project_path).name == 'project-a':
    print('PRIVATE_CHILD_FAILURE_DETAIL', file=sys.stderr)
    raise SystemExit(9)
""",
            encoding="utf-8",
        )

    @staticmethod
    def install_blocking_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import os
import time
from pathlib import Path

pid_log = Path(os.environ['MY_PRECIOUS_TEST_CHILD_PID_LOG'])
release = Path(os.environ['MY_PRECIOUS_TEST_CHILD_RELEASE'])
with pid_log.open('a', encoding='utf-8') as handle:
    handle.write(str(os.getpid()) + '\\n')
while not release.exists():
    time.sleep(0.05)
""",
            encoding="utf-8",
        )

    @staticmethod
    def install_signal_resistant_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import os
import signal
import time
from pathlib import Path

pid_log = Path(os.environ['MY_PRECIOUS_TEST_CHILD_PID_LOG'])
release = Path(os.environ['MY_PRECIOUS_TEST_CHILD_RELEASE'])
signal_count = 0

def handle_term(_signum, _frame):
    global signal_count
    signal_count += 1
    if signal_count >= 3:
        raise SystemExit(0)

signal.signal(signal.SIGTERM, handle_term)
with pid_log.open('a', encoding='utf-8') as handle:
    handle.write(str(os.getpid()) + '\\n')
while not release.exists():
    time.sleep(0.05)
""",
            encoding="utf-8",
        )

    @staticmethod
    def install_reconciliation_flag_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

log = Path(os.environ['MY_PRECIOUS_TEST_RECONCILIATION_LOG'])
is_finalize = '--finalize-archive' in sys.argv[1:]
deferred = '--defer-global-rebuild' in sys.argv[1:]
with log.open('a', encoding='utf-8') as handle:
    if is_finalize:
        handle.write('finalized-reconciled\\n')
    else:
        handle.write(('ingestion-deferred' if deferred else 'ingestion-rebuilt') + '\\n')
""",
            encoding="utf-8",
        )

    @staticmethod
    def install_throughput_contract_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
is_finalize = '--finalize-archive' in args
records = []
if '--source-inventory-stdin' in args:
    payload = json.loads(sys.stdin.read())
    records = [row['relative_path'] for row in payload['records']]
project = ''
if '--project-path' in args:
    project = Path(args[args.index('--project-path') + 1]).name
row = {
    'kind': 'finalize' if is_finalize else 'ingestion',
    'project': project,
    'records': records,
    'inventory_stdin': '--source-inventory-stdin' in args,
    'defer_global_rebuild': '--defer-global-rebuild' in args,
}
with Path(os.environ['MY_PRECIOUS_TEST_THROUGHPUT_LOG']).open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(row, sort_keys=True) + '\\n')
if project and project == os.environ.get('MY_PRECIOUS_TEST_FAIL_PROJECT'):
    raise SystemExit(9)
if is_finalize and os.environ.get('MY_PRECIOUS_TEST_FAIL_FINALIZER') == '1':
    raise SystemExit(10)
""",
            encoding="utf-8",
        )

    @staticmethod
    def wait_for_pid_log(pid_log: Path, minimum_lines: int = 1) -> list[int]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if pid_log.exists():
                values = [int(line) for line in pid_log.read_text(encoding="utf-8").splitlines() if line]
                if len(values) >= minimum_lines:
                    return values
            time.sleep(0.05)
        raise AssertionError("synthetic child did not start")

    @staticmethod
    def process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    @staticmethod
    def wait_for_process_exit(pid: int, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not RunMemoryUpdatesReliabilityTests.process_alive(pid):
                return True
            time.sleep(0.05)
        return not RunMemoryUpdatesReliabilityTests.process_alive(pid)

    @staticmethod
    def runner_command(memory_repo: Path, source_dir: Path) -> list[str]:
        return [
            sys.executable,
            str(memory_repo / "tools/run_memory_updates.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
        ]

    def test_required_clean_worktree_blocks_all_dirty_kinds_before_mutation(self):
        for dirty_kind in ("tracked", "deleted", "untracked"):
            with self.subTest(dirty_kind=dirty_kind), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                memory_repo, source_dir = self.make_fake_repo(root)
                marker = root / "child-launches.txt"
                self.install_failing_fake_updater(memory_repo)
                tracked = memory_repo / "tracked.txt"
                tracked.write_text("baseline\n", encoding="utf-8")
                subprocess.run(["git", "init", "-q"], cwd=memory_repo, check=True)
                subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=memory_repo, check=True)
                subprocess.run(["git", "config", "user.name", "Synthetic Gate"], cwd=memory_repo, check=True)
                subprocess.run(["git", "add", "."], cwd=memory_repo, check=True)
                subprocess.run(["git", "commit", "-qm", "baseline"], cwd=memory_repo, check=True)
                if dirty_kind == "tracked":
                    tracked.write_text("changed\n", encoding="utf-8")
                elif dirty_kind == "deleted":
                    tracked.unlink()
                else:
                    (memory_repo / "untracked.txt").write_text("new\n", encoding="utf-8")
                registry_before = (memory_repo / "config/projects.jsonl").read_bytes()
                env = {**os.environ, "MY_PRECIOUS_TEST_LAUNCH_MARKER": str(marker)}

                result = subprocess.run(
                    [
                        sys.executable,
                        str(memory_repo / "tools/run_memory_updates.py"),
                        "--memory-repo",
                        str(memory_repo),
                        "--source-dir",
                        str(source_dir),
                        "--require-clean-worktree",
                    ],
                    cwd=memory_repo,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("update_status=blocked reason=dirty_worktree", result.stderr)
                self.assertIn("dirty_entry_count=1", result.stderr)
                self.assertEqual((memory_repo / "config/projects.jsonl").read_bytes(), registry_before)
                self.assertFalse(marker.exists())
                self.assertNotIn(str(root), result.stdout + result.stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX flock error classification")
    def test_non_contention_lock_error_propagates_and_lock_artifacts_are_private(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, _ = self.make_fake_repo(root)
            with mock.patch.object(module.tempfile, "gettempdir", return_value=str(root)):
                update_lock = module.UpdateRunLock(memory_repo)
            with mock.patch.object(module.fcntl, "flock", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    update_lock.acquire()
            self.assertIsNone(update_lock.handle)

            self.assertTrue(update_lock.acquire())
            try:
                self.assertEqual(update_lock.lock_root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(update_lock.lock_path.stat().st_mode & 0o777, 0o600)
            finally:
                update_lock.release()

    def test_invalid_source_stream_error_does_not_render_private_identifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root, project_count=0)
            self.install_failing_fake_updater(memory_repo)
            private_identifier = "PRIVATE_SOURCE_STREAM_SENTINEL"
            (memory_repo / "config/source_streams.jsonl").write_text(
                json.dumps(
                    {
                        "stream_id": private_identifier,
                        "source_partition": "source:synthetic",
                        "enabled": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(private_identifier, result.stdout + result.stderr)
            self.assertNotIn(str(root), result.stdout + result.stderr)

    def test_explicit_repo_without_runtime_tool_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            explicit_repo = root / "explicit-memory"
            explicit_tools = explicit_repo / "tools"
            explicit_tools.mkdir(parents=True)
            shutil.copyfile(self.runner_source, explicit_tools / "run_memory_updates.py")
            fallback_repo, source_dir = self.make_fake_repo(root / "fallback")
            self.install_failing_fake_updater(fallback_repo)
            marker = root / "fallback-launches.txt"
            config_path = root / "memory-config.json"
            config_path.write_text(
                json.dumps({"memory_repo": str(fallback_repo)}),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "MY_PRECIOUS_CONFIG": str(config_path),
                "AGENT_SESSION_MEMORY_CONFIG": str(config_path),
                "MY_PRECIOUS_TEST_LAUNCH_MARKER": str(marker),
            }
            env.pop("AGENT_SESSION_MEMORY_REPO", None)
            env.pop("AGENT_MEMORY_REPO", None)

            result = subprocess.run(
                [
                    sys.executable,
                    str(explicit_tools / "run_memory_updates.py"),
                    "--memory-repo",
                    str(explicit_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                cwd=explicit_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reason=memory_repo_unavailable", result.stderr)
            self.assertFalse(marker.exists())
            self.assertNotIn(str(root), result.stdout + result.stderr)

    def test_first_project_failure_stops_all_later_children_and_redacts_child_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2, include_stream=True)
            marker = root / "child-launches.txt"
            self.install_failing_fake_updater(memory_repo)
            env = {**os.environ, "MY_PRECIOUS_TEST_LAUNCH_MARKER": str(marker)}

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/run_memory_updates.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                ],
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["project-a"])
            self.assertIn("update_status=failed reason=project_update_failed", result.stderr)
            self.assertNotIn("PRIVATE_CHILD_FAILURE_DETAIL", result.stdout + result.stderr)

    def test_only_archive_finalizer_reconciles_removed_memory_references(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2, include_stream=True)
            self.install_reconciliation_flag_fake_updater(memory_repo)
            log = root / "reconciliation-flags.txt"

            result = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_RECONCILIATION_LOG": str(log)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                [
                    "ingestion-deferred",
                    "ingestion-deferred",
                    "ingestion-deferred",
                    "finalized-reconciled",
                ],
            )

    def test_runner_dispatches_target_inventories_and_finalizes_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2, include_stream=True)
            self.install_throughput_contract_fake_updater(memory_repo)
            project_a = root / "project-a"
            project_b = root / "project-b"
            fixtures = {
                "a.jsonl": {
                    "timestamp": "2026-07-13T07:00:00Z",
                    "cwd": str(project_a),
                    "role": "user",
                    "content": "Synthetic project A dispatch record.",
                },
                "b.jsonl": {
                    "timestamp": "2026-07-13T08:00:00Z",
                    "cwd": str(project_b),
                    "role": "user",
                    "content": "Synthetic project B dispatch record.",
                },
                "stream.jsonl": {
                    "timestamp": "2026-07-13T09:00:00Z",
                    "role": "user",
                    "content": "Synthetic source stream dispatch record.",
                },
            }
            for name, payload in fixtures.items():
                (source_dir / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")
            log = root / "throughput-contract.jsonl"

            result = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_THROUGHPUT_LOG": str(log)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["kind"] for row in rows], ["ingestion", "ingestion", "ingestion", "finalize"])
            self.assertEqual(
                {row["project"]: row["records"] for row in rows[:-1]},
                {
                    "project-a": ["a.jsonl"],
                    "project-b": ["b.jsonl"],
                    "source-stream": ["stream.jsonl"],
                },
            )
            self.assertTrue(all(row["inventory_stdin"] for row in rows[:-1]))
            self.assertTrue(all(row["defer_global_rebuild"] for row in rows[:-1]))
            self.assertFalse(rows[-1]["inventory_stdin"])
            self.assertFalse(rows[-1]["defer_global_rebuild"])

    def test_runner_suppresses_later_targets_and_finalization_after_ingestion_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2)
            self.install_throughput_contract_fake_updater(memory_repo)
            for name in ("a", "b"):
                project_path = root / f"project-{name}"
                (source_dir / f"{name}.jsonl").write_text(
                    json.dumps(
                        {
                            "timestamp": "2026-07-13T10:00:00Z",
                            "cwd": str(project_path),
                            "role": "user",
                            "content": f"Synthetic failing dispatch record {name}.",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            log = root / "throughput-failure.jsonl"

            result = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env={
                    **os.environ,
                    "MY_PRECIOUS_TEST_THROUGHPUT_LOG": str(log),
                    "MY_PRECIOUS_TEST_FAIL_PROJECT": "project-a",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([(row["kind"], row["project"]) for row in rows], [("ingestion", "project-a")])
            self.assertIn("Archive finalizations: 0", result.stdout)

    def test_second_runner_is_rejected_before_mutation_and_lock_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_blocking_fake_updater(memory_repo)
            pid_log = root / "child-pids.txt"
            release = root / "release-child"
            env = {
                **os.environ,
                "MY_PRECIOUS_TEST_CHILD_PID_LOG": str(pid_log),
                "MY_PRECIOUS_TEST_CHILD_RELEASE": str(release),
            }
            first = subprocess.Popen(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            second = None
            try:
                self.wait_for_pid_log(pid_log)
                registry_before = (memory_repo / "config/projects.jsonl").read_bytes()
                extra_project = root / "project-new"
                extra_project.mkdir()
                (source_dir / "new.jsonl").write_text(
                    json.dumps(
                        {
                            "timestamp": "2026-07-12T00:00:00Z",
                            "cwd": str(extra_project.resolve()),
                            "role": "user",
                            "content": "Synthetic lock contention source record.",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                second = subprocess.Popen(
                    self.runner_command(memory_repo, source_dir),
                    cwd=memory_repo,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    second_out, second_err = second.communicate(timeout=1.5)
                except subprocess.TimeoutExpired:
                    release.touch()
                    second_out, second_err = second.communicate(timeout=5)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn("update_status=blocked reason=concurrent_update", second_err)
                self.assertNotIn(str(root), second_out + second_err)
                self.assertEqual((memory_repo / "config/projects.jsonl").read_bytes(), registry_before)
            finally:
                release.touch()
                if second is not None and second.poll() is None:
                    second.terminate()
                    second.communicate(timeout=5)
                first.communicate(timeout=5)

            third = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(third.returncode, 0, third.stderr)

    def test_sigterm_cleans_current_child_before_runner_exits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_blocking_fake_updater(memory_repo)
            pid_log = root / "child-pids.txt"
            release = root / "release-child"
            env = {
                **os.environ,
                "MY_PRECIOUS_TEST_CHILD_PID_LOG": str(pid_log),
                "MY_PRECIOUS_TEST_CHILD_RELEASE": str(release),
            }
            runner = subprocess.Popen(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            child_pid = self.wait_for_pid_log(pid_log)[0]
            child_exited = False
            try:
                runner.send_signal(signal.SIGTERM)
                runner.communicate(timeout=5)
                child_exited = self.wait_for_process_exit(child_pid)
            finally:
                release.touch()
                if self.process_alive(child_pid):
                    os.kill(child_pid, signal.SIGTERM)
                    self.wait_for_process_exit(child_pid)
                if runner.poll() is None:
                    runner.kill()
                    runner.communicate(timeout=5)
            self.assertTrue(child_exited)

    @unittest.skipUnless(os.name == "posix", "repeated signal cleanup is POSIX-specific")
    def test_repeated_sigterm_does_not_interrupt_child_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_signal_resistant_fake_updater(memory_repo)
            pid_log = root / "child-pids.txt"
            release = root / "release-child"
            env = {
                **os.environ,
                "MY_PRECIOUS_TEST_CHILD_PID_LOG": str(pid_log),
                "MY_PRECIOUS_TEST_CHILD_RELEASE": str(release),
            }
            runner = subprocess.Popen(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            child_pid = self.wait_for_pid_log(pid_log)[0]
            child_exited = False
            output = ""
            try:
                runner.send_signal(signal.SIGTERM)
                time.sleep(0.1)
                if runner.poll() is None:
                    runner.send_signal(signal.SIGTERM)
                stdout, stderr = runner.communicate(timeout=8)
                output = stdout + stderr
                child_exited = self.wait_for_process_exit(child_pid)
            finally:
                release.touch()
                if self.process_alive(child_pid):
                    os.kill(child_pid, signal.SIGKILL)
                self.wait_for_process_exit(child_pid)
                if runner.poll() is None:
                    runner.kill()
                    runner.communicate(timeout=5)

            self.assertTrue(child_exited)
            self.assertIn("update_status=blocked reason=interrupted", output)
            self.assertNotIn("Traceback", output)

    @unittest.skipUnless(os.name == "posix", "orphan lock inheritance is POSIX-specific")
    def test_orphan_child_keeps_lock_until_child_exits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_blocking_fake_updater(memory_repo)
            pid_log = root / "child-pids.txt"
            release = root / "release-child"
            env = {
                **os.environ,
                "MY_PRECIOUS_TEST_CHILD_PID_LOG": str(pid_log),
                "MY_PRECIOUS_TEST_CHILD_RELEASE": str(release),
            }
            first = subprocess.Popen(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            child_pid = self.wait_for_pid_log(pid_log)[0]
            second = None
            try:
                os.kill(first.pid, signal.SIGKILL)
                first.communicate(timeout=5)
                self.assertTrue(self.process_alive(child_pid))
                second = subprocess.Popen(
                    self.runner_command(memory_repo, source_dir),
                    cwd=memory_repo,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    second_out, second_err = second.communicate(timeout=1.5)
                except subprocess.TimeoutExpired:
                    release.touch()
                    second_out, second_err = second.communicate(timeout=5)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn("update_status=blocked reason=concurrent_update", second_err)
                self.assertNotIn(str(root), second_out + second_err)
            finally:
                release.touch()
                if second is not None and second.poll() is None:
                    second.terminate()
                    second.communicate(timeout=5)
                if self.process_alive(child_pid):
                    os.kill(child_pid, signal.SIGTERM)
                self.wait_for_process_exit(child_pid)

            third = subprocess.run(
                self.runner_command(memory_repo, source_dir),
                cwd=memory_repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(third.returncode, 0, third.stderr)


if __name__ == "__main__":
    unittest.main()
