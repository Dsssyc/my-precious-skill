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

    def test_sync_memory_archive_dry_run_allows_memory_node_changes(self):
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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Would stage allowed archive roots", result.stdout)
            self.assertIn("- memories", result.stdout)
            self.assertNotIn("unexpected files", result.stderr)

    def test_sync_memory_archive_dry_run_allows_review_decision_changes(self):
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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Would stage allowed archive roots", result.stdout)
            self.assertIn("- reviews", result.stdout)
            self.assertNotIn("unexpected files", result.stderr)

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
