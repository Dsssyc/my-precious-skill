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
                "query": "zzqmissing qxfactoid kzunseen",
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
            self.assertEqual(report["answer_handoff_supported_case_count"], 1)
            self.assertEqual(report["answer_handoff_abstain_case_count"], 1)
            self.assertEqual(report["answer_handoff_support_coverage_rate"], 1.0)
            self.assertEqual(report["answerability_policy"], "context_package_answerability")
            self.assertEqual(report["context_package_report_kind"], "memory_recall_context_package")
            self.assertEqual(report["context_package_parse_success_count"], 2)
            self.assertEqual(report["context_package_parse_failure_count"], 0)
            self.assertEqual(report["context_package_supported_case_count"], 1)
            self.assertEqual(report["context_package_abstain_case_count"], 1)
            self.assertEqual(report["context_package_support_coverage_rate"], 1.0)
            self.assertEqual(report["context_package_abstention_accuracy"], 1.0)
            self.assertEqual(report["context_package_inactive_rejection_count"], 0)
            self.assertEqual(report["unsupported_claim_count"], 0)
            self.assertEqual(report["inactive_memory_answer_count"], 0)
            self.assertEqual(report["privacy_leak_count"], 0)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["generated_answers_rendered"])

            answer_rows = [json.loads(line) for line in answers.read_text(encoding="utf-8").splitlines()]
            supported_handoff = answer_rows[0]["answer_handoff"]
            self.assertFalse(supported_handoff["abstained"])
            self.assertTrue(supported_handoff["active_memory_only"])
            self.assertEqual(supported_handoff["unsupported_claim_count"], 0)
            self.assertEqual(supported_handoff["inactive_memory_answer_count"], 0)
            self.assertEqual(supported_handoff["privacy_leak_count"], 0)
            self.assertEqual(
                supported_handoff["context_package"],
                {
                    "answerability_reason": "active_current_memory_support",
                    "answerability_status": "supported",
                    "parse_success": True,
                    "report_kind": "memory_recall_context_package",
                },
            )
            self.assertEqual(supported_handoff["support_refs"][0]["memory_id"], "answer_adapter_source_depth")
            self.assertEqual(
                supported_handoff["support_refs"][0]["summary_paths"],
                ["sessions/synthetic/answer-adapter/source-depth/summary.md"],
            )
            self.assertEqual(
                supported_handoff["support_refs"][0]["evidence_refs"],
                ["sessions/synthetic/answer-adapter/source-depth/evidence.md#syn_ev_001"],
            )

            abstain_handoff = answer_rows[1]["answer_handoff"]
            self.assertTrue(abstain_handoff["abstained"])
            self.assertEqual(abstain_handoff["abstain_reason"], "no_supported_memory_hit")
            self.assertEqual(abstain_handoff["support_refs"], [])
            self.assertEqual(abstain_handoff["context_package"]["answerability_status"], "unsupported")
            self.assertEqual(abstain_handoff["context_package"]["answerability_reason"], "no_recall_hits")

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
            self.assertEqual(payload["answer_handoff_present_rate"], 1.0)
            self.assertEqual(payload["answer_handoff_support_coverage_rate"], 1.0)
            self.assertEqual(payload["answer_handoff_supported_case_count"], 1)
            self.assertEqual(payload["answer_handoff_abstain_case_count"], 1)
            self.assertEqual(payload["unsupported_claim_count"], 0)
            self.assertEqual(payload["inactive_memory_answer_count"], 0)
            self.assertEqual(payload["source_benchmarks"], {"MyPreciousAnswerAdapterSynthetic": 2})
            self.assertEqual(payload["case_origins"], {"extractive_answer_adapter_fixture": 2})

    def test_abstains_when_only_inactive_lifecycle_memory_matches(self):
        rows = [
            {
                "case_id": "answer-adapter:inactive-only",
                "query": "What is the inactive-only handoff answer?",
                "category": "generated_answer_abstain",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": "not enough information",
                "expected_abstain": True,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            (repo / "index").mkdir(parents=True)
            (repo / "sessions").mkdir(parents=True)
            cases = root / "answer_cases.jsonl"
            answers = root / "answers.jsonl"
            self.write_jsonl(cases, rows)
            self.write_jsonl(
                repo / "index" / "memories.jsonl",
                [
                    {
                        "memory_id": "inactive_only_old",
                        "layer": "project",
                        "scope": "synthetic",
                        "topic": "answer-handoff",
                        "text": (
                            "Reference answer: SHOULD NOT USE. What is the inactive-only "
                            "handoff answer? What is the inactive-only handoff answer?"
                        ),
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "first_seen": "2026-06-01",
                        "last_seen": "2026-06-01",
                        "derived_from": ["sessions/synthetic/inactive-only/summary.md"],
                        "evidence_refs": [
                            {
                                "path": "sessions/synthetic/inactive-only/evidence.md",
                                "quote_id": "syn_ev_001",
                            }
                        ],
                        "superseded_by": "inactive_only_current",
                    },
                    {
                        "memory_id": "inactive_only_current",
                        "layer": "project",
                        "scope": "synthetic",
                        "topic": "answer-handoff",
                        "text": "Current replacement deliberately lacks the queried inactive answer.",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "first_seen": "2026-06-02",
                        "last_seen": "2026-06-02",
                        "derived_from": [],
                        "evidence_refs": [],
                        "supersedes": ["inactive_only_old"],
                    },
                ],
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
            self.assertEqual(report["memory_answer_count"], 0)
            self.assertEqual(report["abstention_answer_count"], 1)
            self.assertEqual(report["inactive_memory_answer_count"], 0)
            self.assertEqual(report["context_package_parse_success_count"], 1)
            self.assertEqual(report["context_package_supported_case_count"], 0)
            self.assertEqual(report["context_package_abstain_case_count"], 1)
            self.assertEqual(report["context_package_inactive_rejection_count"], 1)
            answer_row = json.loads(answers.read_text(encoding="utf-8"))
            self.assertEqual(answer_row["generated_answer"], "There is not enough information in memory to answer.")
            self.assertTrue(answer_row["answer_handoff"]["abstained"])
            self.assertEqual(answer_row["answer_handoff"]["abstain_reason"], "no_active_current_support")
            self.assertEqual(answer_row["answer_handoff"]["support_refs"], [])
            self.assertEqual(
                answer_row["answer_handoff"]["context_package"]["answerability_reason"],
                "no_active_current_support",
            )

    def test_context_package_parse_failure_fails_closed_to_abstain(self):
        rows = [
            {
                "case_id": "answer-adapter:malformed-context-package",
                "query": "What should malformed context packages do?",
                "category": "generated_answer_abstain",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": "not enough information",
                "expected_abstain": True,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            (repo / "index").mkdir(parents=True)
            (repo / "sessions").mkdir(parents=True)
            cases = root / "answer_cases.jsonl"
            answers = root / "answers.jsonl"
            stub_search = root / "malformed_search.py"
            self.write_jsonl(cases, rows)
            stub_search.write_text(
                "#!/usr/bin/env python3\n"
                "print('{\"report_kind\":\"wrong_package\",\"answerability\":{\"status\":\"supported\"}}')\n",
                encoding="utf-8",
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
                    "--search-script",
                    str(stub_search),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(adapter.returncode, 0, adapter.stderr)
            report = json.loads(adapter.stdout)
            self.assertEqual(report["context_package_parse_success_count"], 0)
            self.assertEqual(report["context_package_parse_failure_count"], 1)
            self.assertEqual(report["context_package_supported_case_count"], 0)
            self.assertEqual(report["context_package_abstain_case_count"], 1)
            self.assertEqual(report["context_package_abstention_accuracy"], 1.0)
            answer_row = json.loads(answers.read_text(encoding="utf-8"))
            self.assertEqual(answer_row["generated_answer"], "There is not enough information in memory to answer.")
            self.assertTrue(answer_row["answer_handoff"]["abstained"])
            self.assertEqual(answer_row["answer_handoff"]["abstain_reason"], "context_package_unavailable")
            self.assertEqual(
                answer_row["answer_handoff"]["context_package"],
                {
                    "answerability_reason": "parse_failed",
                    "answerability_status": "unsupported",
                    "parse_success": False,
                    "report_kind": "memory_recall_context_package",
                },
            )

            rendered = adapter.stdout + adapter.stderr
            self.assertNotIn(rows[0]["query"], rendered)
            self.assertNotIn(str(repo), rendered)
            self.assertNotIn(str(cases), rendered)
            self.assertNotIn(str(answers), rendered)

    def test_abstains_when_top_hit_lacks_query_support(self):
        answer_text = "Use source anchors for provenance without printing raw transcript content"
        rows = [
            {
                "case_id": "answer-adapter:supported-source-depth",
                "query": "What should source-depth answers say about raw transcript content?",
                "category": "generated_answer_positive",
                "source_benchmark": "MyPreciousAnswerAdapterSynthetic",
                "case_origin": "extractive_answer_adapter_fixture",
                "reference_answer": answer_text,
                "expected_memory_id": "answer_adapter_supported_source_depth",
                "expected_summary_path": "sessions/synthetic/answer-adapter/supported-source-depth/summary.md",
                "expected_source_anchor": "records/synthetic-answer-adapter.jsonl#message:4",
                "required_evidence_paths": [
                    "sessions/synthetic/answer-adapter/supported-source-depth/evidence.md"
                ],
            },
            {
                "case_id": "answer-adapter:unsupported-overlap",
                "query": "What should source-depth answers say about deployment passwords?",
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
            self.assertEqual(report["memory_answer_count"], 1)
            self.assertEqual(report["abstention_answer_count"], 1)
            self.assertEqual(report["unsupported_hit_count"], 1)
            self.assertEqual(report["answerability_policy"], "context_package_answerability")

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
                    "failed_case_count=0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(benchmark.returncode, 0, benchmark.stderr)

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
