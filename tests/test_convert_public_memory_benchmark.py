import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/convert_public_memory_benchmark.py").resolve()


class ConvertPublicMemoryBenchmarkTests(unittest.TestCase):
    def test_converts_longmemeval_questions_and_abstention_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "lme_q1",
                            "question_type": "multi-session",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                            "question_date": "2026-06-19",
                        },
                        {
                            "question_id": "lme_q2_abs",
                            "question_type": "single-session-user",
                            "question": "Which unsupported ritual was never discussed?",
                            "answer": "No answer.",
                            "question_date": "2026-06-19",
                        },
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "longmemeval",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rows = self.read_rows(output)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["source_benchmark"], "LongMemEval")
            self.assertEqual(rows[0]["category"], "multi_session_reasoning")
            self.assertEqual(rows[0]["expected_memory_id"], "external_longmemeval_lme_q1")
            self.assertEqual(rows[0]["expected_summary_path"], "sessions/external/longmemeval/lme_q1/summary.md")
            self.assertEqual(rows[0]["expected_source_anchor"], "records/external/longmemeval.json#question_id:lme_q1")
            self.assertEqual(rows[0]["reference_answer"], "The memory skill project.")
            self.assertEqual(rows[0]["question_date"], "2026-06-19")
            self.assertEqual(rows[1]["category"], "abstention")
            self.assertTrue(rows[1]["expected_abstain"])
            self.assertNotIn("expected_memory_id", rows[1])

    def test_converts_locomo_nested_qa_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "locomo.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    [
                        {
                            "sample_id": "conv-A",
                            "qa": [
                                {
                                    "question": "When did the preference change?",
                                    "answer": "After the second session.",
                                    "category": "temporal",
                                    "evidence": ["session-1", "session-2"],
                                }
                            ],
                        }
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "locomo",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rows = self.read_rows(output)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_benchmark"], "LoCoMo")
            self.assertEqual(rows[0]["category"], "temporal_reasoning")
            self.assertEqual(rows[0]["expected_memory_id"], "external_locomo_conv-a_qa-1")
            self.assertEqual(rows[0]["expected_source_anchor"], "records/external/locomo.json#sample:conv-A:qa:1")
            self.assertEqual(rows[0]["reference_evidence"], ["session-1", "session-2"])

    def test_converts_memora_forgetting_checks_to_stale_memory_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "memora.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "questions": {
                            "Remembering": [
                                {
                                    "question_id": "mem_q1",
                                    "question": "Which preference should be recalled?",
                                    "answer": "Use layered recall.",
                                    "question_date": "2026-06-19",
                                    "evaluation": {
                                        "evaluation_questions": [
                                            {"evaluation_type": "memory_presence", "question": "Is the new preference present?"},
                                            {"evaluation_type": "forgetting_absence", "question": "Is the old preference absent?"},
                                        ]
                                    },
                                }
                            ]
                        }
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "memora",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rows = self.read_rows(output)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_benchmark"], "Memora")
            self.assertEqual(rows[0]["category"], "information_extraction")
            self.assertEqual(rows[0]["expected_memory_id"], "external_memora_mem_q1")
            self.assertEqual(rows[0]["stale_memory_id"], "external_memora_mem_q1_stale")
            self.assertEqual(rows[0]["expected_not_memory_id"], "external_memora_mem_q1_stale")
            self.assertEqual(rows[0]["temporal_scope"], "latest")
            self.assertEqual(rows[0]["evaluation_types"], ["memory_presence", "forgetting_absence"])

    def read_rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
