import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/generated_answer_case_audit.py").resolve()


class GeneratedAnswerCaseAuditTests(unittest.TestCase):
    def write_jsonl(self, root: Path, name: str, rows: list[dict]) -> Path:
        path = root / name
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def test_audits_scoreable_case_set_without_rendering_private_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "private_case_alpha",
                        "query": "PRIVATE QUERY SHOULD NOT RENDER",
                        "category": "answer_positive",
                        "source_benchmark": "MyPreciousPrivateDogfood",
                        "case_origin": "private_dogfood",
                        "reference_answer": "PRIVATE REFERENCE SHOULD NOT RENDER",
                        "forbidden_output_patterns": ["PRIVATE_SECRET_PATTERN"],
                    },
                    {
                        "case_id": "private_case_abstain",
                        "query": "PRIVATE ABSTAIN QUERY SHOULD NOT RENDER",
                        "category": "answer_abstain",
                        "source_benchmark": "MyPreciousPrivateDogfood",
                        "case_origin": "private_dogfood",
                        "expected_abstain": True,
                    },
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--require-source-benchmark",
                    "MyPreciousPrivateDogfood",
                    "--require-case-origin",
                    "private_dogfood",
                    "--fail-under",
                    "answer_scorable_case_rate=1.0",
                    "--fail-over",
                    "positive_without_reference_answer=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "generated_answer_case_audit")
            self.assertEqual(payload["cases"], 2)
            self.assertEqual(payload["positive_cases"], 1)
            self.assertEqual(payload["abstain_cases"], 1)
            self.assertEqual(payload["reference_answer_cases"], 1)
            self.assertEqual(payload["answer_scorable_cases"], 2)
            self.assertEqual(payload["positive_without_reference_answer"], 0)
            self.assertEqual(payload["answer_scorable_case_rate"], 1.0)
            self.assertEqual(payload["forbidden_output_pattern_cases"], 1)
            self.assertEqual(payload["source_benchmarks"], {"MyPreciousPrivateDogfood": 2})
            self.assertEqual(payload["case_origins"], {"private_dogfood": 2})
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["queries_rendered"])
            self.assertFalse(payload["privacy"]["reference_answers_rendered"])
            self.assertFalse(payload["privacy"]["case_ids_rendered"])

            rendered = result.stdout + result.stderr
            self.assertNotIn("PRIVATE QUERY SHOULD NOT RENDER", rendered)
            self.assertNotIn("PRIVATE ABSTAIN QUERY SHOULD NOT RENDER", rendered)
            self.assertNotIn("PRIVATE REFERENCE SHOULD NOT RENDER", rendered)
            self.assertNotIn("PRIVATE_SECRET_PATTERN", rendered)
            self.assertNotIn("private_case_alpha", rendered)
            self.assertNotIn(str(cases), rendered)

    def test_fails_unscoreable_positive_case_without_rendering_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "private_case_missing_reference",
                        "query": "PRIVATE QUERY SHOULD STAY PRIVATE",
                        "source_benchmark": "MyPreciousPrivateDogfood",
                        "case_origin": "private_dogfood",
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--fail-under",
                    "answer_scorable_case_rate=1.0",
                    "--fail-over",
                    "positive_without_reference_answer=0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["reference_answer_cases"], 0)
            self.assertEqual(payload["answer_scorable_cases"], 0)
            self.assertEqual(payload["positive_without_reference_answer"], 1)
            self.assertEqual(payload["answer_scorable_case_rate"], 0.0)
            self.assertIn("answer_scorable_case_rate", result.stderr)
            self.assertIn("positive_without_reference_answer", result.stderr)
            rendered = result.stdout + result.stderr
            self.assertNotIn("PRIVATE QUERY SHOULD STAY PRIVATE", rendered)
            self.assertNotIn("private_case_missing_reference", rendered)

    def test_required_source_and_origin_keys_are_aggregate_only_gates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "case_without_required_origin",
                        "query": "QUERY SHOULD STAY PRIVATE",
                        "source_benchmark": "OtherBenchmark",
                        "case_origin": "other_origin",
                        "reference_answer": "REFERENCE SHOULD STAY PRIVATE",
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--require-source-benchmark",
                    "MyPreciousPrivateDogfood",
                    "--require-case-origin",
                    "private_dogfood",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source_benchmarks"], {"OtherBenchmark": 1})
            self.assertEqual(payload["case_origins"], {"other_origin": 1})
            self.assertIn("source_benchmarks.MyPreciousPrivateDogfood", result.stderr)
            self.assertIn("case_origins.private_dogfood", result.stderr)
            rendered = result.stdout + result.stderr
            self.assertNotIn("QUERY SHOULD STAY PRIVATE", rendered)
            self.assertNotIn("REFERENCE SHOULD STAY PRIVATE", rendered)
            self.assertNotIn("case_without_required_origin", rendered)


if __name__ == "__main__":
    unittest.main()
