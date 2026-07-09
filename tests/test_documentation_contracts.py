import re
import unittest
from pathlib import Path


EVALUATION_DOC = Path("docs/evaluations/layered-memory-readiness.md")
DESIGN_DOC = Path("docs/design.md")
UPDATE_SKILL = Path("skills/update-my-precious/SKILL.md")
USING_SKILL = Path("skills/using-my-precious/SKILL.md")
SETUP_SKILL = Path("skills/setup-my-precious/SKILL.md")
TEMPLATE_AGENTS = Path("templates/agent-memory-repo/AGENTS.md")


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluation = EVALUATION_DOC.read_text(encoding="utf-8")
        cls.design = DESIGN_DOC.read_text(encoding="utf-8")
        cls.combined = cls.evaluation + "\n" + cls.design
        cls.skill_contracts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (UPDATE_SKILL, USING_SKILL, SETUP_SKILL, TEMPLATE_AGENTS)
        )

    def assert_contains(self, haystack: str, needle: str):
        if needle not in haystack:
            self.fail(f"missing documentation contract phrase: {needle!r}")

    def evaluation_section(self, heading: str) -> str:
        self.assert_contains(self.evaluation, heading)
        start = self.evaluation.index(heading)
        next_heading = self.evaluation.find("\n## ", start + len(heading))
        return self.evaluation[start:] if next_heading == -1 else self.evaluation[start:next_heading]

    def test_evaluation_doc_lists_packaged_lifecycle_as_core_readiness_dimension(self):
        self.assert_contains(self.evaluation, "clean-room packaged lifecycle setup/update/search/audit")
        self.assert_contains(self.evaluation, "packaged_lifecycle")

    def test_evaluation_doc_no_longer_claims_four_required_packaged_dimensions(self):
        forbidden_patterns = (
            r"requires\s+four\s+packaged\s+synthetic\s+dimensions",
            r"four\s+required\s+packaged\s+dimensions",
            r"四个\s*packaged",
            r"四个\s*核心维度",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(
                re.search(pattern, self.evaluation, flags=re.IGNORECASE),
                msg=f"stale readiness wording still present: {pattern!r}",
            )

    def test_docs_distinguish_memory_readiness_gate_from_release_gate(self):
        self.assert_contains(self.combined, "benchmarks/v1_readiness_gate.py")
        self.assert_contains(self.combined, "tools/run_quality_gates.py")
        self.assert_contains(self.combined, "repo-local release gate")

    def test_docs_record_current_required_scorecards(self):
        self.assert_contains(self.evaluation, "required 5/5")
        self.assert_contains(self.evaluation, "required 6/6")

    def test_evaluation_doc_records_v21_packaged_runtime_consumption_gate(self):
        section = self.evaluation_section("## V2.1 Packaged Runtime Consumption Gate")
        for phrase in (
            "clean packaged deployment repo",
            "benchmarks/using_my_precious_runtime_gate.py",
            "runtime_context_package_parse_success_rate",
            "runtime_supported_decision_accuracy",
            "runtime_abstention_accuracy",
            "runtime_inactive_rejection_count",
            "runtime_malformed_fail_closed_count",
            "privacy_leak_count",
            "not LLM answer quality",
            "not ranking quality",
            "not vector search",
            "not ontology discovery",
                "not public leaderboard parity",
            ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v213_publish_surface_repair_gate(self):
        section = self.evaluation_section("## V2.13 Reusable Publish-Surface Repair Gate")
        for phrase in (
            "tools/repair_publish_surfaces.py",
            "benchmarks/publish_surface_repair_gate.py",
            "sessions/**/meta.json",
            "aggregate counts only",
            "dry-run reports stay aggregate-only",
            "apply mode rebuilds derived surfaces",
            "through the updater",
            "durable adjacent facts remain present",
            "malformed metadata",
            "ambiguous",
            "single-scalar text",
            "pre_repair_readiness_failure_count",
            "post_repair_readiness_pass_count",
            "repairable_apply_success_count",
            "durable_fact_preservation_count",
            "ambiguous_fail_closed_count",
            "malformed_fail_closed_count",
            "privacy_leak_count",
            "not LLM answer quality",
            "not ranking quality",
            "not vector search",
            "ontology discovery",
            "not public leaderboard parity",
            "tools/run_quality_gates.py",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v214_scheduled_recovery_gate(self):
        section = self.evaluation_section("## V2.14 Scheduled Automation Recovery Drill")
        for phrase in (
            "benchmarks/scheduled_publish_recovery_gate.py",
            "agent-native scheduled automation prompt",
            "--push-after-update",
            "memory repository as the only working directory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --push",
            "instead of hand staging",
            "python tools/repair_publish_surfaces.py --apply",
            "publish readiness blocks",
            "blocked",
            "repairable_metadata_noise",
            "ambiguous_scalar_noise",
            "malformed_metadata",
            "sync dry-run publish intent",
            "scheduler_prompt_contract_pass_rate",
            "pre_repair_sync_block_count",
            "repair_apply_success_count",
            "post_repair_publish_intent_count",
            "ambiguous_fail_closed_count",
            "malformed_fail_closed_count",
            "hand_stage_bypass_count",
            "privacy_leak_count",
            "not live scheduler reliability",
            "not live LLM prompt-following quality",
            "not GitHub availability",
            "not ranking quality",
            "not vector search",
            "not private archive quality",
            "not public leaderboard parity",
            "tools/run_quality_gates.py",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v215_scheduled_search_gate(self):
        section = self.evaluation_section("## V2.15 Scheduled Automation Search-Gate Publish Decision Contract")
        for phrase in (
            "benchmarks/scheduled_publish_search_gate.py",
            "search discoverability",
            "no-op state",
            "unexpected dirty surfaces",
            "--push-after-update",
            "python tools/search_memory.py",
            "--health-check",
            "python tools/sync_memory_archive.py --push",
            "python tools/search_memory.py memory",
            "deployment-local policy only",
            "not a reusable release readiness gate",
            "not used as answerability or archive content evidence",
            "discoverable_archive_publish_ready",
            "empty_archive_search_blocked",
            "already_current_no_op",
            "unexpected_dirty_surface_blocked",
            "archive audit",
            "sync dry-run publish intent",
            "avoid an empty commit",
            "unexpected non-archive surface",
            "search_gate_pass_rate",
            "search_blocked_count",
            "no_op_no_empty_commit_count",
            "unexpected_dirty_block_count",
            "publish_intent_count",
            "hand_stage_bypass_count",
            "free_form_search_output_used_count",
            "privacy_leak_count",
            "not live GitHub availability",
            "not live scheduler reliability",
            "not live LLM prompt-following quality",
            "not ranking quality",
            "not vector search",
            "not private archive quality",
            "not public leaderboard parity",
            "tools/run_quality_gates.py",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v216_content_noise_repair_closure_gate(self):
        section = self.evaluation_section("## V2.16 Search-Healthy Content-Noise Repair Closure Gate")
        for phrase in (
            "benchmarks/scheduled_content_noise_repair_closure_gate.py",
            "search health passing is necessary but not sufficient",
            "content-noise readiness",
            "repair -> rebuild -> archive audit -> publish readiness -> search health -> sync dry-run",
            "--push-after-update",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --push",
            "not use free-form search output",
            "not hand-stage files",
            "search_healthy_noise_repaired_publish_ready",
            "search_healthy_ambiguous_noise_blocked",
            "search_healthy_malformed_meta_blocked",
            "clean_after_repair_no_empty_commit",
            "durable_content_preserved",
            "search_health_pre_repair_pass_rate",
            "content_noise_block_count",
            "repair_apply_success_count",
            "post_repair_readiness_pass_count",
            "post_repair_search_health_pass_count",
            "post_repair_publish_intent_count",
            "ambiguous_fail_closed_count",
            "malformed_fail_closed_count",
            "no_empty_commit_count",
            "durable_content_preservation_count",
            "hand_stage_bypass_count",
            "free_form_search_output_used_count",
            "privacy_leak_count",
            "not live scheduler reliability",
            "not live GitHub availability",
            "not live LLM prompt-following quality",
            "not memory quality",
            "not ranking quality",
            "not vector search",
            "not ontology discovery",
            "not private archive quality",
            "not public leaderboard parity",
            "tools/run_quality_gates.py",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v22_runtime_support_coverage_contract(self):
        section = self.evaluation_section("## V2.2 Runtime Support-Coverage Contract")
        for phrase in (
            "query_support",
            "query_support.status: supported",
            "weak-active",
            "same-topic near-miss",
            "runtime_support_coverage_accuracy",
            "runtime_weak_active_rejection_count",
            "runtime_near_miss_abstention_accuracy",
            "runtime_supported_decision_accuracy",
            "runtime_abstention_accuracy",
            "runtime_context_package_parse_success_rate",
            "privacy_leak_count",
            "not ranking quality",
            "not LLM answer quality",
            "not vector search",
            "not ontology discovery",
            "not public leaderboard parity",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v23_hard_negative_recall_gate(self):
        section = self.evaluation_section("## V2.3 Query-Support-Aware Hard-Negative Recall Gate")
        for phrase in (
            "benchmarks/query_support_recall_gate.py",
            "same-topic wrong-scope",
            "weak active/current",
            "broad lexical overlap",
            "inactive/superseded-only",
            "supported_context_recall_at_5",
            "answerable_precision_at_5",
            "query_support_boundary_pass_rate",
            "weak_support_rejection_count",
            "scope_mixed_noise_at_5",
            "inactive_lifecycle_rejection_count",
            "runtime_abstention_accuracy",
            "privacy_leak_count",
            "not live LLM answer quality",
            "not vector search quality",
            "not public leaderboard parity",
            "not automatic ontology discovery",
            "not solved long-horizon memory decay",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v24_induction_consolidation_gate(self):
        section = self.evaluation_section("## V2.4 Packaged Induction Consolidation Gate")
        for phrase in (
            "benchmarks/updater_induction_benchmark.py",
            "repeated and paraphrased automatic induction facts",
            "--limit 5 --depth evidence --context-json",
            "memory_recall_context_package",
            "answerability.status",
            "query_support.status",
            "consolidated_duplicate_suppression_rate",
            "consolidated_support_merge_rate",
            "consolidated_evidence_retention_rate",
            "contradiction_review_routing_rate",
            "scope_shift_review_routing_rate",
            "process_noise_rejection_rate",
            "post_consolidation_recall_at_5",
            "privacy_leak_count",
            "not LLM summarization quality",
            "not vector search",
            "not ontology discovery",
            "not private archive quality",
            "tools/run_quality_gates.py",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_preserves_bounded_claim_language(self):
        for phrase in (
            "private archive",
            "public leaderboard parity",
            "live model answer quality",
            "automatic ontology discovery",
            "long-horizon governance",
        ):
            self.assert_contains(self.evaluation, phrase)

    def test_private_shadow_refresh_section_is_aggregate_only_and_decisive(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "memory_recall_at_5",
            "memory_precision_at_5",
            "top_k_noise_at_5",
            "expected_record_missing",
            "privacy_boundary_pass_rate",
            "lifecycle_integrity.score",
            "ranking/noise reduction",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_cross_scope_safety_fixture(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "Same-Topic Cross-Scope Safety Fixture",
            "same-topic/cross-scope support",
            "same-topic/cross-scope noise",
            "not sufficient to justify a production ranking change",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_runtime_signal_audit(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "Same-Topic Cross-Scope Runtime-Signal Audit",
            "runtime_signal_diagnostics_at_5",
            "support_count=1",
            "medium confidence",
            "not yet sufficient for a ranking patch",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_v12_conservative_ranking_gate(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "V1.2 Conservative Same-Topic Cross-Scope Ranking Gate",
            "weak same-topic/cross-scope tail",
            "`memory_recall_at_5` stayed 1.0",
            "`top_k_noise_at_5` dropped to 0.0",
            "accepted as a narrow ranking/noise reduction patch",
            "aggregate-only",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v13_self_maintenance_lifecycle_gate(self):
        section = self.evaluation_section("## V1.3 Self-Maintenance Lifecycle Gate")
        for phrase in (
            "not a new retrieval capability",
            "public synthetic self-maintenance fixture",
            "`thread_source=automation`",
            "`search_memory.py --health-check`",
            "generic `search_memory.py memory`",
            "`sync_memory_archive.py`",
            "aggregate-only private dogfood",
            "automation_source_records=2",
            "automation_session_entries=0",
            "automation_memory_nodes=0",
            "automation_daily_noise_hits=0",
            "automation_index_noise_hits=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v14_explicit_capture_contract(self):
        section = self.evaluation_section("## V1.4 Explicit Memory Capture Contract")
        for phrase in (
            "explicit memory capture contract",
            "not a new ranking capability",
            "not generated-answer quality",
            "not long-horizon ontology or governance",
            "`capture_explicit_memory.py`",
            "agent-neutral JSONL input",
            "short fact",
            "raw transcript fields are refused",
            "explicit_capture",
            "adapter_input_records=1",
            "captured_memory_nodes=1",
            "rejected_raw_transcript_records=1",
            "search_hit_count=1",
            "privacy_leak_count=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v15_explicit_revision_contract(self):
        section = self.evaluation_section("## V1.5 Explicit Memory Revision And Conflict Contract")
        for phrase in (
            "explicit memory revision contract",
            "not a general long-horizon governance system",
            "not a new ranking capability",
            "not generated-answer quality",
            "replace",
            "withdraw",
            "current fact",
            "old fact is not deleted",
            "superseded and retains evidence traceability",
            "explicit_revision",
            "explicit_revision_input_records=2",
            "explicit_revision_superseded_records=1",
            "explicit_revision_deprecated_records=1",
            "current_fact_search_hit_count=1",
            "stale_fact_default_search_hit_count=0",
            "withdrawn_fact_default_search_hit_count=0",
            "revision_evidence_reachability_count=2",
            "privacy_leak_count=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v16_source_grounded_answer_handoff_contract(self):
        section = self.evaluation_section("## V1.6 Source-Grounded Answer Handoff Contract")
        for phrase in (
            "deterministic answer handoff",
            "not live model answer quality",
            "answer_handoff",
            "support_refs",
            "active/current memory",
            "abstain",
            "answer_handoff_support_coverage_rate",
            "answer_handoff_present_rate",
            "answer_handoff_supported_case_count",
            "answer_handoff_abstain_case_count",
            "unsupported_claim_count=0",
            "inactive_memory_answer_count=0",
            "privacy_leak_count=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v17_private_aggregate_dogfood_gate(self):
        section = self.evaluation_section("## V1.7 Private Aggregate Dogfood Gate")
        for phrase in (
            "private aggregate dogfood",
            "not a public benchmark",
            "not live model answer quality",
            "private_generated_answer_dogfood_gate.py",
            "private dogfood wrapper",
            "answer_handoff_present_rate",
            "answer_handoff_support_coverage_rate",
            "memory_ids_rendered",
            "source_paths_rendered",
            "raw_refs_rendered",
            "only deletes known dogfood-generated artifacts",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v18_agent_facing_recall_context_package(self):
        section = self.evaluation_section("## V1.8 Agent-Facing Recall Context Package")
        for phrase in (
            "memory_recall_context_package",
            "--context-json",
            "answerability.status",
            "active/current",
            "supported answer versus abstain",
            "not live model answer quality",
            "not a ranking overhaul",
            "not automatic ontology",
            "raw refs",
            "local private paths",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v19_context_package_consumption_gate(self):
        section = self.evaluation_section("## V1.9 Context-Package Consumption Gate")
        for phrase in (
            "memory_recall_context_package",
            "search_memory.py --context-json",
            "context_package_handoff_present_rate",
            "context_package_parse_success_rate",
            "context_package_support_coverage_rate",
            "context_package_abstention_accuracy",
            "context_package_inactive_rejection_count",
            "malformed packages fail closed to abstain",
            "not live LLM answer quality",
            "not ranking quality",
            "not vector search",
            "not automatic ontology",
            "not public leaderboard parity",
            "raw refs",
            "local private paths",
            "private queries",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v20_runtime_skill_consumption_contract(self):
        section = self.evaluation_section("## V2.0 Runtime Skill Consumption Contract")
        for phrase in (
            "using-my-precious",
            "memory_recall_context_package",
            "--depth evidence --context-json",
            "answerability.status",
            "Do not use free-form search output as the answerability source",
            "supported package -> answer",
            "unsupported package -> abstain",
            "inactive/superseded-only package -> abstain",
            "malformed or missing package -> abstain",
            "not live LLM answer quality",
            "not vector search",
            "not ranking quality",
            "private query",
            "raw refs",
            "local private paths",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_skill_docs_record_explicit_capture_adapter_contract(self):
        for phrase in (
            "capture_explicit_memory.py",
            "agent-neutral JSONL",
            "automatic induction is the default",
            "explicit capture path",
            "Do not paste raw chat transcripts",
            "short fact",
        ):
            self.assert_contains(self.skill_contracts, phrase)

    def test_skill_docs_record_explicit_revision_adapter_contract(self):
        for phrase in (
            "explicit revision path",
            "`operation: replace`",
            "`operation: withdraw`",
            "`replaces_memory_id`",
            "`deprecates_memory_id`",
            "prefer the current fact",
            "old fact is superseded rather than deleted",
            "provenance remains traceable",
        ):
            self.assert_contains(self.skill_contracts, phrase)

    def test_skill_docs_record_source_grounded_answer_handoff_contract(self):
        for phrase in (
            "source-grounded answer handoff",
            "memory_recall_context_package",
            "--context-json",
            "answerability.status",
            "Answer from archive evidence only",
            "abstain when support is missing",
            "support_refs",
            "active/current memory",
            "do not expose raw refs",
        ):
            self.assert_contains(self.skill_contracts, phrase)


if __name__ == "__main__":
    unittest.main()
