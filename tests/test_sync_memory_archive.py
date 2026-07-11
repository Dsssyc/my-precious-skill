import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def create_git_backed_archive(root: Path) -> Path:
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
    memory_repo = root / "agent-memory"
    subprocess.run(
        [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(["git", "init"], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=memory_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=memory_repo, check=True)
    subprocess.run(["git", "add", "."], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "commit", "-m", "Initial archive"], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return memory_repo


def make_automatic_memory_node(
    memory_repo: Path,
    memory_id: str,
    *,
    layer: str = "global",
    text: str = "Synthetic reviewed automatic memory node.",
) -> dict:
    entry_dir = memory_repo / f"sessions/2026/07/10/{memory_id}"
    entry_dir.mkdir(parents=True, exist_ok=True)
    summary_path = entry_dir / "summary.md"
    evidence_path = entry_dir / "evidence.md"
    summary_path.write_text(f"# Summary\n\n{text}\n", encoding="utf-8")
    evidence_path.write_text(f"ev_{memory_id}: Synthetic supporting evidence.\n", encoding="utf-8")
    return {
        "memory_id": memory_id,
        "layer": layer,
        "scope": "*" if layer == "global" else f"synthetic-{layer}",
        "topic": "reviewed-publish",
        "text": text,
        "rationale": "Synthetic reviewed publish coverage.",
        "source": "automatic",
        "confidence": "high",
        "persistence": "normal",
        "support_count": 1,
        "first_seen": "2026-07-10T00:00:00Z",
        "last_seen": "2026-07-10T00:00:00Z",
        "derived_from": [summary_path.relative_to(memory_repo).as_posix()],
        "evidence_refs": [
            {
                "path": evidence_path.relative_to(memory_repo).as_posix(),
                "quote_id": f"ev_{memory_id}",
            }
        ],
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": None,
        "tags": ["reviewed-publish"],
    }


def write_memory_nodes(memory_repo: Path, nodes: list[dict]) -> None:
    layer_files = {
        "global": "global.jsonl",
        "domain": "domains.jsonl",
        "project": "projects.jsonl",
    }
    for layer, filename in layer_files.items():
        layer_nodes = [node for node in nodes if node["layer"] == layer]
        if layer_nodes:
            payload = "".join(json.dumps(node, sort_keys=True) + "\n" for node in layer_nodes)
            (memory_repo / "memories" / filename).write_text(payload, encoding="utf-8")
    index_payload = "".join(json.dumps(node, sort_keys=True) + "\n" for node in nodes)
    (memory_repo / "index/memories.jsonl").write_text(index_payload, encoding="utf-8")


class SyncMemoryArchiveTests(unittest.TestCase):
    def test_sync_memory_archive_commits_expected_archive_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            entry_dir = memory_repo / "sessions/2026/05/17/synthetic"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("# Summary\n\nSynthetic memory update.\n", encoding="utf-8")
            (memory_repo / "INDEX.md").write_text("# Agent Memory\n\nUpdated.\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--message",
                    "Update synthetic archive",
                ],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("Update synthetic archive", result.stdout)
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertEqual(status, "")

    def test_sync_memory_archive_refuses_unexpected_tool_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            (memory_repo / "tools/run_memory_updates.py").write_text("# unexpected tool edit\n", encoding="utf-8")
            (memory_repo / "INDEX.md").write_text("# Agent Memory\n\nUpdated.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py")],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("tools/run_memory_updates.py", result.stderr)
            head = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertIn("Initial archive", head)

    def test_sync_memory_archive_dry_run_refuses_unexpected_tool_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            (memory_repo / "tools/update_memory_archive.py").write_text("# unexpected tool edit\n", encoding="utf-8")
            (memory_repo / "INDEX.md").write_text("# Agent Memory\n\nUpdated.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("tools/update_memory_archive.py", result.stderr)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_sync_memory_archive_dry_run_refuses_memory_node_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            entry_dir = memory_repo / "sessions/2026/06/17/sync-node"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for sync dry-run memory node.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for sync dry-run memory node.\n", encoding="utf-8")
            memory_node = (
                '{"memory_id":"mem_test","layer":"global","scope":"*","topic":"sync",'
                '"text":"Synthetic memory node for sync dry run.","rationale":"test",'
                '"source":"automatic","confidence":"high","persistence":"normal",'
                '"support_count":1,"first_seen":"2026-06-17","last_seen":"2026-06-17",'
                '"derived_from":["sessions/2026/06/17/sync-node/summary.md"],'
                '"evidence_refs":[{"path":"sessions/2026/06/17/sync-node/evidence.md","quote_id":"ev_001"}],'
                '"raw_refs":[],"supersedes":[],'
                '"superseded_by":null,"tags":["test"]}\n'
            )
            (memory_repo / "memories/global.jsonl").write_text(memory_node, encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(memory_node, encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("memories/global.jsonl", result.stderr)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_dry_run_allows_exact_automatic_memory_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            nodes = [
                make_automatic_memory_node(memory_repo, "mem_reviewed_global", layer="global"),
                make_automatic_memory_node(memory_repo, "mem_reviewed_domain", layer="domain"),
                make_automatic_memory_node(memory_repo, "mem_reviewed_project", layer="project"),
            ]
            write_memory_nodes(memory_repo, nodes)

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                    "--push",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("memories/global.jsonl", result.stdout)
            self.assertIn("memories/domains.jsonl", result.stdout)
            self.assertIn("memories/projects.jsonl", result.stdout)
            self.assertIn("Would push after commit.", result.stdout)

    def test_reviewed_mode_refuses_memory_index_parity_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(memory_repo, "mem_reviewed_parity")
            write_memory_nodes(memory_repo, [node])
            mismatched = dict(node)
            mismatched["text"] = "Mismatched indexed memory text."
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(mismatched, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive audit", combined)
            self.assertIn("category=memory_index_mismatch", combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_refuses_broken_lifecycle_and_evidence_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(memory_repo, "mem_reviewed_broken_refs")
            node["supersedes"] = ["mem_missing_predecessor"]
            node["evidence_refs"][0]["quote_id"] = "ev_missing"
            write_memory_nodes(memory_repo, [node])

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive audit", combined)
            self.assertIn("category=broken_memory_ref", combined)
            self.assertIn("category=broken_supersession_ref", combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_refuses_noisy_automatic_memory_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(
                memory_repo,
                "mem_reviewed_noise",
                text="session_meta wrapper text must not become durable memory.",
            )
            write_memory_nodes(memory_repo, [node])

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive audit", combined)
            self.assertIn("category=noise", combined)
            self.assertNotIn("session_meta wrapper text", combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_refuses_key_like_value_without_rendering_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            fake_key = "sk-" + ("reviewedfake" * 3)
            node = make_automatic_memory_node(
                memory_repo,
                "mem_reviewed_secret",
                text=f"Synthetic memory containing {fake_key} must be rejected.",
            )
            write_memory_nodes(memory_repo, [node])

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("openai_key", combined)
            self.assertNotIn(fake_key, combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_refuses_unexpected_review_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(memory_repo, "mem_reviewed_unexpected")
            write_memory_nodes(memory_repo, [node])
            review_path = memory_repo / "reviews/memory_lifecycle_decisions.jsonl"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            review_path.write_text('{"decision_id":"synthetic"}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("reviews/memory_lifecycle_decisions.jsonl", result.stderr)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_dry_run_checks_candidate_index_without_staging_real_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(memory_repo, "mem_reviewed_whitespace")
            write_memory_nodes(memory_repo, [node])
            (memory_repo / "INDEX.md").write_text("# Agent Memory   \n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trailing whitespace", combined)
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertEqual(staged, "")
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_reviewed_mode_stages_tracked_automatic_memory_file_deletion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            node = make_automatic_memory_node(
                memory_repo,
                "mem_reviewed_tracked_deletion",
                layer="domain",
            )
            write_memory_nodes(memory_repo, [node])
            (memory_repo / "memories/global.jsonl").unlink()

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--message",
                    "Publish reviewed deletion",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            changed = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.splitlines()
            self.assertIn("memories/global.jsonl", changed)
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertEqual(status, "")

    def test_reviewed_mode_refuses_archive_with_no_active_memory_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            old_node = make_automatic_memory_node(memory_repo, "mem_reviewed_deprecated")
            marker_node = make_automatic_memory_node(memory_repo, "mem_reviewed_deprecation_marker")
            old_node["deprecated_by"] = marker_node["memory_id"]
            marker_node["deprecates"] = [old_node["memory_id"]]
            write_memory_nodes(memory_repo, [old_node, marker_node])

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/sync_memory_archive.py"),
                    "--include-reviewed-memory-nodes",
                    "--dry-run",
                ],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search health", combined)
            self.assertIn("no active memory records", combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_sync_memory_archive_dry_run_allows_explicit_memory_node_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            entry_dir = memory_repo / "sessions/2026/06/17/explicit-sync"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for explicit sync memory.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for explicit sync memory.\n", encoding="utf-8")
            memory_node = (
                '{"memory_id":"mem_explicit_sync","layer":"global","scope":"global","topic":"sync",'
                '"text":"Synthetic explicit memory node for sync dry run.","rationale":"test",'
                '"source":"explicit","confidence":"high","persistence":"sticky",'
                '"support_count":1,"first_seen":"2026-06-17","last_seen":"2026-06-17",'
                '"derived_from":["sessions/2026/06/17/explicit-sync/summary.md"],'
                '"evidence_refs":[{"path":"sessions/2026/06/17/explicit-sync/evidence.md","quote_id":"ev_001"}],'
                '"raw_refs":[],"supersedes":[],"superseded_by":null,"tags":["sync"]}'
            )
            (memory_repo / "memories/explicit.jsonl").write_text(memory_node + "\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(memory_node + "\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("memories/explicit.jsonl", result.stdout)
            self.assertNotIn("unexpected files", result.stderr)

    def test_sync_memory_archive_dry_run_with_push_allows_clean_publish_surfaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            daily = memory_repo / "daily/2026/2026-07-08.md"
            daily.parent.mkdir(parents=True)
            daily.write_text(
                "# Daily Memory Index\n\n"
                "## Durable Sessions\n\n"
                "- Synthetic project: Durable archive sync contract was updated.\n",
                encoding="utf-8",
            )
            (memory_repo / "index/sessions.jsonl").write_text(
                '{"summary":"Durable archive sync contract was updated.",'
                '"summary_path":"sessions/2026/07/08/synthetic/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run", "--push"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Would stage allowed archive roots", result.stdout)
            self.assertIn("Would push after commit.", result.stdout)

    def test_sync_memory_archive_dry_run_refuses_noisy_daily_publish_surface(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            sentinel = "PRIVATE_DAILY_NOISE_SHOULD_NOT_RENDER"
            daily = memory_repo / "daily/2026/2026-07-08.md"
            daily.parent.mkdir(parents=True)
            daily.write_text(
                "# Daily Memory Index\n\n"
                f"Command Status: dry-run would push after commit. {sentinel}\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run", "--push"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("publish readiness", combined)
            self.assertIn("publish_readiness_audit", combined)
            self.assertIn("command_progress", combined)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)
            self.assertNotIn(sentinel, combined)

    def test_sync_memory_archive_dry_run_refuses_review_decision_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            review_dir = memory_repo / "reviews"
            review_dir.mkdir()
            (review_dir / "memory_lifecycle_decisions.jsonl").write_text(
                '{"decision_id":"synthetic","action":"noop","current_memory_id":"mem_current",'
                '"older_memory_id":"mem_old","candidate_fingerprint":"sha256:synthetic"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("reviews/memory_lifecycle_decisions.jsonl", result.stderr)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_sync_memory_archive_dry_run_refuses_source_stream_registry_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            (memory_repo / "config/source_streams.jsonl").write_text(
                '{"stream_id":"synthetic","archive_scope":"domain:synthetic",'
                '"source_partition":"source:synthetic","source_dir":"/tmp/synthetic","enabled":true}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--dry-run"],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected files", result.stderr)
            self.assertIn("config/source_streams.jsonl", result.stderr)
            self.assertNotIn("Would stage allowed archive roots", result.stdout)

    def test_sync_memory_archive_refuses_key_like_values_without_leaking_them(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            fake_key = "sk-" + ("notreal" * 4)
            entry_dir = memory_repo / "sessions/2026/05/17/synthetic"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(f"# Summary\n\nDo not publish {fake_key}.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py")],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("openai_key", combined)
            self.assertNotIn(fake_key, combined)

    def test_sync_memory_archive_refuses_aws_key_like_values_before_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            fake_key = "AKIA" + ("0" * 16)
            entry_dir = memory_repo / "sessions/2026/05/17/synthetic"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(f"# Summary\n\nDo not publish {fake_key}.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py")],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("generated archive files contain key-like values", combined)
            self.assertIn("aws_access_key", combined)
            self.assertNotIn(fake_key, combined)

    def test_sync_memory_archive_refuses_audit_quality_findings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = create_git_backed_archive(Path(tmpdir))
            entry_dir = memory_repo / "sessions/2026/05/17/synthetic"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("session_meta: wrapper noise should block sync.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/sync_memory_archive.py")],
                cwd=memory_repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive audit", combined)
            self.assertIn("category=noise", combined)
            head = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=memory_repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
            self.assertIn("Initial archive", head)


if __name__ == "__main__":
    unittest.main()
