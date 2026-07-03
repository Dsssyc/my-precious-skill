import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/private_generated_answer_dogfood_gate.py").resolve()


class PrivateGeneratedAnswerDogfoodGateTests(unittest.TestCase):
    def init_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (repo / "INDEX.md").write_text("# Synthetic memory archive\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "INDEX.md", ".gitignore"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "commit", "-m", "init synthetic archive"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_preflight_passes_for_clean_memory_repo_without_rendering_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--memory-repo", str(repo), "--preflight-only"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "private_generated_answer_dogfood_gate")
            self.assertEqual(payload["status"], "preflight_passed")
            self.assertEqual(payload["dirty_private_artifact_count"], 0)
            self.assertFalse(payload["memory_repo_dirty"])
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["private_paths_rendered"])
            self.assertNotIn(str(repo), result.stdout + result.stderr)

    def test_preflight_rejects_dirty_eval_and_tmp_outputs_without_rendering_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)
            eval_file = repo / "eval" / "generated_answer_private_dogfood_cases.jsonl"
            tmp_file = repo / ".tmp" / "generated-answer-dogfood" / "cases.jsonl"
            eval_file.parent.mkdir(parents=True)
            tmp_file.parent.mkdir(parents=True)
            eval_file.write_text("{}\n", encoding="utf-8")
            tmp_file.write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--memory-repo", str(repo), "--preflight-only"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["dirty_eval_artifact_count"], 1)
            self.assertEqual(payload["dirty_tmp_artifact_count"], 1)
            self.assertEqual(payload["dirty_private_artifact_count"], 2)
            self.assertEqual(payload["failures"], [{"reason": "dirty_private_dogfood_artifacts"}])
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["private_paths_rendered"])

            rendered = result.stdout + result.stderr
            self.assertNotIn(str(repo), rendered)
            self.assertNotIn("generated_answer_private_dogfood_cases", rendered)
            self.assertNotIn("generated-answer-dogfood", rendered)

    def test_preflight_rejects_work_dir_that_would_delete_memory_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(repo),
                    "--work-dir",
                    str(repo),
                    "--preflight-only",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertIn({"reason": "unsafe_work_dir"}, payload["failures"])
            self.assertTrue((repo / "INDEX.md").exists())
            self.assertNotIn(str(repo), result.stdout + result.stderr)

    def test_preflight_rejects_generic_external_work_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            self.init_repo(repo)
            generic_work_dir = root / "tmp"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(repo),
                    "--work-dir",
                    str(generic_work_dir),
                    "--preflight-only",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertIn({"reason": "unsafe_work_dir"}, payload["failures"])
            self.assertNotIn(str(generic_work_dir), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
