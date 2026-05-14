import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SearchMemoryTests(unittest.TestCase):
    def test_search_memory_finds_index_and_summary_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/05/14/example").mkdir(parents=True)

            summary_path = repo / "sessions/2026/05/14/example/summary.md"
            summary_path.write_text(
                "# Session: Agent Memory Archive\n\n"
                "## User intent\n"
                "Design a private agent session memory archive.\n",
                encoding="utf-8",
            )

            (repo / "index/sessions.jsonl").write_text(
                '{"date":"2026-05-14","source_agent":"agent",'
                '"project":"agent-memory","title":"Design private agent memory",'
                '"tags":["agent","memory","archive"],'
                '"summary_path":"sessions/2026/05/14/example/summary.md",'
                '"evidence_path":"sessions/2026/05/14/example/evidence.md",'
                '"unresolved_count":0}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "private memory archive", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("Top memory hits for: private memory archive", result.stdout)
        self.assertIn("sessions/2026/05/14/example/summary.md", result.stdout)
        self.assertIn("index:sessions.jsonl", result.stdout)


if __name__ == "__main__":
    unittest.main()
