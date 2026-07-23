# My Precious Skill Development

This repository develops reusable, agent-neutral skills for private session
memory archives. It is not the private archive itself.

## Repository Boundary

Keep this repository limited to reusable building blocks:

- `skills/`: installable skill folders.
- `benchmarks/`: synthetic benchmark runners, cases, and aggregate quality gates.
- `templates/agent-memory-repo/`: deployment repository template.
- `tests/`: synthetic tests only.
- `docs/`: design notes for the reusable implementation.

Do not store real session memories, raw transcripts, credentials, cookies,
private keys, scheduler state, local logs, or generated private archive data in
this repository.

## Skill Set

- `setup-my-precious`: setup-path skill for local or Git-backed private archive
  repositories.
- `update-my-precious`: write-path skill for on-demand incremental archive
  updates.
- `using-my-precious`: read-path skill for searching an existing archive.

Keep skill language and examples agent-neutral. Do not make the skills depend
on one specific runtime unless a runtime-specific adapter is isolated and
optional.

## Template Sync Rule

`templates/agent-memory-repo/` is the source template. The bundled copy under
`skills/setup-my-precious/assets/agent-memory-repo/` must stay byte-for-byte in
sync with it.

When changing shared tools:

- Copy `templates/agent-memory-repo/tools/update_memory_archive.py` to
  `skills/update-my-precious/scripts/update_memory_archive.py`.
- Copy `templates/agent-memory-repo/tools/memory_consolidation.py` to
  `skills/update-my-precious/scripts/memory_consolidation.py`.
- Copy `templates/agent-memory-repo/tools/search_memory.py` to
  `skills/using-my-precious/scripts/search_memory.py`.
- Copy `templates/agent-memory-repo/tools/resolve_memory_source.py` to
  `skills/using-my-precious/scripts/resolve_memory_source.py`.
- Copy all template changes into
  `skills/setup-my-precious/assets/agent-memory-repo/`.

Verify sync with:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cmp -s templates/agent-memory-repo/tools/memory_consolidation.py skills/update-my-precious/scripts/memory_consolidation.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
cmp -s templates/agent-memory-repo/tools/resolve_memory_source.py skills/using-my-precious/scripts/resolve_memory_source.py
```

## Privacy And Security

- Redact before summarization or evidence rendering.
- Keep evidence snippets short.
- Refuse likely-secret source records by default.
- Do not commit raw transcript files or unredacted source records.
- Keep deployment repository examples generic; do not reference user-specific
  repositories or real incidents.

## Verification

Run the canonical release gate before publishing or opening a release PR:

```bash
python3 tools/run_quality_gates.py
```

Run the focused test suite after changes:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Validate skill folders with the repo-local validator:

```bash
python3 tools/validate_skills.py
```

Runtime-specific skill validators may still be run additionally when they are
available in the current environment.

Run packaged lifecycle/readiness gates when readiness contract changes:

```bash
python3 benchmarks/packaged_lifecycle_gate.py
python3 benchmarks/using_my_precious_runtime_gate.py
python3 benchmarks/real_use_recall_utility_gate.py
python3 benchmarks/copyable_goal_preference_recall_gate.py
python3 benchmarks/query_support_recall_gate.py
python3 benchmarks/progressive_source_drilldown_gate.py
python3 benchmarks/authorized_original_source_gate.py
python3 benchmarks/legacy_source_anchor_upgrade_gate.py
python3 benchmarks/archive_regeneration_closure_gate.py
python3 benchmarks/scope_arbitration_gate.py
python3 benchmarks/scope_answer_handoff_gate.py
python3 benchmarks/generated_answer_scope_adapter_gate.py
python3 benchmarks/automation_publish_readiness_gate.py
python3 benchmarks/publish_surface_repair_gate.py
python3 benchmarks/scheduled_publish_recovery_gate.py
python3 benchmarks/scheduled_publish_search_gate.py
python3 benchmarks/scheduled_content_noise_repair_closure_gate.py
python3 benchmarks/live_automation_prompt_alignment_gate.py
python3 benchmarks/scheduled_update_single_writer_gate.py
python3 benchmarks/scheduled_reboot_replay_gate.py
python3 benchmarks/scheduled_update_throughput_gate.py
python3 benchmarks/scheduled_live_source_deferral_gate.py
python3 benchmarks/selected_record_materialization_gate.py
python3 benchmarks/durable_event_projection_gate.py
python3 benchmarks/durable_semantic_index_gate.py
python3 benchmarks/induction_consolidation_gate.py
python3 benchmarks/lifecycle_governance_gate.py
python3 benchmarks/long_horizon_memory_stress_gate.py
python3 benchmarks/private_lifecycle_governance_shadow_gate.py --synthetic-fixture
python3 benchmarks/search_tool_drift_repair_gate.py
python3 benchmarks/runtime_tool_bundle_parity_gate.py
python3 benchmarks/three_layer_distribution_preflight_gate.py
python3 benchmarks/public_induction_recall_gate.py --offline-fixture
python3 benchmarks/public_query_support_calibration_gate.py --offline-fixture
python3 benchmarks/active_support_recall_closure_gate.py
python3 benchmarks/reviewed_automatic_memory_publish_gate.py
python3 benchmarks/v1_readiness_gate.py --run-packaged
python3 benchmarks/v1_readiness_gate.py --run-packaged --require-answer
```

Run the external LongMemEval source-to-induction measurement only with a
downloaded dataset and generated archives outside this repository:

```bash
python3 benchmarks/public_induction_recall_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --work-dir /tmp/my-precious-public-induction-run \
  --report-file /tmp/my-precious-public-induction-report.json
```

Run V2.37 public query-support calibration and the frozen holdout only with the
pinned dataset and generated archives outside this repository:

```bash
python3 benchmarks/public_query_support_calibration_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort calibration \
  --work-dir /tmp/my-precious-query-support-calibration \
  --report-file /tmp/my-precious-query-support-calibration-report.json

python3 benchmarks/public_query_support_calibration_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort holdout \
  --selected-policy none \
  --work-dir /tmp/my-precious-query-support-holdout \
  --report-file /tmp/my-precious-query-support-holdout-report.json
```

Compile bundled scripts when implementation code changes:

```bash
python3 -m py_compile \
  tools/validate_skills.py \
  tools/run_quality_gates.py \
  benchmarks/packaged_lifecycle_gate.py \
  benchmarks/using_my_precious_runtime_gate.py \
  benchmarks/real_use_recall_utility_gate.py \
  benchmarks/copyable_goal_preference_recall_gate.py \
  benchmarks/query_support_recall_gate.py \
  benchmarks/progressive_source_drilldown_gate.py \
  benchmarks/authorized_original_source_gate.py \
  benchmarks/legacy_source_anchor_upgrade_gate.py \
  benchmarks/archive_regeneration_closure_gate.py \
  benchmarks/scope_arbitration_gate.py \
  benchmarks/scope_answer_handoff_gate.py \
  benchmarks/generated_answer_scope_adapter_gate.py \
  benchmarks/automation_publish_readiness_gate.py \
  benchmarks/publish_surface_repair_gate.py \
  benchmarks/scheduled_publish_recovery_gate.py \
  benchmarks/scheduled_publish_search_gate.py \
  benchmarks/scheduled_content_noise_repair_closure_gate.py \
  benchmarks/live_automation_prompt_alignment_gate.py \
  benchmarks/scheduled_update_single_writer_gate.py \
  benchmarks/scheduled_reboot_replay_gate.py \
  benchmarks/scheduled_update_throughput_gate.py \
  benchmarks/scheduled_live_source_deferral_gate.py \
  benchmarks/private_live_source_inventory_ab_gate.py \
  benchmarks/selected_record_materialization_gate.py \
  benchmarks/durable_event_projection_gate.py \
  benchmarks/durable_semantic_index_gate.py \
  benchmarks/induction_consolidation_gate.py \
  benchmarks/lifecycle_governance_gate.py \
  benchmarks/long_horizon_memory_stress_gate.py \
  benchmarks/private_lifecycle_governance_shadow_gate.py \
  benchmarks/search_tool_drift_repair_gate.py \
  benchmarks/runtime_tool_bundle_parity_gate.py \
  benchmarks/three_layer_distribution_preflight_gate.py \
  benchmarks/public_induction_recall_gate.py \
  benchmarks/public_query_support_calibration_gate.py \
  benchmarks/active_support_recall_closure_gate.py \
  benchmarks/reviewed_automatic_memory_publish_gate.py \
  benchmarks/e2e_induction_recall_benchmark.py \
  benchmarks/updater_induction_benchmark.py \
  benchmarks/layered_recall_benchmark.py \
  benchmarks/build_synthetic_recall_archive.py \
  benchmarks/convert_public_memory_benchmark.py \
  benchmarks/generated_answer_case_audit.py \
  benchmarks/generated_answer_benchmark.py \
  benchmarks/private_generated_answer_dogfood_gate.py \
  benchmarks/source_stream_registry_benchmark.py \
  benchmarks/v1_readiness_gate.py \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/update-my-precious/scripts/memory_consolidation.py \
  skills/update-my-precious/scripts/run_scheduled_memory_transaction.py \
  skills/using-my-precious/scripts/search_memory.py \
  skills/using-my-precious/scripts/resolve_memory_source.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/audit_publish_readiness.py \
  templates/agent-memory-repo/tools/repair_publish_surfaces.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/apply_memory_review_decisions.py \
  templates/agent-memory-repo/tools/author_generated_answer_cases.py \
  templates/agent-memory-repo/tools/capture_explicit_memory.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/memory_consolidation.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/resolve_memory_source.py \
  templates/agent-memory-repo/tools/upgrade_source_anchors.py \
  templates/agent-memory-repo/tools/generate_answer_records.py \
  templates/agent-memory-repo/tools/induction_consolidation_audit.py \
  templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py
```

Remove generated caches before committing:

```bash
rm -rf .uv-cache tests/__pycache__ benchmarks/__pycache__ \
  templates/agent-memory-repo/tools/__pycache__ \
  skills/setup-my-precious/scripts/__pycache__ \
  skills/setup-my-precious/assets/agent-memory-repo/tools/__pycache__ \
  skills/update-my-precious/scripts/__pycache__ \
  skills/using-my-precious/scripts/__pycache__ \
  tools/__pycache__
```

## Git Hygiene

Before committing, check:

```bash
git diff --check
git status --short
```

If untracked original planning/spec artifacts exist under `docs/`, do not
commit them unless the user explicitly asks to keep original planning material
in the repository.
