import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def set_mtime(path: Path, stamp: str) -> None:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    os.utime(path, (dt.timestamp(), dt.timestamp()))


class UpdateMemoryArchiveTests(unittest.TestCase):
    def test_update_memory_archive_creates_searchable_summary(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            config_path = root / "my-precious-config.json"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [
                    sys.executable,
                    str(setup_script),
                    "--path",
                    str(memory_repo),
                    "--mode",
                    "local",
                    "--config-path",
                    str(config_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "session.jsonl"
            source.write_text(
                '{"role":"user","content":"Need migration plan for the archive updater."}\n'
                '{"role":"assistant","content":"Decision: summarize source records before indexing."}\n',
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            update_script = Path("skills/update-my-precious/scripts/update_memory_archive.py").resolve()
            env = os.environ.copy()
            env["MY_PRECIOUS_CONFIG"] = str(config_path)
            env.pop("AGENT_SESSION_MEMORY_REPO", None)
            env.pop("AGENT_MEMORY_REPO", None)
            subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            search_result = subprocess.run(
                [sys.executable, str(Path("skills/using-my-precious/scripts/search_memory.py").resolve()), "migration plan"],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("Top memory hits for: migration plan", search_result.stdout)
            self.assertIn("summary.md", search_result.stdout)

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("migration plan", rows[0]["summary"].lower())
            self.assertEqual(rows[0]["archive_status"], "summarized")

            summary_path = memory_repo / rows[0]["summary_path"]
            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn("Need migration plan", summary_text)
            self.assertNotIn("Draft summary generated", summary_text)
            self.assertTrue((summary_path.parent / "source-map.json").exists())
            self.assertTrue((memory_repo / "daily/2026/2026-05-14.md").exists())

    def test_update_memory_archive_extracts_codex_sessions_without_event_noise(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "gridmen"
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
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-06-02T21:20:48Z",
                    "payload": {
                        "cwd": str(project_path),
                        "base_instructions": {"text": "You are Codex, a coding agent based on GPT-5."},
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-06-02T21:20:49Z",
                    "payload": {"message": "I am checking backend startup logs before changing code."},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:50Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Gridmen backend crashes on GDAL import; figure out what is going on.",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:51Z",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "python - <<'PY'\nfrom osgeo import _gdal\nPY"}),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:52Z",
                    "payload": {
                        "type": "function_call_output",
                        "output": "ImportError: dlopen(... libx265.215.dylib)",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:53Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Root cause: Homebrew libheif still expected libx265.215.dylib; "
                                    "reinstalling Python packages will not fix the GDAL startup crash."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:54Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Final state: verified with direct osgeo._gdal import and Homebrew linkage checks.",
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-02T21:20:54Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "gridmen",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("gdal import", row["user_intent"].lower())
            self.assertIn("libx265.215.dylib", row["summary"])
            self.assertIn("homebrew", " ".join(row["tags"]).lower())
            self.assertNotIn("session_meta", json.dumps(row))
            self.assertNotIn("response_item", json.dumps(row))
            self.assertNotIn("event_msg", json.dumps(row))
            self.assertNotIn("base_instructions", json.dumps(row))

            summary_path = memory_repo / row["summary_path"]
            combined = "\n".join(
                (summary_path.parent / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("Gridmen backend crashes on GDAL import", combined)
            self.assertIn("Homebrew libheif still expected libx265.215.dylib", combined)
            self.assertIn("direct osgeo._gdal import", combined)
            self.assertNotIn("session_meta", combined)
            self.assertNotIn("response_item", combined)
            self.assertNotIn("event_msg", combined)
            self.assertNotIn("base_instructions", combined)

            decision_index = (memory_repo / "index/decisions.jsonl").read_text(encoding="utf-8")
            self.assertIn("Homebrew libheif", decision_index)
            self.assertNotIn("response_item", decision_index)

    def test_update_memory_archive_prefers_colocated_repo_over_configured_repo(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_repo = root / "local-agent-memory"
            configured_repo = root / "configured-agent-memory"
            config_path = root / "my-precious-config.json"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            for repo in (local_repo, configured_repo):
                subprocess.run(
                    [sys.executable, str(setup_script), "--path", str(repo), "--mode", "local", "--skip-config"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            config_path.write_text(json.dumps({"memory_repo": str(configured_repo)}) + "\n", encoding="utf-8")
            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Archive this in the colocated repository."}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            env = os.environ.copy()
            env["MY_PRECIOUS_CONFIG"] = str(config_path)
            env.pop("AGENT_SESSION_MEMORY_REPO", None)
            env.pop("AGENT_MEMORY_REPO", None)
            subprocess.run(
                [
                    sys.executable,
                    str(local_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertTrue((local_repo / "index/sessions.jsonl").exists())
            self.assertFalse((configured_repo / "index/sessions.jsonl").exists())

    def test_update_memory_archive_refuses_secret_records_by_default(self):
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

            source = source_dir / "leaky.jsonl"
            fake_key = "sk-" + "test-notreal" + ("0" * 20)
            source.write_text(json.dumps({"role": "user", "content": f"secret {fake_key}"}) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to archive", result.stderr)
            self.assertFalse(any((memory_repo / "sessions").glob("**/summary.md")))

    def test_update_memory_archive_redacts_secrets_when_explicitly_allowed(self):
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

            source = source_dir / "leaky.jsonl"
            fake_bearer = "abcdefghijklmnopqrstuvwxyz" + "0123456789"
            source.write_text(
                json.dumps({"role": "user", "content": "Authorization: " + "Bearer " + fake_bearer}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--allow-redacted-secrets",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = next((memory_repo / "sessions").glob("**/summary.md")).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json", "redactions.md")
            )
            self.assertIn("[REDACTED_BEARER_TOKEN]", combined)
            self.assertIn("bearer_token", combined)
            self.assertNotIn(fake_bearer, combined)

    def test_update_memory_archive_processes_only_new_records_for_project(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

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

            first = source_dir / "first.jsonl"
            second = source_dir / "second.jsonl"
            first.write_text('{"message":"first session"}\n', encoding="utf-8")
            second.write_text('{"message":"second session"}\n', encoding="utf-8")
            set_mtime(first, "2026-05-14T10:00:00Z")
            set_mtime(second, "2026-05-14T11:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            sessions_path = memory_repo / "index/sessions.jsonl"
            rows = [json.loads(line) for line in sessions_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)

            old = source_dir / "old.jsonl"
            newest = source_dir / "newest.jsonl"
            old.write_text('{"message":"older than high water"}\n', encoding="utf-8")
            newest.write_text('{"message":"new newest session"}\n', encoding="utf-8")
            set_mtime(old, "2026-05-14T10:30:00Z")
            set_mtime(newest, "2026-05-14T12:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rows = [json.loads(line) for line in sessions_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertIn("Records selected: 1", result.stdout)
            self.assertTrue(any("newest.jsonl" in row["title"] for row in rows))
            self.assertFalse(any("old.jsonl" in row["title"] for row in rows))

    def test_update_memory_archive_uses_record_timestamp_and_project_filter(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir()
            project_a.mkdir()
            project_b.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            a_record = source_dir / "a.jsonl"
            b_record = source_dir / "b.jsonl"
            a_record.write_text(
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
            b_record.write_text(
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
            set_mtime(a_record, "2026-05-14T12:00:00Z")
            set_mtime(b_record, "2026-05-14T12:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("a.jsonl", rows[0]["title"])
            self.assertEqual(rows[0]["source_updated_at"], "2026-05-14T10:00:00Z")

            filename_timestamp_record = source_dir / "2026-05-14T10-30-00Z-project-a.jsonl"
            filename_timestamp_record.write_text(
                json.dumps(
                    {
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Filename timestamp should drive this record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(filename_timestamp_record, "2026-05-14T08:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(row["source_updated_at"] == "2026-05-14T10:30:00Z" for row in rows))

            old_record = source_dir / "old-with-new-mtime.jsonl"
            old_record.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T09:00:00Z",
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Old source timestamp with newer file mtime.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(old_record, "2026-05-14T13:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 0", result.stdout)

    def test_update_memory_archive_can_require_project_metadata(self):
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

            scoped = source_dir / "scoped.jsonl"
            unscoped = source_dir / "unscoped.jsonl"
            scoped.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Scoped record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            unscoped.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T11:00:00Z",
                        "role": "user",
                        "content": "Unscoped record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(scoped, "2026-05-14T10:00:00Z")
            set_mtime(unscoped, "2026-05-14T11:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("scoped.jsonl", rows[0]["title"])

    def test_update_memory_archive_ignores_nested_dates_for_source_timestamp(self):
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

            source = source_dir / "nested-date.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": {"date": "2030-01-01T00:00:00Z", "text": "nested date is domain content"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T08:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["source_updated_at"], "2026-05-14T10:00:00Z")

    def test_update_memory_archive_does_not_skip_same_timestamp_after_max_records(self):
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

            for idx in range(3):
                source = source_dir / f"same-{idx}.jsonl"
                source.write_text(
                    json.dumps(
                        {
                            "timestamp": "2026-05-14T10:00:00Z",
                            "cwd": str(project_path),
                            "role": "user",
                            "content": f"same timestamp {idx}",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--max-records",
                    "2",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 3)

    def test_update_memory_archive_keeps_project_high_water_separate(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir()
            project_a.mkdir()
            project_b.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "record.jsonl"
            source.write_text('{"message":"shared record"}\n', encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_b),
                    "--project",
                    "project-b",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Latest archived timestamp: <none>", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            project_paths = {row["project_path"] for row in rows}
            self.assertEqual(project_paths, {str(project_a.resolve()), str(project_b.resolve())})


if __name__ == "__main__":
    unittest.main()
