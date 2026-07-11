import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/authorized_original_source_gate.py").resolve()


class AuthorizedOriginalSourceGateTests(unittest.TestCase):
    def test_gate_proves_exact_authorized_original_event_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--work-dir", tmpdir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)

        self.assertEqual(report["report_kind"], "authorized_original_source_gate")
        self.assertEqual(report["overall_status"], "pass")
        self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
        self.assertEqual(report["fixture"]["source_record_count"], 8)
        self.assertEqual(report["fixture"]["source_event_count"], 32)
        self.assertEqual(report["fixture"]["source_format"], "jsonl")
        self.assertTrue(report["fixture"]["source_records_external_to_archive"])
        self.assertEqual(
            report["command_contract"],
            {
                "search_report_kind": "memory_recall_context_package",
                "resolver_report_kind": "memory_source_preview_package",
                "search_depth": "source",
                "context_json": True,
                "exact_source_ref_only": True,
                "explicit_authorization_required": True,
                "free_form_search_used": False,
            },
        )

        required_cases = {
            "non_first_supporting_event",
            "cross_project_paraphrase_sources",
            "explicit_non_first_event",
            "current_and_superseded_sources",
            "authorized_exact_ref",
            "default_unauthorized",
            "unsupported_no_hit",
            "inactive_source_only",
            "wrong_source_ref",
            "root_escape",
            "symlink_escape",
            "source_hash_mismatch",
            "source_anchor_mismatch",
            "unsupported_source_format",
            "malformed_context_package",
            "legacy_source_map",
            "secret_redaction",
        }
        self.assertEqual(set(report["cases"]), required_cases)
        self.assertTrue(all(report["cases"].values()))

        metrics = report["metrics"]
        for name in (
            "source_context_package_parse_success_rate",
            "source_preview_package_parse_success_rate",
            "source_anchor_assignment_accuracy",
            "memory_evidence_quote_fidelity_rate",
            "authorized_original_event_resolution_rate",
            "default_source_content_block_rate",
            "unsupported_source_rejection_rate",
            "inactive_source_rejection_rate",
            "source_integrity_failure_block_rate",
            "legacy_source_map_fail_closed_rate",
            "source_preview_redaction_accuracy",
        ):
            self.assertEqual(metrics[name], 1.0, name)
        for name in (
            "wrong_event_preview_count",
            "unredacted_secret_count",
            "raw_path_leak_count",
            "raw_ref_leak_count",
            "privacy_leak_count",
        ):
            self.assertEqual(metrics[name], 0, name)
        self.assertLess(metrics["runtime_seconds"], 90.0)

        diagnostics = report["diagnostics"]
        for name in (
            "unauthorized_block_count",
            "unsupported_block_count",
            "inactive_block_count",
            "wrong_ref_block_count",
            "root_escape_block_count",
            "symlink_escape_block_count",
            "source_hash_mismatch_block_count",
            "source_anchor_mismatch_block_count",
            "unsupported_format_block_count",
            "malformed_package_block_count",
            "legacy_source_map_block_count",
        ):
            self.assertGreaterEqual(diagnostics[name], 1, name)

        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["context_packages_rendered"])
        self.assertFalse(report["privacy"]["source_previews_rendered"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["raw_refs_rendered"])

        combined = result.stdout + result.stderr
        for forbidden in (
            "V229 exact original event binding must select the supporting event",
            "V229 induction memories should preserve source citations",
            "V229 induction memory should keep source refs",
            "V229 explicit exact source event must remain addressable",
            "V229 layered retrieval should preserve raw source anchors",
            "V229 layered retrieval should preserve evidence refs",
            "V229 safe secret-bearing source remains inspectable",
            "V229_UNRELATED_DISTRACTOR",
            "ghp_" + "V229_SHOULD_NEVER_RENDER_" + "1234567890",
            "srca_",
            str(Path(tmpdir)),
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
