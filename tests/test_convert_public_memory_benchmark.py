import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/convert_public_memory_benchmark.py").resolve()
BENCHMARK_SCRIPT = Path("benchmarks/layered_recall_benchmark.py").resolve()
SEARCH_SCRIPT = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()


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

            result = subprocess.run(
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
            self.assertEqual(rows[0]["case_id"], "longmemeval:lme_q1")
            self.assertEqual(rows[0]["source_benchmark"], "LongMemEval")
            self.assertEqual(rows[0]["category"], "multi_session_reasoning")
            self.assertEqual(rows[0]["expected_memory_id"], "external_longmemeval_lme_q1")
            self.assertEqual(rows[0]["expected_summary_path"], "sessions/external/longmemeval/lme_q1/summary.md")
            self.assertEqual(rows[0]["expected_source_anchor"], "records/external/longmemeval.json#question_id:lme_q1")
            self.assertEqual(rows[0]["reference_answer"], "The memory skill project.")
            self.assertEqual(rows[0]["question_date"], "2026-06-19")
            self.assertEqual(rows[1]["case_id"], "longmemeval:lme_q2_abs")
            self.assertEqual(rows[1]["category"], "abstention")
            self.assertTrue(rows[1]["expected_abstain"])
            self.assertNotIn("expected_memory_id", rows[1])
            result_payload = json.loads(result.stdout)
            self.assertEqual(result_payload["input_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(result_payload["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_rejects_duplicate_case_ids_after_conversion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "LME Q1",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                        },
                        {
                            "question_id": "lme_q1",
                            "question": "Which project adopted source drilldown?",
                            "answer": "The memory skill project.",
                        },
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate case_id", result.stderr)
            self.assertIn("longmemeval:lme_q1", result.stderr)
            self.assertIn("converted case 2", result.stderr)
            self.assertIn("first seen in converted case 1", result.stderr)
            self.assertFalse(output.exists())

    def test_duplicate_case_id_error_sanitizes_sensitive_converted_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "cookie=SHOULD_NOT_RENDER",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                        },
                        {
                            "question_id": "cookie SHOULD_NOT_RENDER",
                            "question": "Which project adopted source drilldown?",
                            "answer": "The memory skill project.",
                        },
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate case_id", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("should_not_render", combined)
            self.assertFalse(output.exists())

    def test_duplicate_case_id_error_keeps_safe_public_benchmark_ids(self):
        for display_text, slug in (
            ("API Reference", "api_reference"),
            ("Private Archive", "private_archive"),
            ("Session Boundary", "session_boundary"),
        ):
            with self.subTest(display_text=display_text):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    source = root / "longmemeval.json"
                    output = root / "cases.jsonl"
                    source.write_text(
                        json.dumps(
                            [
                                {
                                    "question_id": display_text,
                                    "question": "Which project adopted layered recall?",
                                    "answer": "The memory skill project.",
                                },
                                {
                                    "question_id": slug,
                                    "question": "Which project adopted source drilldown?",
                                    "answer": "The memory skill project.",
                                },
                            ],
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )

                    result = subprocess.run(
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
                        check=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("duplicate case_id", result.stderr)
                    self.assertIn(f"longmemeval:{slug}", result.stderr)
                    self.assertNotIn("[unsafe-path]", result.stderr)
                    self.assertFalse(output.exists())

    def test_rejects_empty_converted_case_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            output = root / "cases.jsonl"
            source.write_text("[]", encoding="utf-8")

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("converted case set is empty", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_limit_that_removes_all_converted_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            output = root / "cases.jsonl"
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "lme_q1",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                        }
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "longmemeval",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--limit",
                    "0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("converted case set is empty", result.stderr)
            self.assertFalse(output.exists())

    def test_missing_input_file_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sensitive_input_root = root / "inputs-cookie=SHOULD_NOT_RENDER"
            missing_input = sensitive_input_root / "missing.json"
            output = root / "cases.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "longmemeval",
                    "--input",
                    str(missing_input),
                    "--output",
                    str(output),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read input benchmark file", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)
            self.assertFalse(output.exists())

    def test_output_write_error_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            sensitive_output = root / "outputs-cookie=SHOULD_NOT_RENDER"
            sensitive_output.mkdir()
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "lme_q1",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                        }
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "longmemeval",
                    "--input",
                    str(source),
                    "--output",
                    str(sensitive_output),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to write output benchmark file", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_success_payload_sanitizes_sensitive_output_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "longmemeval.json"
            sensitive_output_root = root / "outputs-cookie=SHOULD_NOT_RENDER"
            output = sensitive_output_root / "cases.jsonl"
            archive = sensitive_output_root / "archive"
            source.write_text(
                json.dumps(
                    [
                        {
                            "question_id": "lme_q1",
                            "question": "Which project adopted layered recall?",
                            "answer": "The memory skill project.",
                        }
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source",
                    "longmemeval",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--build-synthetic-archive",
                    str(archive),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["output"], "[unsafe-path]")
            self.assertEqual(payload["synthetic_archive"], "[unsafe-path]")
            self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
            self.assertNotIn("cookie=", result.stdout)
            self.assertTrue(output.exists())
            self.assertTrue((archive / "index" / "memories.jsonl").exists())

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
            self.assertEqual(rows[0]["case_id"], "locomo:conv-a_qa-1")
            self.assertEqual(rows[0]["source_benchmark"], "LoCoMo")
            self.assertEqual(rows[0]["category"], "temporal_reasoning")
            self.assertEqual(rows[0]["expected_memory_id"], "external_locomo_conv-a_qa-1")
            self.assertEqual(rows[0]["expected_source_anchor"], "records/external/locomo.json#sample:conv-A:qa:1")
            self.assertEqual(rows[0]["reference_evidence"], ["session-1", "session-2"])

    def test_rejects_non_string_locomo_evidence_items(self):
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
                                    "evidence": ["session-1", 42],
                                }
                            ],
                        }
                    ],
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("LoCoMo sample 1 qa 1 evidence[1] must be a non-empty string", result.stderr)
            self.assertFalse(output.exists())

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
            self.assertEqual(rows[0]["case_id"], "memora:mem_q1")
            self.assertEqual(rows[0]["source_benchmark"], "Memora")
            self.assertEqual(rows[0]["category"], "information_extraction")
            self.assertEqual(rows[0]["expected_memory_id"], "external_memora_mem_q1")
            self.assertEqual(rows[0]["stale_memory_id"], "external_memora_mem_q1_stale")
            self.assertEqual(rows[0]["expected_not_memory_id"], "external_memora_mem_q1_stale")
            self.assertEqual(rows[0]["temporal_scope"], "latest")
            self.assertEqual(rows[0]["evaluation_types"], ["memory_presence", "forgetting_absence"])

    def test_rejects_non_object_memora_question_rows(self):
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
                                },
                                "not-a-question-object",
                            ]
                        }
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Memora task Remembering item 2 is not an object", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_non_object_memora_evaluation_rows(self):
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
                                    "evaluation": {
                                        "evaluation_questions": [
                                            {"evaluation_type": "memory_presence"},
                                            "not-an-evaluation-object",
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

            result = subprocess.run(
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
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Memora evaluation question item 2 is not an object", result.stderr)
            self.assertFalse(output.exists())

    def test_can_build_synthetic_archive_and_score_converted_public_cases(self):
        cases = [
            (
                "longmemeval",
                [
                    {
                        "question_id": "lme_public_e2e",
                        "question_type": "multi-session",
                        "question": "Which recall mode should the public benchmark adapter verify?",
                        "answer": "Layered recall with source drilldown.",
                        "question_date": "2026-06-19",
                    }
                ],
                {},
            ),
            (
                "locomo",
                [
                    {
                        "sample_id": "conv-public-e2e",
                        "qa": [
                            {
                                "question": "Which detail changed after the second conversation?",
                                "answer": "The evaluation target moved to normalized answer reachability.",
                                "category": "temporal",
                                "evidence": ["conversation-1", "conversation-2"],
                            }
                        ],
                    }
                ],
                {
                    "evidence_text_cases": 1,
                    "evidence_text_reachability": 1.0,
                },
            ),
            (
                "memora",
                {
                    "questions": {
                        "Remembering": [
                            {
                                "question_id": "mem_public_e2e",
                                "question": "Which current memory should replace the stale scoring rule?",
                                "answer": "Use answer-token F1 alongside exact reachability.",
                                "question_date": "2026-06-19",
                                "evaluation": {
                                    "evaluation_questions": [
                                        {"evaluation_type": "memory_presence"},
                                        {"evaluation_type": "forgetting_absence"},
                                    ]
                                },
                            }
                        ]
                    }
                },
                {"stale_memory_suppression": 1.0},
            ),
        ]

        for source_name, payload, extra_thresholds in cases:
            with self.subTest(source=source_name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                source = root / f"{source_name}.json"
                output = root / "cases.jsonl"
                archive = root / "archive"
                details = root / "details.jsonl"
                source.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

                convert = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        "--source",
                        source_name,
                        "--input",
                        str(source),
                        "--output",
                        str(output),
                        "--build-synthetic-archive",
                        str(archive),
                        "--include-superseded-distractors",
                    ],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                convert_payload = json.loads(convert.stdout)

                self.assertEqual(convert_payload["cases"], 1)
                self.assertEqual(convert_payload["synthetic_archive"], str(archive.resolve()))
                self.assertTrue((archive / "index" / "memories.jsonl").exists())

                thresholds = {
                    "memory_recall_at_1": 1.0,
                    "memory_recall_at_5": 1.0,
                    "session_drilldown_at_5": 1.0,
                    "source_reachability": 1.0,
                    "evidence_reachability": 1.0,
                    "answer_normalized_reachability": 1.0,
                    "answer_token_f1": 1.0,
                }
                thresholds.update(extra_thresholds)
                command = [
                    sys.executable,
                    str(BENCHMARK_SCRIPT),
                    "--repo",
                    str(archive),
                    "--cases",
                    str(output),
                    "--search-script",
                    str(SEARCH_SCRIPT),
                    "--details-jsonl",
                    str(details),
                ]
                for metric, value in thresholds.items():
                    command.extend(["--fail-under", f"{metric}={value}"])

                scored = subprocess.run(
                    command,
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                scored_payload = json.loads(scored.stdout)
                detail_rows = self.read_rows(details)

                self.assertEqual(scored_payload["cases"], 1)
                self.assertEqual(scored_payload["answer_token_f1"], 1.0)
                self.assertEqual(len(detail_rows), 1)
                self.assertTrue(detail_rows[0]["answer_normalized_reachability_hit"])
                if source_name == "locomo":
                    self.assertEqual(scored_payload["evidence_text_cases"], 1)
                    self.assertEqual(scored_payload["evidence_text_reachability"], 1.0)
                    self.assertEqual(detail_rows[0]["reference_evidence_count"], 2)
                    self.assertTrue(detail_rows[0]["evidence_text_reachability_hit"])

    def read_rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
