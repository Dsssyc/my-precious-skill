# Layered Memory Readiness Evaluation

## Purpose

This document is a stage-gate evaluation for the reusable My Precious skill
repository. It records what the current implementation can measure reliably,
where the packaged benchmark can overstate readiness, and what remains before
the project can claim a full non-project-boundary layered memory system.

The conclusion is intentionally narrow: the current benchmark is a repeatable
local quality gate for retrieval, drilldown, stale suppression, abstention, and
privacy-boundary behavior on synthetic archives. It is not a direct leaderboard
score against public long-memory systems such as MemPalace, LongMemEval,
LoCoMo, Memora, or RULER-style long-context retrieval tests.

## Current Baseline

Baseline date: 2026-06-20

Code point used for the benchmark harness: `da3da62`

Case file:
`benchmarks/cases/layered_recall_synthetic.jsonl`

Case fingerprint:
`d9140c729f420fe902b7f4cce462d6104fa21e77e6f33bd0c3e50278c168c1b5`

Search implementation fingerprint:
`681f812a1de9ccb416c94b5b4310789e72befb5577038d4cb65c4227f36fe075`

Baseline commands:

```bash
python3 benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-layered-postfix-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl

python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-layered-postfix-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-layered-postfix-details.jsonl \
  --failures-json /tmp/my-precious-layered-postfix-failures.json \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

Baseline result:

| Metric | Value |
| --- | ---: |
| cases | 32 |
| positive_cases | 27 |
| abstain_cases | 5 |
| answer_cases | 9 |
| evidence_text_cases | 1 |
| memory_recall_at_1 | 1.0 |
| memory_recall_at_5 | 1.0 |
| memory_mrr | 1.0 |
| memory_ndcg_at_5 | 1.0 |
| memory_precision_at_5 | 0.3012345679012346 |
| memory_micro_precision_at_5 | 0.25471698113207547 |
| memory_explainability | 1.0 |
| layer_calibration | 1.0 |
| scope_filter_recall | 1.0 |
| wrong_scope_suppression | 1.0 |
| session_drilldown_at_5 | 1.0 |
| source_reachability | 1.0 |
| source_precision_at_5 | 0.3049382716049383 |
| source_micro_precision_at_5 | 0.25961538461538464 |
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

Latency for this local run was `8685.746 ms` total, `271.43 ms` mean per case,
and `430.96 ms` max per case. Treat these as local smoke-test timings, not a
performance claim; they depend on the local Python runtime, filesystem cache,
and machine load.

The full unit test suite also passed after the measurement fix:

```text
Ran 332 tests in 71.936s
OK
```

## Synthetic Case Coverage

The packaged synthetic suite contains 32 cases across these categories:

| Category | Cases |
| --- | ---: |
| abstention | 5 |
| cross_project_recall | 3 |
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
- `evidence_text_reachability`: whether required evidence files contain exact
  reference evidence snippets.
- `source_reachability`: whether the expected source anchor appears on the
  expected memory's `source: memory` block at source depth.

Recent hardening:

- Source, evidence, and answer metrics are bound to the expected memory identity
  instead of accepting matching paths or anchors from unrelated blocks.
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

Recent hardening:

- Abstention and suppression are checked across default and scoped searches.
- Unstructured non-no-hit output is rejected even when it does not parse as a
  hit block.

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
- Stale and forbidden memory IDs are checked across default and scoped search
  outputs.
- Unsupported queries are tested for abstention rather than being silently
  treated as recall failures.
- The benchmark emits reproducible case/search fingerprints and structured
  details/failure artifacts.
- The benchmark now includes successful search `stderr` in privacy and
  abstention checks.

## Remaining Gaps Against The Target System

The target system described in
`docs/superpowers/specs/2026-06-17-layered-memory-recall-design.md` is broader
than the current implementation.

Current gaps:

- Project path still remains central to update configuration and scheduled
  ingestion. Project is not yet merely one scope among many.
- Automatic induction is not implemented as a durable default write behavior.
  The benchmark can build synthetic high-level memories, but the archive updater
  does not yet promote, merge, or refresh high-level memories from real session
  events as the normal path.
- Explicit memory is represented in template data, but there is no complete
  force-memory interface that writes sticky high-level memories with audited
  evidence attachments across runtimes.
- The system has `global`, `domain`, and `project` memory files, but lifecycle
  operations such as support-count update, contradiction handling, supersession,
  decay, and confidence revision are still incomplete.
- Raw/source reachability is represented by anchors, not by a fully gated
  drilldown workflow that can safely walk all the way to original chat records.
- The benchmark has one `evidence_text` case; this is useful as a guard but too
  small to prove source-depth robustness.
- Search is lexical and explainable. That is a deliberate design choice, but it
  has not been evaluated against embedding or hybrid semantic retrieval on
  public datasets.
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

## Recommendation

Proceed to next-generation layered memory architecture design.

The reason is not that the current system already satisfies the target design.
It does not. The reason is that the current retrieval benchmark is now stable
enough to act as a regression baseline while the next architecture is designed.
Further small harness hardening will have lower value than designing the missing
write-path ontology: automatic induction, explicit sticky memories, lifecycle
fields, cross-project promotion, and gated source drilldown.

## Next Minimal Roadmap

1. Specify the memory-node lifecycle contract.
   Define promotion, merge, refresh, supersession, confidence, support count,
   evidence refs, and raw refs as enforceable schema behavior.

2. Add automatic induction as a separate write-stage prototype.
   Start with synthetic sessions that promote one cross-project reusable memory
   into `global` or `domain` without requiring real private data.

3. Add explicit-memory write tests.
   A forced memory should create a sticky high-level node with evidence refs and
   should reject source-free facts unless explicitly allowed by policy.

4. Expand source-depth evaluation.
   Increase `evidence_text_cases`, add broken-anchor cases, and test that raw
   source drilldown is gated and sanitized.

5. Run an adapted public benchmark locally.
   Use the existing converter against downloaded public records outside the
   repository. Record dataset version, conversion fingerprints, archive build
   rules, and score JSON.

6. Add governance tests later.
   Do not make multi-principal access control part of the next immediate slice,
   but keep GateMem-style utility/access/forgetting as a future evaluation
   direction.
