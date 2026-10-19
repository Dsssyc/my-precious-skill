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
    def test_default_inventory_protocol_and_manifest_remain_unchanged(self):
        module = load_runner_module()
        record = module.SourceInventoryRecord(
            "record.jsonl", "a" * 64, 3, 1, "2026-10-19T00:00:00Z", ()
        )
        self.assertIsNone(record.source_root)
        self.assertEqual(record.source_identity, "")
        ipc = json.loads(module.source_inventory_payload(iter([record])))
        self.assertEqual(ipc["report_kind"], "memory_source_inventory")
        self.assertEqual(ipc["report_version"], 2)
        self.assertEqual(set(ipc["records"][0]), {
            "relative_path", "sha256", "size", "mtime_ns", "source_updated_at"
        })
        self.assertEqual(json.loads(module.source_inventory_payload([]))["report_version"], 2)
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "inventory.json"
            module.write_source_inventory_manifest(manifest, iter([record]))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["report_version"], 1)
            self.assertEqual(set(payload["records"][0]), set(ipc["records"][0]) | {"project_paths"})
            self.assertEqual(module.load_source_inventory_manifest(manifest), [record])
            legacy_record = module.SourceInventoryRecord(
                "legacy\nname.jsonl", "a" * 64, 3, 1, "2026-10-19T00:00:00Z", ()
            )
            legacy_manifest = Path(tmpdir) / "legacy.json"
            module.write_source_inventory_manifest(legacy_manifest, [legacy_record])
            self.assertEqual(module.load_source_inventory_manifest(legacy_manifest), [legacy_record])

    def test_extended_inventory_manifest_round_trips_roots_and_optional_identities(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            records = [
                module.SourceInventoryRecord(
                    "record.jsonl", "a" * 64, 3, 1, "2026-10-19T00:00:00Z", (root / "project",),
                    source_root=root / "archived",
                    source_identity="codex-session:12345678-1234-4234-9234-123456789abc",
                ),
                module.SourceInventoryRecord(
                    "record.jsonl", "b" * 64, 4, 2, "2026-10-19T00:00:00Z", (),
                    source_root=root / "sessions",
                ),
            ]
            manifest = root / "inventory.json"
            module.write_source_inventory_manifest(manifest, iter(records))
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["report_version"], 2)
            self.assertEqual(module.load_source_inventory_manifest(manifest), records)
            ipc = json.loads(module.source_inventory_payload(iter(records)))
            self.assertEqual(ipc["report_version"], 3)
            self.assertEqual(set(ipc["records"][0]), {
                "relative_path", "sha256", "size", "mtime_ns", "source_updated_at",
                "source_root", "source_identity",
            })
            self.assertEqual(ipc["records"][1]["source_identity"], "")
            self.assertEqual(json.loads(module.source_inventory_payload([], extended=True))["report_version"], 3)

    def test_extended_inventory_manifest_rejects_invalid_fields_and_root_escapes(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            source_dir = root / "sessions"
            source_dir.mkdir()
            (source_dir / "escape").symlink_to(root / "outside", target_is_directory=True)
            record = module.SourceInventoryRecord(
                "record.jsonl", "a" * 64, 3, 1, "2026-10-19T00:00:00Z", (),
                source_root=source_dir,
                source_identity="codex-session:12345678-1234-4234-9234-123456789abc",
            )
            valid = module.source_inventory_manifest_payload([record])
            invalid_rows = [
                {"source_root": "relative"}, {"source_root": None},
                {"source_root": str(source_dir) + "\n"},
                {"relative_path": "../escape.jsonl"}, {"relative_path": "escape/file.jsonl"},
                {"relative_path": "/absolute.jsonl"}, {"relative_path": "./record.jsonl"},
                {"source_identity": None}, {"source_identity": True},
                {"source_identity": "codex-session:12345678-1234-4234-9234-123456789ABC"},
                {"source_identity": "other:12345678-1234-4234-9234-123456789abc"},
                {"size": True}, {"mtime_ns": False}, {"unknown": "field"},
            ]
            invalid_payloads = []
            for patch in invalid_rows:
                invalid_payloads.append({**valid, "records": [{**valid["records"][0], **patch}]})
            missing_identity = dict(valid["records"][0])
            del missing_identity["source_identity"]
            invalid_payloads.extend([
                {**valid, "report_version": True}, {**valid, "report_version": 2.0},
                {**valid, "unknown": "field"},
                {**valid, "records": [missing_identity]},
                {**valid, "records": valid["records"] * 2},
                {**valid, "records": [valid["records"][0], {
                    **valid["records"][0], "relative_path": "other.jsonl",
                    "source_root": str(root / "archived"),
                }]},
            ])
            manifest = root / "invalid.json"
            for index, payload in enumerate(invalid_payloads):
                with self.subTest(index=index):
                    manifest.write_text(json.dumps(payload), encoding="utf-8")
                    manifest.chmod(0o600)
                    with self.assertRaises(module.SourceInventoryError) as raised:
                        module.load_source_inventory_manifest(manifest)
                    self.assertNotIn(str(root), str(raised.exception))
                    self.assertNotIn(record.source_identity, str(raised.exception))

    def test_source_locations_validate_all_rows_and_ignore_disabled_collections(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            memory_repo = root / "memory"
            config = memory_repo / "config"
            config.mkdir(parents=True)
            self.assertEqual(module.load_source_locations(memory_repo), {})
            path = config / "source_locations.jsonl"
            row = {
                "source_dir": str(root / "sessions"),
                "relocation_dirs": [str(root / "archived_sessions")],
                "identity_adapter": "codex-session", "enabled": True,
            }
            disabled = {
                **row, "source_dir": str(root / "disabled"),
                "relocation_dirs": [str(root / "disabled_archive")], "enabled": False,
            }
            path.write_text(json.dumps(row) + "\n" + json.dumps(disabled) + "\n", encoding="utf-8")
            locations = module.load_source_locations(memory_repo)
            self.assertEqual(set(locations), {root / "sessions"})
            self.assertEqual(locations[root / "sessions"].relocation_dirs, (root / "archived_sessions",))
            invalid_rows = [
                {**row, "source_dir": "relative"}, {**row, "source_dir": 1},
                {**row, "source_dir": str(root / "sessions") + "\u0085"},
                {**row, "relocation_dirs": str(root / "archive")},
                {**row, "relocation_dirs": [False]},
                {**row, "relocation_dirs": [str(root / "archived_sessions") + "\n"]},
                {**row, "relocation_dirs": [str(root / "sessions/subdir")]},
                {**row, "relocation_dirs": [str(root)]},
                {**row, "relocation_dirs": row["relocation_dirs"] * 2},
                {**row, "identity_adapter": "unknown"}, {**row, "identity_adapter": []},
                *({**row, "enabled": value} for value in (0, 1, None, "false")),
                {**row, "unexpected": True}, {**disabled, "relocation_dirs": None},
            ]
            invalid_texts = [json.dumps(value) + "\n" for value in invalid_rows]
            invalid_texts.extend([
                json.dumps(row) + "\n" + json.dumps(row) + "\n",
                json.dumps(row) + "\n" + json.dumps({**disabled, "source_dir": row["source_dir"]}),
                json.dumps(row) + "\n" + json.dumps({**disabled, "source_dir": str(root / "sessions/child")}),
                json.dumps(row)[:-1] + ', "enabled": false}\n',
                "{invalid-json}\n", "[]\n", "{}\n",
            ])
            for index, value in enumerate(invalid_texts):
                with self.subTest(index=index):
                    path.write_text(value, encoding="utf-8")
                    with self.assertRaises(module.SourceInventoryError) as raised:
                        module.load_source_locations(memory_repo)
                    self.assertNotIn(str(root), str(raised.exception))

    def test_source_locations_reject_symlinked_registry_and_overlapping_root_aliases(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            memory_repo = root / "memory"
            config = memory_repo / "config"
            config.mkdir(parents=True)
            outside = root / "outside.jsonl"
            outside.write_text("", encoding="utf-8")
            path = config / "source_locations.jsonl"
            path.symlink_to(outside)
            with self.assertRaises(module.SourceInventoryError):
                module.load_source_locations(memory_repo)
            path.unlink()
            source_dir = root / "sessions"
            source_dir.mkdir()
            alias = root / "alias"
            alias.symlink_to(source_dir, target_is_directory=True)
            path.write_text(json.dumps({
                "source_dir": str(source_dir), "relocation_dirs": [str(alias)],
                "identity_adapter": "codex-session", "enabled": True,
            }) + "\n", encoding="utf-8")
            with self.assertRaises(module.SourceInventoryError):
                module.load_source_locations(memory_repo)

    def test_codex_identity_adapter_reads_only_top_level_jsonl_session_metadata(self):
        module = load_runner_module()
        identity = "12345678-1234-4234-9234-123456789abc"
        metadata = {"type": "session_meta", "payload": {"id": identity.upper()}}
        nested = {
            "payload": {"type": "session_meta", "payload": {"id": "invalid"}},
            "content": json.dumps(metadata),
            "id": identity,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            (source_dir / "renamed.jsonl").write_text(
                "\n".join(json.dumps(row) for row in (metadata, nested, metadata)) + "\n",
                encoding="utf-8",
            )
            (source_dir / f"{identity}.jsonl").write_text(
                json.dumps(nested) + "\n" + json.dumps([metadata]) + "\n", encoding="utf-8"
            )
            (source_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

            inventory = module.build_source_inventory(
                source_dir, ("*.jsonl", "*.json"), identity_adapter="codex-session"
            )

            records = {record.relative_path: record for record in inventory}
            self.assertEqual(records["renamed.jsonl"].source_identity, f"codex-session:{identity}")
            self.assertEqual(records[f"{identity}.jsonl"].source_identity, "")
            self.assertEqual(records["metadata.json"].source_identity, "")
            self.assertTrue(all(record.source_root == source_dir.resolve() for record in inventory))
            default_inventory = module.build_source_inventory(source_dir, ("*.jsonl",))
            self.assertTrue(all(record.source_root is None for record in default_inventory))
            self.assertTrue(all(record.source_identity == "" for record in default_inventory))

    def test_codex_identity_adapter_blocks_invalid_or_conflicting_metadata(self):
        module = load_runner_module()
        first_id = "12345678-1234-4234-9234-123456789abc"
        second_id = "23456789-1234-4234-9234-123456789abc"
        valid = {"type": "session_meta", "payload": {"id": first_id}}
        invalid_rows = [
            {"type": "session_meta"},
            {"type": "session_meta", "payload": []},
            *({"type": "session_meta", "payload": {"id": value}} for value in (
                None, True, 7, "not-a-uuid", first_id + "\n"
            )),
            {"type": "session_meta", "payload": {"id": second_id}},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            source_path = source_dir / "record.jsonl"
            for invalid in invalid_rows:
                with self.subTest(invalid=invalid):
                    source_path.write_text(
                        json.dumps(valid) + "\n" + json.dumps(invalid) + "\n", encoding="utf-8"
                    )
                    with self.assertRaises(module.SourceInventoryError) as raised:
                        module.build_source_inventory(
                            source_dir, ("*.jsonl",), identity_adapter="codex-session"
                        )
                    self.assertNotIn(str(source_dir), str(raised.exception))
                    self.assertNotIn(first_id, str(raised.exception))

    def test_codex_identity_adapter_blocks_duplicate_json_fields_that_hide_conflicting_ids(self):
        module = load_runner_module()
        first_id = "12345678-1234-4234-9234-123456789abc"
        second_id = "23456789-1234-4234-9234-123456789abc"
        invalid_lines = [
            '{"type":"session_meta","payload":{"id":"' + first_id + '","id":"' + second_id + '"}}',
            '{"type":"session_meta","type":"message","payload":{"id":"' + first_id + '"}}',
            '{"type":"session_meta","payload":{"id":"' + first_id + '"},"payload":{"id":"' + second_id + '"}}',
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)
            path = source_dir / "record.jsonl"
            for index, value in enumerate(invalid_lines):
                with self.subTest(index=index):
                    path.write_text(value + "\n", encoding="utf-8")
                    with self.assertRaises(module.SourceInventoryError):
                        module.build_source_inventory(source_dir, ("*.jsonl",), "codex-session")
                    self.assertEqual(len(module.build_source_inventory(source_dir, ("*.jsonl",))), 1)
            for adapter in ("unknown", [], None):
                with self.subTest(adapter=adapter), self.assertRaises(module.SourceInventoryError):
                    module.build_source_inventory(source_dir / "missing", ("*.jsonl",), adapter)

    def test_isolated_inventory_rejects_worker_manifest_from_another_or_missing_root(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            expected_root = root / "sessions"
            for index, (adapter, worker_root) in enumerate((
                ("codex-session", root / "outside"), ("codex-session", None), ("", root / "outside"),
            )):
                with self.subTest(adapter=adapter, worker_root=worker_root):
                    manifest = root / f"manifest-{index}.json"
                    record = module.SourceInventoryRecord(
                        "record.jsonl", "a" * 64, 3, 1, "2026-10-19T00:00:00Z", (),
                        source_root=worker_root,
                    )
                    controller = mock.Mock()

                    def worker(command, cwd):
                        module.write_source_inventory_manifest(manifest, [record])
                        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

                    controller.run.side_effect = worker
                    with self.assertRaises(module.SourceInventoryError):
                        module.build_source_inventory_isolated(
                            controller, root, expected_root, ("*.jsonl",), manifest, adapter
                        )

    def test_source_inventory_preserves_subsecond_source_timestamp(self):
        module = load_runner_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()
            (source_dir / "subsecond.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-07-13T01:02:03.123456Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Synthetic subsecond inventory record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            inventory = module.build_source_inventory(source_dir, ("*.jsonl",))

            self.assertEqual(inventory[0].source_updated_at, "2026-07-13T01:02:03.123456Z")

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
            self.assertEqual(module.SOURCE_INVENTORY_REPORT_VERSION, 2)
            self.assertEqual(
                [record.source_updated_at for record in inventory],
                [
                    "2026-07-13T01:00:00Z",
                    "2026-07-13T02:00:00Z",
                    "2026-07-13T03:00:00Z",
                ],
            )
            payload = json.loads(module.source_inventory_payload(inventory))
            self.assertEqual(payload["report_version"], 2)
            self.assertEqual(
                [row["source_updated_at"] for row in payload["records"]],
                [
                    "2026-07-13T01:00:00Z",
                    "2026-07-13T02:00:00Z",
                    "2026-07-13T03:00:00Z",
                ],
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

    def test_source_inventory_fails_closed_on_malformed_jsonl(self):
        module = load_runner_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir) / "records"
            source_dir.mkdir()
            (source_dir / "malformed.jsonl").write_text(
                json.dumps({"timestamp": "2026-07-13T01:00:00Z", "content": "valid prefix"})
                + "\n{not-json}\n",
                encoding="utf-8",
            )

            with self.assertRaises(module.SourceInventoryError) as raised:
                module.build_source_inventory(source_dir, ("*.jsonl",))

            self.assertEqual(str(raised.exception), "source_inventory_malformed")

    def test_source_inventory_treats_literal_unicode_separators_as_json_string_content(self):
        module = load_runner_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()
            rows = [
                {
                    "timestamp": "2026-07-13T01:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "Literal separators stay inside JSON: A\u0085B\u2028C\u2029D.",
                },
                {
                    "timestamp": "2026-07-13T01:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "Second physical record.",
                },
            ]
            source = "\r\n".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in rows
            ) + "\r\n"
            source_path = source_dir / "unicode-separators.jsonl"
            source_path.write_text(source, encoding="utf-8")

            parsed = list(module.iter_json_values(source_path, source))
            inventory = module.build_source_inventory(source_dir, ("*.jsonl",))

            self.assertEqual(parsed, rows)
            self.assertEqual(len(inventory), 1)
            self.assertEqual(inventory[0].source_updated_at, "2026-07-13T01:00:01Z")

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

    @staticmethod
    def install_structured_fake_updater(memory_repo: Path) -> None:
        (memory_repo / "tools/update_memory_archive.py").write_text(
            """#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
mode = os.environ.get('MY_PRECIOUS_TEST_STRUCTURED_MODE', 'updated')
if mode == 'unknown-failure':
    print('PRIVATE_CHILD_FAILURE_DETAIL', file=sys.stderr)
    raise SystemExit(9)
deferred = 1 if mode == 'deferred' and '--finalize-archive' not in args else 0
finalization_failure = mode == 'finalization-review-failure' and '--finalize-archive' in args
payload = {
    'report_kind': 'memory_update_target_report',
    'report_version': 1,
    'status': 'blocked' if finalization_failure else ('deferred' if deferred else 'updated'),
    'reason': 'memory_review_decision_invalid' if finalization_failure else ('source_records_deferred' if deferred else 'updated'),
    'source_batch_complete': not deferred and not finalization_failure,
    'metrics': {
        'records_selected_count': deferred,
        'records_processed_count': 0,
        'records_deferred_count': deferred,
        'records_skipped_count': 0,
        'entries_removed_count': 0,
    },
    'privacy': {
        'aggregate_only': True,
        'paths_rendered': False,
        'source_content_rendered': False,
    },
}
if mode == 'invalid-pair':
    payload['reason'] = 'secret_records_rejected'
if '--report-json' in args:
    print(json.dumps(payload, sort_keys=True, separators=(',', ':')))
if finalization_failure:
    raise SystemExit(2)
""",
            encoding="utf-8",
        )

    @staticmethod
    def inventory_dispatch_controller():
        controller = mock.Mock()

        def run(command, cwd, *, input_text=None):
            if "--inventory-worker-manifest" in command:
                return subprocess.run(
                    command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            report = {
                "report_kind": "memory_update_target_report", "report_version": 1,
                "status": "updated", "reason": "updated", "source_batch_complete": True,
                "metrics": {key: 0 for key in (
                    "records_selected_count", "records_processed_count", "records_deferred_count",
                    "records_skipped_count", "entries_removed_count",
                )},
                "privacy": {
                    "aggregate_only": True, "paths_rendered": False, "source_content_rendered": False,
                },
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(report), stderr="")

        controller.run.side_effect = run
        return controller

    def test_source_collections_scan_each_root_once_and_dispatch_filtered_extended_inventories(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2, include_stream=True)
            archived = root / "archived_sessions"
            older = root / "older_sessions"
            unknown = root / "unknown-source"
            for path in (archived, older, unknown, root / "project-c", root / "project-d"):
                path.mkdir()
            registry = memory_repo / "config/projects.jsonl"
            projects = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
            projects[0].update(archive_scope="project:a", source_partition="partition:a")
            projects.append({
                "project_path": str(root / "project-d"), "source_dir": str(unknown), "enabled": True,
            })
            registry.write_text("".join(json.dumps(row) + "\n" for row in projects), encoding="utf-8")
            stream_registry = memory_repo / "config/source_streams.jsonl"
            stream = json.loads(stream_registry.read_text(encoding="utf-8"))
            stream["project_path"] = str(root / "project-a")
            stream_registry.write_text(json.dumps(stream) + "\n", encoding="utf-8")
            original_streams = stream_registry.read_bytes()
            (memory_repo / "config/source_locations.jsonl").write_text(json.dumps({
                "source_dir": str(source_dir), "relocation_dirs": [str(archived), str(older)],
                "identity_adapter": "codex-session", "enabled": True,
            }) + "\n", encoding="utf-8")
            fixtures = [
                (source_dir / "live.jsonl", "project-a", "12345678-1234-4234-9234-123456789abc"),
                (archived / "same.jsonl", "project-a", "23456789-1234-4234-9234-123456789abc"),
                (source_dir / "same.jsonl", "project-b", "34567890-1234-4234-9234-123456789abc"),
                (older / "renamed.jsonl", "project-c", "45678901-1234-4234-9234-123456789abc"),
                (unknown / "default.jsonl", "project-d", "invalid-default-identity"),
            ]
            for path, project, identity in fixtures:
                path.write_text(json.dumps({
                    "type": "session_meta", "payload": {"id": identity, "cwd": str(root / project)},
                    "content": "SYNTHETIC_PRIVATE_SOURCE_TEXT",
                }) + "\n", encoding="utf-8")
            (older / "generic.jsonl").write_text("{}\n", encoding="utf-8")
            args = module.parse_args(["--source-dir", str(source_dir), "--report-json"])
            controller = self.inventory_dispatch_controller()

            exit_code, report = module.run_updates(
                args, memory_repo, source_dir, ("*.jsonl",), controller
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(report["metrics"]["inventory_worker_count"], 4)
            self.assertEqual(report["metrics"]["projects_updated_count"], 4)
            self.assertEqual(report["metrics"]["source_streams_updated_count"], 1)
            self.assertEqual(report["metrics"]["archive_finalization_count"], 1)
            calls = controller.run.call_args_list
            workers = [call.args[0] for call in calls if "--inventory-worker-manifest" in call.args[0]]
            self.assertCountEqual(
                [command[command.index("--source-dir") + 1] for command in workers],
                [str(source_dir), str(archived), str(older), str(unknown)],
            )
            for command in workers:
                if command[command.index("--source-dir") + 1] == str(unknown):
                    self.assertNotIn("--source-identity-adapter", command)
                else:
                    self.assertEqual(command[command.index("--source-identity-adapter") + 1], "codex-session")
            targets = [call for call in calls if "--source-inventory-stdin" in call.args[0]]
            expected_paths = {
                "project-a": {"live.jsonl", "same.jsonl"}, "project-b": {"same.jsonl"},
                "project-c": {"renamed.jsonl"}, "project-d": {"default.jsonl"},
            }
            for call in targets:
                command = call.args[0]
                payload = json.loads(call.kwargs["input_text"])
                project = Path(command[command.index("--project-path") + 1]).name
                is_stream = "--project" in command and command[command.index("--project") + 1] == "synthetic-stream"
                expected = expected_paths[project] | ({"generic.jsonl"} if is_stream else set())
                self.assertEqual({row["relative_path"] for row in payload["records"]}, expected)
                if project == "project-d":
                    self.assertEqual(payload["report_version"], 2)
                    self.assertNotIn("--source-relocation-dir", command)
                    self.assertNotIn("--source-identity-adapter", command)
                    continue
                self.assertEqual(payload["report_version"], 3)
                self.assertEqual(
                    [command[index + 1] for index, value in enumerate(command) if value == "--source-relocation-dir"],
                    [str(archived), str(older)],
                )
                self.assertEqual(command[command.index("--source-identity-adapter") + 1], "codex-session")
                for row in payload["records"]:
                    if row["relative_path"] == "generic.jsonl":
                        self.assertEqual(row["source_identity"], "")
                        self.assertEqual(row["source_root"], str(older))
                    else:
                        fixture = next(item for item in fixtures if (
                            item[0].name == row["relative_path"] and item[1] == project
                        ))
                        self.assertEqual(row["source_root"], str(fixture[0].parent))
                        self.assertEqual(row["source_identity"], f"codex-session:{fixture[2]}")
                if is_stream:
                    self.assertEqual(command[command.index("--archive-scope") + 1], "domain:synthetic")
                    self.assertEqual(command[command.index("--source-partition") + 1], "source:synthetic")
                elif project == "project-a":
                    self.assertEqual(command[command.index("--archive-scope") + 1], "project:a")
                    self.assertEqual(command[command.index("--source-partition") + 1], "partition:a")
            discovered = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(next(row for row in discovered if row["project_path"] == str(root / "project-c"))["source_dir"], str(source_dir))
            self.assertEqual(stream_registry.read_bytes(), original_streams)
            self.assertNotIn(str(root), json.dumps(report))
            self.assertNotIn(fixtures[0][2], json.dumps(report))
            self.assertNotIn("SYNTHETIC_PRIVATE_SOURCE_TEXT", json.dumps(report))

    def test_source_collection_keeps_embedded_identity_when_record_moves_and_is_renamed(self):
        module = load_runner_module()
        identity = "12345678-1234-4234-9234-123456789abc"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            memory_repo, source_dir = self.make_fake_repo(root)
            archived = root / "archived_sessions"
            archived.mkdir()
            (memory_repo / "config/source_locations.jsonl").write_text(json.dumps({
                "source_dir": str(source_dir), "relocation_dirs": [str(archived)],
                "identity_adapter": "codex-session", "enabled": True,
            }) + "\n", encoding="utf-8")
            active_record = source_dir / "active-name.jsonl"
            active_record.write_text(json.dumps({
                "type": "session_meta", "payload": {"id": identity, "cwd": str(root / "project-a")},
            }) + "\n", encoding="utf-8")
            snapshots = []
            for expected_root, expected_name in ((source_dir, "active-name.jsonl"), (archived, "new-name.jsonl")):
                if expected_root == archived:
                    active_record.rename(archived / expected_name)
                controller = self.inventory_dispatch_controller()
                args = module.parse_args(["--source-dir", str(source_dir), "--report-json"])
                exit_code, report = module.run_updates(args, memory_repo, source_dir, ("*.jsonl",), controller)
                self.assertEqual(exit_code, 0)
                self.assertEqual(report["metrics"]["inventory_worker_count"], 2)
                call = next(call for call in controller.run.call_args_list if "--source-inventory-stdin" in call.args[0])
                payload = json.loads(call.kwargs["input_text"])
                self.assertEqual(payload["report_version"], 3)
                self.assertEqual(len(payload["records"]), 1)
                snapshot = payload["records"][0]
                self.assertEqual(snapshot["relative_path"], expected_name)
                self.assertEqual(snapshot["source_root"], str(expected_root))
                self.assertEqual(snapshot["source_identity"], f"codex-session:{identity}")
                snapshots.append(snapshot)
            self.assertEqual(snapshots[0]["sha256"], snapshots[1]["sha256"])
            self.assertEqual(snapshots[0]["source_updated_at"], snapshots[1]["source_updated_at"])
            self.assertFalse(active_record.exists())

    def test_disabled_and_unreferenced_source_collections_do_not_enable_extra_roots_or_flags(self):
        module = load_runner_module()
        for mode in ("missing", "disabled", "unreferenced"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir).resolve()
                memory_repo, source_dir = self.make_fake_repo(root, include_stream=True)
                archived = root / "archived_sessions"
                archived.mkdir()
                (archived / "malformed.jsonl").write_text("{invalid-json}\n", encoding="utf-8")
                (source_dir / "generic.jsonl").write_text(json.dumps({
                    "type": "session_meta", "payload": {"id": "invalid-default-id", "cwd": str(root / "project-a")},
                }) + "\n", encoding="utf-8")
                if mode != "missing":
                    (memory_repo / "config/source_locations.jsonl").write_text(json.dumps({
                        "source_dir": str(source_dir if mode == "disabled" else root / "unused-sessions"),
                        "relocation_dirs": [str(archived)], "identity_adapter": "codex-session",
                        "enabled": mode != "disabled",
                    }) + "\n", encoding="utf-8")
                args = module.parse_args(["--source-dir", str(source_dir), "--report-json"])
                controller = self.inventory_dispatch_controller()

                exit_code, report = module.run_updates(args, memory_repo, source_dir, ("*.jsonl",), controller)

                self.assertEqual(exit_code, 0)
                self.assertEqual(report["metrics"]["inventory_worker_count"], 1)
                for call in controller.run.call_args_list:
                    command = call.args[0]
                    self.assertNotIn("--source-relocation-dir", command)
                    self.assertNotIn("--source-identity-adapter", command)
                    if "--source-inventory-stdin" in command:
                        self.assertEqual(json.loads(call.kwargs["input_text"])["report_version"], 2)

    def test_empty_filtered_collection_still_sends_v3_and_only_enabled_targets_run(self):
        module = load_runner_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            memory_repo, source_dir = self.make_fake_repo(root, project_count=2, include_stream=True)
            archived = root / "archived_sessions"
            archived.mkdir()
            registry = memory_repo / "config/projects.jsonl"
            projects = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
            projects[1]["enabled"] = False
            registry.write_text("".join(json.dumps(row) + "\n" for row in projects), encoding="utf-8")
            stream_registry = memory_repo / "config/source_streams.jsonl"
            stream = json.loads(stream_registry.read_text(encoding="utf-8"))
            stream["enabled"] = False
            stream_registry.write_text(json.dumps(stream) + "\n", encoding="utf-8")
            (memory_repo / "config/source_locations.jsonl").write_text(json.dumps({
                "source_dir": str(source_dir), "relocation_dirs": [str(archived)],
                "identity_adapter": "codex-session", "enabled": True,
            }) + "\n", encoding="utf-8")
            (archived / "disabled-project.jsonl").write_text(json.dumps({
                "type": "session_meta", "payload": {
                    "id": "12345678-1234-4234-9234-123456789abc", "cwd": str(root / "project-b"),
                },
            }) + "\n", encoding="utf-8")
            args = module.parse_args(["--source-dir", str(source_dir), "--report-json"])
            controller = self.inventory_dispatch_controller()

            exit_code, report = module.run_updates(args, memory_repo, source_dir, ("*.jsonl",), controller)

            self.assertEqual(exit_code, 0)
            self.assertEqual(report["metrics"]["projects_updated_count"], 1)
            self.assertEqual(report["metrics"]["source_streams_updated_count"], 0)
            calls = [call for call in controller.run.call_args_list if "--source-inventory-stdin" in call.args[0]]
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(calls[0].kwargs["input_text"]), {
                "report_kind": "memory_source_inventory", "report_version": 3, "records": [],
            })

    def test_collection_conflicts_and_escapes_block_before_registry_or_updater_mutation(self):
        identity = "12345678-1234-4234-9234-123456789abc"
        for mode in ("different-projects", "disabled-project", "escape"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir).resolve()
                memory_repo, source_dir = self.make_fake_repo(root, project_count=2)
                archived = root / "archived_sessions"
                collection_root = root / "other-sessions"
                archived.mkdir()
                collection_root.mkdir()
                registry = memory_repo / "config/projects.jsonl"
                projects = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
                projects[0]["source_dir"] = str(collection_root)
                projects[1]["enabled"] = mode != "disabled-project"
                registry.write_text("".join(json.dumps(row) + "\n" for row in projects), encoding="utf-8")
                original_registry = registry.read_bytes()
                (source_dir / "discoverable.jsonl").write_text(
                    json.dumps({"cwd": str(root / "would-be-discovered-project")}) + "\n", encoding="utf-8"
                )
                (collection_root / "one.jsonl").write_text(json.dumps({
                    "type": "session_meta", "payload": {"id": identity, "cwd": str(root / "project-a")},
                }) + "\n", encoding="utf-8")
                if mode == "escape":
                    outside = root / "outside.jsonl"
                    outside.write_text("{}\n", encoding="utf-8")
                    (archived / "escaped.jsonl").symlink_to(outside)
                else:
                    (archived / "two.jsonl").write_text(json.dumps({
                        "type": "session_meta", "payload": {"id": identity, "cwd": str(root / "project-b")},
                    }) + "\n", encoding="utf-8")
                (memory_repo / "config/source_locations.jsonl").write_text(json.dumps({
                    "source_dir": str(collection_root), "relocation_dirs": [str(archived)],
                    "identity_adapter": "codex-session", "enabled": True,
                }) + "\n", encoding="utf-8")
                self.install_failing_fake_updater(memory_repo)
                marker = root / "updater-started"

                result = subprocess.run(
                    [*self.runner_command(memory_repo, source_dir), "--report-json"], cwd=memory_repo,
                    env={**os.environ, "MY_PRECIOUS_TEST_LAUNCH_MARKER": str(marker)}, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )

                self.assertNotEqual(result.returncode, 0)
                report = json.loads(result.stdout)
                self.assertEqual(report["reason"], "source_inventory_invalid")
                self.assertEqual(report["failure_stage"], "source_inventory")
                self.assertFalse(marker.exists())
                self.assertEqual(registry.read_bytes(), original_registry)
                self.assertNotIn(str(root), result.stdout + result.stderr)
                self.assertNotIn(identity, result.stdout + result.stderr)

    def test_report_json_aggregates_deferred_target_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_structured_fake_updater(memory_repo)

            result = subprocess.run(
                [*self.runner_command(memory_repo, source_dir), "--report-json"],
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_STRUCTURED_MODE": "deferred"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "memory_update_batch_report")
            self.assertEqual(report["status"], "deferred")
            self.assertEqual(report["reason"], "source_records_deferred")
            self.assertEqual(report["failure_stage"], "none")
            self.assertFalse(report["source_batch_complete"])
            self.assertEqual(report["metrics"]["records_deferred_count"], 1)
            self.assertEqual(report["metrics"]["inventory_worker_count"], 1)
            self.assertNotIn(str(root), result.stdout + result.stderr)

    def test_report_json_classifies_unknown_child_failure_without_rendering_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_structured_fake_updater(memory_repo)

            result = subprocess.run(
                [*self.runner_command(memory_repo, source_dir), "--report-json"],
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_STRUCTURED_MODE": "unknown-failure"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "child_failure_unclassified")
            self.assertEqual(report["failure_stage"], "project_update")
            self.assertEqual(report["metrics"]["child_failure_count"], 1)
            self.assertNotIn("PRIVATE_CHILD_FAILURE_DETAIL", result.stdout + result.stderr)
            self.assertNotIn(str(root), result.stdout + result.stderr)

    def test_report_json_preserves_structured_finalization_review_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_structured_fake_updater(memory_repo)

            result = subprocess.run(
                [*self.runner_command(memory_repo, source_dir), "--report-json"],
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_STRUCTURED_MODE": "finalization-review-failure"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "memory_review_decision_invalid")
            self.assertEqual(report["failure_stage"], "archive_finalization")
            self.assertEqual(report["metrics"]["projects_updated_count"], 1)
            self.assertEqual(report["metrics"]["child_failure_count"], 1)
            self.assertNotIn(str(root), result.stdout + result.stderr)

    def test_report_json_rejects_semantically_impossible_child_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_dir = self.make_fake_repo(root)
            self.install_structured_fake_updater(memory_repo)

            result = subprocess.run(
                [*self.runner_command(memory_repo, source_dir), "--report-json"],
                cwd=memory_repo,
                env={**os.environ, "MY_PRECIOUS_TEST_STRUCTURED_MODE": "invalid-pair"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason"], "child_failure_unclassified")
            self.assertEqual(report["failure_stage"], "project_update")
            self.assertEqual(report["metrics"]["child_failure_count"], 1)
            self.assertNotIn(str(root), result.stdout + result.stderr)

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
