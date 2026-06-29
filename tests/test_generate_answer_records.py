import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("templates/agent-memory-repo/tools/generate_answer_records.py").resolve()
SYNTHETIC_ARCHIVE_BUILDER = Path("benchmarks/build_synthetic_recall_archive.py").resolve()
GENERATED_ANSWER_BENCHMARK = Path("benchmarks/generated_answer_benchmark.py").resolve()


class GenerateAnswerRecordsTests(unittest.TestCase):
    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_extracts_memory_answers_and_feeds_generated_answer_benchmark(self):
        answer_text = "Use source anchors for provenance without printing raw transcript content"
        rows = [
            {
                "case_id": "answer-adapter:source-depth",
                "query": "What should source-depth answers say about raw transcript content?",
                "category": "generated_answer_positive",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": answer_text,
                "expected_memory_id": "answer_adapter_source_depth",
                "expected_summary_path": "sessions/synthetic/answer-adapter/source-depth/summary.md",
                "expected_source_anchor": "records/synthetic-answer-adapter.jsonl#message:1",
                "required_evidence_paths": ["sessions/synthetic/answer-adapter/source-depth/evidence.md"],
                "forbidden_output_patterns": ["BEGIN RAW TRANSCRIPT"],
            },
            {
                "case_id": "answer-adapter:unsupported",
                "query": "Which private archive path stores the unmentioned adapter password?",
                "category": "generated_answer_abstain",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": "not enough information",
                "expected_abstain": True,
                "forbidden_output_patterns": ["password\\s*[:=]"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = root / "answer_cases.jsonl"
            answers = root / "answers.jsonl"
            self.write_jsonl(cases, rows)

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            adapter = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--output",
                    str(answers),
                    "--limit",
                    "3",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(adapter.returncode, 0, adapter.stderr)
            report = json.loads(adapter.stdout)
            self.assertEqual(report["report_kind"], "generated_answer_records_adapter")
            self.assertEqual(report["cases"], 2)
            self.assertEqual(report["answers_written"], 2)
            self.assertEqual(report["memory_answer_count"], 1)
            self.assertEqual(report["abstention_answer_count"], 1)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["generated_answers_rendered"])

            rendered = adapter.stdout + adapter.stderr
            self.assertNotIn(rows[0]["query"], rendered)
            self.assertNotIn(answer_text, rendered)
            self.assertNotIn(str(repo), rendered)
            self.assertNotIn(str(cases), rendered)
            self.assertNotIn(str(answers), rendered)

            benchmark = subprocess.run(
                [
                    sys.executable,
                    str(GENERATED_ANSWER_BENCHMARK),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--fail-under",
                    "case_pass_rate=1.0",
                    "--fail-under",
                    "answer_normalized_match_rate=1.0",
                    "--fail-under",
                    "abstention_accuracy=1.0",
                    "--fail-over",
                    "privacy_leak_count=0",
                    "--fail-over",
                    "failed_case_count=0",
                    "--fail-over",
                    "missing_answer_count=0",
                    "--fail-over",
                    "duplicate_answer_count=0",
                    "--fail-over",
                    "unknown_answer_count=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            payload = json.loads(benchmark.stdout)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertEqual(payload["source_benchmarks"], {"MyPreciousAnswerAdapterSynthetic": 2})
            self.assertEqual(payload["case_origins"], {"extractive_answer_adapter_fixture": 2})

    def test_extracts_multi_sentence_memory_answer(self):
        answer_text = "Use source anchors. Do not print raw transcript content."
        rows = [
            {
                "case_id": "answer-adapter:multi-sentence",
                "query": "What is the multi sentence answer for source anchors?",
                "category": "generated_answer_positive",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": answer_text,
                "expected_memory_id": "answer_adapter_multi_sentence",
                "expected_summary_path": "sessions/synthetic/answer-adapter/multi-sentence/summary.md",
                "expected_source_anchor": "records/synthetic-answer-adapter.jsonl#message:2",
                "required_evidence_paths": ["sessions/synthetic/answer-adapter/multi-sentence/evidence.md"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = root / "answer_cases.jsonl"
            answers = root / "answers.jsonl"
            self.write_jsonl(cases, rows)

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
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

            benchmark = subprocess.run(
                [
                    sys.executable,
                    str(GENERATED_ANSWER_BENCHMARK),
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(benchmark.returncode, 0, benchmark.stderr)

    def test_extracts_answer_longer_than_search_display_clip(self):
        answer_text = (
            "Use source anchors with durable evidence references, preserve provenance status, "
            "avoid printing raw transcript content, keep redacted snippets short, and state "
            "when the archive lacks enough information."
        )
        rows = [
            {
                "case_id": "answer-adapter:long-answer",
                "query": "What is the long answer about source anchors and provenance status?",
                "category": "generated_answer_positive",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": answer_text,
                "expected_memory_id": "answer_adapter_long_answer",
                "expected_summary_path": "sessions/synthetic/answer-adapter/long-answer/summary.md",
                "expected_source_anchor": "records/synthetic-answer-adapter.jsonl#message:3",
                "required_evidence_paths": ["sessions/synthetic/answer-adapter/long-answer/evidence.md"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = root / "answer_cases.jsonl"
            answers = root / "answers.jsonl"
            self.write_jsonl(cases, rows)

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
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

            benchmark = subprocess.run(
                [
                    sys.executable,
                    str(GENERATED_ANSWER_BENCHMARK),
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(benchmark.returncode, 0, benchmark.stderr)


if __name__ == "__main__":
    unittest.main()
