# Layered Memory Readiness Evaluation

## Purpose

This document is a stage-gate evaluation for the reusable My Precious skill
repository. It records what the current implementation can measure reliably,
where the packaged benchmark can overstate readiness, and what remains before
the project can claim a full non-project-boundary layered memory system.

The conclusion is intentionally narrow: the current benchmark is a repeatable
local quality gate for retrieval, drilldown, stale suppression, lifecycle-link
reciprocity, abstention, and privacy-boundary behavior on synthetic archives. It
is not a direct leaderboard score against public long-memory systems such as
MemPalace, LongMemEval, LoCoMo, Memora, or RULER-style long-context retrieval
tests.

## Current Baseline

Baseline date: 2026-06-20

Code point used for the benchmark harness: `98d54ba`

Case file:
`benchmarks/cases/layered_recall_synthetic.jsonl`

Case fingerprint:
`84358ae2053eaa87145cd96be0b9aa463d35eef359157640359297e95646ac33`

Search implementation fingerprint:
`a92d90f51d779a4bd8c4089611a58386599246ce53a42accd0eaf3a16b8bc234`

Baseline commands:

```bash
python3 benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-layered-lifecycle-baseline-98d54ba \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors

python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-layered-lifecycle-baseline-98d54ba \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-layered-lifecycle-details-98d54ba.jsonl \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

Baseline result:

| Metric | Value |
| --- | ---: |
| cases | 34 |
| positive_cases | 29 |
| abstain_cases | 5 |
| answer_cases | 11 |
| evidence_text_cases | 3 |
| memory_recall_at_1 | 1.0 |
| memory_recall_at_5 | 1.0 |
| memory_mrr | 1.0 |
| memory_ndcg_at_5 | 1.0 |
| memory_precision_at_5 | 0.2787356321839081 |
| memory_micro_precision_at_5 | 0.24369747899159663 |
| memory_explainability | 1.0 |
| layer_calibration | 1.0 |
| scope_filter_recall | 1.0 |
| wrong_scope_suppression | 1.0 |
| session_drilldown_at_5 | 1.0 |
| source_reachability | 1.0 |
| source_precision_at_5 | 0.28218390804597704 |
| source_micro_precision_at_5 | 0.24786324786324787 |
| memory_evidence_ref_cases | 29 |
| memory_evidence_ref_reachability | 1.0 |
| lifecycle_supersession_cases | 9 |
| lifecycle_supersession_reciprocity | 1.0 |
| evidence_reachability | 1.0 |
| evidence_text_reachability | 1.0 |
| answer_reachability | 1.0 |
| answer_normalized_reachability | 1.0 |
| answer_token_f1 | 1.0 |
| abstention_accuracy | 1.0 |
| negative_memory_suppression | 1.0 |
| stale_memory_suppression | 1.0 |
| update_consistency | 1.0 |
| privacy_boundary_pass_rate | 1.0 |
| failed_case_count | 0 |
| case_pass_rate | 1.0 |

Latency for this local run was `9999.748 ms` total, `294.110 ms` mean per case,
and `451.506 ms` max per case. Treat these as local smoke-test timings, not a
performance claim; they depend on the local Python runtime, filesystem cache,
and machine load.

## Synthetic Case Coverage

The packaged synthetic suite contains 34 cases across these categories:

| Category | Cases |
| --- | ---: |
| abstention | 5 |
| automatic_induction | 1 |
| cross_project_recall | 3 |
| explicit_memory | 1 |
| information_extraction | 3 |
| knowledge_update | 3 |
| multi_session_reasoning | 3 |
| privacy_boundary | 3 |
| scope_calibration | 3 |
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
| MyPrecious-layered-synthetic | 2 |

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
- `source_precision_at_5` and `source_micro_precision_at_5`: analogous purity
  for source anchors at source depth.

Interpretation:

These precision metrics are intentionally below 1.0 in the current baseline.
The search path returns extra related results in the top 5; the benchmark
therefore rewards correct top-rank recall while still exposing returned-result
noise.

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
- `scope_filter_recall`: whether `--scope <expected_layer>` still recalls the
  expected memory.
- `wrong_scope_suppression`: whether the same expected memory is absent when
  searched through incorrect scopes.

Not measured:

- Automatic promotion from sessions into layers.
- Multi-layer conflict resolution.
- Session-layer and raw/source-layer scope controls as first-class query
  targets.
- Whether a project-independent memory ontology is complete.

### Drilldown And Source Reachability

Measured:

- `session_drilldown_at_5`: whether the supporting session summary path appears
  in session-depth results.
- `evidence_reachability`: whether required evidence paths are reachable from
  the expected memory's memory blocks.
- `memory_evidence_ref_reachability`: whether the expected memory block itself
  exposes each required evidence path in its `evidence:` section, with a
  `path#quote_id` display ref when the quote id is available.
- `evidence_text_reachability`: whether required evidence files contain exact
  reference evidence snippets.
- `source_reachability`: whether the expected source anchor appears on the
  expected memory's `source: memory` block at source depth.

Recent hardening:

- Source, evidence, and answer metrics are bound to the expected memory identity
  instead of accepting matching paths or anchors from unrelated blocks.
- The default memory search result now displays validated evidence references
  without printing evidence file text.
- Diagnostic result IDs are filtered to memory blocks so index/source blocks
  cannot impersonate memory results.

Not measured:

- Raw transcript retrieval or rendering.
- Authorization gates for raw source access.
- Multi-hop drilldown from high-level memory through multiple sessions into
  original raw records.
- Whether source anchors remain valid after archive migration or compaction.

### Answer Reachability

Measured:

- `answer_reachability`: exact reference-answer text is reachable in the
  expected-memory context.
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
  allowed no-hit output.
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
Memora-style records, but this audit did not run public benchmark datasets. A
public benchmark score would require exact dataset versions, conversion logs,
case fingerprints, archive construction rules, answer-grading protocol, and
repeated runs against a real or synthetic archive built from those records.

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
- The benchmark gates `memory_evidence_ref_reachability` at `1.0` across all 29
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

- Project path still remains central to update configuration and scheduled
  ingestion. Project is not yet merely one scope among many.
- Automatic induction is implemented as a conservative minimum slice. It can
  promote synthetic reusable facts into high-level memories and run a
  dependency-light semantic lifecycle pass. A 2026-06-22 aggregate-only dry run
  has now measured induction and review-queue behavior on a real deployment
  archive without rendering private memory text or source paths, but this is
  still not a broad natural-language consolidation engine or an end-to-end
  generated-answer evaluation.
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
  `--raw-source-preview` opt-in with redaction. This is still not a full
  multi-principal authorization system.
- The benchmark has thirteen `evidence_text` cases, including ten semantic
  lifecycle robustness cases for conflict, deprecation, false-merge guards, and
  evidence retention. It now also gates source-depth policy, source ref
  reachability, raw-preview redaction, and source-drilldown privacy on the
  packaged synthetic suite. This is still synthetic and too small to prove
  source-depth robustness on real private histories.
- The reusable template now includes a privacy-safe shadow evaluation runner
  that can report aggregate recall, active-memory suppression, lifecycle
  integrity, top-k noise, noise-source buckets, and provenance coverage for a
  target archive without rendering source content. It can also emit a structural
  report for legacy deployment archives that do not yet have layered memory
  nodes. The 2026-06-22 private-probe gate below measured a layered deployment
  archive with fixed redacted real-history probe cases kept outside this
  reusable repository.
- Search is lexical and explainable. That is a deliberate design choice, but it
  has not been evaluated against embedding or hybrid semantic retrieval on
  public datasets.
- Low-signal memory-node matches are filtered when the query only hits low
  signal fields such as tags and there is no project-context match. This removes
  a narrow top-k noise class without changing the synthetic recall gate.
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
| memory_records | 1376 |
| legacy_session_records | 266 |
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

## Recommendation

Proceed from the minimum verifiable lifecycle slice to deeper consolidation
architecture.

The system now has a bounded proof that high-level memories can be induced from
synthetic session events and that direct explicit memories can be written only
with evidence. It also has synthetic gates for semantic support merge,
refresh/supersession, contradiction, deprecation, false-merge prevention, and
evidence retention. It now also has an ambiguity review queue, explainable
consolidation traces, aggregate review-queue calibration metrics, and a narrow
same-scope low-risk compression rule for semantic lifecycle cases that should
not be auto-retired. It also has an initial gated source-depth workflow with
synthetic quality gates and a real deployment aggregate baseline that passes
the stricter source-map anchor audit. Shadow evaluation now has a private
redacted real-history probe set with numeric recall, precision, noise,
suppression, privacy, provenance, lifecycle, and audit gates. It still does
not satisfy the full target design. The next valuable work is expanding that
private probe set across more retrieval intents and noisy multi-month
histories, then improving durability under broader semantic promotion, decay,
and stronger source-drilldown authorization.

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

3. Reduce project-boundary centrality.
   Treat project as one retrieval scope rather than the primary storage and
   scheduling boundary.

4. Deepen source-depth governance.
   Keep raw source anchors private by default, add authorization checks for
   deeper drilldown, and extend real history source-depth robustness beyond
   aggregate dry-runs.

5. Run adapted public benchmarks locally.
   Use the existing converter against downloaded public records outside the
   repository. Record dataset version, conversion fingerprints, archive build
   rules, and score JSON.

6. Expand the private redacted real-history probe set.
   Keep probe cases in the deployment repository or another private local path,
   never in the reusable skill repository. Add more redacted cases for
   cross-project reuse, near-duplicate memories, stale-memory suppression,
   source-depth decisions, and noisy long-history retrieval while preserving
   aggregate-only reporting in this repository.

7. Add governance tests later.
   Do not make multi-principal access control part of the next immediate slice,
   but keep GateMem-style utility/access/forgetting as a future evaluation
   direction.
