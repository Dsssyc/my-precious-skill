import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import benchmarks.private_generated_answer_dogfood_gate as dogfood_gate


SCRIPT = Path("benchmarks/private_generated_answer_dogfood_gate.py").resolve()


class PrivateGeneratedAnswerDogfoodGateTests(unittest.TestCase):
    def init_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        (repo / "INDEX.md").write_text("# Synthetic memory archive\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".tmp/\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "INDEX.md", ".gitignore"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "commit", "-m", "init synthetic archive"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_preflight_passes_for_clean_memory_repo_without_rendering_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--memory-repo", str(repo), "--preflight-only"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "private_generated_answer_dogfood_gate")
            self.assertEqual(payload["status"], "preflight_passed")
            self.assertEqual(payload["dirty_private_artifact_count"], 0)
            self.assertFalse(payload["memory_repo_dirty"])
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["private_paths_rendered"])
            self.assertNotIn(str(repo), result.stdout + result.stderr)

    def test_preflight_rejects_dirty_eval_and_tmp_outputs_without_rendering_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)
            eval_file = repo / "eval" / "generated_answer_private_dogfood_cases.jsonl"
            tmp_file = repo / ".tmp" / "generated-answer-dogfood" / "cases.jsonl"
            eval_file.parent.mkdir(parents=True)
            tmp_file.parent.mkdir(parents=True)
            eval_file.write_text("{}\n", encoding="utf-8")
            tmp_file.write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--memory-repo", str(repo), "--preflight-only"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["dirty_eval_artifact_count"], 1)
            self.assertEqual(payload["dirty_tmp_artifact_count"], 1)
            self.assertEqual(payload["dirty_private_artifact_count"], 2)
            self.assertEqual(payload["failures"], [{"reason": "dirty_private_dogfood_artifacts"}])
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["private_paths_rendered"])

            rendered = result.stdout + result.stderr
            self.assertNotIn(str(repo), rendered)
            self.assertNotIn("generated_answer_private_dogfood_cases", rendered)
            self.assertNotIn("generated-answer-dogfood", rendered)

    def test_preflight_rejects_work_dir_that_would_delete_memory_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            self.init_repo(repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(repo),
                    "--work-dir",
                    str(repo),
                    "--preflight-only",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertIn({"reason": "unsafe_work_dir"}, payload["failures"])
            self.assertTrue((repo / "INDEX.md").exists())
            self.assertNotIn(str(repo), result.stdout + result.stderr)

    def test_preflight_rejects_generic_external_work_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            self.init_repo(repo)
            generic_work_dir = root / "tmp"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--memory-repo",
                    str(repo),
                    "--work-dir",
                    str(generic_work_dir),
                    "--preflight-only",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertIn({"reason": "unsafe_work_dir"}, payload["failures"])
            self.assertNotIn(str(generic_work_dir), result.stdout + result.stderr)

    def test_cleanup_preserves_unowned_files_in_dogfood_work_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            repo.mkdir()
            case_output = repo / ".tmp" / "generated-answer-dogfood" / "cases.jsonl"
            case_output.parent.mkdir(parents=True)
            case_output.write_text("{}\n", encoding="utf-8")

            work_dir = root / "my_precious_generated_answer_dogfood"
            work_dir.mkdir()
            answer_records = work_dir / "answer_records.jsonl"
            answer_report = work_dir / "answer_report.json"
            sentinel = work_dir / "not-owned-by-dogfood.txt"
            answer_records.write_text("{}\n", encoding="utf-8")
            answer_report.write_text("{}\n", encoding="utf-8")
            sentinel.write_text("keep me\n", encoding="utf-8")

            cleaned = dogfood_gate.cleanup_success_artifacts(
                repo,
                case_output,
                work_dir,
                generated_paths=(answer_records, answer_report),
            )

            self.assertTrue(cleaned)
            self.assertFalse(case_output.exists())
            self.assertFalse(answer_records.exists())
            self.assertFalse(answer_report.exists())
            self.assertTrue(sentinel.exists())

    def test_run_gate_propagates_handoff_metrics_to_aggregate_report_and_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            self.init_repo(repo)
            commands: list[tuple[str, list[str]]] = []

            def fake_capture(name: str, command: list[str]) -> dict:
                commands.append((name, command))
                if name == "case author dry-run":
                    return {
                        "selected_case_count": 2,
                        "positive_case_count": 1,
                        "abstain_case_count": 1,
                        "would_write_count": 2,
                    }
                if name == "case author write":
                    return {
                        "candidate_memory_count": 3,
                        "selected_case_count": 2,
                        "positive_case_count": 1,
                        "abstain_case_count": 1,
                        "written_count": 2,
                        "skip_counts": {"inactive_memory": 1},
                        "source_benchmarks": {"MyPreciousPrivateDogfood": 2},
                        "case_origins": {"private_dogfood": 2},
                    }
                if name == "case audit":
                    return {
                        "cases": 2,
                        "positive_cases": 1,
                        "abstain_cases": 1,
                        "answer_scorable_case_rate": 1.0,
                        "positive_without_reference_answer": 0,
                        "privacy_leak_count": 0,
                        "unsafe_aggregate_identifier_count": 0,
                        "source_benchmarks": {"MyPreciousPrivateDogfood": 2},
                        "case_origins": {"private_dogfood": 2},
                    }
                if name == "answer record adapter":
                    return {
                        "cases": 2,
                        "answers_written": 2,
                        "memory_answer_count": 1,
                        "abstention_answer_count": 1,
                        "answer_handoff_supported_case_count": 1,
                        "answer_handoff_abstain_case_count": 1,
                        "answer_handoff_support_coverage_rate": 1.0,
                        "unsupported_claim_count": 0,
                        "inactive_memory_answer_count": 0,
                        "privacy_leak_count": 0,
                        "no_hit_count": 1,
                        "unsupported_hit_count": 0,
                        "source_benchmarks": {"MyPreciousPrivateDogfood": 2},
                        "case_origins": {"private_dogfood": 2},
                    }
                if name == "v1 readiness gate":
                    return {
                        "overall_status": "extended_evidence_ready",
                        "scorecard": {"required_dimensions": 6, "required_passed": 6},
                        "dimensions": {
                            "generated_answer_eval": {"status": "passed"},
                            "real_archive_shadow_eval": {"status": "passed"},
                        },
                    }
                raise AssertionError(f"unexpected JSON capture step: {name}")

            def fake_to_file(name: str, command: list[str], output: Path) -> dict:
                commands.append((name, command))
                if name == "generated-answer benchmark":
                    payload = {
                        "report_kind": "generated_answer_benchmark",
                        "cases": 2,
                        "positive_cases": 1,
                        "abstain_cases": 1,
                        "case_pass_rate": 1.0,
                        "answer_scorable_case_rate": 1.0,
                        "abstention_accuracy": 1.0,
                        "answer_normalized_match_rate": 1.0,
                        "answer_handoff_present_rate": 1.0,
                        "answer_handoff_support_coverage_rate": 1.0,
                        "answer_handoff_supported_case_count": 1,
                        "answer_handoff_abstain_case_count": 1,
                        "unsupported_claim_count": 0,
                        "inactive_memory_answer_count": 0,
                        "privacy_leak_count": 0,
                        "failed_case_count": 0,
                        "missing_answer_count": 0,
                        "duplicate_answer_count": 0,
                        "unknown_answer_count": 0,
                        "positive_without_reference_answer": 0,
                        "source_benchmarks": {"MyPreciousPrivateDogfood": 2},
                        "case_origins": {"private_dogfood": 2},
                    }
                elif name == "shadow evaluation":
                    payload = {
                        "report_kind": "real_archive_shadow_evaluation",
                        "metrics": {
                            "memory_recall_at_5": 1.0,
                            "privacy_boundary_pass_rate": 1.0,
                        },
                    }
                else:
                    raise AssertionError(f"unexpected JSON file step: {name}")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
                return payload

            args = dogfood_gate.parse_args(
                [
                    "--memory-repo",
                    str(repo),
                    "--work-dir",
                    str(root / "my_precious_generated_answer_dogfood"),
                    "--limit",
                    "1",
                    "--abstain-limit",
                    "1",
                ]
            )
            with mock.patch.object(dogfood_gate, "run_json_capture", side_effect=fake_capture):
                with mock.patch.object(dogfood_gate, "run_json_to_file", side_effect=fake_to_file):
                    report, exit_code = dogfood_gate.run_gate(args)

            self.assertEqual(exit_code, 0)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["answer_benchmark"]["answer_handoff_present_rate"], 1.0)
            self.assertEqual(report["answer_benchmark"]["answer_handoff_support_coverage_rate"], 1.0)
            self.assertEqual(report["answer_benchmark"]["answer_handoff_supported_case_count"], 1)
            self.assertEqual(report["answer_benchmark"]["answer_handoff_abstain_case_count"], 1)
            self.assertEqual(report["answer_benchmark"]["unsupported_claim_count"], 0)
            self.assertEqual(report["answer_benchmark"]["inactive_memory_answer_count"], 0)
            self.assertEqual(report["answer_benchmark"]["privacy_leak_count"], 0)
            self.assertEqual(report["answer_benchmark"]["source_benchmarks"], {"MyPreciousPrivateDogfood": 2})
            self.assertEqual(report["answer_benchmark"]["case_origins"], {"private_dogfood": 2})
            self.assertTrue(report["cleanup_success"])
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["memory_ids_rendered"])
            self.assertFalse(report["privacy"]["source_paths_rendered"])
            self.assertFalse(report["privacy"]["raw_refs_rendered"])

            benchmark_command = next(command for name, command in commands if name == "generated-answer benchmark")
            readiness_command = next(command for name, command in commands if name == "v1 readiness gate")
            self.assertIn("answer_handoff_present_rate=1.0", benchmark_command)
            self.assertIn("answer_handoff_support_coverage_rate=1.0", benchmark_command)
            self.assertIn("answer_handoff_supported_case_count=1", benchmark_command)
            self.assertIn("answer_handoff_abstain_case_count=1", benchmark_command)
            self.assertIn("unsupported_claim_count=0", benchmark_command)
            self.assertIn("inactive_memory_answer_count=0", benchmark_command)
            self.assertIn("--require-answer-source-benchmark", readiness_command)
            self.assertIn("MyPreciousPrivateDogfood", readiness_command)
            self.assertIn("--require-answer-case-origin", readiness_command)
            self.assertIn("private_dogfood", readiness_command)


if __name__ == "__main__":
    unittest.main()
