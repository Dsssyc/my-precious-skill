import re
import subprocess
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

    def test_tracked_reusable_files_exclude_user_specific_identity(self):
        blocked_tokens = (
            "/Users/" + "soku",
            "Dsssyc/" + "agent-memory",
        )
        tracked = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
        offenders: list[str] = []
        for relative in tracked:
            if not relative:
                continue
            path = Path(relative)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(token in text for token in blocked_tokens):
                offenders.append(relative)
        self.assertEqual([], offenders, f"user-specific identity leaked into tracked files: {offenders}")

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

    def test_evaluation_doc_records_v218_live_automation_prompt_alignment_gate(self):
        section = self.evaluation_section("## V2.18 Live Codex Automation Prompt Alignment Gate")
        for phrase in (
            "benchmarks/live_automation_prompt_alignment_gate.py",
            "--automation-config",
            "tools/render_scheduler.py --backend agent-native --push-after-update",
            "python tools/audit_publish_readiness.py",
            "python tools/repair_publish_surfaces.py --apply",
            "archive audit -> publish readiness -> search health -> sync dry-run",
            "live_automation_contract_checked",
            "rendered_prompt_alignment_pass",
            "live_automation_alignment_pass",
            "publish_readiness_gate_present",
            "repair_step_present",
            "post_repair_recheck_present",
            "sync_dry_run_before_push_present",
            "sync_only_publish_path_present",
            "raw_git_publish_path_count",
            "private_archive_content_committed_count",
            "privacy_leak_count",
            "raw `git add`, `git commit`, or",
            "not prove live scheduler reliability",
            "live GitHub availability",
            "prompt-following quality",
            "memory quality",
            "ranking quality",
            "vector search",
            "ontology discovery",
            "private archive quality",
            "public leaderboard parity",
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

    def test_evaluation_doc_records_v230_transactional_legacy_upgrade_gate(self):
        section = self.evaluation_section("## V2.30 Transactional Legacy Source-Anchor Upgrade Gate")
        for phrase in (
            "tools/upgrade_source_anchors.py",
            "benchmarks/legacy_source_anchor_upgrade_gate.py",
            "exact archived source SHA-256",
            "restores original bytes and modes",
            "exactly six external synthetic JSONL records with 24 events",
            "legacy_upgrade_package_parse_success_rate",
            "legacy_exact_binding_accuracy",
            "legacy_transaction_rollback_rate",
            "legacy_post_audit_rollback_rate",
            "legacy_optimistic_concurrency_rejection_rate",
            "partial_upgrade_count",
            "privacy_leak_count",
            "readiness evidence only",
            "not permission to migrate",
            "does not prove arbitrary transcript formats",
            "actual private deployment",
            "public benchmark parity",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v234_runtime_tool_bundle_parity_gate(self):
        section = self.evaluation_section("## V2.34 Runtime Tool-Bundle Parity And Fail-Closed Repair Gate")
        for phrase in (
            "benchmarks/runtime_tool_bundle_parity_gate.py",
            "--check-tools",
            "--refresh-tools",
            "runtime_bundle_report_parse_success_rate",
            "runtime_bundle_post_refresh_parity_rate",
            "runtime_bundle_archive_preservation_rate",
            "runtime_bundle_extra_tool_preservation_rate",
            "runtime_bundle_unsafe_target_rejection_rate",
            "post_refresh_reviewed_sync_dry_run_pass_rate",
            "absolute_path_leak_count",
            "privacy_leak_count",
            "not prove that an installed skill is the latest GitHub release",
            "not prove live private deployment correctness",
            "not prove automatic code deployment",
            "not prove scheduler reliability",
            "not prove LLM quality",
            "not prove ranking quality",
            "not prove vector search",
            "not prove ontology discovery",
            "not prove public leaderboard parity",
        ):
            self.assert_contains(section, phrase)

    def test_evaluation_doc_records_v235_three_layer_distribution_preflight(self):
        section = self.evaluation_section(
            "## V2.35 Three-Layer Distribution And Scheduled Parity Preflight Closure"
        )
        for phrase in (
            "benchmarks/three_layer_distribution_preflight_gate.py",
            "benchmarks/live_automation_prompt_alignment_gate.py",
            "source -> installed skills -> private deployment",
            "source_installed_parity_detection_accuracy",
            "installed_deployment_parity_detection_accuracy",
            "preflight_blocks_update_accuracy",
            "current_preflight_allows_update_accuracy",
            "live_source_installed_skill_parity_rate",
            "live_installed_deployment_bundle_parity_rate",
            "live_preflight_idempotent_rate",
            "live_automation_prompt_alignment_rate",
            "live_archive_mutation_count",
            "live_unexpected_tool_change_count",
            "privacy_leak_count",
            "does not prove scheduler reliability",
            "does not prove network reliability",
            "does not prove future archive-update reliability",
            "never installs or refreshes tools",
        ):
            self.assert_contains(section, phrase)

    def test_setup_contract_checks_bundle_before_refresh(self):
        check_position = self.skill_contracts.index("--check-tools")
        refresh_position = self.skill_contracts.index("--refresh-tools")
        self.assertLess(check_position, refresh_position)

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

    def test_evaluation_doc_records_v236_public_induction_inconclusive_result(self):
        section = self.evaluation_section(
            "## V2.36 Public Conversation Source-To-Induction Recall Evidence Gate"
        )
        for phrase in (
            "public_induction_recall_gate.py",
            "LongMemEval cleaned S",
            "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
            "4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7",
            "`status: failed`",
            "`readiness_status: inconclusive`",
            "40/40",
            "34/40",
            "1912/1912",
            "120/120",
            "13/30",
            "0/13",
            "10/10",
            "process_update",
            "gold-label ingestion count is 0",
            "direct synthetic archive injection count is 0",
            "not LLM answer quality",
            "not official LongMemEval leaderboard parity",
            "not vector search quality",
            "not ontology discovery",
            "not private archive quality",
            "not multi-principal governance",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v237_safe_no_change_result(self):
        section = self.evaluation_section(
            "## V2.37 Public Query-Support Calibration With Frozen Holdout"
        )
        for phrase in (
            "public_query_support_calibration_gate.py",
            "strict_v1",
            "weighted_partial_060_v1",
            "weighted_partial_050_specific_v1",
            "c8ac66423f41b968ca60c9af18ae3f2c949f534a8f875d8997ec83cd8fbb5e19",
            "4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7",
            "5106e9379647edeacb71a7161bacd7c602b8ea246a34b8911f514a81c063613d",
            "`status: failed`",
            "`readiness_status: inconclusive`",
            "`status: completed`",
            "`readiness_status: no_go`",
            "`decision_reason: no_safe_policy`",
            "38/40",
            "32/40",
            "11/30",
            "4/11",
            "2/4",
            "1/3",
            "40/40",
            "34/40",
            "13/30",
            "6/13",
            "0/6",
            "ranking_drift_count = 0",
            "`calibration_passed`",
            "is not a final `go`",
            "production query-support behavior remained unchanged",
            "not ranking repair",
            "not archive-audit repair",
            "not induction-content quality",
            "not LLM answer quality",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_docs_record_v238_single_writer_and_publish_receipt_contract(self):
        section = self.evaluation_section(
            "## V2.38 Scheduled Update Single-Writer And Interrupted-Run Recovery Closure"
        )
        for phrase in (
            "scheduled_update_single_writer_gate.py",
            "--require-clean-worktree",
            "reason=concurrent_update",
            "first failure fail-fast",
            "parent and current child",
            "published",
            "no_op_current",
            "blocked",
            "single_writer_acceptance_rate",
            "orphan_child_lock_retention_rate",
            "publish_attempt_after_failed_update_count",
            "privacy_leak_count",
            "not whole-run rollback",
            "not a cross-host distributed lock",
            "not a GitHub availability SLA",
            "not memory quality",
            "committed durable memory IDs",
            "only the final child",
            "71/71",
            "83 minutes",
            "four stale",
            "`a8fd832`",
            "three local stashes",
            "`status: ACTIVE`",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        design = DESIGN_DOC.read_text(encoding="utf-8")
        for phrase in (
            "V2.38 scheduled execution contract",
            "--require-clean-worktree",
            "reason=concurrent_update",
            "parent and current child",
            "published",
            "no_op_current",
            "blocked",
            "committed durable memory IDs",
            "only the final child",
        ):
            self.assert_contains(design, phrase)

    def test_docs_record_v239_single_inventory_and_finalization_contract(self):
        section = self.evaluation_section(
            "## V2.39 Scheduled Update Single-Inventory And Single-Finalization Throughput Closure"
        )
        for phrase in (
            "scheduled_update_throughput_gate.py",
            "source_inventory_amplification",
            "source_root_rescan_count",
            "nonselected_record_reparse_count",
            "target_dispatch_accuracy",
            "successful_run_finalization_count",
            "failed_run_finalization_count",
            "output_parity_rate",
            "output_parity_scenario_count",
            "fail_closed_inventory_rejection_rate",
            "single_writer_regression_pass_rate",
            "synthetic_redundant_work_reduction_rate",
            "privacy_leak_count",
            "target-specific metadata through stdin",
            "authoritative session metadata",
            "not whole-run rollback",
            "not private wall-clock performance",
            "does not prove memory quality",
            "Private acceptance result: `no_go`",
            "1923.252",
            "165.667",
            "11.609",
            "1800",
            "1518602464",
            "V2.38 remains deployed",
            "private output parity was not accepted",
            "custom-pattern, zero-record, and rewrite/max-record",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_docs_record_v240_selected_record_materialization_contract(self):
        section = self.evaluation_section(
            "## V2.40 Scheduled Selected-Record Materialization Throughput Closure"
        )
        for phrase in (
            "selected_record_materialization_gate.py",
            "selected_record_source_read_amplification",
            "selected_record_redaction_amplification",
            "selected_record_json_decode_amplification",
            "selected_record_preparation_before_mutation_rate",
            "selected_record_raw_payload_retention_count",
            "selected_record_output_parity_rate",
            "selected_record_source_anchor_parity_rate",
            "selected_record_secret_policy_parity_rate",
            "selected_record_mutation_rejection_rate",
            "direct_cli_regression_pass_rate",
            "v239_throughput_regression_pass_rate",
            "v238_single_writer_regression_pass_rate",
            "synthetic_materialization_work_reduction_rate",
            "4.0 to 1.0",
            "2.0 to 1.0",
            "6.0 to 2.0",
            "Private acceptance result: `no_go`",
            "343,800,494",
            "147.893",
            "126.182",
            "1.172062",
            "v239_v240_subset_output_parity_rate",
            "private_shadow_run_count",
            "selected-subset speedup was below the required 2.0",
            "not deployment approval",
            "V2.38 remains deployed",
            "raw source payload",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_docs_record_v241_durable_event_projection_attribution_contract(self):
        section = self.evaluation_section(
            "## V2.41 Scheduled Durable-Event Projection Attribution And Closure"
        )
        for phrase in (
            "durable_event_projection_gate.py",
            "phase_attribution_coverage_rate",
            "implementation_decision_accuracy",
            "nondurable_output_dependency_rate",
            "Private attribution result: `profile_no_go`",
            "347,065,206",
            "126.012448",
            "36.752164",
            "0.291655026",
            "1.411741506",
            "summary_source_anchor",
            "58.319916",
            "private_shadow_run_count",
            "did not reach the required 0.55",
            "V2.38 remains deployed",
            "not projection implementation",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_docs_record_v243_mainline_release_truth_contract(self):
        section = self.evaluation_section(
            "## V2.43 Mainline Release Truth And Candidate-Chain Convergence"
        )
        for phrase in (
            "`9ae179f`",
            "`51bdfbe`",
            "`e25c5bc`",
            "source main",
            "installed skills",
            "private deployment",
            "V2.37",
            "V2.38",
            "V2.39",
            "V2.40",
            "V2.41",
            "V2.42",
            "private performance `no_go` is not a functional failure",
            "`19/19`",
            "`17/19`",
            "two stale target tools",
            "559cd20bf9d458ded5fd17749a0c231cf999700d3bd330dca2071083a2d1cacd",
            "ea3946e3bdb824b7966a62240d0d24dd637e0accdd16d7b7924cbc31d17ae08c",
            "72/72",
            "`published`",
            "`profile_no_go`",
            "`architecture_no_go`",
            "no runtime `DurableSemanticIndex` implementation",
            "selected-record performance work remains closed",
            "does not install or deploy",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        runtime_paths = sorted(
            {
                *Path("skills").rglob("*.py"),
                *Path("templates/agent-memory-repo/tools").rglob("*.py"),
            }
        )
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in runtime_paths
        )
        self.assertIsNone(
            re.search(r"durable[_\s-]*semantic[_\s-]*index", runtime_text, flags=re.IGNORECASE)
        )

    def test_docs_record_v248_reboot_safe_transactional_replay_contract(self):
        section = self.evaluation_section(
            "## V2.48 Reboot-Safe Scheduled Update Transactional Replay Closure"
        )
        for phrase in (
            "benchmarks/scheduled_reboot_replay_gate.py",
            "live_automation_prompt_alignment_gate.py",
            "run_scheduled_memory_transaction.py",
            "transaction_adapter_alignment_pass",
            "single_transaction_adapter_invocation_present",
            "strict_transaction_report_contract_present",
            "duplicate_transaction_adapter_rejection_count",
            "same_line_duplicate_transaction_adapter_rejection_count",
            "missing_transaction_report_rejection_count",
            "Initial private operational recovery result: `published`",
            "pre-final-review adapter",
            "first private attempt",
            "5400-second final-candidate attempt",
            "`staging_reset_failed`",
            "checkout-first",
            "Final-candidate private acceptance result: `published`",
            "9081.302 seconds",
            "recovery_action=stale_staging_replayed",
            "recovery_count=1",
            "remote_publish_count=1",
            "canonical_mutation_count=1",
            "repair_attempt_count=1",
            "canonical and staging worktrees were clean",
            "transaction state was cleared",
            "19/19",
            "existing automation remained `status: ACTIVE`",
            "live_automation_alignment_pass=true",
            "transaction_case_count",
            "clean_publish_accuracy",
            "no_op_decision_accuracy",
            "reboot_replay_success_rate",
            "canonical_clean_after_interruption_rate",
            "stale_staging_recovery_rate",
            "post_push_receipt_reconciliation_rate",
            "concurrent_transaction_rejection_rate",
            "dirty_canonical_rejection_rate",
            "malformed_state_rejection_rate",
            "unsafe_state_path_rejection_rate",
            "remote_race_rejection_rate",
            "repository_scoped_lock_rejection_rate",
            "git_common_dir_lock_rejection_rate",
            "nested_writer_lock_rejection_rate",
            "canonical_fast_forward_recovery_rate",
            "unreceipted_remote_rejection_rate",
            "receipted_remote_advance_replay_rate",
            "receipted_remote_tracked_overlap_count",
            "receipted_remote_untracked_overlap_count",
            "partial_remote_publish_count",
            "duplicate_publish_commit_count",
            "canonical_unverified_mutation_count",
            "deployed_v238_tool_mutation_count",
            "raw_source_copy_count",
            "privacy_leak_count",
            "not exact process continuation",
            "not cloud scheduler uptime",
            "not power-loss durability of the source disk",
            "not distributed locking",
            "not a GitHub availability SLA",
            "not memory quality",
            "not ranking quality",
            "not LLM quality",
            "not vector search",
            "not ontology discovery",
            "not V2.39/V2.40 deployment approval",
            "V2.38 remains deployed",
            "V2.48R2 is a repair and acceptance label",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        update_skill = UPDATE_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "scheduled or broad multi-project refreshes",
            "run_scheduled_memory_transaction.py",
            "--state-dir",
            "persistent staging clone",
            "canonical-repository-scoped lock",
            "surviving nested updater",
            "validated adapter-owned staging",
            "hard-reset and cleaned before",
            "receipted remote advance",
            "unrelated dirty paths remain untouched",
            "Same-path user edits",
            "Remote inspection does not advance canonical",
            "published",
            "no_op_current",
            "blocked",
            "exactly one JSON",
            "on-demand single-project",
        ):
            self.assert_contains(update_skill, phrase)

    def test_docs_record_v249_real_use_recall_utility_contract(self):
        section = self.evaluation_section("## V2.49 Real-Use Recall Utility Closure")
        for phrase in (
            "benchmarks/real_use_recall_utility_gate.py",
            "exact or short controls were supported in `2/2` cases",
            "natural or multi-intent forms were supported in `0/2` cases",
            "query.decomposition_recommended",
            "complete event stream",
            "source user-event anchor",
            "at most two context-package queries",
            "current HEAD",
            "synthetic_case_count",
            "durable_chinese_preference_extraction_recall",
            "natural_goal_preference_supported_recall",
            "project_history_supported_recall",
            "live_state_memory_answer_count",
            "wrong_project_supported_hit_count",
            "unsupported_claim_count",
            "privacy_leak_count",
            "not general semantic-memory quality",
            "not ranking quality",
            "not vector search",
            "not private archive correctness",
            "not public leaderboard parity",
            "not LLM answer quality",
            "Private shadow result: `deployment_no_go`",
            "private_preference_materialization_count",
            "private_preference_source_binding_rate",
            "private_goal_preference_supported",
            "private_project_history_supported",
            "private_transaction_invocation_count=0",
            "source-normalization ordering boundary",
            "skill-invocation prefix",
            "candidate matched only `16/19`",
            "prior `19/19` runtime parity",
            "automation remained ACTIVE",
            "was not installed",
            "V2.39/V2.40",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        for phrase in (
            "complete event stream",
            "original language",
            "assistant-acknowledgement",
            "not translation",
            "query.decomposition_recommended",
            "per-hit `query_support`",
            "current HEAD",
        ):
            self.assert_contains(self.skill_contracts + "\n" + self.design, phrase)

    def test_docs_record_v250_canonical_skill_invocation_contract(self):
        section = self.evaluation_section(
            "## V2.50 Canonical Skill-Invocation Prefix Normalization"
        )
        for phrase in (
            "canonical leading skill invocation",
            "label begins with `$`",
            "target ends in `SKILL.md`",
            "Ordinary Markdown links",
            "original user-event source anchor",
            "memory_recall_context_package",
            "canonical_skill_prefixed_preference_recall",
            "multi_skill_prefix_recall",
            "prefixed_preference_source_binding_rate",
            "invocation_only_rejection_rate",
            "arbitrary_markdown_path_rejection_rate",
            "malformed_prefix_rejection_rate",
            "prefixed_non_durable_rejection_rate",
            "standalone_preference_regression_rate",
            "invocation_artifact_leak_count",
            "privacy_leak_count",
            "aggregate reports match",
            "Private regression result: `deployment_no_go`",
            "one aggregate-only regression",
            "not an unknown holdout",
            "private_newly_qualified_target_count",
            "private_newly_qualified_non_target_count",
            "evidence_slots_consumed_before_fact_phase",
            "target_source_event_binding_count",
            "target_memory_candidate_count",
            "schema-key collision only",
            "No installation was attempted",
            "automation remained `ACTIVE`",
            "retuned or rerun",
            "not ranking quality",
            "not vector search",
            "not LLM answer quality",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        design_section = self.design.split(
            "### V2.50 Canonical Skill-Invocation Prefix Normalization", 1
        )[1]
        for phrase in (
            "natural_user_memory_fact",
            "strict normalizer",
            "raw-prompt",
            "source anchor",
            "real_use_recall_utility_gate.py",
            "deployment_no_go",
            "evidence budget",
            "not installed",
        ):
            self.assert_contains(design_section, phrase)

    def test_docs_record_v251_source_bound_goal_preference_contract(self):
        section = self.evaluation_section(
            "## V2.51 Source-Bound Goal Preference Materialization And Real-Use Recall Closure"
        )
        for phrase in (
            "bounded evidence reservation",
            "evidence count remains at most 6",
            "selected_natural_user_fact_evidence_binding_rate",
            "selected_natural_user_fact_source_anchor_rate",
            "selected_natural_user_fact_candidate_materialization_rate",
            "selected_natural_user_fact_active_memory_rate",
            "goal_preference_context_package_support_rate",
            "remaining_evidence_priority_regression_rate",
            "evidence_budget_overflow_count",
            "non_target_memory_promotion_count",
            "unsupported_claim_count",
            "privacy_leak_count",
            "known producer-shape regression",
            "not an unseen holdout",
            "Private regression result: `deployment_go`",
            "target_supported_package_answer_count",
            "wrong_project_supported_hit_count",
            "live_repository_state_memory_answer_count",
            "19/19",
            "allow-list record count",
            "consumer_intent_supported_recall",
            "HEAD == origin/main",
            "automation definition and schedule were unchanged",
            "not ranking quality",
            "not vector search",
            "not general semantic memory",
            "not public leaderboard parity",
            "not LLM answer quality",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        design_section = self.design.split(
            "### V2.51 Source-Bound Goal Preference Materialization", 1
        )[1]
        for phrase in (
            "NATURAL_USER_FACT_LIMIT",
            "SUMMARY_EVIDENCE_LIMIT",
            "select_summary_evidence",
            "final-state slot",
            "memory_candidate_sources",
            "materialize_source_anchors",
            "source-anchor completeness",
            "memory_recall_context_package",
            "deployment_go",
        ):
            self.assert_contains(design_section, phrase)

    def test_docs_record_v252_live_source_batch_contract(self):
        section = self.evaluation_section("## V2.52 Stable Live-Source Batch Closure")
        for phrase in (
            "scheduled_live_source_deferral_gate.py",
            "private_live_source_inventory_ab_gate.py",
            "metadata-only manifest",
            "live_source_defer_accuracy",
            "stable_sibling_publish_accuracy",
            "deferred_retry_recall",
            "changed_source_partial_mutation_count",
            "changed_source_freshness_advance_count",
            "unknown_failure_block_accuracy",
            "aggregate_failure_reason_coverage",
            "inventory_worker_isolation_accuracy",
            "manifest_metadata_only_accuracy",
            "private_enabled_target_completion_rate",
            "private_output_parity_rate",
            "parent_post_inventory_rss_reduction_rate",
            "all 74 enabled targets",
            "privacy_leak_count",
            "source_batch_complete",
            "child_failure_unclassified",
            "parent-RSS",
            "Controlled live deployment closure",
            "Exactly one controlled transaction",
            "`update_project_processed_count`",
            "`source_record_deferred_count`",
            "`source_target_deferred_count`",
            "`update_child_failure_count`",
            "adapter-owned stale staging state",
            "not an archive-current claim",
            "19/19",
            "not LLM answer quality",
            "not vector search",
            "not ontology discovery",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

        design_section = self.design.split("### V2.52 Stable Live-Source Batch Closure", 1)[1]
        for phrase in (
            "short-lived worker",
            "mode-`0600` manifest",
            "changed or became unavailable",
            "freshness state remain untouched",
            "child_failure_unclassified",
            "`deferred` terminal status",
            "no_op_current",
        ):
            self.assert_contains(design_section, phrase)

        update_skill = UPDATE_SKILL.read_text(encoding="utf-8")
        for phrase in (
            "published",
            "no_op_current",
            "deferred",
            "source_batch_complete",
            "aggregate deferred-target/record counts",
        ):
            self.assert_contains(update_skill, phrase)

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

    def test_docs_record_v253_copyable_goal_preference_recall_closure(self):
        section = self.evaluation_section(
            "## V2.53 Copyable Goal Preference Recall Closure"
        )
        for phrase in (
            "copyable_goal_preference_recall_gate.py",
            "session-local",
            "latest explicit correction",
            "natural_user_memory_fact()",
            "at least two user-event",
            "memory_recall_context_package",
            "controlled baseline",
            "goal-correction inducer disabled",
            "exact target memory ID",
            "actual user role",
            "unrelated supported hits",
            "correction_sequence_qualification_rate",
            "correction_induced_fact_materialization_rate",
            "correction_source_anchor_binding_rate",
            "goal_format_query_supported_recall",
            "supported_summary_fact_resolution_rate",
            "global_scope_accuracy",
            "current_turn_instruction_precedence_accuracy",
            "copyable_text_block_decision_accuracy",
            "nested_fence_collision_avoidance_accuracy",
            "assistant_evidence_promotion_count",
            "non_target_memory_promotion_count",
            "free_form_answerability_use_count",
            "privacy_leak_count",
            "aggregate-only",
            "not ranking quality",
            "not vector search",
            "not ontology discovery",
            "not public leaderboard parity",
            "not LLM answer quality",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_docs_record_v257_jsonl_physical_line_recovery(self):
        section = self.evaluation_section(
            "## V2.57 JSONL Physical-Line Recovery And Dev-Feature Convergence"
        )
        for phrase in (
            "benchmarks/jsonl_record_boundary_recovery_gate.py",
            "str.splitlines()",
            "LF and CRLF",
            "U+0085",
            "U+2028",
            "U+2029",
            "V2.54 production truth",
            "V2.56 remains `no_go`",
            "unicode_separator_inventory_acceptance_rate",
            "unicode_separator_materialization_rate",
            "physical_record_count_accuracy",
            "crlf_compatibility_rate",
            "malformed_jsonl_fail_closed_rate",
            "stale_replay_recovery_rate",
            "valid_case_source_inventory_invalid_count",
            "privacy_leak_count",
            "19/19",
            "exactly one controlled transaction",
            "not overall semantic recall closure",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

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
