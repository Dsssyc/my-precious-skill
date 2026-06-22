import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("templates/agent-memory-repo/tools/shadow_eval_memory_archive.py").resolve()
AUDIT_SCRIPT = Path("templates/agent-memory-repo/tools/audit_memory_archive.py").resolve()
SYNTHETIC_ARCHIVE_BUILDER = Path("benchmarks/build_synthetic_recall_archive.py").resolve()
SYNTHETIC_CASES = Path("benchmarks/cases/layered_recall_synthetic.jsonl").resolve()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_minimal_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True)
    (repo / "sessions/2026/06/21/redacted").mkdir(parents=True)
    (repo / "sessions/2026/06/21/redacted/summary.md").write_text(
        "# Session: Redacted fixture\n\n"
        "A public summary mentions shadow recall marker without private source text.\n",
        encoding="utf-8",
    )
    (repo / "sessions/2026/06/21/redacted/evidence.md").write_text(
        "# Evidence\n\n"
        "redacted_ev_001:\n"
        "SECRET_SOURCE_SNIPPET must not appear in shadow eval output.\n",
        encoding="utf-8",
    )
    records = [
            {
                "memory_id": "mem_shadow_current",
                "layer": "global",
                "scope": "global",
                "topic": "shadow-eval",
                "text": "Shadow recall marker should retrieve the current memory. "
                "Shadow recall marker current target.",
                "source": "automatic",
                "confidence": "high",
                "support_count": 1,
                "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
                "evidence_refs": [
                    {
                        "path": "sessions/2026/06/21/redacted/evidence.md",
                        "quote_id": "redacted_ev_001",
                    }
                ],
                "raw_refs": [
                    {
                        "path": "records/private.jsonl",
                        "anchor": "SECRET_RAW_ANCHOR",
                    }
                ],
                "supersedes": ["mem_shadow_old"],
                "superseded_by": None,
            },
            {
                "memory_id": "mem_shadow_noise",
                "layer": "global",
                "scope": "global",
                "topic": "shadow-eval",
                "text": "Shadow recall marker has a plausible but non-target neighbor.",
                "source": "automatic",
                "confidence": "high",
                "support_count": 1,
                "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
                "evidence_refs": [],
                "raw_refs": [],
            },
            {
                "memory_id": "mem_shadow_old",
                "layer": "global",
                "scope": "global",
                "topic": "shadow-eval",
                "text": "Shadow recall marker should not return the retired memory.",
                "source": "automatic",
                "confidence": "low",
                "support_count": 1,
                "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
                "evidence_refs": [],
                "raw_refs": [],
                "supersedes": [],
                "superseded_by": "mem_shadow_current",
            },
            {
                "memory_id": "mem_shadow_deprecated",
                "layer": "global",
                "scope": "global",
                "topic": "shadow-eval",
                "text": "Deprecated shadow marker should be inactive.",
                "source": "automatic",
                "confidence": "low",
                "support_count": 1,
                "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
                "evidence_refs": [],
                "raw_refs": [],
                "deprecates": [],
                "deprecated_by": "mem_shadow_delete_marker",
            },
            {
                "memory_id": "mem_shadow_delete_marker",
                "layer": "global",
                "scope": "global",
                "topic": "shadow-eval",
                "text": "Deprecated fact: Deprecated shadow marker should be inactive.",
                "source": "automatic",
                "confidence": "high",
                "support_count": 1,
                "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
                "evidence_refs": [
                    {
                        "path": "sessions/2026/06/21/redacted/evidence.md",
                        "quote_id": "redacted_ev_001",
                    }
                ],
                "raw_refs": [],
                "deprecates": ["mem_shadow_deprecated"],
                "deprecated_by": None,
            },
    ]
    for record in records:
        record.setdefault("rationale", "Synthetic redacted fixture for shadow evaluation.")
        record.setdefault("persistence", "normal")
        record.setdefault("first_seen", "2026-06-21")
        record.setdefault("last_seen", "2026-06-21")
        record.setdefault("supersedes", [])
        record.setdefault("superseded_by", None)
        if not record.get("evidence_refs"):
            record["evidence_refs"] = [
                {
                    "path": "sessions/2026/06/21/redacted/evidence.md",
                    "quote_id": "redacted_ev_001",
                }
            ]
        record.setdefault("raw_refs", [])
        record.setdefault("tags", ["shadow-eval", "redacted-fixture"])
    write_jsonl(repo / "index/memories.jsonl", records)


def write_legacy_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True)
    (repo / "sessions/2026/06/21/legacy").mkdir(parents=True)
    (repo / "sessions/2026/06/21/legacy/summary.md").write_text(
        "# Session: Legacy shadow fixture\n\n"
        "Legacy archive summary stays private in aggregate shadow reports.\n",
        encoding="utf-8",
    )
    write_jsonl(
        repo / "index/sessions.jsonl",
        [
            {
                "date": "2026-06-21",
                "project": "legacy-project",
                "title": "Legacy shadow fixture",
                "summary": "Legacy archive summary stays private.",
                "summary_path": "sessions/2026/06/21/legacy/summary.md",
            }
        ],
    )


def memory_record(memory_id: str, layer: str, text: str, *, topic: str = "multi-relevant") -> dict:
    return {
        "memory_id": memory_id,
        "layer": layer,
        "scope": layer if layer != "project" else "project:synthetic",
        "topic": topic,
        "text": text,
        "source": "automatic",
        "confidence": "high",
        "support_count": 1,
        "derived_from": ["sessions/2026/06/21/redacted/summary.md"],
        "evidence_refs": [
            {
                "path": "sessions/2026/06/21/redacted/evidence.md",
                "quote_id": "redacted_ev_001",
            }
        ],
        "raw_refs": [],
        "first_seen": "2026-06-21",
        "last_seen": "2026-06-21",
        "supersedes": [],
        "superseded_by": None,
    }


def write_multi_relevant_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True)
    (repo / "sessions/2026/06/21/redacted").mkdir(parents=True)
    (repo / "sessions/2026/06/21/redacted/summary.md").write_text(
        "# Session: Multi relevant fixture\n\n"
        "Synthetic public summary for multi relevant shadow evaluation.\n",
        encoding="utf-8",
    )
    (repo / "sessions/2026/06/21/redacted/evidence.md").write_text(
        "# Evidence\n\nredacted_ev_001:\nSynthetic public evidence.\n",
        encoding="utf-8",
    )
    write_jsonl(
        repo / "index/memories.jsonl",
        [
            memory_record(
                "mem_multi_primary",
                "domain",
                "multi relevant marker primary durable fact",
            ),
            memory_record(
                "mem_multi_secondary",
                "domain",
                "multi relevant marker secondary durable fact",
            ),
            memory_record(
                "mem_multi_broad_noise_a",
                "domain",
                "multi relevant marker broad lexical domain neighbor alpha",
            ),
            memory_record(
                "mem_multi_broad_noise_b",
                "domain",
                "multi relevant marker broad lexical domain neighbor beta",
            ),
            memory_record(
                "mem_multi_broad_noise_c",
                "domain",
                "multi relevant marker broad lexical domain neighbor gamma",
            ),
            memory_record(
                "mem_multi_scope_noise_a",
                "project",
                "multi relevant marker multi relevant marker wrong project scope neighbor alpha",
            ),
            memory_record(
                "mem_multi_scope_noise_b",
                "project",
                "multi relevant marker multi relevant marker wrong project scope neighbor beta",
            ),
        ],
    )


class ShadowEvalMemoryArchiveTests(unittest.TestCase):
    def test_shadow_eval_reports_legacy_archive_without_memory_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "legacy-agent-memory"
            write_legacy_archive(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["archive"]["format"], "legacy")
        self.assertEqual(payload["archive"]["memory_records"], 0)
        self.assertEqual(payload["archive"]["legacy_session_records"], 1)
        self.assertEqual(payload["probe_cases"]["cases"], 0)
        self.assertIsNone(payload["metrics"]["memory_precision_at_5"])
        self.assertFalse(payload["privacy"]["source_content_rendered"])
        self.assertNotIn("Legacy archive summary", result.stdout)

    def test_shadow_eval_runs_on_packaged_synthetic_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                    "--include-superseded-distractors",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                    "--audit-script",
                    str(AUDIT_SCRIPT),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["report_version"], 1)
        self.assertEqual(payload["probe_cases"]["cases"], 44)
        self.assertEqual(payload["metrics"]["memory_recall_at_5"], 1.0)
        self.assertIn("memory_precision_at_5", payload["metrics"])
        self.assertIn("top_k_noise_at_5", payload["metrics"])
        self.assertIn("noise_sources_at_5", payload["metrics"])
        self.assertIn("provenance_coverage", payload["metrics"])
        self.assertIn("lifecycle_integrity", payload["metrics"])
        self.assertEqual(payload["audit"]["status"], "passed")
        self.assertFalse(payload["privacy"]["source_content_rendered"])

    def test_shadow_eval_accepts_direct_and_file_quality_gates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            fail_under_file = Path(tmpdir) / "fail-under.json"
            fail_over_file = Path(tmpdir) / "fail-over.json"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:gate_pass",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                    }
                ],
            )
            fail_under_file.write_text(
                json.dumps({"metrics.provenance_coverage.score": 1.0}, sort_keys=True),
                encoding="utf-8",
            )
            fail_over_file.write_text(
                json.dumps({"metrics.forbidden_output_violations": 0}, sort_keys=True),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--audit-script",
                    str(AUDIT_SCRIPT),
                    "--fail-under",
                    "memory_recall_at_5=1.0",
                    "--fail-under-file",
                    str(fail_under_file),
                    "--fail-over",
                    "top_k_noise_at_5=1.0",
                    "--fail-over-file",
                    str(fail_over_file),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["metrics"]["memory_recall_at_5"], 1.0)
        self.assertEqual(payload["metrics"]["provenance_coverage"]["score"], 1.0)
        self.assertEqual(result.stderr, "")

    def test_shadow_eval_threshold_failure_outputs_only_safe_metric_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:SECRET_CASE_SHOULD_NOT_RENDER",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                        "forbidden_output_patterns": [
                            "SECRET_SOURCE_SNIPPET",
                            "SECRET_RAW_ANCHOR",
                        ],
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--audit-script",
                    str(AUDIT_SCRIPT),
                    "--fail-under",
                    "memory_recall_at_5=1.1",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("shadow eval threshold failed:", result.stderr)
        self.assertIn("memory_recall_at_5=1.0 below threshold 1.1", result.stderr)
        self.assertNotIn("SECRET_CASE_SHOULD_NOT_RENDER", combined)
        self.assertNotIn("shadow recall marker", combined)
        self.assertNotIn("mem_shadow_current", combined)
        self.assertNotIn("SECRET_SOURCE_SNIPPET", combined)
        self.assertNotIn("SECRET_RAW_ANCHOR", combined)

    def test_shadow_eval_sanitizes_invalid_threshold_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:invalid_threshold",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--fail-under",
                    "memory_recall_at_5=cookie=SHOULD_NOT_RENDER",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "--fail-under threshold must be numeric for memory_recall_at_5: [unsafe-field]",
            result.stderr,
        )
        self.assertNotIn("cookie=", result.stderr)

    def test_shadow_eval_report_is_aggregate_and_privacy_safe_for_redacted_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:shadow_current",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                        "expected_not_memory_id": [
                            "mem_shadow_old",
                            "mem_shadow_deprecated",
                            "mem_shadow_delete_marker",
                        ],
                        "forbidden_output_patterns": [
                            "SECRET_SOURCE_SNIPPET",
                            "SECRET_RAW_ANCHOR",
                        ],
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--audit-script",
                    str(AUDIT_SCRIPT),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        combined = result.stdout + result.stderr
        self.assertNotIn("SECRET_SOURCE_SNIPPET", combined)
        self.assertNotIn("SECRET_RAW_ANCHOR", combined)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["probe_cases"]["cases"], 1)
        self.assertEqual(payload["metrics"]["memory_recall_at_5"], 1.0)
        self.assertLess(payload["metrics"]["memory_precision_at_5"], 1.0)
        self.assertGreater(payload["metrics"]["top_k_noise_at_5"], 0.0)
        self.assertGreater(payload["metrics"]["noise_sources_at_5"]["broad_lexical_match"], 0)
        self.assertIn("scope_mixed", payload["metrics"]["noise_sources_at_5"])
        self.assertIn("inactive_lifecycle", payload["metrics"]["noise_sources_at_5"])
        self.assertIn("low_signal_memory_node", payload["metrics"]["noise_sources_at_5"])
        self.assertEqual(payload["metrics"]["active_memory_suppression"], 1.0)
        self.assertEqual(payload["metrics"]["lifecycle_integrity"]["score"], 1.0)
        self.assertGreater(payload["metrics"]["provenance_coverage"]["score"], 0.0)
        self.assertEqual(payload["audit"]["status"], "passed")
        self.assertFalse(payload["privacy"]["source_content_rendered"])

    def test_shadow_eval_keeps_legacy_single_expected_memory_id_compatible_with_case_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            audit_script = Path(tmpdir) / "audit_with_forbidden_output.py"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:single_current",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                        "forbidden_output_patterns": ["SECRET_AUDIT_STDOUT", "SECRET_AUDIT_STDERR"],
                    }
                ],
            )
            audit_script.write_text(
                "import sys\n"
                "print('SECRET_AUDIT_STDOUT')\n"
                "print('SECRET_AUDIT_STDERR', file=sys.stderr)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--audit-script",
                    str(audit_script),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        combined = result.stdout + result.stderr
        self.assertNotIn("SECRET_AUDIT_STDOUT", combined)
        self.assertNotIn("SECRET_AUDIT_STDERR", combined)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["metrics"]["memory_recall_at_5"], 1.0)
        self.assertEqual(payload["metrics"]["forbidden_output_violations"], 1)
        self.assertEqual(payload["metrics"]["privacy_boundary_pass_rate"], 0.0)
        detail = payload["case_details"][0]
        self.assertEqual(detail["case_id"], "redacted:single_current")
        self.assertEqual(detail["expected_memory_count"], 1)
        self.assertEqual(detail["relevant_result_count"], 1)
        self.assertEqual(detail["forbidden_output_violation_count"], 2)

    def test_shadow_eval_scores_abstain_cases_and_gates_false_positive_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:abstain_clean",
                        "query": "zzqabstain918273",
                        "expected_abstain": True,
                    },
                    {
                        "case_id": "redacted:abstain_false_positive",
                        "query": "shadow recall marker",
                        "expected_abstain": True,
                    },
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
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
            gate_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--fail-under",
                    "abstain_pass_rate=1.0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["probe_cases"]["abstain_cases"], 2)
        self.assertEqual(payload["metrics"]["abstain_pass_rate"], 0.5)
        self.assertGreater(payload["metrics"]["abstain_false_positive_results"], 0)
        clean_detail, noisy_detail = payload["case_details"]
        self.assertTrue(clean_detail["abstention_hit"])
        self.assertFalse(noisy_detail["abstention_hit"])

        combined = gate_result.stdout + gate_result.stderr
        self.assertNotEqual(gate_result.returncode, 0)
        self.assertEqual(gate_result.stdout, "")
        self.assertIn("abstain_pass_rate=0.5 below threshold 1.0", gate_result.stderr)
        self.assertNotIn("shadow recall marker", combined)
        self.assertNotIn("mem_shadow_current", combined)

    def test_shadow_eval_uses_expected_layer_as_soft_scope_preference_for_multi_relevant_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "multi-agent-memory"
            cases = Path(tmpdir) / "multi_cases.jsonl"
            write_multi_relevant_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:multi_relevant",
                        "query": "multi relevant marker",
                        "expected_memory_ids": [
                            "mem_multi_primary",
                            "mem_multi_secondary",
                        ],
                        "expected_layer": "domain",
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["probe_cases"]["positive_cases"], 1)
        self.assertEqual(payload["metrics"]["memory_recall_at_5"], 1.0)
        self.assertEqual(payload["metrics"]["memory_precision_at_5"], 0.4)
        self.assertEqual(payload["metrics"]["top_k_noise_at_5"], 0.6)
        self.assertEqual(payload["metrics"]["noise_sources_at_5"]["broad_lexical_match"], 3)
        self.assertEqual(payload["metrics"]["noise_sources_at_5"]["scope_mixed"], 0)
        detail = payload["case_details"][0]
        self.assertEqual(detail["case_id"], "redacted:multi_relevant")
        self.assertEqual(detail["expected_memory_count"], 2)
        self.assertEqual(detail["result_count"], 5)
        self.assertEqual(detail["relevant_result_count"], 2)
        self.assertEqual(detail["noise_result_count"], 3)
        self.assertTrue(detail["recall_hit"])
        self.assertEqual(detail["noise_sources_at_5"]["broad_lexical_match"], 3)
        self.assertEqual(detail["noise_sources_at_5"]["scope_mixed"], 0)
        serialized = json.dumps(payload)
        self.assertNotIn("mem_multi_primary", serialized)
        self.assertNotIn("mem_multi_secondary", serialized)
        self.assertNotIn("sessions/2026/06/21/redacted", serialized)

    def test_shadow_eval_rejects_invalid_forbidden_output_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "redacted-agent-memory"
            cases = Path(tmpdir) / "redacted_cases.jsonl"
            write_minimal_archive(repo)
            write_jsonl(
                cases,
                [
                    {
                        "case_id": "redacted:invalid_pattern",
                        "query": "shadow recall marker",
                        "expected_memory_id": "mem_shadow_current",
                        "forbidden_output_patterns": ["["],
                    }
                ],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid forbidden_output_patterns[0]", result.stderr)
        self.assertNotIn("mem_shadow_current", result.stderr)
