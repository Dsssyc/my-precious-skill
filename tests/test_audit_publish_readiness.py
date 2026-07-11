import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("templates/agent-memory-repo/tools/audit_publish_readiness.py").resolve()


def run_audit(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--memory-repo", str(memory_repo)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


class AuditPublishReadinessTests(unittest.TestCase):
    def test_clean_daily_and_index_publish_surfaces_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            daily = repo / "daily/2026/2026-07-08.md"
            daily.parent.mkdir(parents=True)
            daily.write_text(
                "# Daily Memory Index\n\n"
                "## Durable Sessions\n\n"
                "- Synthetic project: Durable archive policy was updated.\n\n"
                "## Durable Decisions\n\n"
                "- Keep generated daily records focused on durable outcomes.\n",
                encoding="utf-8",
            )
            write_jsonl(
                repo / "index/sessions.jsonl",
                [
                    {
                        "summary": "Durable archive policy was updated.",
                        "user_intent": "Capture a durable synthetic archive outcome.",
                        "summary_path": "sessions/2026/07/08/synthetic/summary.md",
                        "project_path": "/tmp/synthetic-project-path-is-structured-metadata",
                    }
                ],
            )

            result = run_audit(repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "publish_readiness_audit")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["blocked_file_count"], 0)
            self.assertEqual(report["privacy_leak_count"], 0)

    def test_noisy_daily_command_progress_blocks_without_rendering_text(self):
        sentinel = "PRIVATE_COMMAND_PROGRESS_SHOULD_NOT_RENDER"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            daily = repo / "daily/2026/2026-07-08.md"
            daily.parent.mkdir(parents=True)
            daily.write_text(
                "# Daily Memory Index\n\n"
                "Command Status: dry-run would push after commit.\n"
                f"{sentinel}\n",
                encoding="utf-8",
            )

            result = run_audit(repo)

            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertNotIn(sentinel, combined)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["category_counts"]["command_progress"], 1)
            self.assertEqual(report["blocked_paths"][0]["path"], "daily/2026/2026-07-08.md")

    def test_noisy_index_prompt_environment_blocks_without_rendering_text(self):
        sentinel = "PRIVATE_PROMPT_BLOCK_SHOULD_NOT_RENDER"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            write_jsonl(
                repo / "index/sessions.jsonl",
                [
                    {
                        "summary": f"<environment_context>{sentinel}</environment_context>",
                        "summary_path": "sessions/2026/07/08/synthetic/summary.md",
                    }
                ],
            )

            result = run_audit(repo)

            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertNotIn(sentinel, combined)
            report = json.loads(result.stdout)
            self.assertEqual(report["category_counts"]["prompt_or_environment"], 1)
            self.assertEqual(report["blocked_paths"][0]["path"], "index/sessions.jsonl")

    def test_index_content_raw_source_and_query_noise_blocks_structured_text_only(self):
        sentinel = "/Users/example/private/source-record.jsonl"
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            write_jsonl(
                repo / "index/sessions.jsonl",
                [
                    {
                        "summary": f"raw source path: {sentinel}",
                        "full_query": "synthetic full query should not be indexed",
                        "project_path": "/Users/example/allowed-as-structured-metadata",
                    }
                ],
            )

            result = run_audit(repo)

            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertNotIn(sentinel, combined)
            self.assertNotIn("/Users/example/allowed-as-structured-metadata", combined)
            report = json.loads(result.stdout)
            self.assertEqual(report["category_counts"]["raw_source_reference"], 2)

    def test_secret_like_value_blocks_without_rendering_secret(self):
        fake_key = "sk-" + ("notreal" * 4)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            daily = repo / "daily/2026/2026-07-08.md"
            daily.parent.mkdir(parents=True)
            daily.write_text(f"# Daily\n\nDo not publish {fake_key}.\n", encoding="utf-8")

            result = run_audit(repo)

            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            self.assertNotIn(fake_key, combined)
            report = json.loads(result.stdout)
            self.assertEqual(report["category_counts"]["secret_like_value"], 1)


if __name__ == "__main__":
    unittest.main()
