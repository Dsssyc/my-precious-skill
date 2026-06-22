import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("templates/agent-memory-repo/tools/induction_consolidation_audit.py").resolve()


def write_meta_row(
    repo: Path,
    slug: str,
    *,
    project: str,
    project_path: str,
    source_updated_at: str,
    reusable_facts: list[str],
    tags: list[str],
) -> None:
    entry_rel = f"sessions/2026/06/22/{slug}"
    entry_dir = repo / entry_rel
    entry_dir.mkdir(parents=True)
    (entry_dir / "summary.md").write_text(
        f"Summary for synthetic audit case {slug}.\n",
        encoding="utf-8",
    )
    (entry_dir / "evidence.md").write_text(
        "ev_001: SECRET_AUDIT_FIXTURE_TEXT must not appear in audit output.\n",
        encoding="utf-8",
    )
    (entry_dir / "meta.json").write_text(
        json.dumps(
            {
                "session_id": slug,
                "source_agent": "synthetic",
                "project": project,
                "project_path": project_path,
                "source_record": f"/private/source/{slug}.jsonl",
                "source_updated_at": source_updated_at,
                "summary_path": f"{entry_rel}/summary.md",
                "evidence_path": f"{entry_rel}/evidence.md",
                "source_map_path": f"{entry_rel}/source-map.json",
                "reusable_facts": reusable_facts,
                "decisions": [],
                "unresolved_tasks": [],
                "tags": tags,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


class InductionConsolidationAuditTests(unittest.TestCase):
    def test_induction_consolidation_audit_rejects_non_archive_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", tmpdir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--repo must point to a memory archive", result.stderr)

    def test_induction_consolidation_audit_reports_quantitative_write_path_metrics(self):
        old_superseded = "Memory archive should use literal-only search."
        new_superseding = "Memory archive should use hybrid lexical scoring."
        old_contradicted = "Scheduler updates must keep raw transcript uploads disabled by default."
        new_contradicting = "Scheduler updates must not keep raw transcript uploads disabled by default."
        scoped_fact = "Layer routing should preserve project-specific defaults for nested workspaces."
        broad_fact = "Layer routing should preserve defaults for nested workspaces."
        process_noise = "I checked the failing tests and will now inspect the archive."

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            (repo / "sessions").mkdir(parents=True)
            write_meta_row(
                repo,
                "literal-old",
                project="alpha",
                project_path="/tmp/alpha",
                source_updated_at="2026-06-22T10:00:00Z",
                reusable_facts=[old_superseded],
                tags=["memory", "search"],
            )
            write_meta_row(
                repo,
                "literal-new",
                project="beta",
                project_path="/tmp/beta",
                source_updated_at="2026-06-22T11:00:00Z",
                reusable_facts=[f"Updated fact: {old_superseded} -> {new_superseding}"],
                tags=["memory", "search"],
            )
            write_meta_row(
                repo,
                "contradiction-old",
                project="gamma",
                project_path="/tmp/gamma",
                source_updated_at="2026-06-22T12:00:00Z",
                reusable_facts=[old_contradicted],
                tags=["memory", "scheduler"],
            )
            write_meta_row(
                repo,
                "contradiction-new",
                project="delta",
                project_path="/tmp/delta",
                source_updated_at="2026-06-22T13:00:00Z",
                reusable_facts=[new_contradicting],
                tags=["memory", "scheduler"],
            )
            write_meta_row(
                repo,
                "scope-old",
                project="epsilon",
                project_path="/tmp/epsilon",
                source_updated_at="2026-06-22T14:00:00Z",
                reusable_facts=[scoped_fact],
                tags=["memory", "layering"],
            )
            write_meta_row(
                repo,
                "scope-new",
                project="zeta",
                project_path="/tmp/zeta",
                source_updated_at="2026-06-22T15:00:00Z",
                reusable_facts=[broad_fact],
                tags=["memory", "layering"],
            )
            write_meta_row(
                repo,
                "process-noise",
                project="eta",
                project_path="/tmp/eta",
                source_updated_at="2026-06-22T16:00:00Z",
                reusable_facts=[process_noise],
                tags=["memory"],
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        report = json.loads(result.stdout)
        metrics = report["metrics"]
        self.assertEqual(metrics["induction_candidate_count"], 7)
        self.assertEqual(metrics["accepted_induction_candidate_count"], 6)
        self.assertEqual(metrics["process_noise_rejected_count"], 1)
        self.assertEqual(metrics["promoted_memory_count"], 6)
        self.assertEqual(metrics["ambiguous_scope_review_count"], 1)
        self.assertEqual(metrics["contradiction_preserved_count"], 1)
        self.assertEqual(metrics["supersession_reciprocity"], 1.0)
        self.assertEqual(metrics["evidence_ref_reachability"], 1.0)
        self.assertEqual(metrics["real_history_privacy_pass_rate"], 1.0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertTrue(report["privacy"]["case_details_safe"])
        self.assertIn(
            {
                "case_id": "process-noise-rejection",
                "category": "induction",
                "decision": "reject",
                "failure_reason": "",
            },
            report["case_details"],
        )
        combined = result.stdout + result.stderr
        self.assertNotIn("SECRET_AUDIT_FIXTURE_TEXT", combined)
        self.assertNotIn("/private/source", combined)
        self.assertNotIn(process_noise, combined)
