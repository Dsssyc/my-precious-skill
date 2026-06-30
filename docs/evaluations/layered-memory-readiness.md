# Layered Memory Readiness Evaluation

## Purpose

This document is a stage-gate evaluation for the reusable My Precious skill
repository. It records what the current implementation can measure reliably,
where the packaged benchmark can overstate readiness, and what remains before
the project can claim a full non-project-boundary layered memory system.

The conclusion is intentionally narrow: the current benchmark set provides
repeatable local quality gates for retrieval, layer-path drilldown,
source-reference reachability, broad lexical noise resistance, stale
suppression, lifecycle-link reciprocity, abstention, privacy-boundary behavior,
updater-driven automatic induction on synthetic archives, and end-to-end
induction-to-recall behavior on synthetic source records, plus explicit
non-project source stream registry updates on synthetic archives. It is not a direct
leaderboard score against public long-memory systems such as MemPalace,
LongMemEval, LoCoMo, Memora, or RULER-style long-context retrieval tests.

## V1 Readiness Gate

`benchmarks/v1_readiness_gate.py` is the convergence entrypoint for this
evaluation. It aggregates existing JSON reports without rendering queries,
memory text, source paths, raw refs, private probe cases, or forbidden-pattern
text. The gate requires four packaged synthetic dimensions:

- layered recall and drilldown;
- updater-driven automatic induction;
- end-to-end induction-to-recall; and
- explicit non-project source stream registry update plus layered recall.

When those required dimensions pass, the gate reports
`overall_status: core_synthetic_ready`. That status is deliberately bounded: it
means the core synthetic evidence is green, not that the full
non-project-boundary v1 target, automatic source discovery, public leaderboard
parity, generated-answer accuracy, or long-horizon multi-principal governance
has been proven.

Optional report inputs extend the evidence surface without changing the privacy
boundary:

- `--public-report` accepts a layered recall aggregate report produced from
  converted public benchmark cases outside this repository. The result is an
  adapted local score only, not an official public leaderboard claim. The gate
  now requires aggregate `source_benchmarks` counts plus
  `case_origins.public_benchmark_adapter`, so a generic layered report or the
  packaged synthetic report cannot stand in for adapted public benchmark
  evidence.
- `--shadow-report` accepts a private real-archive shadow-eval aggregate report.
  The report must remain aggregate-only and must declare that private probe
  cases, queries, memory IDs, memory text, source refs, source content, source
  paths, and raw refs were not rendered. Use `--require-shadow` only when the
  local private probe set should be a required readiness gate for the run.
- `--answer-report` accepts an offline generated-answer aggregate report. When
  `--run-packaged --require-answer` is used without an answer report, the gate
  runs the packaged synthetic generated-answer fixture automatically. This is
  synthetic dogfood evidence for the grading path, not proof of live model
  answer quality. Answer reports must include aggregate `source_benchmarks` and
  `case_origins`; metric-only generated-answer JSON is rejected because it
  cannot prove which benchmark or dogfood stream produced the answers.

The strongest recorded local gate below combines a private real-archive
aggregate shadow report with the 100-case converted LongMemEval public-adapter
report. Under the current gate, an equivalent rerun must also pass the packaged
`source_stream_registry` core dimension. That still does not prove full public
benchmark parity, generated-answer correctness, automatic ontology discovery,
or complete long-horizon governance.

The packaged generated-answer gate can be included in local convergence runs:

```bash
python3 benchmarks/v1_readiness_gate.py --run-packaged --require-answer
```

The current packaged generated-answer fixture has 3 cases: 2 positive answer
cases and 1 abstention case. It reports `case_pass_rate: 1.0`,
`answer_normalized_match_rate: 1.0`, `answer_token_f1: 1.0`,
`abstention_accuracy: 1.0`, `privacy_leak_count: 0`,
`missing_answer_count: 0`, `duplicate_answer_count: 0`, and
`unknown_answer_count: 0`. It also carries
`source_benchmarks.MyPreciousGeneratedAnswerSynthetic: 3` and
`case_origins.packaged_generated_answer_fixture: 3`, satisfying the answer
provenance gate without rendering queries, generated answers, or reference
answers.

The deployment template also includes an extractive
`tools/generate_answer_records.py` adapter for producing answer-record JSONL
from memory search hits. Its own report is aggregate-only: it includes case
count, answer records written, memory-answer count, abstention count, no-hit
count, source benchmark counts, case-origin counts, and privacy flags without
rendering queries, generated answers, reference answers, source paths, or raw
refs. This proves the answer-record production path can be wired into the
offline grader, but it remains extractive evidence rather than live model
answer quality.

The current packaged source-stream registry fixture has 1 case and 1
metadata-free source record. It reports `source_stream_update_rate: 1.0`,
`project_registry_independence_rate: 1.0`,
`metadata_free_source_record_rate: 1.0`,
`archive_scope_assignment_rate: 1.0`,
`source_partition_assignment_rate: 1.0`,
`source_stream_memory_recall_at_5: 1.0`,
`source_stream_session_drilldown_rate: 1.0`,
`source_stream_evidence_reachability_rate: 1.0`,
`source_stream_source_policy_pass_rate: 1.0`,
`privacy_leak_count: 0`, and `failed_case_count: 0`.
The readiness gate also requires the source-stream report's privacy block to
declare `aggregate_only: true` and no rendered case details, memory text,
source content, source paths, or raw refs. A report with green source-stream
metrics but missing or unsafe privacy flags is rejected.

Run the packaged convergence gate locally with:

```bash
python3 benchmarks/v1_readiness_gate.py --run-packaged
```

Or aggregate existing reports:

```bash
python3 benchmarks/v1_readiness_gate.py \
  --layered-report /tmp/layered.json \
  --updater-report /tmp/updater.json \
  --e2e-report /tmp/e2e.json \
  --source-stream-report /tmp/source-stream.json
```

## Current Baseline

Baseline date: 2026-06-27

Code point used for the benchmark harness: this document revision

Case file:
`benchmarks/cases/layered_recall_synthetic.jsonl`

Case fingerprint:
`331638f9fba7bdf753d44ca0f04c784b3682ab399f2b3f44387bb2531b008d75`

Search implementation fingerprint:
`af4425503d18e1759306fb3ef404c9a2445ecc75380be4e05942ecac29c0427a`

Baseline commands:

```bash
python3 benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-layered-synthetic-baseline \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors

python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-layered-synthetic-baseline \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-layered-synthetic-details.jsonl \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

Baseline result:

| Metric | Value |
| --- | ---: |
| cases | 45 |
| positive_cases | 40 |
| abstain_cases | 5 |
| answer_cases | 11 |
| evidence_text_cases | 13 |
| memory_recall_at_1 | 1.0 |
| memory_recall_at_5 | 1.0 |
| memory_mrr | 1.0 |
| memory_ndcg_at_5 | 1.0 |
| memory_precision_at_5 | 1.0 |
| memory_micro_precision_at_5 | 1.0 |
| memory_result_count_at_5 | 40 |
| memory_relevant_count_at_5 | 40 |
| memory_noise_count_at_5 | 0 |
| top_k_noise_at_5 | 0.0 |
| memory_explainability | 1.0 |
| layer_calibration | 1.0 |
| layer_path_success_rate | 1.0 |
| scope_filter_recall | 1.0 |
| wrong_scope_suppression | 1.0 |
| session_drilldown_at_5 | 1.0 |
| drilldown_success_rate | 1.0 |
| source_reachability | 1.0 |
| source_ref_reachability | 1.0 |
| source_precision_at_5 | 1.0 |
| source_micro_precision_at_5 | 1.0 |
| source_result_count_at_5 | 40 |
| source_relevant_count_at_5 | 40 |
| memory_evidence_ref_cases | 40 |
| memory_evidence_ref_reachability | 1.0 |
| memory_graph_drilldown_cases | 1 |
| memory_graph_drilldown_rate | 1.0 |
| memory_graph_invalid_edge_cases | 2 |
| memory_graph_invalid_edge_suppression_rate | 1.0 |
| lifecycle_supersession_cases | 9 |
| lifecycle_supersession_reciprocity | 1.0 |
| semantic_lifecycle_cases | 10 |
| semantic_lifecycle_reciprocity | 1.0 |
| semantic_lifecycle_suppression | 1.0 |
| deprecated_lifecycle_cases | 2 |
| deprecated_lifecycle_suppression | 1.0 |
| semantic_false_merge_cases | 3 |
| semantic_false_merge_guard | 1.0 |
| semantic_evidence_retention_cases | 10 |
| semantic_evidence_retention | 1.0 |
| evidence_reachability | 1.0 |
| evidence_text_reachability | 1.0 |
| answer_reachability | 1.0 |
| answer_normalized_reachability | 1.0 |
| answer_token_f1 | 1.0 |
| abstention_accuracy | 1.0 |
| abstain_pass_rate | 1.0 |
| negative_memory_suppression | 1.0 |
| stale_memory_suppression | 1.0 |
| suppression_pass_rate | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| privacy_leak_count | 0 |
| update_consistency | 1.0 |
| failed_case_count | 0 |
| case_pass_rate | 1.0 |

Latency for local verification runs is about `24 s` total, or about `533 ms`
mean per case. Treat these as local smoke-test timings, not a performance
claim; they depend on the local Python runtime, filesystem cache, and machine
load.

## Updater-Driven Induction Baseline

Baseline date: 2026-06-26

Code point used for the benchmark harness: this document revision

Case file:
`benchmarks/cases/updater_induction_synthetic.jsonl`

Case fingerprint:
`bfc1cd71ca7e50755cf68e487f39c2bb8ed23c137f1822a0216a5906f88c9bca`

Runner fingerprint:
`da94d3800a46664891f998d9dac7fe06c0a03631df4668e15cf3a797ce290c62`

Setup script fingerprint:
`d3303d2b061a3568c107cdc6dfadddcf4b254d527ae4c44babbccc5e6f86774d`

Updater script fingerprint:
`b811d68366062e6116623e1278292f139b84d9d787017f64fdd4ec8b771f7b2b`

Baseline command:

```bash
python3 benchmarks/updater_induction_benchmark.py \
  --cases benchmarks/cases/updater_induction_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/updater_induction_synthetic.json \
  --fail-over-file benchmarks/quality-gates/updater_induction_synthetic_max.json
```

Baseline result:

| Metric | Value |
| --- | ---: |
| cases | 29 |
| source_records | 41 |
| expected_automatic_memories | 14 |
| expected_forced_memories | 1 |
| expected_lifecycle_links | 3 |
| expected_memory_id_provenance_links | 3 |
| expected_induction_review_decisions | 3 |
| expected_privacy_refusals | 1 |
| expected_privacy_redactions | 1 |
| induction_success_rate | 1.0 |
| natural_induction_success_rate | 1.0 |
| natural_false_promotion_rate | 0.0 |
| auto_promotion_precision | 1.0 |
| cross_project_generalization_rate | 1.0 |
| project_scope_precision | 1.0 |
| ambiguous_candidate_review_rate | 1.0 |
| induction_review_routing_rate | 1.0 |
| induction_review_decision_apply_rate | 1.0 |
| induction_review_approve_promotion_rate | 1.0 |
| induction_review_ignore_suppression_rate | 1.0 |
| low_confidence_review_rate | 1.0 |
| scope_change_review_rate | 1.0 |
| conflict_review_rate | 1.0 |
| review_routing_rate | 1.0 |
| process_noise_rejection_rate | 1.0 |
| ephemeral_status_rejection_rate | 1.0 |
| hypothetical_rejection_rate | 1.0 |
| acknowledgement_only_rejection_rate | 1.0 |
| temporary_local_decision_rejection_rate | 1.0 |
| generic_rule_rejection_rate | 1.0 |
| layer_assignment_accuracy | 1.0 |
| evidence_retention_rate | 1.0 |
| source_ref_policy_pass_rate | 1.0 |
| lifecycle_link_accuracy | 1.0 |
| memory_id_provenance_rate | 1.0 |
| forced_memory_capture_rate | 1.0 |
| privacy_refusal_pass_rate | 1.0 |
| privacy_redaction_pass_rate | 1.0 |
| privacy_leak_count | 0 |
| failed_case_count | 0 |
| case_pass_rate | 1.0 |

The updater-driven suite contains synthetic scenarios across these categories:

| Category | Cases |
| --- | ---: |
| automatic_induction | 2 |
| forced_memory | 1 |
| lifecycle | 1 |
| natural_induction | 6 |
| natural_precision | 8 |
| natural_review_calibration | 6 |
| natural_review_decision | 3 |
| privacy | 2 |

The runner creates temporary synthetic source records and invokes the deployed
template updater. It does not prebuild `memories/*.jsonl`; the memories,
evidence refs, source-map refs, explicit memory nodes, lifecycle links, and
redaction/refusal outcomes must be produced by `update_memory_archive.py`.
The natural review calibration cases require partial-support, conflict, and
scope-change candidates to land in `index/induction_review_candidates.jsonl`
instead of `index/memories.jsonl`; those review rows preserve evidence and
source refs while storing only candidate-text hashes.
The natural review decision cases write synthetic private
`reviews/induction_review_decisions.jsonl` decisions, then verify that
`approve_promote` creates a memory node while `reject` and `noop` remain
non-mutating. The report records only aggregate apply, promotion, and
suppression rates. Unit coverage now also rejects duplicate decision IDs,
repeated exact rows, and conflicting candidate/fingerprint actions, while
dry-run preflight reports aggregate duplicate/conflict/stale/unsafe/unknown
counts.
A separate aggregate-safe authoring helper now generates pending private
decision skeletons from active `index/induction_review_candidates.jsonl` rows
without rendering candidate text, source paths, queries, raw refs, or
transcripts; it preserves existing manual decisions and skips already reflected
decisions before reviewers fill actions and run apply preflight/write.
The JSON report is aggregate-only: it does not render source content, memory
text, source paths, raw refs, or per-case details.

## End-To-End Induction-To-Recall Baseline

Baseline date: 2026-06-27

Code point used for the benchmark harness: this document revision

Case file:
`benchmarks/cases/e2e_induction_recall_synthetic.jsonl`

Case fingerprint:
`4a619e0895e52f493ed97c2e0ca3be3ce8c526c26c3d3a288eb7e45a7feb6b89`

Runner fingerprint:
`06e45bd2f8fb12c6746978729c700fc93f0325c8b3184fc5fc4a51fc3e9a55a2`

Setup script fingerprint:
`d3303d2b061a3568c107cdc6dfadddcf4b254d527ae4c44babbccc5e6f86774d`

Updater script fingerprint:
`e1c78d281c8d8aca995c9f81420bc59fadca0f4abc06209e175b97d79b998f48`

Search script fingerprint:
`af4425503d18e1759306fb3ef404c9a2445ecc75380be4e05942ecac29c0427a`

Baseline command:

```bash
python3 benchmarks/e2e_induction_recall_benchmark.py \
  --cases benchmarks/cases/e2e_induction_recall_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/e2e_induction_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/e2e_induction_recall_synthetic_max.json
```

Baseline result:

| Metric | Value |
| --- | ---: |
| cases | 12 |
| source_records | 20 |
| recall_cases | 10 |
| natural_induction_success_rate | 1.0 |
| cross_project_generalization_rate | 1.0 |
| project_scope_precision | 1.0 |
| ambiguous_candidate_review_rate | 1.0 |
| process_noise_rejection_rate | 1.0 |
| e2e_memory_recall_at_1 | 1.0 |
| e2e_memory_recall_at_5 | 1.0 |
| e2e_layer_assignment_accuracy | 1.0 |
| e2e_session_drilldown_rate | 1.0 |
| e2e_evidence_reachability_rate | 1.0 |
| e2e_source_policy_pass_rate | 1.0 |
| e2e_lifecycle_active_suppression_rate | 1.0 |
| e2e_memory_id_provenance_rate | 1.0 |
| e2e_forced_memory_recall_rate | 1.0 |
| privacy_leak_count | 0 |
| failed_case_count | 0 |
| case_pass_rate | 1.0 |

The e2e suite contains synthetic scenarios across these categories:

| Category | Cases |
| --- | ---: |
| automatic_induction | 2 |
| forced_memory | 1 |
| lifecycle | 1 |
| natural_induction | 6 |
| privacy | 2 |

The runner creates temporary synthetic source records, invokes the deployed
template updater, derives recall cases from generated memory nodes, and scores
them through the real copied `search_memory.py`. Active recall expectations
cover six generated memories; deprecate lifecycle behavior is measured through
suppression probes against retired target memory IDs rather than by treating a
deprecation marker as an active recall target.
The JSON report is aggregate-only: it does not render source content, memory
text, source paths, raw refs, or per-case details.

## Synthetic Case Coverage

The packaged synthetic suite contains 45 cases across these categories:

| Category | Cases |
| --- | ---: |
| abstention | 3 |
| automatic_induction | 1 |
| broad_lexical_noise | 2 |
| cross_project_recall | 3 |
| explicit_memory | 1 |
| information_extraction | 3 |
| knowledge_update | 3 |
| memory_graph_drilldown | 1 |
| multi_session_reasoning | 3 |
| privacy_boundary | 3 |
| scope_calibration | 3 |
| semantic_lifecycle | 10 |
| source_reachability | 3 |
| stale_memory_suppression | 3 |
| temporal_reasoning | 3 |

The cases are inspired by public benchmark dimensions, but they are synthetic
templates only. They do not contain copied public benchmark records or private
session memories.

Source labels in the synthetic file are:

| Source label | Cases |
| --- | ---: |
| LongMemEval | 12 |
| RULER-style-stress | 5 |
| Memora | 5 |
| LOCoMo | 4 |
| LongMemEval-V2 | 3 |
| MemPalace-analysis | 3 |
| MyPrecious-layered-synthetic | 12 |

These labels indicate which public benchmark family or design concern inspired
the case. They do not mean the public benchmark dataset was run.

## Metric Inventory

### Memory Recall And Ranking

Measured:

- `memory_recall_at_1`: whether the expected high-level memory node is the first
  returned memory hit.
- `memory_recall_at_5`: whether the expected high-level memory node appears
  within the first five returned memory hits.
- `memory_mrr`: reciprocal-rank score across positive cases.
- `memory_ndcg_at_5`: rank-sensitive top-5 score.
- `memory_ranked_cases`, `memory_rank_missing_cases`, `memory_rank_mean`,
  `memory_rank_median`, and `memory_rank_histogram`: rank distribution and
  missing-hit visibility.

Not measured:

- Semantic answer quality from a generator after retrieval.
- Recall over large real histories with organic noise distribution.
- Robustness to paraphrases beyond the synthetic case wording.
- Long-horizon drift across months of real user behavior.

### Precision And Result Purity

Measured:

- `memory_precision_at_5`: per-case macro purity of top-5 memory results.
- `memory_micro_precision_at_5`: aggregate relevant-result ratio across top-5
  memory results.
- `top_k_noise_at_5`: aggregate top-5 memory noise, computed as
  non-relevant memory results divided by returned memory results.
- `source_precision_at_5` and `source_micro_precision_at_5`: analogous purity
  for source anchors at source depth.
- `privacy_leak_count`: count of benchmark cases whose configured forbidden
  output patterns or generic secret-like identifiers appeared in memory,
  session, source, or source-preview output.

Interpretation:

The current packaged synthetic baseline is intentionally strict:
`memory_precision_at_5`, `memory_micro_precision_at_5`,
`source_precision_at_5`, and `source_micro_precision_at_5` all score 1.0, with
`top_k_noise_at_5=0.0` and `privacy_leak_count=0`. Future regressions should
therefore show up as aggregate noise or leak counts before they are treated as
acceptable related context.

Not measured:

- Whether extra related hits are useful to an agent.
- Whether the ranking is optimal among many semantically plausible memories.
- Precision at larger `k` values.

### Explainability

Measured:

- `memory_explainability`: expected-memory hits must carry high-signal `why:`
  reasons such as structured field matches, phrase matches, important token
  coverage, or project context.

Not measured:

- Human judgment of whether explanations are persuasive.
- Faithfulness of every explanation token to the scoring implementation.

### Layer And Scope Calibration

Measured:

- `layer_calibration`: whether expected `global`, `domain`, and `project`
  memories are returned at the intended layer.
- `layer_path_success_rate`: whether a positive case retrieves the expected
  memory within top 5, includes the supporting summary path, and satisfies the
  expected layer when one is configured.
- `scope_filter_recall`: whether `--scope <expected_layer>` still recalls the
  expected memory.
- `wrong_scope_suppression`: whether the same expected memory is absent when
  searched through incorrect scopes.

Not measured by the layered recall benchmark:

- Automatic promotion from sessions into layers.
- Multi-layer conflict resolution.
- Session-layer and raw/source-layer scope controls as first-class query
  targets.
- Whether a project-independent memory ontology is complete.

The updater-driven induction benchmark now covers automatic promotion into
`global`, `domain`, and `project` memory layers on synthetic source records,
but it still does not prove ontology completeness or organic multi-project
distribution on real private history.

### Drilldown And Source Reachability

Measured:

- `session_drilldown_at_5`: whether the supporting session summary path appears
  in session-depth results.
- `drilldown_success_rate`: whether a positive case can traverse the expected
  summary, evidence, and source-ref path without violating source-depth privacy
  policy.
- `evidence_reachability`: whether required evidence paths are reachable from
  the expected memory's memory blocks.
- `memory_evidence_ref_reachability`: whether the expected memory block itself
  exposes each required evidence path in its `evidence:` section, with a
  `path#quote_id` display ref when the quote id is available.
- `evidence_text_reachability`: whether required evidence files contain exact
  reference evidence snippets.
- `source_reachability`: whether the expected source anchor appears on the
  expected memory's `source: memory` block at source depth.
- `memory_graph_drilldown_rate`: whether a high-level memory whose
  `derived_from` names another memory ID can still expose the supporting
  summary, evidence, and source ref through bounded active-memory graph
  resolution.
- `memory_graph_invalid_edge_suppression_rate`: whether audit-valid inactive
  memory-id graph edges, currently superseded and deprecated nodes, avoid
  leaking their memory IDs or support paths into the expected memory's
  drilldown context. Structurally invalid missing or cyclic edges are covered
  by focused search tests rather than the packaged audit-clean benchmark
  archive.

Recent hardening:

- Source, evidence, and answer metrics are bound to the expected memory identity
  instead of accepting matching paths or anchors from unrelated blocks.
- The default memory search result now displays validated evidence references
  without printing evidence file text.
- Diagnostic result IDs are filtered to memory blocks so index/source blocks
  cannot impersonate memory results.
- Valid `derived_from` memory IDs are resolved through a bounded active-memory
  graph to concrete support paths and source ref statuses; memory IDs
  themselves remain metadata and are not rendered as `drill:` file paths.

Not measured:

- Raw transcript retrieval or rendering.
- Authorization gates for raw source access.
- Multi-hop raw transcript content retrieval beyond source-ref status and
  optional redacted preview checks.
- Whether source anchors remain valid after archive migration or compaction.

### Answer Reachability

Measured:

- `answer_reachability`: exact reference-answer text is reachable in the
  expected-memory context or in verified local drilldown files.
- `answer_normalized_reachability`: case- and punctuation-insensitive answer
  reachability.
- `answer_token_f1`: best-window token overlap between retrieved context and
  reference answer.

Not measured:

- Generated answer correctness.
- Semantic equivalence when exact wording differs.
- Whether retrieved context is minimal or well organized for an LLM reader.

### Abstention And Suppression

Measured:

- `abstention_accuracy`: unsupported queries produce no parseable hits and only
  allowed no-hit output, or public-adapter abstention-answer cases retrieve
  structured related context while the reference answer says the requested fact
  was absent.
- `abstention_answer_cases` and `abstention_answer_pass_rate`: the subset of
  `expected_abstain` cases whose reference answers explicitly say the requested
  fact was not mentioned, not specified, or otherwise unanswerable.
- `negative_memory_suppression`: explicitly forbidden memory IDs do not appear
  in executed search outputs.
- `stale_memory_suppression`: superseded memory IDs do not appear.
- `update_consistency`: the latest expected memory is found while stale memory
  is suppressed.
- `lifecycle_supersession_cases`: stale/update cases whose synthetic archive
  contains an expected supersession relationship.
- `lifecycle_supersession_reciprocity`: the current memory lists every stale
  memory ID in `supersedes`, and each stale memory points back through
  `superseded_by`.

Recent hardening:

- Abstention and suppression are checked across default and scoped searches.
- Unstructured non-no-hit output is rejected even when it does not parse as a
  hit block.
- The packaged synthetic gate now uses `--include-superseded-distractors` and
  checks lifecycle reciprocity directly instead of inferring lifecycle health
  only from search-result suppression.

Not measured:

- Memory decay policies.
- Forgetting after explicit deletion.
- Conflict handling when a later memory only partially supersedes an older one.

### Privacy Boundary

Measured:

- `privacy_boundary_pass_rate`: configured forbidden patterns do not appear in
  memory, session, source, or scoped search subprocess output.
- Output details and failure JSON avoid raw reference answers, raw forbidden
  patterns, returned snippets, and unsafe returned identifiers.

P1 measurement issue fixed during this audit:

- Before `da3da62`, successful search subprocess `stderr` was not included in
  privacy checks. A search script could write a forbidden pattern to `stderr`
  while returning valid `stdout`, and the privacy metric would incorrectly pass.
- The fix keeps ranking/source parsing on `stdout` only, but evaluates
  privacy and no-hit abstention against combined `stdout` plus `stderr`.

Not measured:

- Secret detection beyond configured patterns and built-in unsafe identifier
  sanitizers.
- Policy-grade data retention guarantees.
- Cross-user or multi-principal access control.

## Public Benchmark Comparability

Long-memory benchmark terminology is related but not interchangeable:

- LongMemEval evaluates long-term chat-assistant memory across information
  extraction, multi-session reasoning, temporal reasoning, knowledge updates,
  and abstention, using 500 curated questions embedded in scalable chat
  histories: <https://arxiv.org/abs/2410.10813>.
- LongMemEval-V2 shifts toward agent experience in web environments, with 451
  curated questions over up to 500 trajectories and 115M tokens, using a context
  gathering formulation: <https://arxiv.org/abs/2605.12493>.
- LoCoMo evaluates very long-term conversational memory over conversations with
  about 300 turns on average and up to 35 sessions, including QA and other
  long-range dialogue tasks: <https://arxiv.org/abs/2402.17753>.
- RULER is a long-context stress benchmark, not a persistent memory archive
  benchmark. It extends needle-in-a-haystack retrieval into multi-hop tracing and
  aggregation tasks: <https://arxiv.org/abs/2404.06654>.
- Memora-related work emphasizes balancing abstraction and specificity and
  reports improved retrieval/reasoning on LoCoMo and LongMemEval:
  <https://arxiv.org/abs/2602.03315>. A separate 2026 benchmark paper using the
  Memora name emphasizes remembering, reasoning, recommending, and
  forgetting-aware memory accuracy: <https://arxiv.org/abs/2604.20006>.
- GateMem is relevant to future privacy/governance work because it evaluates
  utility, access control, and active forgetting in shared-memory settings:
  <https://arxiv.org/abs/2606.18829>.

MemPalace comparability should be stated especially carefully:

- The available critical analysis reports that MemPalace claimed 96.6% Recall@5
  on LongMemEval, but attributes much of the headline retrieval performance to
  verbatim storage plus ChromaDB embedding behavior rather than the spatial
  metaphor alone: <https://arxiv.org/abs/2604.21284>.
- My Precious currently emphasizes summarized, redacted, source-traceable memory
  and dependency-light lexical retrieval. A direct Recall@5 comparison against a
  verbatim embedding store would mix storage philosophy, privacy posture,
  retrieval engine, and benchmark protocol.
- The correct comparison today is capability coverage and measurement rigor, not
  a headline public-benchmark score.

The repository has a converter for locally downloaded LongMemEval, LoCoMo, and
Memora-style records. This audit includes bounded adapted local LongMemEval
probes, including a 100-case cleaned-split run with case fingerprints and
aggregate gates. That is still not a public benchmark score. A public benchmark
score would require exact dataset versions, full conversion logs, archive
construction rules, the upstream answer-grading protocol, and repeated runs
against a real or benchmark-faithful archive built from those records.

## Verified Capabilities

The current implementation can be trusted for these bounded claims:

- A synthetic archive can store `global`, `domain`, and `project` memory nodes.
- The search path can retrieve the expected high-level memory at rank 1 across
  the packaged synthetic suite.
- Scoped search can preserve recall for the correct layer and suppress wrong
  layers on the packaged scope-calibration cases.
- Search can drill from high-level memories to session paths, evidence paths,
  and expected source anchors in the synthetic archive.
- Default memory results expose validated evidence references as
  `path#quote_id` entries while leaving evidence text unread and unprinted.
- Stale and forbidden memory IDs are checked across default and scoped search
  outputs.
- Unsupported queries are tested for abstention rather than being silently
  treated as recall failures.
- The benchmark emits reproducible case/search fingerprints and structured
  details/failure artifacts.
- The benchmark now includes successful search `stderr` in privacy and
  abstention checks.
- Archive audit rejects high-level memory nodes without non-empty
  `derived_from` and `evidence_refs`, and it checks missing evidence quote IDs
  in both root memory files and `index/memories.jsonl`.
- `derived_from` may also link to an existing memory ID for high-level
  memory-to-memory induction provenance, but this does not replace concrete
  `evidence_refs` or make the memory ID a drilldown file path.
- The read path now resolves bounded, active memory-id `derived_from` edges to
  concrete summary/evidence/source support paths while suppressing inactive
  graph edges in the packaged benchmark and missing or cyclic graph edges in
  focused search tests.
- The updater now writes memory-id `derived_from` provenance for synthetic
  lifecycle supersession, contradiction, and deprecation links, while retaining
  concrete summary/evidence support paths. Updater and e2e benchmark gates keep
  this memory-to-memory provenance rate at `1.0`.
- The updater can induce a `domain` high-level memory from multiple synthetic
  session source records. The generated memory is automatic, has two supporting
  summaries, has evidence refs whose quote IDs exist in `evidence.md`, and is
  indexed.
- The updater has a direct explicit-memory write path that creates sticky
  high-level memories only when an existing summary path and evidence quote ref
  are supplied. Source-free direct explicit writes are refused.
- The packaged synthetic benchmark now includes `automatic_induction` and
  `explicit_memory` categories with category pass rate and layer calibration
  gated at `1.0`.
- The benchmark gates `memory_evidence_ref_reachability` at `1.0` across all 40
  positive cases, including the `automatic_induction` and `explicit_memory`
  categories.
- Repeated exact explicit memories merge support and evidence instead of
  creating duplicate high-level memory nodes.
- A synthetic updated fact can create a current memory, mark the previous memory
  as superseded, preserve evidence traceability, and keep search results on the
  active current memory.
- The benchmark gates `lifecycle_supersession_reciprocity` at `1.0` across the
  9 packaged stale/update cases that include superseded distractors.

## Remaining Gaps Against The Target System

The target system described in
`docs/superpowers/specs/2026-06-17-layered-memory-recall-design.md` is broader
than the current implementation.

Current gaps:

- Project path is no longer the only high-water-mark key. The updater and
  global runner now support explicit `archive_scope` and `source_partition`
  keys, write them into `meta.json`, `source-map.json`,
  `index/sessions.jsonl`, `index/scopes.jsonl`, and
  `index/source_partitions.jsonl`, and keep the resolved project path as the
  default for both keys for compatibility. Incremental high-water and
  source-hash freshness are partitioned by source partition inside the archive
  scope, so multiple source streams can feed the same domain without one
  stream's newer timestamp hiding another stream's older unarchived records.
  The global runner now also supports explicit `config/source_streams.jsonl`
  rows that can update a domain/global stream without first materializing a
  project registry row. Project path still remains a possible source-record
  filtering context and automatic discovery signal, so project is not yet
  merely one scope among a complete ontology.
- Automatic induction is implemented as a conservative minimum slice. It can
  promote synthetic reusable facts into high-level memories and run a
  dependency-light semantic lifecycle pass. Aggregate-only private deployment
  archive runs have now measured induction, review-queue behavior, and the
  2026-06-29 `--require-shadow` v1 readiness path without rendering private
  memory text, probe cases, queries, source paths, or raw refs. This is still
  not a broad natural-language consolidation engine, a public benchmark score,
  or an end-to-end generated-answer evaluation.
- Direct explicit-memory writes exist in the reusable updater, but runtime-level
  adapters and governing-prompt integration still need policy design.
- The system has `global`, `domain`, and `project` memory files, and now has a
  minimum semantic lifecycle loop for support merge, paraphrase consolidation,
  false partial-supersession guards, refresh/supersession, contradiction links,
  deprecation links, partial supersession, and retired-node confidence revision
  on synthetic records. Decay, large-history conflict policy, and richer
  confidence revision are still incomplete.
- Raw/source reachability now has an initial gated drilldown workflow. Source
  depth reports stable `source_ref_id`, `status`, and `reason` fields by
  default, and short raw-source previews require explicit
  `--raw-source-preview` target selection plus `--authorize-raw-source-preview`
  confirmation with redaction. This is still not a full multi-principal
  authorization system.
- The benchmark has thirteen `evidence_text` cases, including ten semantic
  lifecycle robustness cases for conflict, deprecation, false-merge guards, and
  evidence retention. It now also gates source-depth policy, source ref
  reachability, raw-preview authorization, raw-preview redaction, and
  source-drilldown privacy on the packaged synthetic suite. This is still
  synthetic and too small to prove source-depth robustness on real private
  histories.
- The reusable template now includes a privacy-safe shadow evaluation runner
  that can report aggregate recall, active-memory suppression, lifecycle
  integrity, top-k noise, noise-source buckets, provenance coverage, and a
  privacy-safe diagnostic summary for recall misses, abstention false
  positives, suppression failures, privacy failures, and top-k noise. The
  diagnostic summary uses only case ordinals, short case-label hashes, counts,
  and noise buckets. It can also emit a structural report for legacy deployment
  archives that do not yet have layered memory nodes. The 2026-06-23 v2
  private-probe gate below expanded the fixed
  redacted real-history probe set with natural-language labels, hard negatives,
  abstention checks, and a lifecycle relation-gap baseline kept outside this
  reusable repository.
- The reusable benchmark folder now includes a v1 readiness convergence gate
  that aggregates the required synthetic layered/updater/e2e reports and
  optional public-adapter or private shadow-eval aggregate reports. The
  required source-stream dimension now gates both source-stream metrics and the
  aggregate-only privacy shape for source/source-ref evidence. This closes the
  "many separate green checks with no single bounded readiness summary" gap,
  but it does not close the underlying project-boundary, long-horizon,
  generated-answer, or governance gaps by itself.
- Search is lexical and explainable. That is a deliberate design choice, but it
  has not been evaluated against embedding or hybrid semantic retrieval on
  public datasets.
- Low-signal memory-node matches are filtered when the query only hits low
  signal fields such as tags and there is no project-context match. This removes
  a narrow top-k noise class without changing the synthetic recall gate.
- Hard-negative memory search now keeps lexical explainability while requiring
  distinctive specific query tokens to appear in retained memory hits. Queries
  with only generic-token coverage abstain instead of returning broad lexical
  memory noise.
- No current test proves long-term behavior over hundreds of sessions,
  multi-month updates, high-cardinality users, or multi-principal governance.
- The benchmark does not grade generated answers and therefore cannot claim
  end-to-end assistant answer accuracy.

## P0/P1 Measurement Audit Result

Finding fixed:

- P1: successful search `stderr` was omitted from privacy checks. Fixed in
  `da3da62` with a fail-first regression test.

No additional P0/P1 measurement false-positive path was confirmed during this
pass. Existing recent hardening already addresses the most direct false-positive
paths:

- Expected source anchors must belong to the expected memory block.
- Evidence and answer reachability are bound to expected-memory context.
- Source/result diagnostics filter non-memory blocks where memory identity is
  required.
- Abstention rejects unstructured non-no-hit output.
- Scoped searches are included in suppression and privacy checks.

Lower-priority evaluation improvements remain, but they should not be mixed into
this convergence audit as open-ended optimization.

## Real Archive Shadow Eval V2 Snapshot

Date: 2026-06-22

This run used redacted probe case files outside this repository and did not copy
private source records, memory text, source paths, queries, or raw anchors into
the skill repository. The target deployment archive had 1,376 layered memory
records. Archive audit passed, provenance coverage scored 1.0, and lifecycle
integrity scored 1.0.

| probe set | cases | recall@5 | precision@5 | top-k noise@5 | broad lexical noise | scope-mixed noise |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v1 single expected ID baseline | 12 | 1.00 | 0.30 | 0.70 | 20 | 8 |
| v2 grouped expected IDs baseline | 8 | 1.00 | 0.60 | 0.40 | 0 | 8 |
| v1 single + scope-aware preferred layer | 12 | 1.00 | 0.375 | 0.625 | 20 | 0 |
| v2 grouped + scope-aware preferred layer | 8 | 1.00 | 1.00 | 0.00 | 0 | 0 |

The v2 protocol supports `expected_memory_ids` for cases where several memory
nodes are legitimate answers to the same query. Precision and noise are computed
against that full relevant-ID set. The v1 single-ID probe therefore overstated
noise in duplicate-query families; the grouped v2 probe removes those false
broad-lexical noise counts. The scope-aware preferred-layer run uses
`expected_layer` as a soft retrieval preference: when preferred-layer hits exist,
wrong-layer hits do not fill the top-k list; when no preferred-layer hit exists,
cross-layer memories remain reachable.

## Real Archive Shadow Eval Gate V1 Private Probe Snapshot

Date: 2026-06-22

This run used the reusable `shadow_eval_memory_archive.py` quality-gate options
against the deployment archive. The fixed redacted real-history probe cases and
gate files live in the private deployment archive, not in this reusable skill
repository. This document records only aggregate metrics, schema coverage, and
the location strategy. The run did not render private source records, memory
text, source paths, queries, raw anchors, memory ids, or probe content.

Gate thresholds:

| gate | threshold |
| --- | ---: |
| metrics.memory_recall_at_5 | >= 1.0 |
| metrics.memory_precision_at_5 | >= 1.0 |
| metrics.active_memory_suppression | >= 1.0 |
| metrics.privacy_boundary_pass_rate | >= 1.0 |
| metrics.provenance_coverage.score | >= 1.0 |
| metrics.lifecycle_integrity.score | >= 1.0 |
| metrics.forbidden_output_violations | <= 0 |
| metrics.top_k_noise_at_5 | <= 0.0 |
| metrics.noise_sources_at_5.* | <= 0 |

Private probe result:

| metric | value |
| --- | --- |
| archive_format | layered |
| memory_records | 1377 |
| legacy_session_records | 267 |
| probe_cases | 6 |
| positive_cases | 6 |
| layers_covered | global, domain, project |
| schema_fields_covered | expected_memory_id, expected_memory_ids, expected_layer, expected_not_memory_id, forbidden_output_patterns |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 1.0 |
| top_k_noise_at_5 | 0.0 |
| active_memory_suppression | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| forbidden_output_violations | 0 |
| noise_sources_at_5.broad_lexical_match | 0 |
| noise_sources_at_5.scope_mixed | 0 |
| noise_sources_at_5.inactive_lifecycle | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 |
| provenance_coverage.score | 1.0 |
| provenance_coverage.evidence_ref_coverage | 1.0 |
| lifecycle_integrity.score | 1.0 |
| audit_status | passed |

The private deployment archive stores the redacted probe JSONL, separate
fail-under/fail-over threshold files, and an aggregate-only baseline JSON in its
private evaluation area. The reusable skill repository must keep only aggregate
figures like the table above.

## Real Archive Shadow Eval Gate V2 Hard-Negative Snapshot

Date: 2026-06-23

This run expanded the private deployment archive's redacted real-history probe
set. The probe cases use redacted natural-language labels and non-sensitive
phrases rather than topic-only keywords. The private probe JSONL, fail-under
gate, fail-over gate, and aggregate baseline JSON remain in the private
deployment archive. This reusable skill repository records only aggregate
metrics and coverage categories.

Gate thresholds were tightened from the post-hard-negative v2 baseline:

| gate | threshold |
| --- | ---: |
| metrics.memory_recall_at_5 | >= 1.0 |
| metrics.memory_precision_at_5 | >= 0.42424242424242425 |
| metrics.abstain_pass_rate | >= 1.0 |
| metrics.active_memory_suppression | >= 1.0 |
| metrics.privacy_boundary_pass_rate | >= 1.0 |
| metrics.provenance_coverage.score | >= 1.0 |
| metrics.lifecycle_integrity.score | >= 1.0 |
| metrics.top_k_noise_at_5 | <= 0.5757575757575757 |
| metrics.abstain_false_positive_results | <= 0 |
| metrics.forbidden_output_violations | <= 0 |
| metrics.noise_sources_at_5.broad_lexical_match | <= 35 |
| metrics.noise_sources_at_5.scope_mixed | <= 3 |
| metrics.noise_sources_at_5.inactive_lifecycle | <= 0 |
| metrics.noise_sources_at_5.low_signal_memory_node | <= 0 |

Private probe result:

| metric | value |
| --- | --- |
| archive_format | layered |
| memory_records | 1377 |
| legacy_session_records | 267 |
| probe_cases | 27 |
| positive_cases | 24 |
| abstain_cases | 3 |
| layers_covered | global, domain, project |
| category_groups | abstain, agent workflow, audit, consolidation, cross-project, domain recall, frontend QA, git workflow, global recall, induction, layer preference, project recall, public benchmark, review queue, scope conflict, source depth |
| schema_fields_covered | expected_abstain, expected_memory_id, expected_memory_ids, expected_layer, expected_not_memory_id, forbidden_output_patterns |
| hard_negative_cases | 24 |
| privacy_cases | 9 |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 0.42424242424242425 |
| top_k_noise_at_5 | 0.5757575757575757 |
| noise_sources_at_5.broad_lexical_match | 35 |
| noise_sources_at_5.scope_mixed | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 |
| abstain_pass_rate | 1.0 |
| abstain_false_positive_results | 0 |
| active_memory_suppression | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| forbidden_output_violations | 0 |
| provenance_coverage.score | 1.0 |
| provenance_coverage.evidence_ref_coverage | 1.0 |
| lifecycle_integrity.score | 1.0 |
| lifecycle_relation_gap | false |
| lifecycle_relation_records.supersedes | 2 |
| lifecycle_relation_records.superseded_by | 2 |
| records_with_any_lifecycle_relation | 4 |
| audit_status | passed |

Compared with the first v2 hard-negative baseline, recall stayed at 1.0,
precision moved from 0.3925233644859813 to 0.42424242424242425, top-k noise
moved from 0.6074766355140186 to 0.5757575757575757, broad lexical noise moved
from 61 to 35, scope-mixed noise moved from 4 to 3, abstain pass rate moved
from 0.3333333333333333 to 1.0, and
abstain false-positive results moved from 7 to 0. The reusable search change is
strategy-level rather than probe-specific: it preserves lexical recall, rejects
pure generic-token coverage, requires distinctive specific query tokens to
appear in retained memory hits, and diversifies same topic/scope memory results
so loose near-neighbor automatic memories do not fill top-k. The initial v2
baseline had no real supersedes, deprecates, or contradicts relations. The
2026-06-23 lifecycle review calibration below adds two aggregate-only real
supersession pairs while preserving the tightened v2 gate thresholds.

## Real Archive Induction And Review Queue Snapshot

Date: 2026-06-22

This run used `induction_consolidation_audit.py` against the deployment archive
and emitted aggregate JSON only. It did not copy private source records, memory
text, source paths, raw refs, queries, or evidence snippets into this repository.

| metric | value |
| --- | ---: |
| session_meta_records | 266 |
| induction_candidate_count | 2253 |
| accepted_induction_candidate_count | 2253 |
| promoted_memory_count | 1374 |
| auto_merge_count | 293 |
| represented_review_candidate_count | 339 |
| review_candidate_count_after_compression | 203 |
| compressed_review_candidate_count | 136 |
| ambiguous_scope_review_count | 51 |
| low_confidence_semantic_overlap_review_count | 152 |
| skipped_lifecycle_count | 339 |
| supersession_reciprocity | 1.0 |
| evidence_ref_reachability | 1.0 |
| real_history_privacy_pass_rate | 1.0 |

Review reason distribution after low-risk same-scope compression:

| reason | count |
| --- | ---: |
| ambiguous_scope_narrowing_requires_review | 51 |
| low_confidence_semantic_overlap_requires_review | 152 |

Safe scope-pair distribution after compression:

| scope pair bucket | count |
| --- | ---: |
| different_layer | 26 |
| same_layer_different_scope | 33 |
| same_scope | 144 |

The compression rule is intentionally narrow: it only compresses same-layer,
same-scope `low_confidence_semantic_overlap_requires_review` rows that share the
same current memory node. Ambiguous scope narrowing and cross-scope/cross-layer
reviews stay explicit in the manual review queue.

## Real Archive Source Drilldown Governance Snapshot

Date: 2026-06-22

This run traversed deployment archive memory `raw_refs` with the reusable search
policy code and emitted aggregate JSON only. It did not render private source
records, memory text, source paths, raw refs, queries, or evidence snippets.

| metric | value |
| --- | ---: |
| memory_count | 1376 |
| represented_memory_count | 1376 |
| raw_ref_count | 2140 |
| source_ref_reachability | 1.0 |
| source_depth_policy_pass_rate | 1.0 |
| unsafe_source_ref_rejected_count | 0 |
| raw_preview_authorization_pass_rate | 1.0 |
| raw_preview_redaction_pass_rate | 1.0 |
| source_drilldown_privacy_pass_rate | 1.0 |
| available_source_ref_count | 2140 |
| unavailable_source_ref_count | 0 |

Reason distribution:

| reason | count |
| --- | ---: |
| source_map_reachable | 2140 |

The deployment archive passed the stricter source-map anchor audit after
treating the legacy `explicit_memory` source-map anchor as a controlled alias
for `source_record`.

## Real Archive Lifecycle Review Decision Snapshot

Date: 2026-06-23

This run used the reusable `apply_memory_review_decisions.py` dry-run and write
commands against the private deployment archive. The commands emitted aggregate
JSON only and did not render private memory text, source paths, raw refs, review
candidate content, queries, or memory ids.

Future induction review authoring should use
`author_induction_review_decisions.py --dry-run` followed by `--write` only to
append aggregate-safe skeleton rows, then keep manual action selection inside
the private deployment archive before apply preflight/write.

| metric | value |
| --- | ---: |
| review_candidate_count_before_apply | 202 |
| review_candidate_count_after_apply | 197 |
| decision_count | 6 |
| applied_decision_count | 2 |
| ignored_decision_count | 4 |
| action_counts.approve_supersedes | 2 |
| action_counts.noop | 2 |
| action_counts.reject | 2 |
| pre_apply_dry_run.relation_records_before.supersedes | 1 |
| pre_apply_dry_run.relation_records_before.superseded_by | 1 |
| pre_apply_dry_run.relation_records_after.supersedes | 2 |
| pre_apply_dry_run.relation_records_after.superseded_by | 2 |
| post_apply_dry_run.relation_records.supersedes | 2 |
| post_apply_dry_run.relation_records.superseded_by | 2 |
| records_with_any_lifecycle_relation | 4 |
| reciprocal_supersession_ok | 1 |
| ignored_non_mutating_ok | 1 |
| stale_search_suppressed | 1 |
| lifecycle_integrity.score | 1.0 |
| lifecycle_integrity.broken_refs | 0 |
| lifecycle_integrity.illegal_state_records | 0 |
| audit_status | passed |
| shadow_eval_v2_gate_status | passed |
| shadow_eval_v2.noise_sources_at_5.inactive_lifecycle | 0 |

The reusable tool now supports a private
`reviews/memory_lifecycle_decisions.jsonl` file for reviewed lifecycle
decisions. The private deployment archive now has a small calibrated batch:
two reviewed supersession decisions applied to real-history memory nodes and
four reviewed `noop`/`reject` decisions kept non-mutating. The proof keeps the
private decision file and real identifiers in the deployment repository while
recording only aggregate counts in this reusable skill repository.

## Real Archive Candidate Quality Calibration Snapshot

Date: 2026-06-23

This run tightened the review-candidate generator with an aggregate-derived
minimum overlap rule for `ambiguous_scope_narrowing_requires_review`. The rule
keeps ambiguous scope narrowing candidates only when `overlap_ratio >= 0.45`.
It did not render private memory text, source paths, raw refs, review candidate
content, queries, or memory ids.

| metric | value |
| --- | ---: |
| review_candidate_count_before | 197 |
| review_candidate_count_after | 176 |
| removed_candidate_count | 21 |
| removed_reason_counts.ambiguous_scope_narrowing_requires_review | 21 |
| removed_overlap_ratio_bucket_counts.lt_0.45 | 21 |
| after_candidate_type_counts.ambiguous_semantic_lifecycle | 132 |
| after_candidate_type_counts.compressed_low_risk_semantic_lifecycle | 44 |
| after_reason_counts.ambiguous_scope_narrowing_requires_review | 26 |
| after_reason_counts.low_confidence_semantic_overlap_requires_review | 150 |
| after_overlap_ratio_bucket_counts.0.45-0.59 | 88 |
| after_overlap_ratio_bucket_counts.0.60-0.74 | 54 |
| after_overlap_ratio_bucket_counts.0.75-1.00 | 34 |
| after_overlap_token_bucket_counts.0-5 | 107 |
| after_overlap_token_bucket_counts.6-8 | 42 |
| after_overlap_token_bucket_counts.9-12 | 18 |
| after_overlap_token_bucket_counts.13+ | 9 |
| shadow_eval_v2_gate_status | passed |
| shadow_eval_v2.memory_precision_at_5 | 0.3978494623655914 |
| shadow_eval_v2.top_k_noise_at_5 | 0.6021505376344086 |
| shadow_eval_v2.noise_sources_at_5.broad_lexical_match | 52 |
| shadow_eval_v2.noise_sources_at_5.scope_mixed | 4 |
| audit_status | passed |

The candidate-quality change removed the entire `<0.45` overlap-ratio bucket
from ambiguous scope narrowing review while preserving the existing v2 shadow
eval thresholds. The top-k noise profile is unchanged by design; this slice
improves manual review signal density, not search ranking.

## Real Archive Top-K Noise Reduction Snapshot

Date: 2026-06-23

This run tightened memory result ranking with same topic/scope diversification:
after scoring memory hits, only the highest-scoring hit for each
`(layer, scope, topic)` bucket is retained. The run used private redacted v2
shadow cases and emitted aggregate JSON only. It did not render private memory
text, source paths, raw refs, shadow case content, queries, or memory ids.

| metric | before | after |
| --- | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.3978494623655914 | 0.42424242424242425 |
| top_k_noise_at_5 | 0.6021505376344086 | 0.5757575757575757 |
| noise_sources_at_5.broad_lexical_match | 52 | 35 |
| noise_sources_at_5.scope_mixed | 4 | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 |
| case_noise_result_count_distribution.1 | 1 | 7 |
| case_noise_result_count_distribution.2 | 2 | 4 |
| case_noise_result_count_distribution.3 | 1 | 1 |
| case_noise_result_count_distribution.4_plus | 12 | 5 |
| abstain_pass_rate | 1.0 | 1.0 |
| active_memory_suppression | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |
| audit_status | passed | passed |
| shadow_eval_v2_gate_status | passed | passed |

The change reduces broad lexical top-k fill without changing case-level recall,
abstention, active-memory suppression, privacy, provenance, or lifecycle
integrity gates. It intentionally favors a more diverse top-k set over listing
multiple near-neighbor memories with the same layer, scope, and topic.

## Real Archive Relative Memory Score Floor Snapshot

Date: 2026-06-29

This run tightened memory result pruning after memory scoring and same
topic/scope diversification: retained memory hits must now score at least 99%
of the top memory hit for the query, after earlier 85% and 95% floors. The run
used the private deployment archive's redacted v2 shadow cases and emitted
aggregate JSON only. It did not render private memory text, source paths, raw
refs, shadow case content, queries, or memory ids.

| metric | 85% floor | 95% floor | 99% floor |
| --- | ---: | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.42424242424242425 | 0.5 | 0.6086956521739131 |
| top_k_noise_at_5 | 0.5757575757575757 | 0.5 | 0.3913043478260869 |
| noise_sources_at_5.broad_lexical_match | 35 | 25 | 15 |
| noise_sources_at_5.scope_mixed | 3 | 3 | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 | 0 |
| abstain_pass_rate | 1.0 | 1.0 | 1.0 |
| active_memory_suppression | 1.0 | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 | 0 |
| provenance_coverage.score | 1.0 | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 | 1.0 |
| audit_status | passed | passed | passed |
| shadow_eval_v2_gate_status | passed | passed | passed |

The change removes another slice of broad lexical top-k fill without changing
case-level recall, abstention, active-memory suppression, privacy, provenance,
or lifecycle integrity gates. It does not solve real retrieval quality: the
remaining top-k noise is still 0.3913043478260869, and scope-mixed noise is
unchanged. The v1 readiness gate keeps the lower 0.4 precision and 0.6 noise
thresholds as regression floors rather than raising them to this latest local
result.

## Real Archive Extended V1 Gate Snapshot

Date: 2026-06-29

This run used the current reusable `shadow_eval_memory_archive.py` and
`v1_readiness_gate.py` against the private deployment archive's redacted v2
probe cases. The shadow report was written only outside this repository and
contained aggregate JSON. It did not render private probe cases, queries,
memory IDs, memory text, source refs, source paths, source content, or raw refs.
Current reruns must expose those fields in the report-level `privacy` block or
the v1 readiness gate rejects the private shadow evidence.

Commands:

```bash
python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v2.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  --fail-under-file /path/to/private-agent-memory/eval/shadow_eval_real_history_v2.fail-under.json \
  --fail-over-file /path/to/private-agent-memory/eval/shadow_eval_real_history_v2.fail-over.json \
  > /tmp/private-shadow-eval.json

python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --shadow-report /tmp/private-shadow-eval.json \
  --require-shadow \
  > /tmp/private-v1-readiness-shadow.json
```

Extended readiness summary:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 5 |
| v1_readiness.scorecard.required_passed | 5 |
| v1_readiness.scorecard.optional_dimensions | 2 |
| v1_readiness.scorecard.optional_passed | 0 |
| public_benchmark_adapter.status | not_run_optional |
| real_archive_shadow_eval.status | passed |
| generated_answer_eval.status | not_run_optional |
| privacy.aggregate_only | true |
| shadow_privacy.private_probe_cases_rendered | false |
| shadow_privacy.queries_rendered | false |
| shadow_privacy.memory_ids_rendered | false |
| shadow_privacy.source_refs_rendered | false |
| shadow_privacy.raw_refs_rendered | false |
| shadow_quality_floor.memory_precision_at_5 | >= 0.4 |
| shadow_quality_floor.top_k_noise_at_5 | <= 0.6 |
| shadow_quality_floor.abstain_pass_rate | >= 1.0 |
| shadow_quality_floor.active_memory_suppression | >= 1.0 |
| shadow_quality_floor.noise_sources_at_5.scope_mixed | <= 3 |
| shadow_quality_floor.noise_sources_at_5.inactive_lifecycle | <= 0 |

Private real-archive shadow metrics:

| metric | value |
| --- | ---: |
| archive.memory_records | 1402 |
| archive.legacy_session_records | 275 |
| probe_cases.cases | 27 |
| probe_cases.positive_cases | 24 |
| probe_cases.abstain_cases | 3 |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 0.6086956521739131 |
| top_k_noise_at_5 | 0.3913043478260869 |
| noise_sources_at_5.broad_lexical_match | 15 |
| noise_sources_at_5.scope_mixed | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 |
| abstain_pass_rate | 1.0 |
| active_memory_suppression | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| forbidden_output_violations | 0 |
| provenance_coverage.score | 1.0 |
| provenance_coverage.evidence_ref_coverage | 1.0 |
| lifecycle_integrity.score | 1.0 |
| lifecycle_integrity.broken_refs | 0 |
| lifecycle_integrity.illegal_state_records | 0 |
| audit_status | passed |

This is stronger than the packaged-only `core_synthetic_ready` baseline because
the private deployment archive must pass recall, abstention, active-memory
suppression, privacy, provenance, lifecycle, and audit gates under
`--require-shadow`, and the v1 gate now rejects private shadow reports whose
report-level privacy shape does not explicitly rule out rendered probe cases,
queries, memory IDs, source refs, and raw refs. Current reruns must also satisfy
a minimum real-archive retrieval quality floor:
`memory_precision_at_5 >= 0.4`, `top_k_noise_at_5 <= 0.6`,
`abstain_pass_rate >= 1.0`, `active_memory_suppression >= 1.0`,
`noise_sources_at_5.scope_mixed <= 3`, and
`noise_sources_at_5.inactive_lifecycle <= 0`. This prevents recall-only
readiness claims. The top-k profile still shows a real quality gap:
case-level recall is perfect on the private probe set, but precision is only
0.5 and most remaining noise is broad lexical match fill. Public benchmark
adapter evidence is not included in this shadow-only run; the current combined
gate below adds 100-case adapted public evidence, but still does not replace a
full public benchmark evaluation.

## Public Adapter Smoke Snapshot

Date: 2026-06-29

This run used a five-object sample from the public LongMemEval cleaned
`longmemeval_s_cleaned` split, sampled outside this repository from:
`https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned`.
The sample, converted cases, synthetic archive, details, and JSON reports were
written only under `/tmp`. No public benchmark raw records were committed.

This is a public-adapter smoke test, not a LongMemEval leaderboard result. It
proves that real public benchmark rows can pass through the current converter,
synthetic archive builder, layered recall benchmark, and v1 readiness gate with
the required public-adapter provenance fields. It does not evaluate retrieval
over the full public corpus or the original benchmark answer-generation
protocol.

Commands:

```bash
python3 benchmarks/convert_public_memory_benchmark.py \
  --source longmemeval \
  --input /tmp/longmemeval_s_cleaned_first5_20260629.json \
  --output /tmp/my_precious_public_adapter_20260629/longmemeval_cases.jsonl \
  --build-synthetic-archive /tmp/my_precious_public_adapter_20260629/archive

python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my_precious_public_adapter_20260629/archive \
  --cases /tmp/my_precious_public_adapter_20260629/longmemeval_cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my_precious_public_adapter_20260629/details.jsonl \
  --fail-under case_pass_rate=1.0 \
  --fail-under memory_recall_at_5=1.0 \
  --fail-under answer_reachability=1.0 \
  --fail-over privacy_leak_count=0 \
  --fail-over failed_case_count=0 \
  > /tmp/my_precious_public_adapter_20260629/layered_report.json

python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --public-report /tmp/my_precious_public_adapter_20260629/layered_report.json \
  --shadow-report /tmp/private-shadow-eval.json \
  --require-public \
  --require-shadow \
  > /tmp/private-v1-readiness-public-shadow.json
```

Public-adapter smoke metrics:

| metric | value |
| --- | ---: |
| source_dataset | LongMemEval cleaned |
| source_split | longmemeval_s_cleaned |
| sampled_public_objects | 5 |
| sample_sha256 | ab78de9138e5580cda2c196973013c7f7915ec52cdbfa0efb8961af2e83de7d8 |
| converted_case_count | 5 |
| converted_cases_sha256 | 2a33530937be285cf7f85d446f621b90f92a9c5eab41b258ee23e6aeeab597ab |
| source_benchmarks.LongMemEval | 5 |
| case_origins.public_benchmark_adapter | 5 |
| public_adapter.case_pass_rate | 1.0 |
| public_adapter.memory_recall_at_5 | 1.0 |
| public_adapter.memory_precision_at_5 | 1.0 |
| public_adapter.answer_reachability | 1.0 |
| public_adapter.answer_normalized_reachability | 1.0 |
| public_adapter.answer_token_f1 | 1.0 |
| public_adapter.privacy_leak_count | 0 |
| public_adapter.failed_case_count | 0 |
| public_adapter.claim_boundary | adapted local score only |

Combined public-plus-shadow v1 readiness summary:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 5 |
| v1_readiness.scorecard.required_passed | 5 |
| v1_readiness.scorecard.optional_dimensions | 1 |
| v1_readiness.scorecard.optional_passed | 0 |
| public_benchmark_adapter.status | passed |
| real_archive_shadow_eval.status | passed |
| generated_answer_eval.status | not_run_optional |
| layered_recall.raw_preview_authorization_pass_rate | 1.0 |
| privacy.aggregate_only | true |

## Public Adapter Limited-Read Probe

Date: 2026-06-29

After the five-object smoke gate, the converter was extended so `--limit` can
stop early for JSONL files and top-level JSON arrays. This makes bounded probes
against large public benchmark downloads practical without committing public
records or requiring the local file to contain the complete upstream JSON array.

This probe used the first 80 MiB of the public LongMemEval cleaned
`longmemeval_s_cleaned` split, written only under `/tmp` from:
`https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned`. The converter
read the first 100 top-level records with `--limit 100`, wrote converted cases
and a synthetic archive under `/tmp`, then scored that archive with the layered
recall benchmark.

This is a passing strict public-adapter probe, not a LongMemEval leaderboard
result. It proves the adapter can process a larger bounded public sample, that
positive retrieval-side cases can pass at 1.0, and that public abstention rows
whose reference answers say the requested fact was not mentioned can pass with
structured related-context retrieval instead of a brittle no-hit-only rule. It
still does not run the original public answer-generation protocol or claim full
public benchmark parity.

Commands:

```bash
curl -L --fail --range 0-83886079 \
  -o /tmp/my_precious_public_limit_20260629/longmemeval_s_head80m.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

python3 benchmarks/convert_public_memory_benchmark.py \
  --source longmemeval \
  --input /tmp/my_precious_public_limit_20260629/longmemeval_s_head80m.json \
  --output /tmp/my_precious_public_limit_20260629/longmemeval_cases_100.jsonl \
  --limit 100 \
  --build-synthetic-archive /tmp/my_precious_public_limit_20260629/archive_100_after_fix

python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my_precious_public_limit_20260629/archive_100_after_fix \
  --cases /tmp/my_precious_public_limit_20260629/longmemeval_cases_100.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my_precious_public_limit_20260629/details_100_raw_auth_gate.jsonl \
  --fail-under case_pass_rate=1.0 \
  --fail-under memory_recall_at_5=1.0 \
  --fail-under answer_reachability=1.0 \
  --fail-under abstention_accuracy=1.0 \
  --fail-under raw_preview_authorization_pass_rate=1.0 \
  --fail-over privacy_leak_count=0 \
  --fail-over failed_case_count=0 \
  > /tmp/my_precious_public_limit_20260629/layered_report_100_raw_auth_gate.json

python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --public-report /tmp/my_precious_public_limit_20260629/layered_report_100_raw_auth_gate.json \
  --require-public \
  > /tmp/my_precious_v1_public_100_abstention_gate_20260629.json

python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v2.jsonl \
  --fail-under-file /path/to/private-agent-memory/eval/shadow_eval_real_history_v2.fail-under.json \
  --fail-over-file /path/to/private-agent-memory/eval/shadow_eval_real_history_v2.fail-over.json \
  > /tmp/my_precious_private_shadow_v2_current_20260629.json

python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --public-report /tmp/my_precious_public_limit_20260629/layered_report_100_raw_auth_gate.json \
  --shadow-report /tmp/my_precious_private_shadow_v2_current_20260629.json \
  --require-public \
  --require-shadow \
  > /tmp/my_precious_v1_public100_shadow_raw_auth_current_20260629.json
```

Limited-read conversion metrics:

| metric | value |
| --- | ---: |
| head_bytes | 83,886,080 |
| head_sha256 | 9e8b4180467c348d6d553c9e1c5dcd2764ae825291a789e96e2f87a128cb0f61 |
| converted_case_count | 100 |
| converted_cases_sha256 | daa6294cbd6b857d1d8e4149cc3f5ffd0c06fb5b4a5ae1f522a9f4340a6b5596 |

Strict 100-case probe metrics:

| metric | value |
| --- | ---: |
| source_benchmarks.LongMemEval | 100 |
| case_origins.public_benchmark_adapter | 100 |
| positive_cases | 94 |
| abstain_cases | 6 |
| case_pass_rate | 1.0 |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 1.0 |
| source_reachability | 1.0 |
| source_ref_reachability | 1.0 |
| answer_reachability | 1.0 |
| answer_normalized_reachability | 1.0 |
| answer_token_f1 | 1.0 |
| abstention_accuracy | 1.0 |
| abstention_answer_cases | 6 |
| abstention_answer_pass_rate | 1.0 |
| raw_preview_authorization_pass_rate | 1.0 |
| raw_preview_redaction_pass_rate | 1.0 |
| source_drilldown_privacy_pass_rate | 1.0 |
| privacy_leak_count | 0 |
| top_k_noise_at_5 | 0.0 |
| failed_case_count | 0 |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 4 |
| v1_readiness.scorecard.required_passed | 4 |
| v1_readiness.scorecard.optional_dimensions | 2 |
| v1_readiness.scorecard.optional_passed | 0 |
| v1_readiness.public_benchmark_adapter.status | passed |
| generated_answer_eval.status | not_run_optional |
| public_adapter.claim_boundary | adapted local score only |

## Public Generated-Answer Adapter Probe

Date: 2026-06-29

This probe used the same local 100-case LongMemEval adapted archive under
`/tmp`. It ran `tools/generate_answer_records.py` to create answer records, then
scored those records with `benchmarks/generated_answer_benchmark.py`. The
generated answer records, details file, converted public cases, and synthetic
archive remained outside this repository.

Commands:

```bash
python3 templates/agent-memory-repo/tools/generate_answer_records.py \
  --repo /tmp/my_precious_public_limit_20260629/archive_100_after_fix \
  --cases /tmp/my_precious_public_limit_20260629/longmemeval_cases_100.jsonl \
  --output /tmp/my_precious_public_limit_20260629/generated_answer_records_100_query_support.jsonl \
  --limit 5 \
  > /tmp/my_precious_public_limit_20260629/generated_answer_adapter_report_100_query_support.json

python3 benchmarks/generated_answer_benchmark.py \
  --cases /tmp/my_precious_public_limit_20260629/longmemeval_cases_100.jsonl \
  --answers /tmp/my_precious_public_limit_20260629/generated_answer_records_100_query_support.jsonl \
  --details-jsonl /tmp/my_precious_public_limit_20260629/generated_answer_details_100_query_support.jsonl \
  > /tmp/my_precious_public_limit_20260629/generated_answer_report_100_query_support.json
```

Adapter aggregate report:

| metric | value |
| --- | ---: |
| cases | 100 |
| answers_written | 100 |
| answerability_policy | query_token_support |
| memory_answer_count | 94 |
| abstention_answer_count | 6 |
| no_hit_count | 1 |
| unsupported_hit_count | 5 |
| source_benchmarks.LongMemEval | 100 |
| case_origins.public_benchmark_adapter | 100 |
| privacy.aggregate_only | true |
| privacy.queries_rendered | false |
| privacy.generated_answers_rendered | false |
| privacy.reference_answers_rendered | false |
| privacy.source_paths_rendered | false |
| privacy.raw_refs_rendered | false |

Full 100-case generated-answer metrics:

| metric | value |
| --- | ---: |
| reference_answer_cases | 89 |
| answer_scorable_cases | 89 |
| answer_scorable_case_rate | 0.89 |
| positive_without_reference_answer | 11 |
| case_pass_rate | 0.89 |
| answer_normalized_match_rate | 0.8829787234042553 |
| answer_token_f1 | 0.8829787234042553 |
| abstention_accuracy | 1.0 |
| failed_case_count | 11 |
| missing_answer_count | 0 |
| duplicate_answer_count | 0 |
| unknown_answer_count | 0 |
| privacy_leak_count | 0 |
| source_benchmarks.LongMemEval | 100 |
| case_origins.public_benchmark_adapter | 100 |

Breakdown:

| subset | cases | case_pass_rate | answer_normalized_match_rate | answer_token_f1 | abstention_accuracy | failed_case_count | privacy_leak_count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| reference-positive | 83 | 1.0 | 1.0 | 1.0 | 0.0 | 0 | 0 |
| reference-abstain | 6 | 1.0 | 0.0 | 0.0 | 1.0 | 0 | 0 |
| all reference-answer cases | 89 | 1.0 | 1.0 | 1.0 | 1.0 | 0 | 0 |
| all 100 adapted cases | 100 | 0.89 | 0.8829787234042553 | 0.8829787234042553 | 1.0 | 11 | 0 |

`v1_readiness_gate.py --require-answer` correctly rejects the full public
100-case answer report because eleven positive cases have no reference answer
and therefore cannot prove answer correctness:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | not_ready |
| generated_answer_eval.status | failed |
| generated_answer_eval.case_pass_rate | 0.89 |
| generated_answer_eval.answer_normalized_match_rate | 0.8829787234042553 |
| generated_answer_eval.abstention_accuracy | 1.0 |
| generated_answer_eval.failed_case_count | 11 |
| generated_answer_eval.positive_without_reference_answer | 11 |
| generated_answer_eval.answer_scorable_case_rate | 0.89 |

The answer-scorable public subset keeps the same 83 reference-positive cases
and 6 abstention cases, while excluding the 11 positive rows that carry no
reference answer:

```bash
python3 templates/agent-memory-repo/tools/generate_answer_records.py \
  --repo /tmp/my_precious_public_limit_20260629/archive_100_after_fix \
  --cases /tmp/my_precious_public_limit_20260629/longmemeval_cases_100_answer_scorable.jsonl \
  --output /tmp/my_precious_public_limit_20260629/generated_answer_records_89_query_support.jsonl \
  --limit 5 \
  > /tmp/my_precious_public_limit_20260629/generated_answer_adapter_report_89_query_support.json

python3 benchmarks/generated_answer_benchmark.py \
  --cases /tmp/my_precious_public_limit_20260629/longmemeval_cases_100_answer_scorable.jsonl \
  --answers /tmp/my_precious_public_limit_20260629/generated_answer_records_89_query_support.jsonl \
  --details-jsonl /tmp/my_precious_public_limit_20260629/generated_answer_details_89_query_support.jsonl \
  --fail-under case_pass_rate=1.0 \
  --fail-under answer_normalized_match_rate=1.0 \
  --fail-under abstention_accuracy=1.0 \
  --fail-under answer_scorable_case_rate=1.0 \
  --fail-over privacy_leak_count=0 \
  --fail-over failed_case_count=0 \
  --fail-over missing_answer_count=0 \
  --fail-over duplicate_answer_count=0 \
  --fail-over unknown_answer_count=0 \
  --fail-over positive_without_reference_answer=0 \
  > /tmp/my_precious_public_limit_20260629/generated_answer_report_89_query_support.json
```

Answer-scorable subset metrics:

| metric | value |
| --- | ---: |
| cases | 89 |
| positive_cases | 83 |
| abstain_cases | 6 |
| reference_answer_cases | 89 |
| answer_scorable_cases | 89 |
| answer_scorable_case_rate | 1.0 |
| positive_without_reference_answer | 0 |
| adapter.memory_answer_count | 83 |
| adapter.abstention_answer_count | 6 |
| adapter.no_hit_count | 1 |
| adapter.unsupported_hit_count | 5 |
| case_pass_rate | 1.0 |
| answer_normalized_match_rate | 1.0 |
| answer_token_f1 | 1.0 |
| abstention_accuracy | 1.0 |
| failed_case_count | 0 |
| missing_answer_count | 0 |
| duplicate_answer_count | 0 |
| unknown_answer_count | 0 |
| privacy_leak_count | 0 |
| source_benchmarks.LongMemEval | 89 |
| case_origins.public_benchmark_adapter | 89 |

The combined packaged-plus-public readiness run accepts that answer-scorable
report:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 6 |
| v1_readiness.scorecard.required_passed | 6 |
| public_benchmark_adapter.status | passed |
| generated_answer_eval.status | passed |
| generated_answer_eval.answer_scorable_case_rate | 1.0 |
| generated_answer_eval.positive_without_reference_answer | 0 |

This closes the public-adapter answer abstention gap without reading
`expected_abstain` or `reference_answer` inside the answer-record adapter. The
adapter now requires the selected memory hit to support the query through
complete normalized query text or query-token coverage before extracting an
answer; unsupported top hits become the standard abstention answer. It does not
close full public generated-answer readiness because 11 positive adapted cases
still lack reference answers for grading, and it does not claim live model
answer quality or private real-archive generated-answer behavior.

Current packaged-plus-public-answer v1 readiness summary:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 6 |
| v1_readiness.scorecard.required_passed | 6 |
| v1_readiness.scorecard.optional_dimensions | 1 |
| v1_readiness.scorecard.optional_passed | 0 |
| public_benchmark_adapter.status | passed |
| real_archive_shadow_eval.status | not_run_optional |
| generated_answer_eval.status | passed for 89 answer-scorable public cases |
| generated_answer_eval.answer_scorable_case_rate | 1.0 |
| generated_answer_eval.positive_without_reference_answer | 0 |
| privacy.aggregate_only | true |
| privacy.memory_text_rendered | false |
| privacy.private_probe_cases_rendered | false |
| privacy.queries_rendered | false |
| privacy.source_paths_rendered | false |
| privacy.raw_refs_rendered | false |

## Private Generated-Answer Dogfood Scoreability Audit

Date: 2026-06-29

The private redacted real-history shadow probe was inspected only for aggregate
schema readiness. No private queries, case IDs, memory IDs, memory text, source
paths, raw refs, generated answers, or reference answers were rendered or copied
into this repository.

Aggregate schema counts:

| probe set | cases | rows with reference_answer | rows with expected_abstain | rows with forbidden_output_patterns |
| --- | ---: | ---: | ---: | ---: |
| redacted real-history v1 | 6 | 0 | 0 | 3 |
| redacted real-history v2 | 27 | 0 | 3 | 9 |

This means the existing private shadow probes are retrieval/no-hit/provenance
fixtures, not generated-answer scoring fixtures. They cannot produce a private
generated-answer readiness claim because positive answer correctness requires
reference answers. The generated-answer benchmark and v1 readiness gate now make
that boundary explicit through `answer_scorable_case_rate` and
`positive_without_reference_answer`: a required answer report with unscored
positive rows is rejected even if other answer metrics are present.

The v1 readiness gate can now also require a specific aggregate answer-evidence
stream without rendering or committing the private case rows:

```bash
python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --answer-report /tmp/private-generated-answer-report.json \
  --require-answer \
  --require-answer-case-origin private_dogfood
```

For public or mixed answer evaluations, the same gate can require a named
`source_benchmarks` key with
`--require-answer-source-benchmark NAME`. These source/origin checks make the
answer dimension required and prove only aggregate provenance for the supplied
answer report. They do not create private reference-answer cases, do not score
live model generation, and do not turn the existing shadow probe fixtures into
generated-answer fixtures.

## Private Dogfood Generated-Answer Run

Date: 2026-06-30

`author_generated_answer_cases.py`, `generate_answer_records.py`,
`generated_answer_benchmark.py`, and `v1_readiness_gate.py` were run against
the private deployment archive. The private case, answer, audit, benchmark, and
gate files were written only under the private deployment archive's `eval/`
directory. No private queries, case IDs, reference answers, generated answers,
memory IDs, source paths, raw refs, or memory text were rendered or copied into
this reusable skill repository.

The first private dogfood run authored only positive answer cases, so the answer
benchmark passed positive matching but the v1 readiness gate rejected it because
there were no expected-abstain cases and `abstention_accuracy` was therefore
`0.0`. The follow-up run used `--abstain-limit 5` to add deterministic no-hit
negative cases without rendering their query text.

Aggregate authoring metrics:

| metric | value |
| --- | ---: |
| candidate_memory_count | 1402 |
| selected_case_count | 25 |
| positive_case_count | 20 |
| abstain_case_count | 5 |
| would_write_count | 25 |
| written_count | 25 |
| source_benchmarks.MyPreciousPrivateDogfood | 25 |
| case_origins.private_dogfood | 25 |
| skip_counts.insufficient_query_terms | 2 |

Aggregate case-audit metrics:

| metric | value |
| --- | ---: |
| cases | 25 |
| positive_cases | 20 |
| abstain_cases | 5 |
| reference_answer_cases | 20 |
| answer_scorable_case_rate | 1.0 |
| positive_without_reference_answer | 0 |
| unsafe_aggregate_identifier_count | 0 |

Aggregate answer-adapter metrics:

| metric | value |
| --- | ---: |
| cases | 25 |
| answers_written | 25 |
| memory_answer_count | 20 |
| abstention_answer_count | 5 |
| no_hit_count | 5 |
| unsupported_hit_count | 0 |

Aggregate answer-benchmark metrics:

| metric | value |
| --- | ---: |
| cases | 25 |
| positive_cases | 20 |
| abstain_cases | 5 |
| answer_scorable_case_rate | 1.0 |
| case_pass_rate | 1.0 |
| answer_normalized_match_rate | 1.0 |
| abstention_accuracy | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| privacy_leak_count | 0 |
| failed_case_count | 0 |
| missing_answer_count | 0 |
| duplicate_answer_count | 0 |
| unknown_answer_count | 0 |
| positive_without_reference_answer | 0 |

Private answer dogfood v1 readiness summary:

| metric | value |
| --- | ---: |
| v1_readiness.overall_status | extended_evidence_ready |
| v1_readiness.scorecard.required_dimensions | 5 |
| v1_readiness.scorecard.required_passed | 5 |
| v1_readiness.scorecard.optional_dimensions | 2 |
| v1_readiness.scorecard.optional_passed | 0 |
| generated_answer_eval.status | passed |
| generated_answer_eval.abstention_accuracy | 1.0 |
| generated_answer_eval.answer_normalized_match_rate | 1.0 |
| generated_answer_eval.answer_scorable_case_rate | 1.0 |

This proves the reusable deployment helper can author a bounded private dogfood
case set from active layered memories, include expected-abstain negative cases,
generate extractive answer records, and satisfy the generated-answer dimension
of the v1 readiness gate with aggregate-only reports. The claim remains bounded:
the positive answers are extractive from existing memories, the negative cases
are deterministic no-hit probes, and this is not a live model answer-quality
benchmark or proof of long-horizon human-authored memory behavior.

## V1 Completion Audit

Date: 2026-06-30

Code point: `dcf69c7 Add abstain cases to private answer dogfood`

Fresh current-code command:

```bash
python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --answer-report /path/to/private-agent-memory/eval/generated_answer_private_dogfood_abstain_benchmark_20260630.json \
  --require-answer \
  --require-answer-case-origin private_dogfood \
  --require-answer-source-benchmark MyPreciousPrivateDogfood
```

The command emitted aggregate-only JSON and returned success. It did not render
private case rows, queries, reference answers, generated answers, memory text,
source paths, or raw refs.

Current required v1 gate summary:

| dimension | status | evidence level | key metrics |
| --- | --- | --- | --- |
| layered_recall | passed | packaged synthetic | `memory_recall_at_5=1.0`, `layer_path_success_rate=1.0`, `drilldown_success_rate=1.0`, `source_ref_reachability=1.0`, `raw_preview_authorization_pass_rate=1.0`, `privacy_leak_count=0` |
| automatic_induction | passed | packaged synthetic | `natural_induction_success_rate=1.0`, `cross_project_generalization_rate=1.0`, `forced_memory_capture_rate=1.0`, `induction_review_routing_rate=1.0`, `privacy_leak_count=0` |
| e2e_induction_to_recall | passed | packaged synthetic | `e2e_memory_recall_at_5=1.0`, `e2e_layer_assignment_accuracy=1.0`, `e2e_session_drilldown_rate=1.0`, `e2e_source_policy_pass_rate=1.0`, `privacy_leak_count=0` |
| source_stream_registry | passed | packaged synthetic | `source_stream_update_rate=1.0`, `project_registry_independence_rate=1.0`, `archive_scope_assignment_rate=1.0`, `source_partition_assignment_rate=1.0`, `source_stream_evidence_reachability_rate=1.0`, `privacy_leak_count=0` |
| generated_answer_eval | passed | private deployment aggregate | `case_pass_rate=1.0`, `answer_normalized_match_rate=1.0`, `abstention_accuracy=1.0`, `answer_scorable_case_rate=1.0`, `privacy_leak_count=0` |

Current v1 readiness status:

| metric | value |
| --- | ---: |
| overall_status | extended_evidence_ready |
| required_dimensions | 5 |
| required_passed | 5 |
| optional_dimensions | 2 |
| optional_passed | 0 |

Requirement audit:

| target requirement | current status | evidence |
| --- | --- | --- |
| Reusable agent-neutral skills, not a private archive | satisfied | repository boundary in `AGENTS.md` and `docs/design.md`; setup/update/using skills separate setup, write, and read paths |
| Non-project-boundary memory path | satisfied for v1 | source-stream registry gate proves archive scope and source partition can update and recall without project registry dependence |
| Automatic induction | satisfied for v1 | updater and e2e gates pass natural induction, review routing, decision apply, forced capture, and privacy refusal/redaction metrics |
| Explicit forced memory | satisfied for v1 | updater and e2e gates include `forced_memory_capture_rate=1.0` and `e2e_forced_memory_recall_rate=1.0` |
| Layered recall across memory/session/source/raw evidence | satisfied for v1 | layered and e2e gates pass layer calibration, session drilldown, evidence/source reachability, source-depth policy, raw-preview authorization, and redaction checks |
| Safe drilldown from high-level memory to evidence/source | satisfied for v1 | source ref reachability, source-depth policy, source-drilldown privacy, raw-preview authorization, and raw-preview redaction are required gate metrics |
| Quantified readiness gate | satisfied for v1 | `v1_readiness_gate.py` returns `extended_evidence_ready` with 5/5 required dimensions passed |
| Privacy boundary proof | satisfied for v1 | all required reports are aggregate-only and gate privacy leak counts are zero; private dogfood artifacts remain in the private deployment archive |
| Deployment dogfood | satisfied for v1 | private dogfood answer flow authors, audits, answers, grades, and gates 20 positive plus 5 expected-abstain cases as aggregate-only evidence |

This audit closes the v1 required readiness target. The following are not v1
blockers and should be treated as v1.1 or research work unless the project goal
is explicitly widened:

- automatic ontology/source discovery beyond explicit source-stream rows;
- model-backed or human-authored generated-answer quality evaluation;
- official public leaderboard parity with LongMemEval, LoCoMo, Memora, RULER,
  or MemPalace-style systems;
- broader private real-archive shadow coverage and lower top-k noise floors;
- richer long-horizon lifecycle, decay, deletion, and multi-principal
  governance.

## V1.1 Real-Archive Shadow Gate Baseline

Date: 2026-06-30

Code point: `bef93e3 Document v1 readiness completion audit`

This starts v1.1 real-archive evidence hardening without adding new v1
features. The reusable repository now carries stricter aggregate shadow-gate
threshold files:

- `benchmarks/quality-gates/real_archive_shadow_v11.json`
- `benchmarks/quality-gates/real_archive_shadow_v11_max.json`

The gate files contain only numeric aggregate thresholds. They do not contain
private probe rows, queries, memory IDs, memory text, source refs, source paths,
raw refs, generated answers, or answer text.

Command:

```bash
python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v2.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  --fail-under-file benchmarks/quality-gates/real_archive_shadow_v11.json \
  --fail-over-file benchmarks/quality-gates/real_archive_shadow_v11_max.json \
  > /tmp/my_precious_v11_shadow_gate_20260630.json
```

The command emitted aggregate-only JSON and returned success against the
current private deployment archive. The private archive was read-only for this
run; the aggregate report was written under `/tmp`.

V1.1 gate thresholds:

| metric | v1 floor | v1.1 floor |
| --- | ---: | ---: |
| memory_precision_at_5 | 0.42424242424242425 | 0.6 |
| top_k_noise_at_5 | <= 0.5757575757575757 | <= 0.4 |
| noise_sources_at_5.broad_lexical_match | <= 35 | <= 15 |
| noise_sources_at_5.scope_mixed | <= 3 | <= 3 |
| noise_sources_at_5.inactive_lifecycle | <= 0 | <= 0 |
| noise_sources_at_5.low_signal_memory_node | <= 0 | <= 0 |

Current v1.1 aggregate result:

| metric | value |
| --- | ---: |
| archive.memory_records | 1402 |
| archive.legacy_session_records | 275 |
| probe_cases.cases | 27 |
| probe_cases.positive_cases | 24 |
| probe_cases.abstain_cases | 3 |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 0.6086956521739131 |
| top_k_noise_at_5 | 0.3913043478260869 |
| noise_sources_at_5.broad_lexical_match | 15 |
| noise_sources_at_5.scope_mixed | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 |
| abstain_pass_rate | 1.0 |
| abstain_false_positive_results | 0 |
| active_memory_suppression | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| forbidden_output_violations | 0 |
| provenance_coverage.score | 1.0 |
| lifecycle_integrity.score | 1.0 |
| audit_status | passed |
| diagnostics.failure_case_count | 8 |
| diagnostics.failure_types.top_k_noise | 8 |
| diagnostics.failure_types.recall_miss | 0 |
| diagnostics.failure_types.abstain_false_positive | 0 |
| diagnostics.failure_types.privacy_failure | 0 |

This is a gate-hardening step, not a search-quality breakthrough. It raises the
real-archive regression floor to the best known aggregate profile while keeping
the remaining gap visible: eight private probe cases still have top-k noise,
with `broad_lexical_match=15` and `scope_mixed=3`. A future v1.1 optimization
should stop unless it can reduce those aggregate counts without reducing
`memory_recall_at_5`, `abstain_pass_rate`, `active_memory_suppression`,
`privacy_boundary_pass_rate`, provenance coverage, or lifecycle integrity.

## Recommendation

Freeze the required v1 readiness target and proceed only with v1.1 or research
work that materially improves real-world evidence quality.

The system now has a bounded proof that high-level memories can be induced from
synthetic session events and that direct explicit memories can be written only
with evidence. It also has synthetic gates for semantic support merge,
refresh/supersession, contradiction, deprecation, false-merge prevention, and
evidence retention. It now also has an ambiguity review queue, explainable
consolidation traces, aggregate review-queue calibration metrics, and a narrow
same-scope low-risk compression rule for semantic lifecycle cases that should
not be auto-retired. Natural induction now has a separate aggregate-safe review
candidate surface for low-confidence, conflicting, and scope-changing synthetic
candidates, with evidence/source refs preserved and candidate text hashed rather
than rendered. It now also has a synthetic private decision/apply loop for those
candidates: approve decisions promote, while reject/noop decisions stay
non-mutating, with aggregate-only result indexes and aggregate-only
duplicate/conflict preflight. It also has an initial gated source-depth workflow
with synthetic quality gates and a real deployment aggregate baseline that
passes the stricter source-map anchor audit. Shadow
evaluation now has a private redacted real-history probe set with numeric
recall, precision, noise, abstention, suppression, privacy, provenance,
lifecycle, audit gates, and privacy-safe diagnostic grouping. The
post-hard-negative v2 run preserves recall while eliminating current no-hit
false positives and reducing broad lexical noise under redacted
natural-language labels. It still records scope-mixed and broad lexical top-k
noise. The real deployment archive now has an aggregate-only lifecycle review
decision tool and a calibrated real-history batch with reciprocal supersession
links, ignored non-mutating decisions, stale search suppression, audit pass, and
v2 shadow gate pass. It also has an aggregate-derived candidate-quality rule
that removes low-overlap ambiguous scope review noise while preserving current
shadow-eval gates. Same topic/scope result diversification now reduces
real-history top-k noise while preserving recall and privacy gates. A stricter
99% relative memory-score floor now removes another aggregate slice of broad
lexical real-history top-k fill while preserving recall, abstention, privacy,
provenance, and lifecycle gates; remaining top-k noise is
0.3913043478260869 and is not solved. The public adapter now has bounded-read
support for larger samples,
short-query ranking does not let low-signal short phrases outrank full-coverage
entity matches, and answer reachability can use verified local drilldown files
rather than only clipped search titles. The 100-case LongMemEval cleaned probe
now passes strict local public-adapter readiness with perfect positive-case
retrieval, source and answer reachability, privacy, and answer-level public
abstention metrics. The source-depth path now also requires an explicit
raw-preview authorization flag before redacted raw snippets render. The
reusable benchmark suite now also has an offline generated-answer grading gate
for provided answer records plus a packaged synthetic generated-answer fixture
that is wired into `--run-packaged --require-answer`; answer reports now also
need aggregate source benchmark and case-origin counts before the readiness gate
accepts them. The deployment template can now produce extractive answer records
from archive search hits for that grader, with aggregate-only stdout and no
reference-answer input. A private dogfood answer run now proves the reusable
case-authoring, extractive-answer, answer-benchmark, and v1 gate path on 20
positive cases plus 5 expected-abstain no-hit cases without copying private
case material into this repository. A public LongMemEval 100-case
generated-answer adapter probe now proves full positive reference-answer
extraction on 83 reference positive cases and full abstention accuracy on 6
public abstention cases. The 89-case answer-scorable public subset passes the
generated-answer gate at 1.0 for case pass rate, normalized answer match, token
F1, abstention accuracy, and privacy. The full 100-case answer report still
fails because 11 positive cases lack reference answers for scoring, so this is
answer-scorable public-adapter evidence rather than full public
generated-answer readiness. The explicit source-stream registry path now has a
packaged synthetic benchmark and is required by the core v1 readiness gate. The
current readiness runs still cannot claim live model answer quality or
long-horizon human-authored memory behavior. The suite now has a separate
aggregate-only
`generated_answer_case_audit.py` preflight for private or public answer case
sets before answer records exist. That audit can require source benchmark and
case-origin counts such as `MyPreciousPrivateDogfood` and `private_dogfood`,
and can gate `answer_scorable_case_rate`, `positive_without_reference_answer`,
and `unsafe_aggregate_identifier_count` without rendering private case IDs,
queries, or reference answers. The deployment template now also has
`author_generated_answer_cases.py`, which can author private dogfood case JSONL
from active layered memory nodes with aggregate-only stdout and optional
expected-abstain no-hit cases. This closes the reusable tooling gap for
creating, auditing, and grading a private dogfood answer case set through the
offline v1 gate. The remaining answer-quality gap is model-backed or
human-authored evaluation, not the reusable plumbing for aggregate private
dogfood evidence. The next valuable work is to broaden real-archive shadow
coverage, continue reducing remaining scope-mixed top-k noise, and broaden
consolidation/decay evidence.

## Next Roadmap After The Minimum Slice

1. Strengthen automatic induction.
   Move from literal `Reusable fact:` extraction toward a reviewable
   consolidation stage that can merge repeated facts, preserve contradictory
   evidence, route ambiguous scope changes to review, and avoid process-noise
   promotion.

2. Deepen lifecycle operations.
   Extend the semantic merge/refresh/deprecation path beyond the current review
   queue and trace v1 to handle richer confidence revision, decay, deletion
   policy, and noisy multi-month evidence histories.

3. Continue reducing project-boundary centrality.
   The archive now has opt-in `archive_scope` and `source_partition` keys, plus
   an explicit `config/source_streams.jsonl` runner path, so both the memory
   domain and high-water/source-hash stream can be independent from
   `project_path`. A packaged synthetic source-stream registry benchmark now
   gates this path through update, layered recall, evidence reachability, and
   source-policy checks. Automatic source discovery and ontology mapping are
   still not solved; source-stream rows are manual runtime policy.

4. Deepen source-depth governance.
   Keep raw source anchors private by default. The current CLI now requires a
   separate raw-preview authorization flag, but this is still a single-user
   confirmation gate rather than a multi-principal ACL. The next source-depth
   step is real-history robustness beyond aggregate dry-runs and, later, a
   policy model for multi-principal access.

5. Scale adapted public benchmarks locally.
   The converter can now run bounded larger-sample probes against downloaded
   public records outside the repository. The 100-case LongMemEval cleaned
   local probe passes memory/source/answer reachability, privacy, and
   answer-level abstention gates at 1.0. The reusable suite now has offline
   generated-answer grading for provided answers plus aggregate-only case-set
   scoreability audit and private case authoring before answers exist; the next
   step is to run the private dogfood answer flow in the deployment archive,
   plus larger bounded public samples, without committing private answer text.

6. Continue v2 hard-negative and no-hit quality.
   Keep probe cases in the deployment repository or another private local path,
   never in the reusable skill repository. Preserve the current recall and
   abstention gates, continue reducing remaining broad lexical and scope-mixed
   top-k noise, and keep quality changes tied to aggregate before/after buckets.

7. Add governance tests later.
   Do not make multi-principal access control part of the next immediate slice,
   but keep GateMem-style utility/access/forgetting as a future evaluation
   direction.
