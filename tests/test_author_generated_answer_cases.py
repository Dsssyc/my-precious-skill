import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("templates/agent-memory-repo/tools/author_generated_answer_cases.py").resolve()
CASE_AUDIT = Path("benchmarks/generated_answer_case_audit.py").resolve()
GENERATE_ANSWERS = Path("templates/agent-memory-repo/tools/generate_answer_records.py").resolve()
ANSWER_BENCHMARK = Path("benchmarks/generated_answer_benchmark.py").resolve()


class AuthorGeneratedAnswerCasesTests(unittest.TestCase):
    def write_memory_index(self, repo: Path, rows: list[dict]) -> None:
        path = repo / "index" / "memories.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def memory_row(self, memory_id: str, text: str, **overrides) -> dict:
        row = {
            "memory_id": memory_id,
            "layer": "global",
            "scope": "*",
            "topic": "source-depth",
            "text": text,
            "source": "automatic",
            "confidence": "high",
            "support_count": 2,
            "tags": ["source", "provenance"],
            "raw_refs": [],
        }
        row.update(overrides)
        return row

    def test_dry_run_reports_aggregate_case_authoring_without_rendering_private_text(self):
        private_answer = "Use source anchors for provenance without printing raw transcript content."
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            output = repo / "eval" / "private_cases.jsonl"
            self.write_memory_index(
                repo,
                [
                    self.memory_row("mem_private_answer", private_answer),
                    self.memory_row("mem_retired", "Retired answer should not render.", superseded_by="mem_new"),
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--output",
                    str(output),
                    "--dry-run",
                    "--limit",
                    "3",
                    "--source-benchmark",
                    "MyPreciousPrivateDogfood",
                    "--case-origin",
                    "private_dogfood",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "generated_answer_case_authoring")
            self.assertFalse(report["write_enabled"])
            self.assertEqual(report["candidate_memory_count"], 2)
            self.assertEqual(report["selected_case_count"], 1)
            self.assertEqual(report["would_write_count"], 1)
            self.assertEqual(report["written_count"], 0)
            self.assertEqual(report["source_benchmarks"], {"MyPreciousPrivateDogfood": 1})
            self.assertEqual(report["case_origins"], {"private_dogfood": 1})
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["memory_text_rendered"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["reference_answers_rendered"])
            self.assertFalse(report["privacy"]["memory_ids_rendered"])
            self.assertFalse(output.exists())

            rendered = result.stdout + result.stderr
            self.assertNotIn(private_answer, rendered)
            self.assertNotIn("mem_private_answer", rendered)
            self.assertNotIn(str(repo), rendered)
            self.assertNotIn(str(output), rendered)

    def test_write_creates_scoreable_private_case_set_accepted_by_case_audit(self):
        private_answer = "Use source anchors for provenance without printing raw transcript content."
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            output = repo / "eval" / "private_cases.jsonl"
            self.write_memory_index(repo, [self.memory_row("mem_private_answer", private_answer)])

            author = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--output",
                    str(output),
                    "--write",
                    "--source-benchmark",
                    "MyPreciousPrivateDogfood",
                    "--case-origin",
                    "private_dogfood",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            report = json.loads(author.stdout)
            self.assertTrue(report["write_enabled"])
            self.assertEqual(report["written_count"], 1)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_benchmark"], "MyPreciousPrivateDogfood")
            self.assertEqual(rows[0]["case_origin"], "private_dogfood")
            self.assertEqual(rows[0]["reference_answer"], private_answer)
            self.assertEqual(rows[0]["expected_memory_id"], "mem_private_answer")
            self.assertIn("query", rows[0])
            self.assertNotEqual(rows[0]["query"], private_answer)
            self.assertNotIn("mem_private_answer", rows[0]["case_id"])

            audit = subprocess.run(
                [
                    sys.executable,
                    str(CASE_AUDIT),
                    "--cases",
                    str(output),
                    "--require-source-benchmark",
                    "MyPreciousPrivateDogfood",
                    "--require-case-origin",
                    "private_dogfood",
                    "--fail-under",
                    "answer_scorable_case_rate=1.0",
                    "--fail-over",
                    "positive_without_reference_answer=0",
                    "--fail-over",
                    "unsafe_aggregate_identifier_count=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            audit_report = json.loads(audit.stdout)
            self.assertEqual(audit_report["cases"], 1)
            self.assertEqual(audit_report["answer_scorable_case_rate"], 1.0)

            rendered = author.stdout + author.stderr + audit.stdout + audit.stderr
            self.assertNotIn(private_answer, rendered)
            self.assertNotIn("mem_private_answer", rendered)
            self.assertNotIn(str(repo), rendered)

    def test_authored_cases_feed_extractive_answer_benchmark(self):
        private_answer = "Use source anchors for provenance without printing raw transcript content."
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = repo / "eval" / "private_cases.jsonl"
            answers = root / "answers.jsonl"
            self.write_memory_index(repo, [self.memory_row("mem_private_answer", private_answer)])

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--output",
                    str(cases),
                    "--write",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            adapter = subprocess.run(
                [
                    sys.executable,
                    str(GENERATE_ANSWERS),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--output",
                    str(answers),
                    "--limit",
                    "3",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            adapter_report = json.loads(adapter.stdout)
            self.assertEqual(adapter_report["memory_answer_count"], 1)
            self.assertEqual(adapter_report["abstention_answer_count"], 0)

            benchmark = subprocess.run(
                [
                    sys.executable,
                    str(ANSWER_BENCHMARK),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--fail-under",
                    "case_pass_rate=1.0",
                    "--fail-under",
                    "answer_normalized_match_rate=1.0",
                    "--fail-over",
                    "failed_case_count=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            benchmark_report = json.loads(benchmark.stdout)
            self.assertEqual(benchmark_report["case_pass_rate"], 1.0)
            self.assertEqual(benchmark_report["answer_normalized_match_rate"], 1.0)

            rendered = adapter.stdout + adapter.stderr + benchmark.stdout + benchmark.stderr
            self.assertNotIn(private_answer, rendered)
            self.assertNotIn("mem_private_answer", rendered)
            self.assertNotIn(str(repo), rendered)


if __name__ == "__main__":
    unittest.main()
