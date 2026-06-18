import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LayeredRecallBenchmarkTests(unittest.TestCase):
    def test_layered_recall_benchmark_reports_memory_and_session_metrics(self):
        script = Path("benchmarks/layered_recall_benchmark.py").resolve()
        search_script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            (repo / "index").mkdir(parents=True)
            (repo / "sessions/2026/06/04/source").mkdir(parents=True)
            (repo / "sessions/2026/06/04/source/summary.md").write_text("# Session\n", encoding="utf-8")
            (repo / "sessions/2026/06/04/source/evidence.md").write_text("# Evidence\n", encoding="utf-8")
            raw_source = repo / "records/private.jsonl"
            raw_source.parent.mkdir(parents=True)
            raw_source.write_text("Synthetic private source placeholder.\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "Avoid repeated permission prompts after permission is granted.",
                        "rationale": "Explicit user preference.",
                        "source": "explicit",
                        "confidence": "high",
                        "persistence": "sticky",
                        "support_count": 1,
                        "first_seen": "2026-06-04T10:00:00Z",
                        "last_seen": "2026-06-04T10:00:00Z",
                        "derived_from": ["sessions/2026/06/04/source/summary.md"],
                        "evidence_refs": [{"path": "sessions/2026/06/04/source/evidence.md", "quote_id": "ev_001"}],
                        "raw_refs": [{"path": "records/private.jsonl", "anchor": "message:42"}],
                        "supersedes": [],
                        "superseded_by": None,
                        "tags": ["permissions"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            cases = root / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "query": "permission prompts after granted",
                        "expected_memory_id": "mem_permission",
                        "expected_summary_path": "sessions/2026/06/04/source/summary.md",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--search-script",
                    str(search_script),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["cases"], 1)
        self.assertEqual(payload["memory_recall_at_5"], 1.0)
        self.assertEqual(payload["session_drilldown_at_5"], 1.0)
        self.assertEqual(payload["source_reachability"], 1.0)
