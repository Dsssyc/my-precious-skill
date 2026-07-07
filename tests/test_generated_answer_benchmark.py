import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/generated_answer_benchmark.py").resolve()
PACKAGED_CASES = Path("benchmarks/cases/generated_answer_synthetic.jsonl").resolve()
PACKAGED_ANSWERS = Path("benchmarks/cases/generated_answer_synthetic_answers.jsonl").resolve()


class GeneratedAnswerBenchmarkTests(unittest.TestCase):
    def write_jsonl(self, root: Path, name: str, rows: list[dict]) -> Path:
        path = root / name
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path

    def test_scores_positive_and_abstention_answers_without_rendering_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "query": "RAW QUERY SHOULD NOT RENDER",
                        "category": "answer_positive",
                        "source_benchmark": "SyntheticAnswer",
                        "reference_answer": "Use layered recall for durable preferences.",
                        "forbidden_output_patterns": ["SHOULD_NOT_RENDER"],
                    },
                    {
                        "case_id": "abstain_case",
                        "query": "PRIVATE ABSTAIN QUERY SHOULD NOT RENDER",
                        "category": "answer_abstain",
                        "reference_answer": "not enough information",
                        "expected_abstain": True,
                    },
                ],
            )
            answers = self.write_jsonl(
                root,
                "answers.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "generated_answer": "Use layered recall for durable preferences.",
                        "answer_handoff": {
                            "contract_version": 1,
                            "abstained": False,
                            "active_memory_only": True,
                            "support_refs": [
                                {
                                    "memory_id": "positive_memory",
                                    "summary_paths": ["sessions/synthetic/positive/summary.md"],
                                    "evidence_refs": ["sessions/synthetic/positive/evidence.md#ev_001"],
                                }
                            ],
                            "unsupported_claim_count": 0,
                            "inactive_memory_answer_count": 0,
                            "privacy_leak_count": 0,
                        },
                    },
                    {
                        "case_id": "abstain_case",
                        "generated_answer": "There is not enough information in memory to answer.",
                        "answer_handoff": {
                            "contract_version": 1,
                            "abstained": True,
                            "abstain_reason": "no_supported_memory_hit",
                            "active_memory_only": True,
                            "support_refs": [],
                            "unsupported_claim_count": 0,
                            "inactive_memory_answer_count": 0,
                            "privacy_leak_count": 0,
                        },
                    },
                ],
            )
            details = root / "details.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--details-jsonl",
                    str(details),
                    "--fail-under",
                    "case_pass_rate=1.0",
                    "--fail-under",
                    "answer_normalized_match_rate=1.0",
                    "--fail-under",
                    "abstention_accuracy=1.0",
                    "--fail-over",
                    "privacy_leak_count=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "generated_answer_benchmark")
            self.assertEqual(payload["cases"], 2)
            self.assertEqual(payload["positive_cases"], 1)
            self.assertEqual(payload["abstain_cases"], 1)
            self.assertEqual(payload["reference_answer_cases"], 2)
            self.assertEqual(payload["answer_scorable_cases"], 2)
            self.assertEqual(payload["positive_without_reference_answer"], 0)
            self.assertEqual(payload["answer_scorable_case_rate"], 1.0)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertEqual(payload["answer_exact_match_rate"], 1.0)
            self.assertEqual(payload["answer_normalized_match_rate"], 1.0)
            self.assertEqual(payload["abstention_accuracy"], 1.0)
            self.assertEqual(payload["answer_handoff_present_rate"], 1.0)
            self.assertEqual(payload["answer_handoff_support_coverage_rate"], 1.0)
            self.assertEqual(payload["answer_handoff_supported_case_count"], 1)
            self.assertEqual(payload["answer_handoff_abstain_case_count"], 1)
            self.assertEqual(payload["unsupported_claim_count"], 0)
            self.assertEqual(payload["inactive_memory_answer_count"], 0)
            self.assertEqual(payload["privacy_leak_count"], 0)
            self.assertEqual(payload["failed_case_count"], 0)
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["queries_rendered"])
            self.assertFalse(payload["privacy"]["generated_answers_rendered"])
            self.assertFalse(payload["privacy"]["reference_answers_rendered"])

            rendered = result.stdout + result.stderr + details.read_text(encoding="utf-8")
            self.assertNotIn("RAW QUERY SHOULD NOT RENDER", rendered)
            self.assertNotIn("PRIVATE ABSTAIN QUERY SHOULD NOT RENDER", rendered)
            self.assertNotIn("Use layered recall for durable preferences.", rendered)
            self.assertNotIn("There is not enough information in memory to answer.", rendered)
            self.assertNotIn(str(cases), rendered)
            self.assertNotIn(str(answers), rendered)

    def test_packaged_generated_answer_fixture_passes_strict_quality_gate(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--cases",
                str(PACKAGED_CASES),
                "--answers",
                str(PACKAGED_ANSWERS),
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

        payload = json.loads(result.stdout)
        self.assertEqual(payload["report_kind"], "generated_answer_benchmark")
        self.assertEqual(payload["cases"], 4)
        self.assertEqual(payload["positive_cases"], 3)
        self.assertEqual(payload["abstain_cases"], 1)
        self.assertEqual(payload["reference_answer_cases"], 4)
        self.assertEqual(payload["answer_scorable_cases"], 4)
        self.assertEqual(payload["positive_without_reference_answer"], 0)
        self.assertEqual(payload["answer_scorable_case_rate"], 1.0)
        self.assertEqual(payload["source_benchmarks"], {"MyPreciousGeneratedAnswerSynthetic": 4})
        self.assertEqual(payload["case_origins"], {"packaged_generated_answer_fixture": 4})
        self.assertEqual(payload["case_pass_rate"], 1.0)
        self.assertEqual(payload["answer_normalized_match_rate"], 1.0)
        self.assertEqual(payload["abstention_accuracy"], 1.0)
        self.assertEqual(payload["answer_handoff_present_rate"], 1.0)
        self.assertEqual(payload["answer_handoff_support_coverage_rate"], 1.0)
        self.assertEqual(payload["answer_handoff_supported_case_count"], 3)
        self.assertEqual(payload["answer_handoff_abstain_case_count"], 1)
        self.assertEqual(payload["unsupported_claim_count"], 0)
        self.assertEqual(payload["inactive_memory_answer_count"], 0)
        self.assertEqual(payload["privacy_leak_count"], 0)

    def test_handoff_metrics_fail_when_support_refs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "query": "QUERY SHOULD STAY PRIVATE",
                        "category": "answer_positive",
                        "reference_answer": "Keep answers grounded.",
                    }
                ],
            )
            answers = self.write_jsonl(
                root,
                "answers.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "generated_answer": "Keep answers grounded.",
                        "answer_handoff": {
                            "contract_version": 1,
                            "abstained": False,
                            "active_memory_only": True,
                            "support_refs": [],
                            "unsupported_claim_count": 0,
                            "inactive_memory_answer_count": 0,
                            "privacy_leak_count": 0,
                        },
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--fail-under",
                    "answer_handoff_support_coverage_rate=1.0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["answer_handoff_present_rate"], 1.0)
            self.assertEqual(payload["answer_handoff_support_coverage_rate"], 0.0)
            self.assertEqual(payload["answer_handoff_supported_case_count"], 0)
            self.assertIn("answer_handoff_support_coverage_rate", result.stderr)

    def test_handoff_privacy_scan_rejects_raw_refs_and_local_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "query": "QUERY SHOULD STAY PRIVATE",
                        "category": "answer_positive",
                        "reference_answer": "Keep answers grounded.",
                    }
                ],
            )
            answers = self.write_jsonl(
                root,
                "answers.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "generated_answer": "Keep answers grounded.",
                        "answer_handoff": {
                            "contract_version": 1,
                            "abstained": False,
                            "active_memory_only": True,
                            "support_refs": [
                                {
                                    "memory_id": "positive_memory",
                                    "summary_paths": ["/Users/private/archive/summary.md"],
                                    "evidence_refs": ["sessions/synthetic/positive/evidence.md#ev_001"],
                                    "raw_refs": ["records/private.jsonl#message:1"],
                                }
                            ],
                            "unsupported_claim_count": 0,
                            "inactive_memory_answer_count": 0,
                            "privacy_leak_count": 0,
                        },
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--fail-over",
                    "privacy_leak_count=0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["privacy_leak_count"], 1)
            rendered = result.stdout + result.stderr
            self.assertNotIn("/Users/private/archive/summary.md", rendered)
            self.assertNotIn("records/private.jsonl#message:1", rendered)

    def test_reports_failures_without_rendering_sensitive_answer_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "query": "QUERY SHOULD STAY PRIVATE",
                        "category": "answer_positive",
                        "reference_answer": "Keep private archive boundaries strict.",
                        "forbidden_output_patterns": ["SECRET_NEVER_RENDER"],
                    }
                ],
            )
            answers = self.write_jsonl(
                root,
                "answers.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "generated_answer": "SECRET_NEVER_RENDER unrelated answer",
                    },
                    {
                        "case_id": "positive_case",
                        "generated_answer": "duplicate answer should not render",
                    },
                    {
                        "case_id": "unknown_case",
                        "generated_answer": "unknown answer should not render",
                    },
                ],
            )
            details = root / "details.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
                    "--details-jsonl",
                    str(details),
                    "--fail-under",
                    "case_pass_rate=1.0",
                    "--fail-over",
                    "privacy_leak_count=0",
                    "--fail-over",
                    "duplicate_answer_count=0",
                    "--fail-over",
                    "unknown_answer_count=0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["duplicate_answer_count"], 1)
            self.assertEqual(payload["unknown_answer_count"], 1)
            self.assertEqual(payload["privacy_leak_count"], 1)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertLess(payload["case_pass_rate"], 1.0)

            rendered = result.stdout + result.stderr + details.read_text(encoding="utf-8")
            self.assertNotIn("SECRET_NEVER_RENDER", rendered)
            self.assertNotIn("QUERY SHOULD STAY PRIVATE", rendered)
            self.assertNotIn("Keep private archive boundaries strict.", rendered)
            self.assertNotIn("duplicate answer should not render", rendered)
            self.assertNotIn("unknown answer should not render", rendered)
            self.assertNotIn(str(cases), rendered)
            self.assertNotIn(str(answers), rendered)

    def test_reports_positive_cases_without_reference_answers_as_unscored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases = self.write_jsonl(
                root,
                "cases.jsonl",
                [
                    {
                        "case_id": "positive_case",
                        "query": "QUERY SHOULD STAY PRIVATE",
                        "category": "answer_positive",
                    }
                ],
            )
            answers = self.write_jsonl(
                root,
                "answers.jsonl",
                [{"case_id": "positive_case", "generated_answer": "Some plausible answer."}],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(cases),
                    "--answers",
                    str(answers),
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
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertIn("positive_without_reference_answer", result.stderr)
            rendered = result.stdout + result.stderr
            self.assertNotIn("QUERY SHOULD STAY PRIVATE", rendered)
            self.assertNotIn("Some plausible answer.", rendered)


if __name__ == "__main__":
    unittest.main()
