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
updater-driven automatic induction on synthetic archives, end-to-end
induction-to-recall behavior on synthetic source records, explicit non-project
source stream registry updates on synthetic archives, clean-room packaged
lifecycle setup/update/search/audit with self-maintenance safeguards, and
deterministic source-grounded answer handoff records, plus agent-facing recall
context packaging and consumption for supported answer versus abstain
decisions, including packaged explicit-memory capture/revision/withdrawal
governance checks, packaged progressive source-drilldown consumption,
packaged scope arbitration across global/domain/project memory layers, and
packaged scope-aware answer-handoff consumption. It is
not a direct leaderboard score
against public long-memory systems such as MemPalace, LongMemEval, LoCoMo,
Memora, or RULER-style long-context retrieval tests.

## V1 Readiness Gate

`benchmarks/v1_readiness_gate.py` is the memory-readiness convergence
entrypoint for this evaluation. It aggregates existing JSON reports without
rendering queries, memory text, source paths, raw refs, private probe cases, or
forbidden-pattern text. The current packaged gate requires five core synthetic
dimensions:

- layered recall and drilldown;
- updater-driven automatic induction;
- end-to-end induction-to-recall;
- explicit non-project source stream registry update plus layered recall; and
- clean-room packaged lifecycle setup/update/search/audit
  (`packaged_lifecycle`).

The current packaged core command,
`python3 benchmarks/v1_readiness_gate.py --run-packaged`, reports required 5/5.
The current packaged generated-answer command,
`python3 benchmarks/v1_readiness_gate.py --run-packaged --require-answer`,
reports required 6/6.

When those required dimensions pass, the gate reports
`overall_status: core_synthetic_ready`. That status is deliberately bounded: it
means the core synthetic evidence is green, not that the full
non-project-boundary v1 target, private archive behavior, automatic source
discovery, public leaderboard parity, live model answer quality, automatic
ontology discovery, or long-horizon multi-principal governance has been proven.

Repo release verification is a separate contract. `tools/run_quality_gates.py`
is the canonical repo-local release gate; it runs skill validation, packaged
lifecycle, packaged v1 readiness with and without generated-answer evidence,
unit tests, Python compilation, template sync checks, and diff hygiene while
emitting aggregate-only JSON.

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
  builds the packaged synthetic generated-answer archive, runs the extractive
  answer-record adapter, and grades the generated `answer_handoff` records.
  This is deterministic answer handoff evidence for the grading path, not live
  model answer quality. Answer reports must include aggregate
  `source_benchmarks`, `case_origins`, `answer_handoff_present_rate`,
  `answer_handoff_support_coverage_rate`, supported/abstention handoff counts,
  `unsupported_claim_count`, and `inactive_memory_answer_count`; metric-only
  or answer-text-only generated-answer JSON is rejected because it cannot prove
  which benchmark stream produced the answers or whether the answers were
  grounded in active/current memory evidence.

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

The current packaged generated-answer fixture has 5 cases: 3 positive answer
cases and 2 abstention cases, including one inactive-only support rejection.
It reports `case_pass_rate: 1.0`,
`answer_normalized_match_rate: 1.0`, `answer_token_f1: 1.0`,
`abstention_accuracy: 1.0`, `privacy_leak_count: 0`,
`missing_answer_count: 0`, `duplicate_answer_count: 0`, and
`unknown_answer_count: 0`. It also reports
`answer_handoff_present_rate: 1.0`,
`answer_handoff_support_coverage_rate: 1.0`,
`answer_handoff_supported_case_count: 3`,
`answer_handoff_abstain_case_count: 2`,
`context_package_parse_success_rate: 1.0`,
`context_package_support_coverage_rate: 1.0`,
`context_package_abstention_accuracy: 1.0`,
`context_package_inactive_rejection_count: 1`,
`unsupported_claim_count: 0`, and `inactive_memory_answer_count: 0`. It carries
`source_benchmarks.MyPreciousGeneratedAnswerSynthetic: 5` and
`case_origins.packaged_generated_answer_fixture: 5`, satisfying the answer
provenance and source-grounded handoff gates without rendering queries,
generated answers, reference answers, source paths, or raw refs.

The deployment template also includes an extractive
`tools/generate_answer_records.py` adapter for producing answer-record JSONL
from memory search hits. Its own report is aggregate-only: it includes case
count, answer records written, memory-answer count, abstention count, answer
handoff support coverage, no-hit count, source benchmark counts, case-origin
counts, and privacy flags without rendering queries, generated answers,
reference answers, source paths, or raw refs. Each non-abstention
`answer_handoff` carries `support_refs` to active/current memory, summary, and
evidence layers; unsupported or inactive-only cases abstain. This proves the
answer-record production path can be wired into the offline grader, but it
remains extractive evidence rather than live model answer quality.

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

## V1.3 Self-Maintenance Lifecycle Gate

V1.3 is not a new retrieval capability. It is a self-maintenance lifecycle
contract added after an automation review showed that scheduled archive updates
can fail for operational reasons even when recall benchmarks remain green.

The public synthetic self-maintenance fixture now runs inside
`benchmarks/packaged_lifecycle_gate.py`. It creates one ordinary local source
record and two scheduled automation source records marked with
`thread_source=automation`. The update path must archive only the ordinary
durable source record. The automation records are present in the source
fixture, but they must not produce archive session entries, memory nodes, daily
durable entries, or search indexes.

The packaged lifecycle report exposes only aggregate contract metrics:

| metric | expected value |
| --- | ---: |
| automation_source_records=2 | true |
| automation_session_entries=0 | true |
| automation_memory_nodes=0 | true |
| automation_daily_noise_hits=0 | true |
| automation_index_noise_hits=0 | true |
| search_health_check | passed |
| sync_dry_run | passed |

The automation gate contract is explicit: `search_memory.py --health-check` is
the readiness check for archive searchability. A generic `search_memory.py memory`
content query is not a readiness check and must not block or permit publication.
The scheduled prompt rendered by `render_scheduler.py` also keeps automation run
notes separate from generated daily archive files and routes any publish step
through `sync_memory_archive.py` rather than hand-staging files.

Private dogfood for this contract must stay aggregate-only private dogfood:
audit status, search health status, clean/dirty status, and counts of archived
automation-thread entries or automation-run noise are allowed. Private source
text, source paths, queries, memory IDs, raw refs, and automation transcript
content are not part of this public readiness record.

## V1.4 Explicit Memory Capture Contract

V1.4 is an explicit memory capture contract. It is not a new ranking capability,
not generated-answer quality, and not long-horizon ontology or governance.

The deployment template now includes `capture_explicit_memory.py`, a minimal
runtime adapter for explicit memory requests. Automatic induction remains the
default behavior for ordinary source records. When a user or governing prompt
explicitly asks to remember, force-save, or distill a short fact, the adapter
accepts agent-neutral JSONL input with `text`, optional `layer`, optional
`scope`, and optional `source`. It creates evidence-bound support files, calls
the existing explicit-memory updater path, and writes sticky `source: explicit`
memory nodes.

The adapter contract is that raw transcript fields are refused, along with
message arrays, raw source content, tool logs, and automation run notes. The
public packaged lifecycle gate covers
one accepted short fact and one refused raw-transcript-shaped input. Its
readiness output stays aggregate-only through the `explicit_capture` metrics:

| metric | expected value |
| --- | ---: |
| adapter_input_records=1 | true |
| captured_memory_nodes=1 | true |
| rejected_raw_transcript_records=1 | true |
| search_hit_count=1 | true |
| privacy_leak_count=0 | true |

The sync helper publish boundary is deliberately narrow: `memories/explicit.jsonl`
is allowed so user-forced memories can be published through the safe sync path,
while automatic memory node files and review files remain outside automatic sync.

## V1.5 Explicit Memory Revision And Conflict Contract

V1.5 is an explicit memory revision contract. It is not a general long-horizon governance system, not a new ranking capability, and not generated-answer quality.

The deployment template keeps `capture_explicit_memory.py` as the single
runtime adapter for explicit memory requests, and extends its agent-neutral
JSONL input with bounded operations. `operation: replace` uses
`replaces_memory_id` to mark an old explicit memory as superseded by the new
current fact. `operation: withdraw` uses `deprecates_memory_id` to retire an
old explicit memory without inventing a replacement fact. In both cases the old
fact is not deleted; the old fact is superseded and retains evidence
traceability through the existing memory lifecycle links and drilldown paths.
The contract phrase is explicit: old fact is not deleted.
The old fact is superseded and retains evidence traceability.

Search default behavior must prefer the current fact. A stale replaced fact and
a withdrawn fact must not appear as active default memory hits, while source
and evidence drilldown for the current replacement remains reachable. Raw
transcript fields, message arrays, source content, tool logs, automation run
notes, and unsafe revision target identifiers remain refused.

The public packaged lifecycle gate covers one accepted replace operation and
one accepted withdraw operation. Its readiness output stays aggregate-only
through the `explicit_revision` metrics:

| metric | expected value |
| --- | ---: |
| explicit_revision_input_records=2 | true |
| explicit_revision_superseded_records=1 | true |
| explicit_revision_deprecated_records=1 | true |
| current_fact_search_hit_count=1 | true |
| stale_fact_default_search_hit_count=0 | true |
| withdrawn_fact_default_search_hit_count=0 | true |
| revision_evidence_reachability_count=2 | true |
| privacy_leak_count=0 | true |

## V1.6 Source-Grounded Answer Handoff Contract

V1.6 is a deterministic answer handoff contract. It is not live model answer quality,
not semantic generation, not a ranking overhaul, and not a general long-horizon
governance system.

The read path now has a bounded extractive answer-record adapter:
`tools/generate_answer_records.py` searches layered memory nodes, uses only
active/current memory hits, and writes private answer records with an
`answer_handoff` object. A non-abstention handoff must carry `support_refs`
that connect the answer to memory, summary, and evidence layers. If support is
missing, if only inactive lifecycle memory matches, or if the candidate answer
would violate the privacy boundary, the adapter must abstain instead of
fabricating an answer.

The public packaged generated-answer fixture covers supported answers,
abstain behavior, multi-hop summary/evidence reachability through `support_refs`,
privacy boundary checks, and currentness when an old stale fact has been
superseded by an active/current memory. The readiness gate keeps the output
aggregate-only and requires these metrics:

| metric | expected value |
| --- | ---: |
| answer_handoff_present_rate | 1.0 |
| answer_handoff_support_coverage_rate | 1.0 |
| answer_handoff_supported_case_count | >= 1 |
| answer_handoff_abstain_case_count | >= 1 |
| unsupported_claim_count=0 | true |
| inactive_memory_answer_count=0 | true |
| privacy_leak_count=0 | true |

The handoff privacy rule is intentionally stricter than ordinary answer text
grading: benchmark reports must not render queries, generated answers,
reference answers, memory text, source paths, raw refs, raw transcripts,
scheduler state, credentials, or local private paths. This makes V1.6 useful as
an answer handoff audit, but it still does not claim live model answer quality.

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

## V1.7 Private Aggregate Dogfood Gate

V1.7 is a private aggregate dogfood gate for the V1.6 answer handoff
contract. It is not a public benchmark, not live model answer quality, not a
ranking overhaul, and not automatic ontology or long-horizon governance.

`benchmarks/private_generated_answer_dogfood_gate.py` now has public synthetic
coverage for the private dogfood wrapper path. The wrapper is allowed to expose
only aggregate counts, rates, pass/fail status, and generic failure reasons.
`v1_readiness_gate.py` normalizes the wrapper's nested generated-answer report
and requires the same handoff metrics as V1.6:
`answer_handoff_present_rate`, `answer_handoff_support_coverage_rate`,
supported/abstention handoff counts, `unsupported_claim_count=0`,
`inactive_memory_answer_count=0`, and `privacy_leak_count=0`.

The private dogfood wrapper privacy block is now a readiness contract of its
own. In addition to ordinary answer-report privacy flags, the gate rejects a
private dogfood wrapper unless `private_paths_rendered`, `memory_text_rendered`,
`memory_ids_rendered`, `source_paths_rendered`, and `raw_refs_rendered` are all
false. This keeps private queries, answers, memory IDs, source paths, raw refs,
and source text out of the reusable repository's evidence stream.

The private runner also only deletes known dogfood-generated artifacts during
cleanup. It removes the temporary case file and the known aggregate work files,
then removes now-empty dogfood directories. It does not recursively delete
arbitrary files that merely happen to be inside the configured work directory.
This makes cleanup evidence stronger without weakening the existing fail-closed
preflight for dirty private `eval/` and `.tmp/` artifacts.

The V1.7 evidence is still bounded. A safe real private archive run can report
aggregate metrics for deployment confidence, but the reusable repository's
claim is that the private dogfood orchestration enforces the V1.6
source-grounded handoff and privacy contract. It does not store private cases,
private answers, raw transcripts, source paths, raw refs, scheduler logs, or
archive data.

## V1.8 Agent-Facing Recall Context Package

V1.8 adds an agent-facing recall context package to the read path. The
`search_memory.py --context-json` mode emits
`report_kind: memory_recall_context_package` with query metadata,
active/current hit currentness, rank, layer and scope, why signals, summary and
evidence drill paths, source-ref status metadata when requested, privacy flags,
and top-level `answerability.status`.

This is a packaging and answerability contract, not live model answer quality,
not a ranking overhaul, and not automatic ontology or governance discovery. The
package lets a future agent decide supported answer versus abstain without
parsing free-form search output. Supported means active/current memory support
with summary or evidence drilldown. Unsupported covers no hits, related context
without active/current support, or only inactive/superseded support.

The privacy boundary is part of the evidence. The context package must not
render memory text, raw transcript text, raw refs, raw source content, local private paths,
credentials, or scheduler state. It may render archive-relative summary and
evidence drill paths and aggregate source-ref status identifiers.

## V1.9 Context-Package Consumption Gate

V1.9 proves that the answerability adapter consumes
`memory_recall_context_package` as the machine-readable read-path handoff. The
generated-answer adapter calls `search_memory.py --context-json`, parses the
package, and records a privacy-safe `context_package` handoff block for every
answer record. Supported answers require a supported active/current package hit
whose package `matched:` metadata covers the query support tokens and whose
summary/evidence support refs are present. Unsupported packages, missing token
coverage, inactive-only support, or malformed packages fail closed to abstain.

`generated_answer_benchmark.py` now reports context-package consumption
metrics: `context_package_handoff_present_rate`,
`context_package_parse_success_rate`, `context_package_support_coverage_rate`,
`context_package_abstention_accuracy`,
`context_package_supported_case_count`,
`context_package_abstain_case_count`,
`context_package_parse_failure_count`, and
`context_package_inactive_rejection_count`. `v1_readiness_gate.py` requires the
rate/count metrics when generated-answer evidence is required.

The V1.9 evidence remains bounded. It proves deterministic context-package
consumption for supported versus abstain decisions. It is not live LLM answer quality,
not ranking quality, not vector search, not automatic ontology discovery, and
not public leaderboard parity. The package and benchmark reports must stay
aggregate/privacy-safe: no memory text, raw transcript text, raw source
content, raw refs, local private paths, credentials, scheduler state, private queries,
generated answers, or reference answers are rendered in the readiness output.

## V2.0 Runtime Skill Consumption Contract

V2.0 moves context-package consumption into the runtime instructions for the
`using-my-precious` read-path skill and the deployment repository guidance. An
agent answering a historical memory question should first request
`memory_recall_context_package` with `--depth evidence --context-json`, then
use `answerability.status` and per-hit support metadata as the decision
boundary. Do not use free-form search output as the answerability source.
Free-form search remains useful only for exploration or drilldown after the
package decision.

The agent-facing decision recipe is deliberately small:

| package state | action |
| --- | --- |
| supported package -> answer | Answer only from supported active/current hits with `query_support.status: supported` plus summary and evidence drill paths. |
| unsupported package -> abstain | Say the archive has no supported memory for the requested fact. |
| inactive/superseded-only package -> abstain | Treat stale-only support as insufficient unless a current replacement is separately supported. |
| malformed or missing package -> abstain | Fail closed rather than deriving answerability from free-form text. |

This is a runtime skill consumption contract, not live LLM answer quality, not vector search,
not ranking quality, and not automatic ontology discovery. The same privacy
boundary applies at the skill layer: no private query text, memory text, raw refs,
raw source content, source paths, credentials, scheduler state, or local private paths
should be rendered in answers, skill examples, benchmark reports, or reusable
repository artifacts.

## V2.1 Packaged Runtime Consumption Gate

V2.1 adds `benchmarks/using_my_precious_runtime_gate.py` to prove that the
package-first read path is executable from a clean packaged deployment repo,
not only documented in the reusable skill. The gate installs the packaged
template through the setup script, writes synthetic public memory rows into the
deployment repo, invokes that repo's copied `tools/search_memory.py` with
`--depth evidence --context-json`, parses
`report_kind: memory_recall_context_package`, and applies the documented
runtime decision recipe without using free-form search output as the
answerability source.

The synthetic cases are intentionally small: supported active/current memory
with summary and evidence drill paths answers; unsupported/no-hit packages
abstain; inactive/superseded-only support abstains; malformed packages fail
closed to abstain. The gate reports only aggregate metrics:
`runtime_context_package_parse_success_rate`,
`runtime_supported_decision_accuracy`, `runtime_abstention_accuracy`,
`runtime_inactive_rejection_count`, `runtime_malformed_fail_closed_count`, and
`privacy_leak_count`.

This proves packaged runtime consumption of context packages. It is not LLM answer quality,
not ranking quality, not vector search, not ontology discovery,
and not public leaderboard parity. It also does not expand governance,
embeddings, ranking, or live-answer generation. The command is stable and
synthetic, so it is included in `tools/run_quality_gates.py` as part of the
repo-local release gate.

## V2.2 Runtime Support-Coverage Contract

V2.2 tightens the supported package boundary. `memory_recall_context_package`
hits now include per-hit `query_support` metadata derived from existing
token-coverage signals. A hit is answerable only when it is active/current,
has summary and evidence drill paths, and has
`query_support.status: supported`. Active/current drillable hits with weak or
partial query coverage are unsupported near-misses and must abstain.

`benchmarks/using_my_precious_runtime_gate.py` now keeps the V2.1 supported,
unsupported/no-hit, inactive/superseded-only, and malformed cases, and adds
weak-active and same-topic near-miss hard negatives. The gate reports
`runtime_support_coverage_accuracy`,
`runtime_weak_active_rejection_count`,
`runtime_near_miss_abstention_accuracy`,
`runtime_supported_decision_accuracy`, `runtime_abstention_accuracy`,
`runtime_context_package_parse_success_rate`, and `privacy_leak_count`.

This proves deterministic support-coverage decision reliability for the
package-first runtime contract. It is not ranking quality, not LLM answer quality,
not vector search, not ontology discovery, and not public leaderboard parity.

## V2.3 Query-Support-Aware Hard-Negative Recall Gate

V2.3 adds `benchmarks/query_support_recall_gate.py` to quantify the
query-support boundary under hard-negative recall conditions. The gate builds a
small synthetic public archive, invokes `search_memory.py` with
`--limit 5 --depth evidence --context-json`, parses
`report_kind: memory_recall_context_package`, and treats
`query_support`, lifecycle status, and summary/evidence drill paths as the
only answerability source. Free-form search output is not used.

The synthetic cases cover supported active/current memory, same-topic wrong-scope
near miss, weak active/current support, broad lexical overlap,
inactive/superseded-only support, unsupported/no-hit abstention, and malformed
package fail-closed behavior. The gate reports aggregate metrics:
`supported_context_recall_at_5`, `answerable_precision_at_5`,
`query_support_boundary_pass_rate`, `weak_support_rejection_count`,
`scope_mixed_noise_at_5`, `inactive_lifecycle_rejection_count`,
`runtime_abstention_accuracy`, and `privacy_leak_count`.

The V2.3 synthetic baseline passes with
`supported_context_recall_at_5=1.0`, `answerable_precision_at_5=1.0`,
`query_support_boundary_pass_rate=1.0`, `weak_support_rejection_count=2`,
`scope_mixed_noise_at_5=0.0`, `inactive_lifecycle_rejection_count=1`,
`runtime_abstention_accuracy=1.0`, and `privacy_leak_count=0`. It also records
`scope_mixed_related_hit_count_at_5=1` to show that a wrong-scope related hit
can still be observed in top-k while remaining outside the answerable surface.

This proves query-support-aware hard-negative recall diagnostics for context
packages. It is not live LLM answer quality, not vector search quality, not public
benchmark status, not public leaderboard parity, not automatic ontology discovery,
and not solved long-horizon memory decay.

## V2.4 Packaged Induction Consolidation Gate

V2.4 extends `benchmarks/updater_induction_benchmark.py` to prove that the
packaged write path can consolidate repeated and paraphrased automatic induction facts
in a synthetic deployment archive. The gate creates synthetic
source records, runs the packaged updater, verifies that same-fact paraphrases
produce one current memory node, checks merged support/evidence refs, and then
recalls that consolidated memory through the copied `search_memory.py` with
`--limit 5 --depth evidence --context-json`. The post-consolidation recall
check parses `report_kind: memory_recall_context_package` and uses
`answerability.status`, per-hit `query_support.status`, and summary/evidence
drill paths as the only answerability source.

The synthetic cases also keep the negative write-path boundary in view:
contradictory facts route to induction review, scope narrowing/broadening
ambiguity routes to induction review, and repeated process/status noise remains
rejected rather than promoted. The gate reports aggregate metrics:
`consolidated_duplicate_suppression_rate`,
`consolidated_support_merge_rate`,
`consolidated_evidence_retention_rate`,
`contradiction_review_routing_rate`,
`scope_shift_review_routing_rate`, `process_noise_rejection_rate`,
`post_consolidation_recall_at_5`, and `privacy_leak_count`.

This proves packaged synthetic induction consolidation behavior. It is not LLM summarization quality,
not vector search, not ontology discovery, not full human memory modeling,
not multi-month decay, not deletion policy, and not private archive quality.
The command is stable and non-duplicative because it extends the existing
updater benchmark already included in `tools/run_quality_gates.py`.

## V2.5 Packaged Explicit Memory Governance Gate

V2.5 extends `benchmarks/packaged_lifecycle_gate.py` to prove that explicit
memory capture, replace, and withdraw operations in a clean packaged
deployment repo preserve the package-first runtime contract. The gate uses the
packaged `capture_explicit_memory.py` adapter to create synthetic explicit
facts, then invokes the copied deployment `tools/search_memory.py` with
`--depth evidence --context-json` and parses
`report_kind: memory_recall_context_package`. Free-form search output is not
used as answerability evidence.

The synthetic cases cover one current explicit fact that must answer through a
supported active/current context package, one replaced legacy fact that must
abstain, one withdrawn obsolete fact that must abstain, duplicate explicit
inputs that must not create extra active/current nodes, and conflict, unsafe
target, and unknown target inputs that must fail closed. The gate reports
aggregate metrics:
`explicit_context_package_parse_success_rate`,
`explicit_current_fact_answerability_rate`,
`explicit_replaced_fact_abstention_rate`,
`explicit_withdrawn_fact_abstention_rate`,
`explicit_revision_link_integrity_rate`,
`explicit_bulk_duplicate_suppression_rate`,
`explicit_conflict_fail_closed_count`,
`explicit_unsafe_target_refusal_count`,
`explicit_unknown_target_refusal_count`, and `privacy_leak_count`.

V2.5 also tightens context-package query support for lifecycle qualifiers such
as `legacy`, `obsolete`, `retired`, `deprecated`, `superseded`, `withdrawn`,
and `inactive`. An active/current replacement cannot answer a query for a
legacy or withdrawn fact merely because it shares broad topic words. This
proves packaged explicit-memory governance consumption of context packages.
It is not LLM answer quality, ranking quality, vector search, ontology
discovery, public leaderboard parity, or a complete long-horizon governance
system. The command is stable and already runs through the packaged lifecycle
gate included in `tools/run_quality_gates.py`.

## V2.6 Packaged Progressive Source Drilldown Gate

V2.6 adds `benchmarks/progressive_source_drilldown_gate.py` to prove that the
package-first read path can consume progressive source drilldown metadata from
a clean packaged deployment repo. The gate installs the packaged template,
writes synthetic public memory rows and source anchors, then invokes the
copied deployment `tools/search_memory.py` with both
`--depth evidence --context-json` and `--depth source --context-json`. It
parses `report_kind: memory_recall_context_package` and uses only context
package fields for answer, drill, block, and abstain decisions. Free-form
search output is not used as source reachability evidence.

The synthetic cases cover a supported answer at evidence depth, a supported
source drilldown at source depth, a high-level memory derived from lower
support memory with multi-hop source-ref resolution, an evidence-only memory
that must not satisfy an original-source request, inactive/superseded
source-only support that must abstain, unsafe raw/source refs that must block,
and malformed packages that must fail closed. The gate reports aggregate
metrics:
`source_context_package_parse_success_rate`,
`source_drilldown_decision_accuracy`,
`memory_to_summary_drilldown_rate`,
`summary_to_evidence_drilldown_rate`,
`evidence_to_source_ref_reachability_rate`,
`memory_graph_multihop_source_resolution_rate`,
`evidence_only_original_source_rejection_count`,
`inactive_source_rejection_count`, `unsafe_source_ref_block_count`,
`raw_source_content_default_block_rate`, and `privacy_leak_count`.

This proves packaged progressive source drilldown consumption of context
packages. It does not prove raw transcript ingestion, private archive quality,
LLM answer quality, vector search, ranking quality, ontology discovery, or a
source browser UI. Raw source content remains blocked by default; source-depth
context packages render source-ref status metadata rather than raw source
content. The command is stable and included in `tools/run_quality_gates.py`.

## V2.7 Packaged Scope Arbitration And Override Gate

V2.7 adds `benchmarks/scope_arbitration_gate.py` to prove that the
package-first read path can consume context-package layer and scope metadata
from a clean packaged deployment repo when deciding whether to answer or
abstain. The gate installs the packaged template, writes synthetic public
global/domain/project memory rows, then invokes the copied deployment
`tools/search_memory.py` with `--depth evidence --context-json` plus
`--project-path` and `--preferred-scope` where applicable. It parses
`report_kind: memory_recall_context_package` and uses only context package
fields for answerability and scope arbitration. Free-form search output is not
used as answerability evidence.

The synthetic cases cover global foundational fallback, domain-preferred
support across projects, current project support overriding broader memory,
same-topic wrong-project support that must abstain, stale broad support that
must abstain after supersession, missing project context for project-only
support, unsupported no-hit packages, and malformed packages that fail closed.
The gate reports aggregate metrics:
`scope_context_package_parse_success_rate`,
`global_fallback_answerability_rate`, `domain_preference_accuracy`,
`project_override_accuracy`, `wrong_project_rejection_count`,
`broad_stale_rejection_count`,
`missing_project_context_abstention_accuracy`,
`scope_arbitration_decision_accuracy`,
`scope_mixed_related_hit_count_at_5`, and `privacy_leak_count`.

This proves packaged scope arbitration and override decision behavior for
context packages. It does not prove LLM answer quality, vector search,
embedding-store readiness, ranking overhaul, ontology discovery, private
archive quality, or public leaderboard parity. The command is stable and
included in `tools/run_quality_gates.py`.

## V2.8 Packaged Scope-Aware Answer Handoff Gate

V2.8 adds `benchmarks/scope_answer_handoff_gate.py` to prove that the
package-first answer handoff path can consume scope-arbitrated context-package
metadata from a clean packaged deployment repo. The gate installs the packaged
template, writes synthetic public global/domain/project memory rows, then
invokes the copied deployment `tools/search_memory.py` with
`--depth evidence --context-json` plus `--project-path` and
`--preferred-scope` where applicable. It parses
`report_kind: memory_recall_context_package` and builds deterministic
answer-or-abstain handoff decisions only from context package fields and
summary/evidence `support_refs`. Free-form search output is not used as
answerability evidence.

The synthetic cases cover global foundational answer handoff, domain-preferred
answer handoff, current project override handoff, same-topic wrong-project
support that must abstain, project-only support without project context that
must abstain, stale broad support that must abstain after supersession,
unsupported no-hit packages, and malformed packages that fail closed. The gate
reports aggregate metrics:
`scope_handoff_context_package_parse_success_rate`,
`scope_handoff_supported_answer_accuracy`,
`scope_handoff_abstention_accuracy`,
`scope_handoff_support_ref_coverage_rate`,
`scope_handoff_project_override_accuracy`,
`scope_handoff_wrong_project_rejection_count`,
`scope_handoff_missing_project_context_rejection_count`,
`scope_handoff_stale_broad_rejection_count`,
`scope_handoff_malformed_fail_closed_count`, `unsupported_claim_count`, and
`privacy_leak_count`.

This proves packaged scope-aware answer handoff consumption for context
packages. It does not prove live LLM answer quality, semantic equivalence,
ranking overhaul, vector search, ontology discovery, private archive quality,
or public leaderboard parity. The command is stable and included in
`tools/run_quality_gates.py`.

## V2.9 Packaged Generated-Answer Adapter Scope Contract Gate

V2.9 adds `benchmarks/generated_answer_scope_adapter_gate.py` to prove that the
scope-aware package-first contract is consumed by the real packaged
`tools/generate_answer_records.py` adapter, not only by the focused V2.8
handoff helper. The gate installs a clean packaged deployment repo, writes
synthetic public global/domain/project memory rows and synthetic answer cases,
then invokes the copied deployment `tools/generate_answer_records.py`. The
adapter reads case-level `preferred_scope` and `project_path`, passes them into
the copied `tools/search_memory.py --depth evidence --context-json`, parses
`report_kind: memory_recall_context_package`, and writes deterministic
answer-or-abstain records from the context-package handoff metadata and
summary/evidence `support_refs`. Free-form search output is not used as
answerability evidence.

The synthetic cases cover global current support, domain-preferred support,
current project override support, same-topic wrong-project rejection, project
support without project context rejection, stale broader support rejection
after supersession, unsupported no-hit packages, and malformed package
fail-closed behavior. The gate reports aggregate metrics:
`adapter_context_package_parse_success_rate`,
`adapter_scope_supported_answer_accuracy`,
`adapter_scope_abstention_accuracy`,
`adapter_scope_support_ref_coverage_rate`,
`adapter_project_override_accuracy`,
`adapter_wrong_project_rejection_count`,
`adapter_missing_project_context_rejection_count`,
`adapter_stale_broad_rejection_count`,
`adapter_malformed_fail_closed_count`,
`adapter_scope_field_pass_through_rate`, `unsupported_claim_count`, and
`privacy_leak_count`.

This proves packaged generated-answer adapter consumption of the scope-aware
context-package contract. It does not prove live LLM answer quality, semantic
ranking quality, vector search, ontology discovery, private archive quality, or
public leaderboard parity. The command is stable and included in
`tools/run_quality_gates.py`.

## V2.10 Deterministic Automation Publish Readiness Gate

V2.10 adds `benchmarks/automation_publish_readiness_gate.py` to prove that a
clean packaged deployment repository can distinguish safe automatic publish
intent from publish-blocking generated noise before `sync_memory_archive.py`
commits or pushes. The packaged repo now includes
`tools/audit_publish_readiness.py`, which scans only publish-facing generated
surfaces under `daily/` and text-bearing fields in `index/*.jsonl`. The audit
reports archive-relative paths, categories, and counts only; it does not render
matched snippets, memory text, source paths, raw refs, full queries, or secret
values.

The sync helper runs this readiness audit after the existing key-like value
scan and before the archive audit or Git staging. Clean daily and indexed
summary surfaces can reach `sync_memory_archive.py --dry-run --push` publish
intent. Noisy daily/indexed surfaces fail closed before staging, committing, or
pushing.

The synthetic cases cover clean daily records, clean indexed summaries, daily
command-progress noise, indexed prompt/environment noise, indexed raw source
path/full-query noise, and secret-like values. The gate reports aggregate
metrics including `publish_readiness_clean_pass_rate`,
`publish_readiness_noise_rejection_rate`, `sync_clean_publish_intent_count`,
`sync_noisy_block_count`, `automation_noise_rejection_count`,
`raw_source_reference_rejection_count`, `secret_like_rejection_count`,
`aggregate_only_report_count`, and `privacy_leak_count`.

This proves deterministic packaged automation publish readiness and
pre-commit/pre-push fail-closed behavior. It does not prove memory quality, LLM
answer quality, private archive quality, GitHub availability, semantic ranking
quality, vector search, ontology discovery, or public leaderboard parity. The
command is stable and included in `tools/run_quality_gates.py`.

## V2.13 Reusable Publish-Surface Repair Gate

V2.13 adds `tools/repair_publish_surfaces.py` and
`benchmarks/publish_surface_repair_gate.py` to prove that V2.12-style
publish-surface failures can be repaired in a reusable packaged deployment
repo without weakening `tools/audit_publish_readiness.py` or bypassing
`tools/sync_memory_archive.py`. The helper scans only structured
`sessions/**/meta.json` fields, emits aggregate counts only, and edits metadata
only when the repair is deterministic.

The synthetic gate reproduces command-progress, permission/sandbox chatter,
raw-source reference, and noisy tag/fact/summary cases that flow into
`daily/` and text-bearing `index/*.jsonl` publish surfaces. It verifies that
dry-run reports stay aggregate-only, apply mode rebuilds derived surfaces
through the updater, durable adjacent facts remain present, and publish
readiness passes after repair.

The gate also covers fail-closed boundaries: malformed metadata and ambiguous
single-scalar text are not guessed or partially repaired. Aggregate metrics
include `pre_repair_readiness_failure_count`,
`post_repair_readiness_pass_count`, `repairable_apply_success_count`,
`durable_fact_preservation_count`, `ambiguous_fail_closed_count`,
`malformed_fail_closed_count`, and `privacy_leak_count`.

This proves deterministic packaged publish-surface repair. It is not memory
quality, not LLM answer quality, not ranking quality, not vector search, not
ontology discovery, not GitHub availability, not private archive quality, and
not public leaderboard parity. The command is stable and included in
`tools/run_quality_gates.py`.

## V2.14 Scheduled Automation Recovery Drill

V2.14 adds `benchmarks/scheduled_publish_recovery_gate.py` to prove that the
agent-native scheduled automation prompt and packaged deployment runtime can
execute the publish-surface recovery sequence deterministically. The gate
creates clean packaged repositories through setup tooling, renders an
agent-native prompt with `--push-after-update`, verifies the prompt contract,
then runs synthetic recovery cases without live scheduler or LLM execution.

The prompt contract checks that the rendered automation instructions use the
memory repository as the only working directory, run
`python tools/search_memory.py --health-check` before
`python tools/sync_memory_archive.py --push`, rely on the sync helper instead of hand staging,
invoke `python tools/repair_publish_surfaces.py --apply` only
for publish readiness blocks, and stop when the repair helper reports
`blocked`.

The synthetic cases cover `repairable_metadata_noise`,
`ambiguous_scalar_noise`, and `malformed_metadata`. Repairable metadata noise
must block sync dry-run before staging, repair successfully, pass readiness,
and then reach sync dry-run publish intent. Ambiguous scalar noise and
malformed metadata must fail closed and never reach publish intent.

Aggregate metrics include `scheduler_prompt_contract_pass_rate`,
`pre_repair_sync_block_count`, `repair_apply_success_count`,
`post_repair_publish_intent_count`, `ambiguous_fail_closed_count`,
`malformed_fail_closed_count`, `hand_stage_bypass_count`, and
`privacy_leak_count`.

This proves deterministic scheduled automation recovery behavior. It is not live scheduler reliability, not live LLM prompt-following quality, not GitHub availability, not memory quality, not ranking quality, not vector search, not ontology discovery, not private archive quality, and not public leaderboard parity. The command is stable and included in `tools/run_quality_gates.py`.

## V2.15 Scheduled Automation Search-Gate Publish Decision Contract

V2.15 adds `benchmarks/scheduled_publish_search_gate.py` to prove that a clean
packaged deployment repository can classify scheduled publish decisions around
search discoverability, no-op state, and unexpected dirty surfaces before a
push is attempted. The gate renders an agent-native prompt with
`--push-after-update`, verifies the prompt uses `python tools/search_memory.py --health-check` before `python tools/sync_memory_archive.py --push`, and checks
that the prompt does not require a generic content query such as
`python tools/search_memory.py memory`.

The reusable release contract is deliberately narrow: `search_memory.py --health-check` is the required pre-sync archive searchability gate. Generic free-form content queries are deployment-local policy only; they are not a reusable release readiness gate and are not used as answerability or archive content evidence.

The synthetic cases cover `discoverable_archive_publish_ready`,
`empty_archive_search_blocked`, `already_current_no_op`, and
`unexpected_dirty_surface_blocked`. The publish-ready case must pass readiness
and search health after archive audit, then reach sync dry-run publish intent.
The search-blocked case must pass archive audit and publish readiness but stop
before sync publish intent when search health fails. The no-op case must avoid an empty commit or push intent.
The dirty case must block on an unexpected non-archive surface before publish.

Aggregate metrics include `search_gate_pass_rate`, `search_blocked_count`,
`no_op_no_empty_commit_count`, `unexpected_dirty_block_count`,
`publish_intent_count`, `hand_stage_bypass_count`,
`free_form_search_output_used_count`, and `privacy_leak_count`.

This proves deterministic scheduled publish decision classification around search/no-op/dirty blockers. It is not live GitHub availability, not live scheduler reliability, not live LLM prompt-following quality, not memory quality, not ranking quality, not vector search, not ontology discovery, not private archive quality, and not public leaderboard parity. The command is stable and included in `tools/run_quality_gates.py`.

## V2.16 Search-Healthy Content-Noise Repair Closure Gate

V2.16 adds `benchmarks/scheduled_content_noise_repair_closure_gate.py` to prove that a clean packaged deployment repository can close the scheduled publish loop when search health passes but publish-facing content still contains prompt/progress/usage/process noise. The gate renders an agent-native prompt with `--push-after-update`, checks `python tools/search_memory.py --health-check` before `python tools/sync_memory_archive.py --push`, verifies the prompt does not use free-form search output as answerability or archive-content evidence, and checks that it does not hand-stage files.

The reusable contract is deliberately layered: search health passing is necessary but not sufficient for publish. The content-noise readiness gate must still block publish until the repository reaches the deterministic repair -> rebuild -> archive audit -> publish readiness -> search health -> sync dry-run chain.

The synthetic cases cover `search_healthy_noise_repaired_publish_ready`,
`search_healthy_ambiguous_noise_blocked`,
`search_healthy_malformed_meta_blocked`,
`clean_after_repair_no_empty_commit`, and `durable_content_preserved`.
Repairable content noise must fail readiness before publish, repair through
`tools/repair_publish_surfaces.py`, rebuild derived surfaces through the
updater, pass archive audit/readiness/search health, and then reach sync
dry-run publish intent. Ambiguous scalar noise and malformed metadata must fail
closed before publish. A clean rerun after repair must avoid an empty commit or
push intent. Durable facts, summaries, tags, and evidence refs must survive
repair and rebuild.

Aggregate metrics include `search_health_pre_repair_pass_rate`,
`content_noise_block_count`, `repair_apply_success_count`,
`post_repair_readiness_pass_count`, `post_repair_search_health_pass_count`,
`post_repair_publish_intent_count`, `ambiguous_fail_closed_count`,
`malformed_fail_closed_count`, `no_empty_commit_count`,
`durable_content_preservation_count`, `hand_stage_bypass_count`,
`free_form_search_output_used_count`, and `privacy_leak_count`.

This proves deterministic closure for search-healthy content-noise repair. It is not live scheduler reliability, not live GitHub availability, not live LLM prompt-following quality, not memory quality, not ranking quality, not vector search, not ontology discovery, not private archive quality, and not public leaderboard parity. The command is stable and included in `tools/run_quality_gates.py`.

## V2.17 Real Deployment Publish Readiness Closure

V2.17 closes the observed deployment gap where archive audit and
`search_memory.py --health-check` passed, but `sync_memory_archive.py --push`
correctly refused to publish because generated publish-facing index fields
still contained command-progress or permission/sandbox chatter. The reusable
repair helper now handles a narrower deterministic case: a single-scalar
`summary` value that is entirely noisy can be replaced only when the same
structured `meta.json` record contains a clean durable fallback such as
`user_intent`, `reusable_facts`, `decisions`, `unresolved_tasks`, or `title`.
If no clean fallback exists, the repair still fails closed.

`benchmarks/publish_surface_repair_gate.py` adds
`fallback_summary_metadata_noise` to prove this exact failure class without
rendering private memory text. The packaged gate now requires 3 pre-repair
readiness failures, 2 post-repair readiness passes, 2 repairable apply
successes, 2 durable-content preservation checks, 1 ambiguous fail-closed
case, 1 malformed fail-closed case, and `privacy_leak_count=0`.

A private deployment dogfood run on 2026-07-09 stayed aggregate-only and
reported the following closure metrics after repair and sync:

| metric | value |
| --- | ---: |
| `publish_readiness_status` | `passed` |
| `publish_readiness_blocked_file_count` | 0 |
| `command_progress_count` | 0 |
| `permission_or_sandbox_count` | 0 |
| `raw_source_reference_count` | 0 |
| `privacy_leak_count` | 0 |
| `archive_audit_passed` | true |
| `search_health_memory_records` | 1444 |
| `search_health_active_memory_records` | 1442 |
| `sync_dry_run_status_after_publish` | `no_op` |

This proves a real deployment publish-readiness closure for this failure
class and keeps the reusable claim bounded. It is not live scheduler
reliability, not live LLM prompt-following quality, not GitHub availability in
general, not memory quality, not ranking quality, not vector search, not
ontology discovery, not private archive quality, and not public leaderboard
parity.

## V2.18 Live Codex Automation Prompt Alignment Gate

V2.18 closes the remaining scheduler configuration gap: the reusable
agent-native prompt and the real Codex scheduled automation now both spell out
the same publish-readiness, repair, recheck, sync dry-run, and sync-helper
publish path. The previous live automation prompt already ran the updater,
archive audit, search health check, and sync helper, but it did not explicitly
run `python tools/audit_publish_readiness.py`, did not run
`python tools/repair_publish_surfaces.py --apply` for repairable
publish-surface blockers, and did not require a post-repair
archive audit -> publish readiness -> search health -> sync dry-run chain.

`benchmarks/live_automation_prompt_alignment_gate.py` validates the public
synthetic prompt contract by rendering a clean packaged deployment repository
with `tools/render_scheduler.py --backend agent-native --push-after-update`.
It also supports a local live check with
`--automation-config /Users/example/.codex/automations/update-my-precious-memory/automation.toml`
without rendering the automation prompt text. The gate includes negative
prompts for missing publish-readiness coverage and raw git publish paths, so
the release check rejects both stale scheduler contracts and prompts that
bypass `tools/sync_memory_archive.py`.

The live Codex automation was inspected and updated on 2026-07-09. The
aggregate-only live alignment run reported:

| metric | value |
| --- | ---: |
| `live_automation_contract_checked` | 1 |
| `rendered_prompt_alignment_pass` | true |
| `live_automation_alignment_pass` | true |
| `publish_readiness_gate_present` | true |
| `repair_step_present` | true |
| `post_repair_recheck_present` | true |
| `sync_dry_run_before_push_present` | true |
| `sync_only_publish_path_present` | true |
| `raw_git_publish_path_count` | 0 |
| `private_archive_content_committed_count` | 0 |
| `privacy_leak_count` | 0 |

The aligned scheduled path is:
update -> archive audit -> publish readiness -> repair only for deterministic
repairable publish-surface blockers -> archive audit -> publish readiness ->
`search_memory.py --health-check` -> `sync_memory_archive.py --dry-run --push`
-> `sync_memory_archive.py --push`. Generic free-form content search output is
not used as archive readiness evidence, and raw `git add`, `git commit`, or
`git push` is not an allowed publish path.

This proves deterministic scheduler prompt alignment and publish-path
self-recovery coverage for the live Codex automation configuration. It does
not prove live scheduler reliability, live GitHub availability, live LLM
prompt-following quality, memory quality, ranking quality, vector search,
ontology discovery, private archive quality, or public leaderboard parity. The
synthetic command is stable and included in `tools/run_quality_gates.py`; the
local live check is a deployment verification command and is not required for
portable release gates.

## V2.19 Reviewable Automatic Induction Consolidation Gate

V2.19 adds `benchmarks/induction_consolidation_gate.py` as a packaged write-path
gate for deterministic automatic induction consolidation. The gate creates a
clean synthetic deployment archive, feeds synthetic source records through the
copied `tools/update_memory_archive.py`, and scores only structured memory,
review, and trace indexes. It does not use free-form summaries as
answerability evidence.

The gate proves four bounded behaviors: repeated durable facts consolidate into
one active memory with multiple support refs; paraphrased durable facts merge
only when deterministic normalized keys match; contradictory facts are
preserved with evidence instead of silently overwriting each other; and process
noise such as command status, prompt echo, approval/sandbox chatter, raw paths,
and automation narration is rejected before active-memory promotion. Ambiguous
scope narrowing is routed to induction review rather than becoming active
current memory automatically.

The V2.19 synthetic packaged run reported:

| metric | value |
| --- | ---: |
| `induction_duplicate_merge_accuracy` | 1.0 |
| `induction_paraphrase_merge_accuracy` | 1.0 |
| `induction_contradiction_preservation_count` | 1 |
| `induction_ambiguous_scope_review_count` | 1 |
| `induction_process_noise_rejection_count` | 4 |
| `induction_active_memory_precision` | 1.0 |
| `induction_support_ref_coverage_rate` | 1.0 |
| `review_routing_accuracy` | 1.0 |
| `privacy_leak_count` | 0 |

This proves a narrow deterministic consolidation and review-routing contract
for synthetic automatic induction. It does not prove live LLM induction
quality, vector search, broad ranking behavior, ontology discovery,
multi-principal governance, private archive quality, or public benchmark
leaderboard parity. The gate is deterministic and included in
`tools/run_quality_gates.py`.

## V2.20 Long-Horizon Lifecycle Governance Gate

V2.20 adds `benchmarks/lifecycle_governance_gate.py` as a packaged lifecycle
governance gate for synthetic long-horizon archive histories. The gate creates
a clean deployment archive, feeds synthetic source records through the copied
`tools/update_memory_archive.py`, queries the copied `tools/search_memory.py`
with context packages, and scores only structured memory, review, trace, and
context-package outputs. It does not use free-form search output as
answerability evidence.

The V2.20 gate proves six bounded behaviors: refreshed memories supersede old
support while default context packages answer from the active/current
replacement rather than the old node; deprecated-only support abstains;
explicit deletion is represented as a conservative `Deleted fact:` tombstone
marker using existing inactive lifecycle links rather than physical deletion;
related but non-equivalent partial conflicts route to review; isolated stale
low-support automatic memories are lowered to low confidence and routed to
memory review; and noisy multi-month prompt/progress/automation fragments do
not become active memory.

The V2.20 synthetic packaged run reported:

| metric | value |
| --- | ---: |
| `lifecycle_refresh_accuracy` | 1.0 |
| `lifecycle_deprecation_suppression_accuracy` | 1.0 |
| `lifecycle_deletion_tombstone_accuracy` | 1.0 |
| `lifecycle_partial_conflict_review_count` | 1 |
| `lifecycle_decay_or_stale_review_routing_accuracy` | 1.0 |
| `lifecycle_active_current_precision` | 1.0 |
| `lifecycle_inactive_search_suppression_rate` | 1.0 |
| `lifecycle_support_ref_coverage_rate` | 1.0 |
| `lifecycle_noisy_history_rejection_count` | 4 |
| `privacy_leak_count` | 0 |

This proves deterministic packaged lifecycle governance for refresh,
deprecation, tombstone deletion, inactive suppression, stale review routing,
and noisy synthetic multi-month histories. It does not prove physical deletion,
multi-principal ACL, live LLM memory judgment, vector search, ontology
discovery, private archive quality, public benchmark leaderboard parity, or a
complete long-horizon governance system. The gate is deterministic and included
in `tools/run_quality_gates.py`.

## V2.21 Aggregate-Only Private Lifecycle Shadow Gate

V2.21 adds `benchmarks/private_lifecycle_governance_shadow_gate.py` as a
read-only lifecycle observability gate for the same governance surfaces that
V2.20 made deterministic. The release gate uses only the public synthetic
fixture mode:

```bash
python3 benchmarks/private_lifecycle_governance_shadow_gate.py --synthetic-fixture
```

The runner can also be used as optional local dogfood against a private
deployment archive:

```bash
python3 benchmarks/private_lifecycle_governance_shadow_gate.py \
  --memory-repo /path/to/private-agent-memory \
  --output /tmp/my-precious-private-lifecycle-shadow.json
```

The private mode is intentionally not part of `tools/run_quality_gates.py`.
It may read structured archive indexes and use private memory text internally
as `tools/search_memory.py --depth evidence --context-json` queries, but its
report is aggregate-only. It does not render private queries, memory text,
memory IDs, source paths, source content, or raw refs. Reports may be written
only to stdout or an explicit `/tmp/...` path. If the archive-bundled search
tool cannot emit a context package, the runner may fall back to this repo's
template `search_memory.py`; only the fallback success count is rendered.

The V2.21 synthetic fixture reported:

| metric | value |
| --- | ---: |
| `private_lifecycle_relation_integrity_score` | 1.0 |
| `private_inactive_search_suppression_sample_rate` | 1.0 |
| `private_active_current_support_sample_rate` | 1.0 |
| `private_context_package_parse_success_rate` | 1.0 |
| `private_tombstone_marker_count` | 1 |
| `private_stale_review_candidate_count` | 1 |
| `private_support_ref_reachability_sample_rate` | 1.0 |
| `private_review_queue_actionability_rate` | 1.0 |
| `privacy_leak_count` | 0 |
| `rendered_private_query_count` | 0 |
| `rendered_memory_text_count` | 0 |
| `rendered_source_path_count` | 0 |
| `rendered_raw_ref_count` | 0 |

This proves deterministic aggregate-only lifecycle observability for relation
integrity, inactive search suppression, active/current context package support,
support-ref reachability, stale review routing, tombstone markers, and review
queue actionability. It does not prove private archive correctness by itself,
private coverage completeness, LLM answer quality, ranking quality, vector
search, ontology discovery, physical deletion, scheduler publication behavior,
or public leaderboard parity.

## V2.22 Aggregate-Only Active Support Failure Diagnosis

V2.22 keeps the V2.21 private lifecycle shadow gate private-data-free while
making active/current support failures actionable. The runner still emits only
aggregate JSON, but it now separates a low
`private_active_current_support_sample_rate` into fixed diagnosis counters:
expected active node missing, package-level unsupported answerability,
missing query support, missing summary/evidence drilldown, wrong active hit,
archive-bundled search-tool context-package failure, template search-tool
fallback success, and unknown privacy-preserved failure.

The release gate remains synthetic and private-free:

```bash
python3 benchmarks/private_lifecycle_governance_shadow_gate.py --synthetic-fixture
```

The V2.22 healthy synthetic fixture keeps the V2.21 metrics green and reports
zero active-support failures:

| metric | value |
| --- | ---: |
| `active_support_expected_node_missing_count` | 0 |
| `active_support_package_unsupported_count` | 0 |
| `active_support_query_support_missing_count` | 0 |
| `active_support_summary_drill_missing_count` | 0 |
| `active_support_evidence_drill_missing_count` | 0 |
| `active_support_wrong_active_hit_count` | 0 |
| `archive_search_tool_context_package_failure_count` | 0 |
| `template_search_tool_fallback_success_count` | 0 |
| `unknown_privacy_preserved_failure_count` | 0 |

The public test fixture also covers two fail-closed cases: a deliberately
broken archive-bundled search tool must be counted through aggregate fallback
counters without rendering command output, and a deliberately corrupted active
support node must produce nonzero support-failure counters without rendering
the query, memory text, memory ID, source path, raw ref, or package body.

An optional local private dogfood run after V2.22 stayed aggregate-only and
reported `privacy_leak_count: 0`. It converted the previously opaque
`private_active_current_support_sample_rate: 0.5` result into aggregate
diagnostics: `archive_search_tool_context_package_failure_count: 8`,
`template_search_tool_fallback_success_count: 8`,
`active_support_expected_node_missing_count: 1`,
`active_support_package_unsupported_count: 1`, and
`active_support_wrong_active_hit_count: 2`. This is observability evidence,
not a private archive correctness claim and not a private archive repair.

## V2.23 Archive-Bundled Search Tool Drift Repair

V2.23 closes the deployment-tool drift exposed by V2.22. It adds a narrow
setup-path repair contract:

```bash
python skills/setup-my-precious/scripts/setup_memory_archive.py \
  --path /path/to/agent-memory \
  --refresh-tools \
  --skip-config
```

The repair command refreshes only reusable `tools/**` files from the bundled
template. It does not rewrite archive data, indexes, source records, daily
records, session summaries, or user-owned config. It also fails closed when a
tool target resolves outside the archive, such as through a symlink.

The release gate now includes:

```bash
python3 benchmarks/search_tool_drift_repair_gate.py
```

The gate constructs a clean packaged deployment repo, deliberately replaces the
deployment repo's bundled `tools/search_memory.py` with a stale tool that cannot
emit `report_kind: memory_recall_context_package`, runs the documented
`--refresh-tools` repair command, and then verifies the deployment repo's own
`tools/search_memory.py` can produce a package-first
`--depth evidence --context-json` result. Template fallback is not used as
post-repair success evidence.

| metric | value |
| --- | ---: |
| `stale_search_tool_detected_count` | 1 |
| `repair_attempt_count` | 2 |
| `post_repair_context_package_success_count` | 1 |
| `template_fallback_used_after_repair_count` | 0 |
| `archive_data_mutation_count` | 0 |
| `unsafe_repair_fail_closed_count` | 1 |
| `privacy_leak_count` | 0 |

This proves synthetic deployment search-tool drift detection and repair. It
does not prove private archive correctness, private content repair, ranking
quality, LLM answer quality, vector search, ontology discovery, or scheduler
publish behavior.

## V2.25 Active Current Support Root-Cause Closure Gate

V2.25 addresses the remaining post-V2.24 active/current support question
without editing private archive content. V2.24 proved that the real deployment
search tool no longer needs template fallback to emit
`memory_recall_context_package`; the remaining private shadow failures were in
active/current support classification rather than deployment-tool drift.

The new public gate is:

```bash
python3 benchmarks/active_support_recall_closure_gate.py
```

It creates a clean packaged deployment archive, writes private-data-free
synthetic memory rows, invokes the copied deployment repo search tool with
`--depth evidence --context-json`, parses only
`report_kind: memory_recall_context_package`, and reuses the same
`active_support_diagnosis` recipe as the private lifecycle shadow gate. It does
not use free-form search output as answerability evidence.

The fixture covers four public cases:

- supported active/current memory with package, hit, query support, summary
  drilldown, and evidence drilldown all supported;
- expected active node missing while another active supported hit is present;
- expected active node present but package/hit answerability unsupported; and
- expected active node missing with an unsupported no-hit package.

The gate reports:

| metric | value |
| --- | ---: |
| `active_support_synthetic_case_pass_rate` | 1.0 |
| `active_support_context_package_parse_success_rate` | 1.0 |
| `active_support_expected_node_missing_reproduction_count` | 1 |
| `active_support_package_unsupported_reproduction_count` | 2 |
| `active_support_wrong_active_hit_reproduction_count` | 1 |
| `active_support_repair_success_rate` | 1.0 |
| `privacy_leak_count` | 0 |

An optional aggregate-only private dogfood run after V2.25 kept the V2.24
tool-drift repair green: `archive_search_tool_context_package_failure_count: 0`,
`template_search_tool_fallback_success_count: 0`,
`private_context_package_parse_success_rate: 1.0`, and
`privacy_leak_count: 0`. It still reported active-support failures through
aggregate counters, including expected-node-missing, package-unsupported, and
wrong-active-hit counts. Because the public synthetic closure gate passes, this
classifies the remaining private shadow failure as a private archive content or
sampling follow-up, not as a proven reusable search-tool or diagnosis bug.

This proves public synthetic coverage for the active-support failure taxonomy
and the aggregate diagnosis path. It does not prove private archive
correctness, private content repair, ranking quality, LLM answer quality,
vector search, ontology discovery, or public leaderboard parity.

## V2.27 Reviewed Automatic Memory Publish Gate

V2.27 closes the packaged publication mismatch between updater-generated
automatic memory layers and the intentionally narrow default sync boundary.
The default command still rejects automatic memory files. The only opt-in is
`--include-reviewed-memory-nodes`, which adds exactly
`memories/global.jsonl`, `memories/domains.jsonl`, and
`memories/projects.jsonl`; it does not allow the whole `memories/` directory,
review inputs, source-stream registries, tools, docs, or scheduler state.

The public synthetic gate is:

```bash
python3 benchmarks/reviewed_automatic_memory_publish_gate.py
```

It initializes a fresh packaged archive for every case and uses a local bare
Git remote for a real commit-and-push lifecycle. Reviewed mode runs changed-path
and key-like scans, archive and publish-readiness audits, memory/index parity,
lifecycle and evidence-reference checks, source drilldown checks, search health,
and candidate cached-diff validation before publication. Dry-run uses a temporary
Git index, so it exercises staged validation without changing the real index.

The gate reports:

| metric | value |
| --- | ---: |
| `default_mode_automatic_memory_rejection_rate` | 1.0 |
| `reviewed_mode_safe_dry_run_pass_rate` | 1.0 |
| `reviewed_mode_live_push_success_rate` | 1.0 |
| `reviewed_mode_exact_stage_scope_rate` | 1.0 |
| `reviewed_mode_exact_add_pathspec_rate` | 1.0 |
| `reviewed_mode_dry_run_index_preservation_rate` | 1.0 |
| `reviewed_mode_unsafe_rejection_accuracy` | 1.0 |
| `reviewed_mode_index_parity_rejection_count` | 1 |
| `reviewed_mode_lifecycle_rejection_count` | 1 |
| `reviewed_mode_content_noise_rejection_count` | 1 |
| `reviewed_mode_publish_readiness_rejection_count` | 1 |
| `reviewed_mode_secret_rejection_count` | 1 |
| `reviewed_mode_unexpected_path_rejection_count` | 5 |
| `privacy_leak_count` | 0 |

The unsafe cases cover index mismatch, broken lifecycle/evidence references,
automatic-memory noise, a key-like value without rendering it, search-health
failure, publish-readiness-only noise, and separate review/tool/source-stream/
unapproved-memory-sibling/other unexpected paths. The safe dry-run case seeds a
pre-existing staged blob and verifies that the real Git index is byte-identical
after candidate validation.

This proves deterministic packaged staged-path, audit, commit, and push closure
for an explicitly reviewed automatic-memory mode. It does not prove LLM answer
quality, ranking quality, vector search, ontology discovery, or public
leaderboard parity.

## V2.28 Bounded Long-Horizon Event-Boundary Memory Gate

V2.28 adds the first bounded packaged stress gate over hundreds of event
boundaries and multiple incremental epochs:

```bash
python3 benchmarks/long_horizon_memory_stress_gate.py
```

The gate creates a clean archive through the setup script and processes exactly
240 synthetic session records as six monthly epochs of 40 records. The workload
uses 12 project contexts, three archive domains, and two explicit non-project
source partitions. Each epoch runs the copied updater and its induction and
consolidation path before checkpoint recall. The final epoch is replayed without
new input to gate idempotence. No final memory node is preseeded.

The narratives cover cross-project support merge, paraphrase consolidation, a
three-generation supersession chain, pending conflict review followed by an
explicit approval, deprecation, 204 similar one-session distractors split
between temporary local decisions and process-log updates, and a sticky
explicit memory captured from a source event. The 16 checkpoint cases contain
nine answer cases and seven abstention cases, including a post-resolution probe
that requires the older
conflicting preference to remain unsupported. Answerability comes only
from copied deployment `search_memory.py` calls using
`--depth evidence --context-json`; answer cases additionally verify memory,
session, evidence, and source-ref depth packages.

The fail-first harness initially reported
`long_horizon_lifecycle_reciprocity_rate=0.6666666666666666` while every runtime
behavior metric passed. Inspection showed an oracle error: under the accepted
clean-cut contract, the final generation supersedes both prior generations and
both inactive nodes point directly to that unique current node. The harness had
incorrectly required the oldest node to retain the already-inactive intermediate
successor. Correcting that expectation required no updater, consolidation, or
search implementation change.

The expanded 24-support cross-project case then reproduced a separate generic
package handoff defect. Before the runtime fix, the active memory remained in
the underlying memory collector's top five but was displaced from a
`--limit 5` context package by higher-scoring session/index/markdown support
artifacts. The fail-first report had
`long_horizon_checkpoint_answer_accuracy=0.875` and
`long_horizon_active_current_recall_at_5=0.7777777777777778`; lifecycle, index,
replay, noise, and privacy gates still passed. The bounded fix prioritizes
active memory hits only while constructing the machine-readable context
package. Human-readable search ordering is unchanged. The search tool was then
synchronized across the template, setup asset, and read-path skill copy.

Two independent final runs passed in 37.789828 and 37.808815 seconds. Their JSON
reports were identical after removing `runtime_seconds`. Final metrics were:

| metric group | result |
| --- | ---: |
| ingest, checkpoint decision, abstention, active-current recall | 1.0 |
| stale suppression, cross-project generalization, paraphrase consolidation | 1.0 |
| noise rejection, explicit-memory survival, idempotent replay | 1.0 |
| session, evidence, and source-ref drilldown | 1.0 |
| lifecycle reciprocity, index parity, context-package parsing | 1.0 |
| `duplicate_active_memory_count` | 0 |
| `unexpected_active_memory_count` | 0 |
| `privacy_leak_count` | 0 |

The gate is deterministic, completes well below its 180-second limit, and is
not duplicative of the smaller lifecycle fixtures, so it is part of
`tools/run_quality_gates.py`.

The required aggregate-only private shadow command was also run on 2026-07-10
with `--sample-limit 24`. Against the pre-fix deployed search tool, it returned
`privacy_leak_count=0`, context-package parsing 1.0, inactive suppression 1.0,
lifecycle relation integrity 1.0, and support-ref reachability 1.0, but did not
pass overall. Active-current support was `0.7083333333333334`, with seven
expected-node-missing and seven package-unsupported samples. An aggregate-only
diagnosis found all seven expected nodes in the memory collector's top five and
in context packages at limit 50. Running the same shadow against the fixed
repository template produced active-current support 1.0 and zeroed all six
active-support failure counters, isolating deployment-tool drift rather than a
private-content defect.

After an explicitly approved tool-only deployment, the private repository's
`tools/search_memory.py` was synchronized byte-for-byte with the fixed template.
No memory record, index, session, source record, automation, scheduler, or
publish configuration changed. The deployed search health check, archive audit,
and publish-readiness audit passed. The exact deployed private shadow then
returned active-current support 1.0, context-package parsing 1.0, inactive
suppression 1.0, lifecycle relation integrity 1.0, review actionability 1.0,
and support-ref reachability 1.0. All active-support failure counters and
`privacy_leak_count` were zero. Neither run rendered a private query, memory
text, ID, source path, raw ref, or source content. This closes deployed-runtime
drift only; the aggregate shadow still does not establish private archive
content correctness or answer quality.

V2.28 proves bounded deterministic packaged behavior over 240 synthetic event
boundaries. It does not prove production scale, high-cardinality users, live
LLM induction or answer quality, vector retrieval, automatic ontology
discovery, multi-principal governance, official benchmark parity, or solved
long-term decay and deletion policy.

## V2.29 Exact Evidence-To-Original-Event Drilldown Gate

V2.29 closes the first bounded L0 source-event gap without putting source
content into the normal recall package. The updater now preserves physical
JSONL line number, per-line event ordinal, and normalized event hash. Generated
evidence quotes receive opaque source anchors, and versioned source maps bind
each quote to its exact locator while storing no raw event text. Automatic,
explicit, consolidated, and lifecycle memories retain their exact evidence and
source pairs.

The source preview is a separate machine-readable operation. The agent first
uses copied deployment search with `--depth source --context-json`, selects one
exact `source_ref_id` from a supported active/current hit, and then invokes:

```bash
python tools/resolve_memory_source.py "<query>" \
  --repo /path/to/agent-memory \
  --source-ref-id "src_<exact-id>" \
  --allow-source-root /path/to/authorized/source-root \
  --authorize-source-preview \
  --preview-json
```

The resolver emits `report_kind: memory_source_preview_package`. Before it
returns one bounded redacted preview, it re-runs the copied source-depth context
package, verifies active/current query support and exact-ref membership, checks
lexical and resolved root containment plus symlink components, validates the
whole source-record SHA-256, loads only the anchored JSONL line/event, and
validates the event hash. It accepts no `all` selector. Missing authorization
and every unsupported, stale, malformed, escaped, tampered, unsupported-format,
or legacy state returns no preview.

The deterministic packaged gate is:

```bash
python3 benchmarks/authorized_original_source_gate.py
```

It initializes a clean deployment archive and feeds exactly eight external
synthetic JSONL source records containing 32 events through the copied updater
and its real induction/consolidation path. No final memory node, evidence file,
source map, or index is prewritten. Cases cover a supporting fact after an
unrelated first event, two cross-project paraphrases with distinct sources, an
explicit non-first event, current versus superseded source events, authorized
and default-denied access, no-hit, inactive-only, wrong ref, root and symlink
escape, source and event hash mismatch, unsupported format, malformed context,
legacy source map, and a secret-bearing event whose safe text remains visible
after redaction.

Two independent runs completed in 4.924 and 4.891 seconds. Their reports were
identical after removing `runtime_seconds`, so the gate was added to
`tools/run_quality_gates.py`. Aggregate metrics were:

| metric | result |
| --- | ---: |
| `source_context_package_parse_success_rate` | 1.0 |
| `source_preview_package_parse_success_rate` | 1.0 |
| `source_anchor_assignment_accuracy` | 1.0 |
| `memory_evidence_quote_fidelity_rate` | 1.0 |
| `authorized_original_event_resolution_rate` | 1.0 |
| `default_source_content_block_rate` | 1.0 |
| `unsupported_source_rejection_rate` | 1.0 |
| `inactive_source_rejection_rate` | 1.0 |
| `source_integrity_failure_block_rate` | 1.0 |
| `legacy_source_map_fail_closed_rate` | 1.0 |
| `source_preview_redaction_accuracy` | 1.0 |
| `wrong_event_preview_count` | 0 |
| `unredacted_secret_count` | 0 |
| `raw_path_leak_count` | 0 |
| `raw_ref_leak_count` | 0 |
| `privacy_leak_count` | 0 |

V2.29 proves bounded generic JSONL event resolution in a clean packaged
deployment after package-first support validation. It does not prove arbitrary
transcript-format support, private production correctness, bulk source access,
multi-principal authorization, LLM answer or induction quality, ranking
quality, vector search, ontology discovery, or public leaderboard parity.

## V2.30 Transactional Legacy Source-Anchor Upgrade Gate

V2.30 adds a safe migration path for entries created before V2.29. Existing
backfill first removes and regenerates an archive entry, so it cannot establish
semantic parity or exact rollback for an anchor-only migration. The new copied
deployment tool, `tools/upgrade_source_anchors.py`, instead reconstructs
provenance from the unchanged evidence quote and external JSONL source event.
It does not re-run summarization or induction.

Focused fail-first evidence confirms the distinction: when existing backfill
has removed the selected entry and its mocked `write_record()` returns `None`,
the command returns success with the old entry still absent. That behavior is
valid evidence that backfill is not the transactional migration primitive; it
is not changed by V2.30.

Dry run and apply both emit
`report_kind: memory_source_anchor_upgrade_package`. Apply accepts exactly one
source record, requires an exact archived source SHA-256 plus lexical and
canonical root containment, and rejects zero or multiple event matches. The only
allowed changes are source-anchor version/mappings, corresponding meta anchor
IDs, and matching memory raw-ref anchors. Every replacement is prepared before
mutation; target hashes are rechecked; archive audit and search health run
after replacement; any failure restores original bytes and modes.

The deterministic packaged gate is:

```bash
python3 benchmarks/legacy_source_anchor_upgrade_gate.py
```

It creates exactly six external synthetic JSONL records with 24 events, uses
the copied updater to generate real summaries, evidence, source maps, memory
nodes, and indexes, then removes provenance fields only to create the legacy
fixture. Cases cover a non-first automatic fact, natural-user transformation,
non-first explicit memory, incremental cross-project paraphrase sources,
current and superseded nodes, secret redaction policy, already-current replay,
missing/drifted/malformed sources, root and symlink escape, malformed source
map, absent and ambiguous quotes, stale target fingerprints, mid-transaction
failure, and post-audit rollback.

Two independent runs completed in 5.983 and 5.937 seconds. Reports were
identical after removing `runtime_seconds`, so the gate was added to
`tools/run_quality_gates.py`. Every deterministic rate below was `1.0`:

| metric group | metrics |
| --- | --- |
| package and eligibility | `legacy_upgrade_package_parse_success_rate`, `legacy_upgrade_eligibility_accuracy` |
| binding and semantic parity | `legacy_exact_binding_accuracy`, `legacy_memory_id_parity_rate`, `legacy_memory_text_hash_parity_rate`, `legacy_evidence_quote_parity_rate`, `legacy_lifecycle_parity_rate`, `legacy_support_count_parity_rate` |
| apply and resolver | `legacy_safe_apply_success_rate`, `legacy_post_upgrade_resolver_success_rate`, `legacy_idempotent_replay_rate`, `legacy_already_current_noop_rate` |
| transaction safety | `legacy_transaction_rollback_rate`, `legacy_post_audit_rollback_rate`, `legacy_optimistic_concurrency_rejection_rate` |
| fail-closed policy | `legacy_source_hash_drift_rejection_rate`, `legacy_missing_source_rejection_rate`, `legacy_unsafe_path_rejection_rate`, `legacy_ambiguous_binding_rejection_rate`, `legacy_secret_policy_accuracy` |

`unexpected_semantic_change_count`, `partial_upgrade_count`,
`wrong_event_preview_count`, `unredacted_secret_count`,
`raw_path_leak_count`, `raw_ref_leak_count`, and `privacy_leak_count` were all
zero.

The 2026-07-11 aggregate-only private readiness scan sampled 24 legacy entries
without installing or applying a private tool. Twenty-three were eligible and
one was rejected as `ambiguous_evidence_event_binding`; the eligible sample
contained 86 exact quote bindings. The private repository Git status hash was
unchanged before and after the scan. This is readiness evidence only and not permission to migrate;
it is also not proof of private content correctness.

V2.30 proves bounded, single-record, provenance-only migration for supported
JSONL in a clean packaged deployment. It does not prove arbitrary transcript formats.
It also does not prove batch or production-wide migration safety,
actual private deployment, public benchmark parity, LLM answer or induction quality, ranking
quality, vector search, ontology discovery, or multi-principal governance.

## V2.31 Archive Regeneration Reference-Closure Gate

V2.31 closes two archive-regeneration failures observed by the deployment
workflow without weakening the archive auditor. Replacing a source record can
delete its old session package while an existing sticky explicit memory still
contains the old summary, evidence, and source-map references. Daily rendering
can also clip a combined summary inside a Markdown emphasis span, producing an
incomplete durable index line.

The updater now reconciles archive-internal explicit-memory provenance after
existing and newly generated nodes have been merged. A failed component
invalidates its complete session support bundle; valid memory-ID lifecycle
links and non-session reference policy remain unchanged. Support counts are
rederived from surviving evidence bundles. If reconciliation leaves an
explicit memory without evidence, the updater exits with a bounded aggregate
diagnostic instead of silently deleting or persisting the node.

Daily records use a dedicated bounded clipper. It prefers sentence or word
boundaries and removes Markdown emphasis markers before clipping when the
normal boundary would leave an unbalanced span. The global clip behavior and
the audit categories remain unchanged.

The deterministic packaged gate is:

```bash
python3 benchmarks/archive_regeneration_closure_gate.py
```

It creates two independent pairs of clean synthetic deployment repositories.
Each successful case performs a source update, creates an explicit lifecycle
link through the copied updater, replaces the source package, reruns the copied
updater, and then executes packaged archive audit, search health, reviewed sync
dry-run, and an idempotent replay. A separate case removes the only support for
a sticky explicit memory and requires a fail-closed result. The two structured
reports are identical.

| metric | result |
| --- | ---: |
| `regeneration_bundle_reconciliation_accuracy` | 1.0 |
| `stale_derived_ref_count` | 0 |
| `stale_evidence_ref_count` | 0 |
| `stale_raw_ref_count` | 0 |
| `support_count_consistency_rate` | 1.0 |
| `lifecycle_link_retention_rate` | 1.0 |
| `orphan_explicit_fail_closed_accuracy` | 1.0 |
| `daily_structure_safe_clip_accuracy` | 1.0 |
| `daily_durable_fact_retention_rate` | 1.0 |
| `post_regeneration_archive_audit_pass_rate` | 1.0 |
| `post_regeneration_search_health_pass_rate` | 1.0 |
| `reviewed_sync_dry_run_pass_rate` | 1.0 |
| `idempotent_replay_rate` | 1.0 |
| `privacy_leak_count` | 0 |

V2.31 proves reference and daily-render closure for supported synthetic
packaged regeneration. It does not prove whole-repository transaction rollback,
private deployment correctness or recovery, LLM summarization quality, ranking
quality, vector search, ontology discovery, or public leaderboard parity.

## V2.34 Runtime Tool-Bundle Parity And Fail-Closed Repair Gate

V2.34 adds `benchmarks/runtime_tool_bundle_parity_gate.py` and a structured
full-bundle contract to `setup_memory_archive.py`. The setup script's bundled
`assets/agent-memory-repo/tools/` directory is the source of truth for this
comparison. `--check-tools --report-json` reports deterministic SHA-256 bundle
identities and exits nonzero for missing, stale, or unsafe expected tools.
`--refresh-tools --dry-run --report-json` reports `repairable` without mutation;
live `--refresh-tools` replaces only missing or stale source-owned files,
preserves matching and extra user-owned tools, verifies post-refresh parity,
and fails closed on unsafe targets or replacement failure.

The packaged gate creates clean synthetic deployments twice. In each repair
case it makes two tools stale, removes two tools, adds an extra user tool,
preserves synthetic archive-side data, and exercises check, dry-run, refresh,
post-check, idempotent replay, packaged update, archive audit, search health,
and reviewed sync dry-run. A separate symlink case must be rejected before the
first write. The two aggregate reports must be identical.

| metric | result |
| --- | ---: |
| `runtime_bundle_report_parse_success_rate` | 1.0 |
| `runtime_bundle_clean_detection_accuracy` | 1.0 |
| `runtime_bundle_drift_detection_accuracy` | 1.0 |
| `runtime_bundle_missing_detection_accuracy` | 1.0 |
| `runtime_bundle_stale_detection_accuracy` | 1.0 |
| `runtime_bundle_refresh_success_rate` | 1.0 |
| `runtime_bundle_post_refresh_parity_rate` | 1.0 |
| `runtime_bundle_archive_preservation_rate` | 1.0 |
| `runtime_bundle_extra_tool_preservation_rate` | 1.0 |
| `runtime_bundle_unsafe_target_rejection_rate` | 1.0 |
| `runtime_bundle_idempotent_refresh_rate` | 1.0 |
| `post_refresh_packaged_update_success_rate` | 1.0 |
| `post_refresh_archive_audit_pass_rate` | 1.0 |
| `post_refresh_search_health_pass_rate` | 1.0 |
| `post_refresh_reviewed_sync_dry_run_pass_rate` | 1.0 |
| `absolute_path_leak_count` | 0 |
| `privacy_leak_count` | 0 |

V2.34 proves deterministic parity checking and archive-preserving repair
against the setup script's bundled reusable tools.

It does not prove that an installed skill is the latest GitHub release.
It does not prove live private deployment correctness.
It does not prove automatic code deployment.
It does not prove scheduler reliability.
It does not prove LLM quality.
It does not prove ranking quality.
It does not prove vector search.
It does not prove ontology discovery.
It does not prove public leaderboard parity.

## V2.35 Three-Layer Distribution And Scheduled Parity Preflight Closure

V2.35 consumes the merged V2.34 interface without changing installable skills
or runtime templates. It makes the release boundary explicit as
`source -> installed skills -> private deployment`: merged source is installed
through a reviewed, rollback-capable copy; the installed setup skill then
checks and repairs only its source-owned deployment tools; scheduled automation
checks parity before updater execution and never installs or refreshes tools.

`benchmarks/three_layer_distribution_preflight_gate.py` models all three layers
in public-data-free temporary directories. It detects stale installed skills,
missing/stale and unsafe deployment tools, malformed or wrong-contract reports,
nonzero exits, and non-`current` states. Every rejected case leaves the fake
updater untouched. Explicit repair occurs outside the scheduled harness, after
which two identical `current` reports allow one updater marker. The gate runs
twice and requires identical aggregate evidence and a valid deterministic
bundle hash.

| synthetic metric | result |
| --- | ---: |
| `source_installed_parity_detection_accuracy` | 1.0 |
| `installed_deployment_parity_detection_accuracy` | 1.0 |
| `stale_installed_rejection_accuracy` | 1.0 |
| `drifted_deployment_rejection_accuracy` | 1.0 |
| `unsafe_deployment_rejection_accuracy` | 1.0 |
| `malformed_preflight_rejection_accuracy` | 1.0 |
| `preflight_blocks_update_accuracy` | 1.0 |
| `current_preflight_allows_update_accuracy` | 1.0 |
| `preflight_idempotence_rate` | 1.0 |
| `archive_preservation_rate` | 1.0 |
| `extra_tool_preservation_rate` | 1.0 |
| `privacy_leak_count` | 0 |

`benchmarks/live_automation_prompt_alignment_gate.py` additionally requires the
real automation contract to place `--check-tools --report-json` before updater
execution, describe fail-closed handling, retain the existing audit and reviewed
sync chain, and reject updater-before-preflight or executable auto-refresh
prompts. Aggregate-only local closure produced the following evidence without
recording paths, prompt text, hashes, or private archive content:

| live metric | result |
| --- | ---: |
| `live_source_installed_skill_parity_rate` | 1.0 |
| `live_installed_deployment_bundle_parity_rate` | 1.0 |
| `live_preflight_current_rate` | 1.0 |
| `live_preflight_idempotent_rate` | 1.0 |
| `live_automation_prompt_alignment_rate` | 1.0 |
| `live_archive_mutation_count` | 0 |
| `live_unexpected_tool_change_count` | 0 |
| `privacy_leak_count` | 0 |

V2.35 proves explicit local three-layer distribution and a deterministic
scheduled prompt preflight contract. It does not prove scheduler reliability.
It does not prove network reliability.
It does not prove future archive-update reliability, automatic release discovery, private memory quality, LLM quality,
ranking quality, vector search, ontology discovery, or public leaderboard
parity.

## V2.36 Public Conversation Source-To-Induction Recall Evidence Gate

V2.36 adds `benchmarks/public_induction_recall_gate.py`. Unlike the existing
public adapter, this gate does not generate external memory nodes from
question/answer rows. It reads LongMemEval conversations outside the repository,
keeps benchmark questions and gold labels in the scorer, writes each haystack
session as one role/content-only source record, creates one clean packaged
deployment per selected question, runs the copied updater and audit, and
consumes session-, evidence-, and source-depth context packages. Evidence-depth
packages are the only answer-or-abstain source. The session baseline uses the
same copied search module's structured `Hit.path` because privacy-safe session
packages intentionally do not render L1 paths.

The offline schema-compatible fixture is included in the canonical quality gate:

```bash
python3 benchmarks/public_induction_recall_gate.py --offline-fixture
```

The external run used the official LongMemEval cleaned S file pinned to source
commit `98d7416c24c778c2fee6e6f3006e7a073259d48f`:

```text
https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json
```

The downloaded file remained outside this repository. Its SHA-256 was
`d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
The input contained 500 rows. Fixed seed `my-precious-v236` selected five
positive cases from each of the six official non-abstention question types plus
ten abstention cases. The 40-case selection fingerprint was
`4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7`.
Those cases contained 1,912 haystack sessions.

The external command used `/tmp` only for the downloaded input, generated
archives, and aggregate report:

```bash
python3 benchmarks/public_induction_recall_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --seed my-precious-v236 \
  --positive-per-type 5 \
  --abstention-count 10 \
  --work-dir /tmp/my-precious-public-induction-run \
  --report-file /tmp/my-precious-public-induction-report.json
```

The final aggregate report SHA-256 was
`eb101f6c38356dcdf3c1fa2bb9817c20666b2aab7309ab84b91b40fa4b44c271`.
It returned `status: failed` and
`readiness_status: inconclusive`. This is an accepted bounded negative result,
not a passing public gate.

Structural and ingestion evidence:

| metric | numerator / denominator | rate or count |
| --- | ---: | ---: |
| deterministic case selection | 1/1 | 1.0 |
| source-record conversion | 1912/1912 | 1.0 |
| session-boundary preservation | 1912/1912 | 1.0 |
| role preservation | 1912/1912 | 1.0 |
| timestamp preservation | 1912/1912 | 1.0 |
| packaged setup success | 40/40 | 1.0 |
| updater success | 40/40 | 1.0 |
| archive audit success | 34/40 | 0.85 |
| context-package parse success | 120/120 | 1.0 |
| automatic-memory yield | 40/40 | 1.0 |
| active memory nodes | count | 6280 |
| induction review candidates | count | 58 |
| inactive memory nodes | count | 0 |
| gold-label ingestion count | count | 0 |
| answer-field ingestion count | count | 0 |
| synthetic memory-marker injection count | count | 0 |
| direct synthetic archive injection count | count | 0 |
| free-form answerability use count | count | 0 |
| privacy leak count | count | 0 |

The gold-label ingestion count is 0; direct synthetic archive injection count is 0.
Questions, answers, case IDs, memory IDs, memory text, source
content, source paths, raw refs, and context-package payloads were not rendered
in the aggregate report.

The six audit failures were deterministic `category=process_update` findings in
generated archive surfaces. Aggregate distribution was one knowledge-update
case, two single-session-preference cases, one single-session-user case, and two
temporal-reasoning cases. Findings occurred across generated summary, evidence,
daily, session-index, decision-index, and memory-index files. This shows that
some natural conversation wording is promoted into content that the existing
coding-agent archive audit classifies as process noise. V2.36 does not change
production induction or audit heuristics to hide that result.

Recall and decision evidence:

| metric | numerator / denominator | rate |
| --- | ---: | ---: |
| L1 gold-session recall at 5 | 13/30 | 0.4333333333 |
| induced gold provenance recall at 1 | 0/30 | 0.0 |
| induced gold provenance recall at 5 | 0/30 | 0.0 |
| induction provenance retention at 5 | 0/13 | 0.0 |
| supported-decision precision | 0/0 | 0.0 |
| abstention accuracy | 10/10 | 1.0 |
| malformed-package fail closed | 1/1 | 1.0 |
| missing-package fail closed | 1/1 | 1.0 |
| inactive-only rejection | 1/1 | 1.0 |
| superseded-only rejection | 1/1 | 1.0 |

Only 13/30 positive cases were baseline-retrievable, below the predeclared
minimum of 20, so the run is `inconclusive` rather than a performance `no_go`.
No evidence package produced a supported answer decision, so supported-decision
precision has a zero denominator. The 10/10 abstention result therefore shows
fail-closed behavior, not useful positive-answer coverage. Evidence and source
anchor reachability also had zero supported-hit denominators; their vacuous
rate values are not positive readiness evidence. The meaningful retention
result is 0/13 on baseline-retrievable positives.

V2.36 proves that a label-isolated public conversation harness can execute the
real packaged setup, updater, audit, and structured context-package paths and
produce an aggregate negative result without leaking public case material. It
also falsifies the stronger claim that the current automatic-induction path is
ready for this bounded LongMemEval natural-conversation slice.

It is not LLM answer quality. It is not official LongMemEval leaderboard parity.
It is not vector search quality. It is not ontology discovery. It is not private archive quality.
It is not multi-principal governance. Any follow-up should be
a separate bounded goal that first chooses which observed blocker to study:
coding-agent process-noise audit compatibility, L1 public-query retrieval, or
natural-conversation induction support. V2.36 does not implement those changes.

## V2.37 Public Query-Support Calibration With Frozen Holdout

V2.37 adds `benchmarks/public_query_support_calibration_gate.py`. It reuses the
V2.36 label-isolated source conversion and real packaged lifecycle, but separates
policy calibration from a frozen holdout. The holdout is exactly the V2.36
selection with fingerprint
`4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7`.
Seed `my-precious-v237-calibration` selects another five positives per official
question type plus ten abstentions after excluding every holdout ID. The
calibration fingerprint is
`c8ac66423f41b968ca60c9af18ae3f2c949f534a8f875d8997ec83cd8fbb5e19`;
the cohort overlap count is 0.

The three policies were frozen before public scoring:

| policy | rule |
| --- | --- |
| `strict_v1` | existing complete meaningful, strict, or important-token coverage |
| `weighted_partial_060_v1` | at least two matches, weighted coverage at least 0.60, and no missing importance-4 token |
| `weighted_partial_050_specific_v1` | at least two matches, weighted coverage at least 0.50, one importance-2 match, and no missing importance-4 token |

Rank, gold provenance, question type, benchmark IDs, and dataset-specific token
exceptions were not candidate-policy inputs. Free-form output was not used for
answerability. The fast synthetic policy-selection contract is canonical:

```bash
python3 benchmarks/public_query_support_calibration_gate.py --offline-fixture
```

The public runs used the same pinned LongMemEval cleaned S file as V2.36:

```text
https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json
SHA-256: d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442
```

Calibration command:

```bash
python3 benchmarks/public_query_support_calibration_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort calibration \
  --work-dir /tmp/my-precious-v237-calibration \
  --report-file /tmp/my-precious-v237-calibration-report.json
```

The calibration report SHA-256 is
`789f979563fbb249464723cdd76a1d28f8c9ac12cdeb44f5f6287f8979958ec7`.
It returned `status: failed`, `readiness_status: inconclusive`, and
`decision_reason: insufficient_gold_candidates`.

Calibration structure and attribution:

| metric | numerator / denominator | rate or count |
| --- | ---: | ---: |
| packaged setup | 40/40 | 1.0 |
| updater success | 38/40 | 0.95 |
| archive audit success | 32/40 | 0.80 |
| context-package parse success | 38/40 | 0.95 |
| baseline-retrievable positives | 11/30 | 0.3666666667 |
| gold-derived memory present | 11/11 | 1.0 |
| active/current gold-derived memory | 11/11 | 1.0 |
| gold memory candidate at 1 | 4/11 | 0.3636363636 |
| gold memory candidate at 5 | 4/11 | 0.3636363636 |
| retrieval first loss | 7/11 | 0.6363636364 |
| query-support first loss | 4/11 | 0.3636363636 |
| attribution invariant violations | count | 0 |
| privacy leaks | count | 0 |

Two calibration cases were rejected by the existing updater secret gate for
cookie-like and GitHub-token-like source patterns. V2.37 did not use
`--allow-redacted-secrets`, change the updater, replace the selected cases, or
lower the five-candidate minimum. The resulting four gold candidates make the
calibration performance decision inconclusive. Audit failures were also
retained rather than repaired because archive-audit behavior is outside this
goal.

Calibration policy results:

| policy | gold support | precision | abstention | hard-negative rejection |
| --- | ---: | ---: | ---: | ---: |
| `strict_v1` | 0/4 | 0/0 | 10/10 | 3/3 |
| `weighted_partial_060_v1` | 2/4 | 2/2 | 10/10 | 1/3 |
| `weighted_partial_050_specific_v1` | 2/4 | 2/3 | 9/10 | 1/3 |

Both partial policies failed the predeclared `hard_negative_rejection_rate =
1.0` requirement. The looser policy also produced one false abstention-cohort
support. Therefore neither policy was eligible even apart from the insufficient
public denominator.

Had a policy passed calibration, the gate would have emitted the intermediate
`calibration_passed` state before guarded integration. That state is not a final `go`;
selected-runtime parity and all final safety thresholds remain holdout requirements.

Frozen holdout command:

```bash
python3 benchmarks/public_query_support_calibration_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort holdout \
  --selected-policy none \
  --work-dir /tmp/my-precious-v237-holdout \
  --report-file /tmp/my-precious-v237-holdout-report.json
```

The frozen holdout returned `status: completed`, `readiness_status: no_go`, and
`decision_reason: no_safe_policy`. The aggregate-only report SHA-256 was
`5106e9379647edeacb71a7161bacd7c602b8ea246a34b8911f514a81c063613d`.

Frozen holdout structure and attribution:

| metric | numerator / denominator | rate or count |
| --- | ---: | ---: |
| packaged setup | 40/40 | 1.0 |
| updater success | 40/40 | 1.0 |
| archive audit success | 34/40 | 0.85 |
| context-package parse success | 40/40 | 1.0 |
| baseline-retrievable positives | 13/30 | 0.4333333333 |
| gold-derived memory present and active | 13/13 | 1.0 |
| gold memory candidate at 1 | 6/13 | 0.4615384615 |
| gold memory candidate at 5 | 6/13 | 0.4615384615 |
| strict query-supported gold candidates | 0/6 | 0.0 |
| retrieval first loss | 7/13 | 0.5384615385 |
| query-support first loss | 6/13 | 0.4615384615 |
| abstention accuracy | 10/10 | 1.0 |
| hard-negative rejection | 3/3 | 1.0 |
| ranking_drift_count = 0 | count | 0 |
| privacy leaks | count | 0 |

This formalizes the V2.36 preflight: induction provenance was present for all
13 baseline cases, seven were lost before context top five, and six correct
rank-one candidates were rejected by strict query support. The two proposed
partial relaxations were not safe enough to ship. The production query-support behavior remained unchanged;
no search-tool template sync was required.

V2.37 is a bounded safe-no-change result. It proves disjoint public calibration,
frozen holdout attribution, policy/runtime parity, and fail-closed candidate
selection. It is not ranking repair. It is not archive-audit repair. It is not induction-content quality.
It is not LLM answer quality, vector search,
ontology discovery, private archive quality, or public leaderboard parity.

## V2.38 Scheduled Update Single-Writer And Interrupted-Run Recovery Closure

V2.38 closes the reusable runtime defect reproduced by overlapping scheduled
updates: two global runners could mutate one deployment archive concurrently,
a failed child did not stop later children, and task completion could be reported
without a verifiable remote publication receipt.

The deterministic public gate is:

```bash
python3 benchmarks/scheduled_update_single_writer_gate.py
```

The runner now acquires a repo-scoped exclusive lock before registry discovery
or archive mutation. The parent and current child hold the same lock ownership;
therefore an orphaned child keeps a second writer blocked until that child exits.
A competing runner returns nonzero with
`update_status=blocked reason=concurrent_update` and aggregate-only output. The
project/source-stream loops use first failure fail-fast behavior, and managed
SIGINT/SIGTERM handling terminates the current child before releasing ownership.
Scheduled global commands use `--require-clean-worktree`, which rejects tracked,
deleted, and untracked startup state before any child launch.

The synthetic gate reports:

| metric | value |
| --- | ---: |
| `single_writer_acceptance_rate` | 1.0 |
| `concurrent_writer_rejection_rate` | 1.0 |
| `dirty_startup_rejection_rate` | 1.0 |
| `first_failure_fail_fast_rate` | 1.0 |
| `post_failure_child_launch_count` | 0 |
| `parent_termination_child_cleanup_rate` | 1.0 |
| `orphan_child_lock_retention_rate` | 1.0 |
| `lock_release_after_exit_rate` | 1.0 |
| `publish_attempt_after_failed_update_count` | 0 |
| `privacy_leak_count` | 0 |

The scheduler prompt contract separately requires a publication receipt. Codex
task completion is not publish success. After the sync helper, the automation
fetches the remote and verifies a clean worktree plus equality between
`git rev-parse HEAD` and `git rev-parse origin/main`. It may emit only
`published`, `no_op_current`, or `blocked`; a command failure, missing receipt,
dirty state, or commit mismatch is `blocked`. The alignment gate includes
negative cases for a missing clean-worktree flag and a missing receipt contract.

The bounded private recovery was completed on 2026-07-12 without committing
private evidence to this repository. The failed generated state was first
classified by aggregate path counts and quarantined locally. A controlled run
then completed 71/71 registered project updates, zero source-stream updates, and
exit zero in approximately 83 minutes while process sampling showed one runner
and at most one updater child.

The first post-run audit correctly blocked publication on four stale memory-ID
targets retained by one explicit node after clean-cut regeneration removed the
old automatic nodes. The reusable repair now reconciles against both current and
committed durable memory IDs, removes only targets proven to have disappeared,
and preserves unknown missing refs for fail-closed audit. Its focused
updater/audit suite passed 184 tests. A zero-record locked rebuild then closed
the stale edges. The archive audit, publish-readiness audit, and search health
check passed; publish-surface repair reported zero malformed or ambiguous
records and zero privacy leaks.

The serialized runner defers stale-edge closure on all non-final updater
children, so only the final child reconciles after every prior child succeeds.
Later-project regeneration therefore cannot be erased by an earlier intermediate rebuild.

The reviewed sync helper committed and pushed archive commit `a8fd832`. A fresh
fetch proved local `HEAD` equals `origin/main`, the commit advanced from the
pre-publication SHA, and the worktree was clean. A total of three local stashes
containing the original failed state and blocked recovery checkpoints remain retained. The
original concurrent-failure stash was never reapplied or published; later clean
recovery checkpoints were used locally to continue the same recovery, while the
stash refs themselves were never pushed or dropped. The live automation prompt
alignment gate passed with zero privacy leaks and zero raw Git publish paths,
after which the existing automation was restored to `status: ACTIVE`.

V2.38 proves current-platform, single-host scheduled update ownership,
first-failure propagation, bounded process cleanup, dirty-startup rejection,
and deterministic publication-status semantics. It is not whole-run rollback,
not a cross-host distributed lock, not a GitHub availability SLA, and not memory quality.
It also does not change ranking, induction, schema, archive audit
heuristics, or sync allowlists.

## V2.39 Scheduled Update Single-Inventory And Single-Finalization Throughput Closure

Date: 2026-07-13

V2.39 addresses the two repeated-work paths measured after V2.38's controlled
71-project run took approximately 83 minutes. The global runner previously
scanned the shared source directory once for project discovery, then each
project updater scanned and parsed it again. Every successful updater also ran
the archive-wide `rebuild_indexes()` path, even when it selected zero records.

The deterministic public gate is:

```bash
python3 benchmarks/scheduled_update_throughput_gate.py
```

The runner now builds one in-memory inventory for each unique canonical source
root and pattern set. It reuses that inventory for project discovery and target
selection, then sends only target-specific metadata through stdin. The payload
contains relative paths and integrity metadata, never source content. The child
revalidates containment, metadata, hash, project matching, and automation-source
exclusion before mutation. Malformed, duplicate, outside-root, symlink-escape,
or changed inventory records fail closed with aggregate-only diagnostics.

Each ingestion child writes authoritative session metadata while deferring
derived surfaces. During this interval high-water selection reads authoritative
session metadata rather than the now-stale generated session index. After every
project and source-stream child succeeds, one finalize-only child rebuilds all
derived indexes, daily views, memory nodes, and clean-cut references. An
ingestion failure launches no finalizer; a finalizer failure propagates nonzero.
Dry runs and runs without runnable targets do not finalize.

The public gate uses a lightweight 71-target scheduling case for deterministic
operation counts and a smaller actual-updater case for byte-for-byte comparison
against the V2.38 scripts. It also reruns the V2.38 single-writer gate.

| metric | value |
| --- | ---: |
| `source_inventory_amplification` | 1.0 |
| `source_root_rescan_count` | 0 |
| `nonselected_record_reparse_count` | 0 |
| `target_dispatch_accuracy` | 1.0 |
| `successful_run_finalization_count` | 1 |
| `failed_run_finalization_count` | 0 |
| `output_parity_rate` | 1.0 |
| `output_parity_scenario_count` | 4 |
| `fail_closed_inventory_rejection_rate` | 1.0 |
| `single_writer_regression_pass_rate` | 1.0 |
| `synthetic_redundant_work_reduction_rate` | 0.986013986013986 |
| `privacy_leak_count` | 0 |

The four actual-updater parity scenarios cover registered projects with a
shared archive scope and independent source partitions, a source stream, and
custom-pattern, zero-record, and rewrite/max-record execution. This
proves deterministic source-inventory reuse, target dispatch, a single
successful final rebuild, failure suppression, and final archive-output parity
for the synthetic contract. It is not whole-run rollback, not distributed
locking, and not private wall-clock performance. It does not prove memory quality,
ranking, induction quality, LLM answer quality, vector search, ontology
discovery, GitHub availability, or public leaderboard parity. Private bounded
timing and deployment evidence remain separate acceptance gates and must not be
inferred from the synthetic operation-count result.

### Private acceptance result: `no_go`

The bounded private shadow measurement used one immutable source snapshot with
338 candidate files and 2,611,465,503 aggregate source bytes. No source content,
project names, repository paths, or generated archive records were copied into
this repository. A controlled 12-target, zero-new-record A/B isolated repeated
inventory and rebuild work:

| private shadow metric | value |
| --- | ---: |
| V2.38 baseline elapsed seconds | 1923.252 |
| V2.39 candidate elapsed seconds | 165.667 |
| controlled-case speedup | 11.609x |
| V2.39 source inventory seconds | 42.796 |
| V2.39 archive-state seconds | 3.919 |
| V2.39 target discovery seconds | 116.146 |
| selected records in the bounded hotspot profile | 25 |
| selected aggregate source bytes | 1518602464 |

The required 71-target default-update shadow run did not complete before the
hard 1800-second acceptance limit. Therefore V2.39 failed the full private
wall-clock gate even though the isolated repeated-work case improved. The
timed-out report did not retain reviewable private byte-parity evidence, so
private output parity was not accepted; the public synthetic parity result must
not be substituted for it.

One bounded diagnostic pass showed that inventory construction, archive-state
reads, and target discovery accounted for approximately 163 seconds, while the
selected records represented approximately 1.52 GB. This supports the inference
that record materialization remained the dominant unclosed path, but it does not
identify or prove a safe materialization optimization. Changing record writing,
summarization, source parsing, or source-anchor behavior is outside this goal's
single-inventory and single-finalization scope, so no further correction was
attempted.

The candidate was not installed or deployed. V2.38 remains deployed, and V2.39
is retained only as a source-level implementation and reproducible public gate.
A future goal may address large-record materialization only with a separately
bounded contract, output-parity evidence, and its own private acceptance limit.

## V2.40 Scheduled Selected-Record Materialization Throughput Closure

Date: 2026-07-13

V2.40 addresses the selected-record materialization work isolated by V2.39.
The internal inventory contract now carries normalized `source_updated_at`
metadata. Scheduled children apply schema, containment, high-water, source-hash
freshness, and `--max-records` selection before opening selected source content.
Each selected JSONL record is then read once, hashed from those bytes, redacted
once, and decoded at most twice per valid line for original-anchor and redacted
event semantics.

Selected records become compact `PreparedArchiveRecord` values containing only
derived archive artifacts and redaction counts. They retain no raw source payload.
Every selected record must validate and prepare before the first existing entry
is removed or new archive file is written. Non-JSON inputs retain the established
fallback, and direct updater calls retain their prior discovery behavior.

The deterministic public command is:

```bash
python3 benchmarks/selected_record_materialization_gate.py
```

| metric | value |
| --- | ---: |
| `selected_record_source_read_amplification` | 1.0 |
| `selected_record_redaction_amplification` | 1.0 |
| `selected_record_json_decode_amplification` | 2.0 |
| `selected_record_preparation_before_mutation_rate` | 1.0 |
| `selected_record_raw_payload_retention_count` | 0 |
| `selected_record_output_parity_rate` | 1.0 |
| `selected_record_source_anchor_parity_rate` | 1.0 |
| `selected_record_secret_policy_parity_rate` | 1.0 |
| `selected_record_mutation_rejection_rate` | 1.0 |
| `direct_cli_regression_pass_rate` | 1.0 |
| `v239_throughput_regression_pass_rate` | 1.0 |
| `v238_single_writer_regression_pass_rate` | 1.0 |
| `synthetic_materialization_work_reduction_rate` | 0.6666666666666667 |
| `privacy_leak_count` | 0 |

Against the fixed V2.39 source, full-content read amplification changed from
4.0 to 1.0, redaction amplification from 2.0 to 1.0, and source JSON decode
amplification from 6.0 to 2.0. The synthetic gate also requires byte-for-byte
archive output, source-anchor, secret-policy, mutation, direct-CLI, V2.39
throughput, and V2.38 single-writer parity.

### Private acceptance result: `no_go`

The bounded acceptance used one immutable CoW source snapshot. It discovered
310 source inventory records, 72 enabled targets, and 27 selected candidates.
The deterministic subset contained two unique selected records totaling
343,800,494 bytes. Only aggregate counts and timings were retained; no project
names, repository paths, source content, or archive content entered this
repository.

| private acceptance metric | value |
| --- | ---: |
| V2.39 subset elapsed seconds | 147.893 |
| V2.40 subset elapsed seconds | 126.182 |
| `private_selected_materialization_speedup` | 1.172062 |
| `v239_v240_subset_output_parity_rate` | 1.0 |
| `private_shadow_run_count` | 0 |
| `privacy_leak_count` | 0 |

The selected-subset speedup was below the required 2.0 threshold. Per the
convergence rule, V2.38 parity and the 72-target candidate shadow were not run,
and no further micro-optimization was attempted. The candidate was not
installed or deployed. V2.38 remains deployed.

The public operation-count result and synthetic output parity are not deployment approval.
V2.40 does not prove memory quality, ranking, induction
quality, LLM quality, vector search, scheduler reliability, GitHub availability,
ontology discovery, or public leaderboard parity.

## V2.41 Scheduled Durable-Event Projection Attribution And Closure

Date: 2026-07-13

V2.41 tests whether early projection of durable events can close the residual
selected-record preparation time left by V2.40. The public attribution command
is:

```bash
python3 benchmarks/durable_event_projection_gate.py
```

The synthetic gate uses mixed JSONL records with durable user/final messages
and large status, commentary, function-call, and function-output payloads. Its
profiling harness produces the same prepared artifacts as the normal V2.40
path. A counterfactual run using only the existing `user`, `assistant`, and
`record` events preserves artifact content, event order, and source hashes.

| deterministic metric | value |
| --- | ---: |
| `phase_attribution_coverage_rate` | 1.0 |
| `implementation_decision_accuracy` | 1.0 |
| `profile_harness_output_parity_rate` | 1.0 |
| `nondurable_output_dependency_rate` | 0.0 |
| `durable_event_projection_parity_rate` | 1.0 |
| `durable_event_order_parity_rate` | 1.0 |
| `durable_event_hash_parity_rate` | 1.0 |
| `privacy_leak_count` | 0 |

These metrics prove bounded phase attribution and that non-durable events do
not contribute to the synthetic durable archive output. They are not projection implementation,
private hotspot evidence, deployment approval, or memory-quality evidence.

### Private attribution result: `profile_no_go`

The single permitted private attribution used one immutable CoW snapshot. It
found 311 inventory records, 72 enabled targets, and 28 selected candidates.
The deterministic subset contained two unique records totaling 347,065,206
bytes. Only aggregate phase timings and counts were retained.

| private attribution metric | value |
| --- | ---: |
| total selected-record preparation seconds | 126.012448 |
| avoidable non-durable processing seconds | 36.752164 |
| `avoidable_nondurable_processing_share` | 0.291655026 |
| `projected_max_speedup` | 1.411741506 |
| `phase_attribution_coverage_rate` | 1.0 |
| `nondurable_output_dependency_rate` | 0.0 |
| `summary_source_anchor` seconds | 58.319916 |
| `redaction` seconds | 16.845393 |
| `nondurable_event_normalization` seconds | 30.489503 |
| `private_shadow_run_count` | 0 |
| `privacy_leak_count` | 0 |

The measured avoidable share did not reach the required 0.55 threshold, and
the Amdahl upper bound did not reach 2.2x. The conditional projection was
therefore not implemented. Per the convergence rule, the larger
`summary_source_anchor` phase was recorded but not pursued as a second
optimization strategy, and no 72-target shadow was run.

The implementation decision combines the private aggregate timing share with
the public counterfactual `nondurable_output_dependency_rate=0.0`; it does not
claim private artifact-parity evidence.

All private temporary snapshots and reports were removed after recording the
aggregate result. The candidate was not installed or deployed, the automation
configuration was restored unchanged, and V2.38 remains deployed.

## V2.42 Scheduled Durable Semantic Index Final Performance Closure

Date: 2026-07-13

V2.42 tests the final permitted architecture for closing scheduled
selected-record preparation under the current archive semantics and 2x target.
The proposed architecture would build one durable semantic index per selected
record, combining early non-durable event rejection with removal of repeated
summary and source-lookup work. The public attribution command is:

```bash
python3 benchmarks/durable_semantic_index_gate.py
```

The synthetic gate uses stack-based exclusive timing, so nested helper time is
assigned only to the innermost phase. It observes repeated work in the current
path and compares normal preparation with a test-only durable-event projection
and semantic-cache counterfactual. It does not add a runtime semantic index.

| deterministic public metric | value |
| --- | ---: |
| `exclusive_phase_attribution_coverage_rate` | 1.0 |
| `exclusive_phase_overlap_seconds` | 0.0 |
| `baseline_raw_event_traversal_count` | 13 |
| `baseline_source_event_lookup_full_scan_count` | 4 |
| `baseline_source_event_for_text_scan_count` | 2 |
| `baseline_source_text_normalization_count` | 24 |
| `baseline_repeated_semantic_normalization_count` | 63 |
| `baseline_nondurable_text_materialization_count` | 6 |
| `counterfactual_archive_output_parity_rate` | 1.0 |
| `counterfactual_summary_field_parity_rate` | 1.0 |
| `counterfactual_source_anchor_parity_rate` | 1.0 |
| `counterfactual_event_order_parity_rate` | 1.0 |
| `counterfactual_event_hash_parity_rate` | 1.0 |
| `privacy_leak_count` | 0 |

### Private architecture result: `architecture_no_go`

One immutable CoW source/archive snapshot was used after the deployed runtime
passed 19/19 tool parity, the private archive was clean and current, the update
lock was available, and the existing automation was paused without changing
its prompt. The deterministic two-record subset remained inside the required
256-512 MiB window. Only aggregate counts and timings were retained.

| private attribution metric | value |
| --- | ---: |
| inventory records | 313 |
| enabled targets | 72 |
| selected candidates | 19 |
| subset records | 2 |
| subset aggregate bytes | 351763185 |
| total preparation seconds | 131.576364 |
| fused avoidable processing seconds | 75.622322 |
| `fused_avoidable_processing_share` | 0.574740927 |
| `fused_projected_max_speedup` | 2.351507735 |
| `exclusive_phase_attribution_coverage_rate` | 1.0 |
| `exclusive_phase_overlap_seconds` | 0.0 |
| repeated semantic normalization seconds | 32.855674 |
| non-durable event normalization seconds | 31.667363 |
| non-durable event materialization seconds | 6.191203 |
| source lookup seconds | 2.794896 |
| repeated event scan seconds | 2.113185 |
| `private_candidate_run_count` | 0 |
| `private_full_shadow_run_count` | 0 |
| `privacy_leak_count` | 0 |

The removable share missed the required 0.60 threshold and its Amdahl upper
bound missed the required 2.5x threshold. The runtime `DurableSemanticIndex`
candidate was therefore not implemented. No warm-up, alternating A/B subset
timings, 72-target shadow, installation, deployment, or publication occurred.
The numerator already treats all measured repeated normalization, repeated
scan, source-lookup, and non-durable phases as fully removable, so the reported
share and speedup are optimistic upper bounds rather than guaranteed gains.
Per the convergence rule, this closes scheduled selected-record performance
work under the current semantics and 2x target until the target, constraints,
or evidence changes; no second hotspot or alternative optimization was pursued.

The private snapshot and harness were deleted, the private archive remained
clean and current, and the automation was restored to its original active
configuration and prompt hash. V2.38 remains deployed.

V2.42 proves exclusive public attribution, counterfactual output parity, and a
bounded private architecture decision. It does not prove runtime semantic-index
behavior, private candidate speedup, memory quality, ranking, induction quality,
LLM quality, vector search, ontology discovery, GitHub availability, deployment
approval, or public benchmark parity.

## V2.43 Mainline Release Truth And Candidate-Chain Convergence

Date: 2026-07-13

V2.43 converges the six linear V2.37-V2.42 source commits without rewriting
their verified history. At the dated V2.43 preflight, source main was V2.36
commit `9ae179f`, and the verified implementation input ended at V2.42 commit
`51bdfbe`. The integration pull request records that immutable comparison; it
does not assert the remote state after the pull-request lifecycle. Merging the
pull request advances the reusable source and packaged template, but it does
not install or deploy that source on its own.

The release decision keeps public functional evidence separate from private
deployment performance. In particular, a private performance `no_go` is not a functional failure.
V2.39 and V2.40 remain eligible for source integration because their public
functional, privacy, packaged-runtime, output-parity, and regression gates pass;
their failed private timing thresholds still prohibit treating them as installed
or deployed performance improvements.

| version | change class | public result | installed/private result | release implication |
| --- | --- | --- | --- | --- |
| V2.37 | evaluation-only query-support calibration | safe no-change; no runtime policy selected | not installed or deployed | retain the bounded `no_go` evidence without changing query support |
| V2.38 | scheduled runner, updater, recovery, and publication runtime | functional and privacy gates pass | the V2.43 preflight observed installed skills and private deployment matching the runtime bundle from commit `e25c5bc` | deployed baseline observed by this preflight and source integration input |
| V2.39 | single-inventory and single-finalization runtime | public output parity and regressions pass | private full run exceeded 1800 seconds; output parity was not accepted | integrate as source runtime, without deployment approval |
| V2.40 | selected-record preparation runtime | public artifact, anchor, secret-policy, and regression parity pass | private subset speedup 1.172062; no full shadow | integrate as source runtime, without deployment approval |
| V2.41 | attribution benchmark only | deterministic gate passes | private `profile_no_go`; no projection runtime | retain evidence only |
| V2.42 | final architecture benchmark only | deterministic gate passes | private `architecture_no_go`; no candidate run | retain the final closure and no runtime `DurableSemanticIndex` implementation |

The three release layers were checked independently with aggregate-only evidence:

| layer comparison | observed status | claim boundary |
| --- | --- | --- |
| source candidate to private deployment | the 2026-07-13 preflight reported `17/19` matching tools, with two stale target tools; source bundle `559cd20bf9d458ded5fd17749a0c231cf999700d3bd330dca2071083a2d1cacd` | expected drift from the V2.39/V2.40 source-only runtime; not a deployment defect |
| installed skills to private deployment | the 2026-07-13 preflight reported `19/19` matching tools and equal bundle fingerprint `ea3946e3bdb824b7966a62240d0d24dd637e0accdd16d7b7924cbc31d17ae08c` | both matched the V2.38 runtime at preflight time; not latest-source parity |
| private deployment operation | the 2026-07-13 receipt was clean and current; the 04:05-07:13 scheduled run completed 72/72 enabled targets and reported `published` | dated V2.38 operational evidence only; not approval of V2.39/V2.40 performance |

The packaged runtime contains no `DurableSemanticIndex` symbol, and
selected-record performance work remains closed under the current archive
semantics and 2x target. Reopening it requires a changed target, changed
constraints, or materially different evidence rather than another hotspot or
micro-optimization. The V2.43 convergence commit itself changes only
documentation and its focused contract test. It does not install or deploy
skills, alter the private archive, change the automation prompt, rerun a private
72-target timing shadow, or claim that a source pull request has already been
merged.

## V2.44 Public Induction First-Loss Attribution And Bounded Repair

Date: 2026-07-13

V2.44 adds `benchmarks/public_induction_first_loss_gate.py` to attribute every
selected positive LongMemEval case to exactly one earliest deterministic loss.
The updater, consolidator, archive, and search path receive only normal
role/content source records and metadata. Questions, answers, `has_answer`
positions, answer-session labels, and expected support events remain
scorer-only. Scorer event positions are resolved to generated evidence anchors
after ingestion; they are never written into source records or used as direct
memory input. Free-form search output is not an answerability source.

The ordered, mutually exclusive taxonomy is:

| category | first failed contract |
| --- | --- |
| `source_rejected` | the normal source refusal boundary rejected the record |
| `update_failed` | packaged setup or updater execution did not complete |
| `archive_audit_failed` | the generated archive failed its normal audit |
| `session_support_omitted` | no expected scorer support event survived as an evidence anchor |
| `memory_induction_omitted_or_overcompressed` | preserved support had no active automatic memory |
| `memory_present_not_top5` | active support memory did not enter the context top five |
| `top1_not_query_supported` | a top-five support candidate did not produce supported query evidence |
| `supported` | active support survived into a supported context package |

Every taxonomy category emits an aggregate count and rate, including
`memory_present_not_top5_rate` and `top1_not_query_supported_rate`.

The offline public-data-free contract is canonical:

```bash
python3 benchmarks/public_induction_first_loss_gate.py --offline-fixture
```

The external runs used the same official LongMemEval cleaned S artifact as
V2.36 and V2.37. The downloaded input and every generated archive/report stayed
outside this repository.

| frozen input | SHA-256 or selection fingerprint |
| --- | --- |
| dataset | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| calibration selection | `c8ac66423f41b968ca60c9af18ae3f2c949f534a8f875d8997ec83cd8fbb5e19` |
| frozen holdout selection | `4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7` |
| cohort overlap | 0 |

The baseline calibration command was:

```bash
python3 benchmarks/public_induction_first_loss_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort calibration \
  --work-dir /tmp/my-precious-v244-calibration \
  --report-file /tmp/my-precious-v244-calibration-report.json
```

Calibration found one eligible induction defect. `session_support_omitted`
accounted for 15 cases, all 15 pre-retrieval induction losses, exceeding both
the minimum five cases and 0.40 share. Only one candidate was permitted:
`durable_first_person_projection_v1`, a general first-person declaration
projection with evidence-slot priority. It contained no answer-label input,
question phrase list, ranking change, top-k change, query-support relaxation,
lifecycle change, or secret-policy change.

| calibration metric | baseline | frozen candidate |
| --- | ---: | ---: |
| `positive_first_loss_attribution_coverage_rate` | 1.0 | 1.0 |
| `session_support_event_preservation_rate` | 19/56 (0.3392857143) | 19/56 (0.3392857143) |
| `source_rejected` | 2 | 2 |
| `update_failed` | 0 | 0 |
| `archive_audit_failed` | 6 | 5 |
| `session_support_omitted` | 15 | 15 |
| `memory_induction_omitted_or_overcompressed` | 0 | 0 |
| `memory_present_not_top5` | 6 | 5 |
| `top1_not_query_supported` | 1 | 3 |
| `supported` | 0 | 0 |
| `pre_retrieval_induction_loss_count` | 15 | 15 |
| updater success | 38/40 | 38/40 |
| archive audit success | 32/40 | 33/40 |
| `abstention_accuracy` | 1.0 | 1.0 |
| `false_promotion_count` | 0 | 0 |
| `privacy_leak_count` | 0 | 0 |

The candidate was frozen despite zero calibration gain so that the single
allowed strategy could receive one final, non-tunable holdout decision. The
baseline holdout used the baseline runtime bundle; the candidate run consumed
only its aggregate baseline report and the frozen strategy slug:

```bash
python3 benchmarks/public_induction_first_loss_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort holdout \
  --calibration-report /tmp/my-precious-v244-calibration-report.json \
  --work-dir /tmp/my-precious-v244-holdout-baseline \
  --report-file /tmp/my-precious-v244-holdout-baseline-report.json

python3 benchmarks/public_induction_first_loss_gate.py \
  --public-input /tmp/longmemeval_s_cleaned.json \
  --dataset-source-url https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json \
  --cohort holdout \
  --calibration-report /tmp/my-precious-v244-calibration-report.json \
  --baseline-report /tmp/my-precious-v244-holdout-baseline-report.json \
  --candidate-strategy durable_first_person_projection_v1 \
  --runtime-root /tmp/my-precious-v244-candidate-runtime \
  --work-dir /tmp/my-precious-v244-holdout-candidate \
  --report-file /tmp/my-precious-v244-holdout-candidate-report.json
```

The baseline reproduced the V2.36/V2.37 split through
`baseline_retrievable_positive_count = 13` and
`previously_unexplained_positive_count = 17`. The latter partition has its own
`previously_unexplained_first_loss_attribution_coverage_rate = 1.0` and
`previously_unexplained_first_loss_partition_invariant_violation_count = 0`.
The previously unexplained 17 positives are now accounted for as follows:

| first loss among the previous 17 | count | rate |
| --- | ---: | ---: |
| `source_rejected` | 0 | 0.0 |
| `update_failed` | 0 | 0.0 |
| `archive_audit_failed` | 3 | 0.1764705882 |
| `session_support_omitted` | 10 | 0.5882352941 |
| `memory_induction_omitted_or_overcompressed` | 0 | 0.0 |
| `memory_present_not_top5` | 4 | 0.2352941176 |
| `top1_not_query_supported` | 0 | 0.0 |
| `supported` | 0 | 0.0 |

The full 30-positive baseline first-loss partition was 0 source rejection, 0
update failure, 4 audit failures, 15 session-support omissions, 0 memory-node
omissions, 9 top-five retrieval losses, 2 query-support losses, and 0 supported
cases. Its support-event preservation was 19/46 (0.4130434783).

The frozen candidate did not change either owning induction metric:

| final comparison | result | required |
| --- | ---: | ---: |
| baseline targeted loss | 15 | - |
| candidate targeted loss | 15 | - |
| `recovered_holdout_positive_count` | 0 | at least 2 |
| `targeted_holdout_loss_reduction_rate` | 0.0 | at least 0.25 |
| `recovered_pre_retrieval_positive_count` | 0 | at least 2 |
| `pre_retrieval_induction_loss_reduction_rate` | 0.0 | at least 0.25 |
| candidate updater success | 40/40 | no regression |
| candidate archive audit success | 34/40 | no regression |
| `abstention_accuracy` | 10/10 (1.0) | 1.0 |
| `hard_negative_rejection_rate` | 1.0 | 1.0 |
| `false_promotion_count` | 0 | 0 |
| `gold_label_ingestion_count` | 0 | 0 |
| `direct_memory_injection_count` | 0 | 0 |
| `privacy_leak_count` | 0 | 0 |

The required V2.37 synthetic boundary rerun also kept the strict policy's three
hard-negative rejections at 3/3. Candidate `safety_passed` was 1, but
`gain_passed` was 0. The candidate merely moved two later losses from
`memory_present_not_top5` to `top1_not_query_supported`; it did not recover an
induction loss or a supported case.

| aggregate artifact | SHA-256 |
| --- | --- |
| baseline calibration report | `8950a2bdd0d1a469173039a0634ce9e8fec6e86cf7a8440defd184f4c777c45d` |
| candidate calibration report | `3b9b806803719061e99d19997cdad886b9cf7b386c6b2b0a4d83906bd561ce4d` |
| baseline holdout report | `849c775ee07bb73476243c0352ea8b4adb288783a162270ff5a4ae2235664adc` |
| candidate holdout report | `92d82da6e5ab005deb945b8ab14324fc5657befd3ae8021d5b232650a51abb23` |
| baseline runtime bundle | `d6c2b27f44432590a96bc21ec76dd11ee2906e68bbc2eebf30b4cfa2517dd1c0` |
| candidate runtime bundle | `4f8fb5aaa33bdba6d9865615d8708c54a72255c123fab94c8ff56a6320260d7b` |
| baseline configuration | `882bbd00305319992d591139e70576a1dec2a1e36f9a7bd16bb9bccd001a505b` |
| candidate configuration | `fdec2cd60b2e25474e12dde1ca2b8542c6f7dbcb20cdbc24fa33f8154de7fd48` |
| candidate strategy | `654054d60b0e6b3bf11c0ece8759c39176cd7f8af9985758c1871b08039c0f5a` |

Terminal public decision: `induction_no_go`, reason
`insufficient_holdout_gain`. The failed candidate production change and its
candidate-only tests were removed. No second hypothesis was attempted. Because
there was no public go, the conditional private aggregate shadow was skipped.
V2.44 does not install or deploy skills, modify the private archive, alter the
scheduler, or promote the V2.39/V2.40 runtime.

V2.44 proves deterministic source-to-session-to-memory first-loss attribution,
scorer isolation, a complete explanation of the previous 17/30 holdout gap,
and a bounded safe no-go for the only candidate. It is not LLM answer quality.
It is not ranking quality. It is not vector search. It is not ontology discovery.
It is not public leaderboard parity. It does not prove that a different future
induction design will fail.

## V2.45 Session Support Preservation Attribution And One-Shot Repair

Date: 2026-07-13

V2.45 adds `benchmarks/session_support_preservation_gate.py`. It keeps the
V2.44 source-to-session-to-memory stages intact, then uses a benchmark-owned
scorer sidecar to explain each expected support event. The packaged updater
receives only ordinary role/content events and normal metadata. Questions,
answers, `has_answer`, answer-session identifiers, and expected support
positions remain scorer-only and are applied after ingestion. Reports contain
only aggregate counts and synthetic fixture results.

The ordered event taxonomy is mutually exclusive:

| category | first failed event contract |
| --- | --- |
| `source_event_missing_after_extraction` | the expected source event is absent after normal extraction |
| `durability_filter_rejected` | the event exists but has no durable candidate |
| `no_summary_channel_candidate` | a durable candidate enters no summary channel |
| `evidence_budget_evicted` | a summary candidate does not survive the fixed six-item evidence budget |
| `evidence_bound_to_wrong_ordinal` | evidence text is bound to a different source event position |
| `evidence_source_entry_missing` | selected evidence has no source entry |
| `source_anchor_materialization_failed` | the source entry does not materialize as a matching anchor |
| `preserved` | evidence and its source anchor match the expected event locator |

The public-data-free gate is part of the canonical quality runner:

```bash
python3 benchmarks/session_support_preservation_gate.py --offline-fixture
```

Its fixture executes real packaged positive, duplicate-text wrong-ordinal, and
abstention cases, plus synthetic cases for the remaining taxonomy branches. It
requires `support_event_attribution_coverage_rate == 1.0`,
`support_event_partition_invariant_violation_count == 0`, hard-negative
rejection and abstention accuracy of 1.0, and zero label ingestion, direct
memory injection, or privacy leakage.

The external calibration used the pinned LongMemEval cleaned S artifact. All
input, generated archives, and aggregate reports remained outside this
repository.

| frozen input | SHA-256 or selection fingerprint |
| --- | --- |
| dataset | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| calibration selection | `c8ac66423f41b968ca60c9af18ae3f2c949f534a8f875d8997ec83cd8fbb5e19` |
| frozen holdout selection | `4d94450bf30e279ad120b16dfd0fed38dbe18f98e73403f73db254311fdab7a7` |
| cohort overlap | 0 |

V2.44 was reproduced before V2.45 attribution began: calibration retained its
15 `session_support_omitted` cases and 19/56 compatibility preservation count;
the full V2.44 holdout retained 15 omissions and 19/46. Its runtime bundle was
`d6c2b27f44432590a96bc21ec76dd11ee2906e68bbc2eebf30b4cfa2517dd1c0`.

V2.45 also records a scorer correction rather than silently rewriting that
history. The generated public source format stores one turn per JSONL line, so
a LongMemEval turn position maps to `(line_number = turn_ordinal,
event_ordinal = 1)`. V2.44 compared the turn position only with
`event_ordinal`, which produced false matches. V2.45 preserves the V2.44 count
as a compatibility metric while using the complete locator for event
attribution. On calibration this yielded
`v244_locator_support_status_disagreement_count = 14`, 4/56 canonically
preserved support events, and 19 canonical `session_support_omitted` cases. The
difference is a scorer correction, not a production runtime regression.

The complete-locator calibration event partition was:

| event category | count |
| --- | ---: |
| `source_event_missing_after_extraction` | 0 |
| `durability_filter_rejected` | 0 |
| `no_summary_channel_candidate` | 25 |
| `evidence_budget_evicted` | 25 |
| `evidence_bound_to_wrong_ordinal` | 2 |
| `evidence_source_entry_missing` | 0 |
| `source_anchor_materialization_failed` | 0 |
| `preserved` | 4 |

Among the 19 omitted cases, `no_summary_channel_candidate` occurred in 14
cases, or 0.7368421053. `evidence_budget_evicted` occurred in 9 and
`evidence_bound_to_wrong_ordinal` in 2; case incidence can overlap because a
case may contain multiple expected support events. The fixed ordering selected
the dominant allowed surface without inspecting holdout.

Exactly one label-free candidate was tested:
`latest_noninitial_user_declaration_v1`. It selected at most the latest
noninitial user event that passed normal durability/noise checks, was no longer
than 240 characters, contained no question mark, and could bind back to its
own event. It added one summary candidate with priority inside the existing
six-item evidence budget. It did not add answer labels, question phrase lists,
ranking changes, top-k changes, query-support relaxation, or a second repair
rule. A focused synthetic test was RED before the change and GREEN afterward.

The one-shot calibration comparison was:

| metric | V2.45 baseline | candidate |
| --- | ---: | ---: |
| `support_event_attribution_coverage_rate` | 1.0 | 1.0 |
| `support_event_partition_invariant_violation_count` | 0 | 0 |
| preserved support events | 4/56 | 10/56 |
| `source_rejected` | 2 | 2 |
| `update_failed` | 0 | 0 |
| `archive_audit_failed` | 6 | 28 |
| `session_support_omitted` | 19 | 0 |
| `memory_induction_omitted_or_overcompressed` | 0 | 0 |
| `memory_present_not_top5` | 0 | 0 |
| `top1_not_query_supported` | 3 | 0 |
| `supported` | 0 | 0 |
| `hard_negative_rejection_rate` | 1.0 | 1.0 |
| `abstention_accuracy` | 1.0 | 1.0 |
| `gold_label_ingestion_count` | 0 | 0 |
| `answer_ingestion_count` | 0 | 0 |
| `direct_memory_injection_count` | 0 | 0 |
| `privacy_leak_count` | 0 | 0 |

The comparison calculated nominal recovery of 19 session omissions, 19
pre-retrieval losses, and 6 support events, so `gain_passed` was 1. Those are
not accepted recoveries: 22 additional positives moved to the earlier
`archive_audit_failed` stage. Consequently `safety_passed` was 0 and the
candidate was not frozen. The candidate production change and candidate-only tests were removed.
The baseline updater remains the shipped implementation.
The candidate holdout was not run, and no second candidate was attempted. A
baseline-only holdout command was mistakenly started before calibration freeze,
then interrupted before completion; its output was not inspected, its temporary
artifacts were deleted, and it produced no report or decision.

After the no-go, scorer-only harness hardening made the configuration
fingerprint cover every dominance, gain, allowed-surface, stage-shift, and
safety rule; it also made zero-omission reports use a null target and made
V2.44 contract mismatch return `baseline_not_reproducible`. These changes did
not change the taxonomy, thresholds, candidate metrics, or terminal decision.
The table distinguishes historical evaluated-report fingerprints from the
final hardened policy fingerprints.

| aggregate artifact or frozen component | SHA-256 |
| --- | --- |
| V2.44 reproduced calibration report | `7b50ef70c6fda03f53b17ade1efd8616ade291e80a95a2868c62f4eb89ba57f7` |
| V2.44 reproduced holdout report | `849c775ee07bb73476243c0352ea8b4adb288783a162270ff5a4ae2235664adc` |
| V2.45 baseline calibration report | `ddc3b0e591c271a2e105b8a386aacabc8b969818b25290f123a36ea3f625bcf1` |
| V2.45 candidate calibration report | `5ca991f3b7ca070ab88c4ce19045a87f45a315215b88432e2efe466077f678f9` |
| evaluated V2.45 baseline configuration | `3dd6307117d7ac0e555e24fb8a231e962051237cabf11db151795595d28e6789` |
| evaluated candidate configuration | `816b2d7a55bba0fc293607c79b118576b65d8815cdfcea22992936a5807e1117` |
| evaluated candidate runtime bundle | `82c1a8f19c514cf981953d0ddbfc7eba153c7ae069299e625cbc1e71284211f6` |
| candidate strategy | `746ad2c7eaea3426d1a0b3649fb41483d31a2bd5c9c2eb4326e7e8eabb7332ed` |
| final hardened baseline policy | `a3fddc8dc79692a0ecb0421741e8d9c8c763420567ab5fb8034c94b485b2e470` |
| final hardened candidate decision policy | `21cbccd2389390333ea33306e2730de4ffd9fffe054be507649e0dd204b8d96f` |

Terminal public decision: `session_support_no_go: safety_regression`.

V2.45 proves deterministic event-level session-support attribution, complete
locator handling, scorer isolation, and a bounded one-candidate calibration
no-go. It is not LLM answer quality, not ranking quality, not vector search,
not ontology discovery, and not public leaderboard parity. It does not prove private deployment readiness
and does not prove scheduler reliability. It does not install or deploy skills,
alter a private archive, or change an automation prompt.

## V2.48 Reboot-Safe Scheduled Update Transactional Replay Closure

Date: 2026-07-16

V2.48 adds the skill-side
`skills/update-my-precious/scripts/run_scheduled_memory_transaction.py`
adapter and `benchmarks/scheduled_reboot_replay_gate.py`. Scheduled generation
runs in an adapter-owned persistent staging clone rather than the canonical
archive checkout. Aggregate phase state and staging live in an explicit
mode-`0700` state directory outside both the archive and source trees. The
exclusive lock is keyed by the canonical repository's Git common directory, so
changing `--state-dir` cannot create a second writer. Before resetting staging,
the adapter also probes the deployed V2.38 updater lock, which remains held by a
surviving nested updater child even if the adapter and runner disappear. The
staging clone invokes the deployment repository's existing runtime tools; the
canonical checkout changes only after a matching remote publication receipt.

The public gate uses sixteen synthetic cases and synthetic source records.
It performs real `SIGKILL` interruption during update, after the staging commit
but before push, and after push but before canonical fast-forward. The next
invocation must either regenerate unpublished work from current `origin/main`
or reconcile the already-pushed commit without publishing a duplicate. It also
checks clean publish, no-op, repository-scoped concurrent writers using both
the same and different state directories, a linked worktree sharing the same
Git common directory, a surviving nested updater child, dirty canonical,
malformed state, symlinked staging, remote-race behavior, and an unreceipted
remote advance. Remote inspection uses a non-mutating receipt query, so a
rejected unreceipted advance leaves both canonical `HEAD` and `origin/main`
unchanged. The sixteenth case combines an interrupted `updating` transaction
without a candidate, dirty adapter-owned tracked and untracked staging paths,
and a separately receipted remote advance that overlaps both path classes. Once
ownership, remote identity, writer exclusion, and fetch all pass, staging is
hard-reset and cleaned before `main` checkout. Replay then returns
`no_op_current` from the latest receipt with no duplicate publication. The
canonical-fast-forward case waits until the real two-stage protocol has applied
the candidate checkout while retaining the base ref, then sends `SIGKILL`;
replay accepts only worktree and index entries whose blob and mode exactly match
the base or verified candidate. Same-path user edits fail closed and remain
untouched. Two consecutive gate runs produced identical metrics:

| Metric | Result |
| --- | ---: |
| `transaction_case_count` | 16 |
| `clean_publish_accuracy` | 1.0 |
| `no_op_decision_accuracy` | 1.0 |
| `reboot_replay_success_rate` | 1.0 |
| `canonical_clean_after_interruption_rate` | 1.0 |
| `stale_staging_recovery_rate` | 1.0 |
| `post_push_receipt_reconciliation_rate` | 1.0 |
| `concurrent_transaction_rejection_rate` | 1.0 |
| `dirty_canonical_rejection_rate` | 1.0 |
| `malformed_state_rejection_rate` | 1.0 |
| `unsafe_state_path_rejection_rate` | 1.0 |
| `remote_race_rejection_rate` | 1.0 |
| `repository_scoped_lock_rejection_rate` | 1.0 |
| `git_common_dir_lock_rejection_rate` | 1.0 |
| `nested_writer_lock_rejection_rate` | 1.0 |
| `canonical_fast_forward_recovery_rate` | 1.0 |
| `unreceipted_remote_rejection_rate` | 1.0 |
| `receipted_remote_advance_replay_rate` | 1.0 |
| `receipted_remote_tracked_overlap_count` | 1 |
| `receipted_remote_untracked_overlap_count` | 1 |
| `partial_remote_publish_count` | 0 |
| `duplicate_publish_commit_count` | 0 |
| `canonical_unverified_mutation_count` | 0 |
| `deployed_v238_tool_mutation_count` | 0 |
| `raw_source_copy_count` | 0 |
| `privacy_leak_count` | 0 |

`benchmarks/live_automation_prompt_alignment_gate.py` now keeps the legacy
agent-native prompt regression while separately validating the V2.48
parity-preflight plus single-adapter contract. Its synthetic transaction cases
report `transaction_adapter_alignment_pass=true`,
`single_transaction_adapter_invocation_present=true`,
`strict_transaction_report_contract_present=true`,
`duplicate_transaction_adapter_rejection_count=1`,
`same_line_duplicate_transaction_adapter_rejection_count=1`, and
`missing_transaction_report_rejection_count=1`. This prevents a live automation
from passing merely because it retains the superseded prose-driven direct
updater/audit/sync chain.

Initial private operational recovery result: `published`. This run used the
pre-final-review adapter and therefore proves the quarantine and deployment
workflow, not acceptance of the final source candidate. Before the run, the
interrupted generated-only working state was quarantined in one local, unpushed
stash and the canonical checkout was restored to its previously published
commit. The first private attempt then completed with one terminal transaction report:
`remote_publish_count=1`, `canonical_mutation_count=1`,
`repair_attempt_count=1`, `recovery_count=0`, and `privacy_leak_count=0`.
After a fresh remote fetch, canonical and staging worktrees were clean and each
matched `origin/main`; transaction state was cleared. Archive audit,
publish-readiness, search health, and reviewed sync dry-run all passed.

Final-candidate acceptance then proceeded through three bounded, fail-closed
steps. The 5400-second final-candidate attempt timed out while the durable phase
was still `updating`; it had no candidate commit, left canonical and remote at
the same clean receipt, terminated the process group, restored the prior
adapter and automation definition, and created no source commit. A later
10800-second reopening returned after 3.709 seconds with
`staging_reset_failed`: the checkout-first staging sequence encountered 51
dirty tracked paths and 45 untracked paths after a separately verified remote
publication changed 106 paths, including 36 tracked and 35 untracked overlaps.
It produced no candidate, publication, canonical mutation, or privacy leak and
again rolled deployment back. A fail-first synthetic case reproduced that exact
boundary before the implementation was changed.

V2.48R2 changes only the validated adapter-owned staging normalization order:
hard reset and clean now precede `main` checkout after all safety checks and a
successful fetch. The repaired sixteen-case gate reports the three new metrics
above while every prior required rate remains `1.0` and every safety/privacy
count remains zero. Existing unreceipted remote advance, remote race, unsafe
staging, dirty canonical, nested-writer, interruption, and post-push cases retain
their previous fail-closed behavior.

Final-candidate private acceptance result: `published`. Exactly one repaired
candidate invocation completed in 9081.302 seconds and emitted one valid
transaction JSON object with `recovery_action=stale_staging_replayed`,
`recovery_count=1`, `remote_publish_count=1`,
`canonical_mutation_count=1`, `repair_attempt_count=1`, and
`privacy_leak_count=0`. Transaction state was cleared; canonical and staging
worktrees were clean and matched the freshly queried remote receipt. Archive
audit, publish-readiness, search health, reviewed sync dry-run, 19/19 runtime
parity, and the pinned V2.38 runner and scheduler hashes all passed afterward.
V2.48R2 is a repair and acceptance label, not a new memory feature or runtime
tool-bundle version.

Installed-to-deployment runtime parity remained `19/19`, with equal V2.38 bundle
fingerprints and unchanged pinned runner/scheduler hashes. The existing automation remained `status: ACTIVE`
with its name, schedule, model, reasoning effort, local environment, and
workspace preserved. Only its prompt changed: it now runs parity preflight plus
exactly one transaction adapter command. The saved definition passed the live gate with
`live_automation_alignment_pass=true`, one adapter invocation, strict JSON
validation, zero direct publish-chain commands, and zero privacy leaks.

This is local, single-host reboot-safe transactional replay, not exact process continuation.
An interruption during canonical checkout may leave a transient, receipt-backed
tracked-state mismatch; the next invocation validates its exact base/candidate
entries and repairs it instead of being permanently blocked by dirty startup.
It is not cloud scheduler uptime and not power-loss durability of the source disk.
It is not distributed locking and not a GitHub availability SLA.
It is not memory quality, not ranking quality, and not LLM quality.
It is not vector search, not ontology discovery, and not V2.39/V2.40 deployment approval.
The adapter is an isolated skill-side addition; V2.38 remains deployed and its
existing 19-tool runtime bundle is not changed by this public gate.

## V2.49 Real-Use Recall Utility Closure

Date: 2026-07-17

The aggregate-only pre-change real-use probe showed the practical failure that
motivated this slice: exact or short controls were supported in `2/2` cases,
while natural or multi-intent forms were supported in `0/2` cases. The archive
already contained 54 goal-related memory-index rows and four decision rows
containing the convergence term, but the durable goal-writing preference had
not entered automatic induction or review. The frozen fail-first reproduced
both the missing durable Chinese preference and missing broad-query
decomposition signal without rendering query text, memory text, IDs, refs, or
private paths.

The write-path candidate adds high-precision English and Chinese durable-user
preference extraction over the complete event stream. It preserves the user's
original language and source user-event anchor. Temporary/current-task,
tentative, hypothetical, question, quoted-example, process, and assistant
acknowledgement text remains rejected. The read-path candidate adds only
`query.decomposition_recommended` and `query.decomposition_reason`; it does not
weaken package or per-hit support, active/current, lifecycle, scope, drilldown,
or privacy checks. `using-my-precious` now bounds global-preference and
project-history facets to at most two context-package queries each and routes
current HEAD, tests, and reviewed-code state to repository inspection.

`python3 benchmarks/real_use_recall_utility_gate.py` creates clean packaged
archives, invokes the copied updater for three synthetic source records, and
consumes only `memory_recall_context_package` output from the copied search
tool. Two internal runs produce identical aggregate reports:

| Metric | Result |
| --- | ---: |
| `synthetic_case_count` | 12 |
| `durable_chinese_preference_extraction_recall` | 1.0 |
| `durable_english_preference_regression_rate` | 1.0 |
| `long_session_middle_preference_recall` | 1.0 |
| `noise_insertion_stability_rate` | 1.0 |
| `temporary_constraint_rejection_rate` | 1.0 |
| `hypothetical_statement_rejection_rate` | 1.0 |
| `quoted_prompt_rejection_rate` | 1.0 |
| `assistant_acknowledgement_promotion_count` | 0 |
| `global_preference_scope_accuracy` | 1.0 |
| `bounded_facet_plan_accuracy` | 1.0 |
| `natural_goal_preference_supported_recall` | 1.0 |
| `project_history_supported_recall` | 1.0 |
| `live_state_memory_answer_count` | 0 |
| `wrong_project_supported_hit_count` | 0 |
| `broad_query_false_answer_count` | 0 |
| `max_query_variants_per_facet` | 2 |
| `unsupported_claim_count` | 0 |
| `privacy_leak_count` | 0 |

The deterministic decision harness separately rejects malformed packages,
inactive-only support, weak support, missing drill paths, wrong-project scope,
and excess query variants. Free-form output never supplies answerability.

This public result proves only the bounded synthetic real-use slice.
It is not general semantic-memory quality, ranking quality, vector search, private
archive correctness, live repository truth, public leaderboard parity, or LLM
answer quality. More explicitly, it is not ranking quality, not vector search,
not private archive correctness, not public leaderboard parity, and not LLM answer quality.

### Private shadow result: `deployment_no_go`

After the public release gate and production review passed, the three-skill
runtime candidate was frozen at
`dad6e085d1cfe6c56f396659c49d6e33e4b87bf745cd6c7238481498cccf1d32`.
One aggregate-only shadow copied a fixed, complete-event prefix from the real
source stream and the canonical archive into temporary storage. The candidate
setup path produced `19/19` runtime parity in that copy before the copied
updater and package-first search path ran.

| Private shadow metric | Result |
| --- | ---: |
| `private_preference_materialization_count` | 0 |
| `private_preference_source_binding_rate` | 0.0 |
| `private_goal_preference_supported` | 0 |
| `private_project_history_supported` | 1 |
| `private_live_state_memory_answer_count` | 0 |
| `private_wrong_project_supported_hit_count` | 0 |
| `max_query_variants_per_facet` | 2 |
| `unsupported_claim_count` | 0 |
| `canonical_archive_mutation_count` | 0 |
| `privacy_leak_count` | 0 |

The aggregate-only read-side diagnosis found 37 target-bearing user-event
representations, but the frozen extractor qualified zero user preferences.
Exactly one target was rejected by the raw-prompt/local-path boundary, and
that same target qualified when the already existing skill-invocation prefix
normalizer was applied first. This is a source-normalization ordering boundary,
not a last-five selection failure and not a package answerability relaxation
request. No private text, query, path, ID, or raw ref was retained in the
reports.

The one-shot holdout rule forbade retuning the candidate after this result.
Consequently `install_attempt_count=0` and
`private_transaction_invocation_count=0`; the automation remained ACTIVE and
the canonical archive remained clean and current. Installed skills and the
private deployment retained their prior `19/19` runtime parity, while the
frozen candidate matched only `16/19`, proving that it was not installed.
Rollback was unnecessary because no private runtime or archive mutation
occurred. V2.39/V2.40 therefore remain source-integrated but not deployment
approved.

V2.49 proves the public synthetic preference/facet slice and records a real
source-adapter `deployment_no_go`. It does not prove private preference recall,
general semantic-memory quality, ranking quality, vector search, public
leaderboard parity, or LLM answer quality. A future bounded goal may test
prefix normalization before raw-prompt rejection with a new frozen candidate;
that change is not part of V2.49.

## V2.50 Canonical Skill-Invocation Prefix Normalization

Date: 2026-07-18

V2.50 closes the public source-adapter boundary identified by the V2.49
private no-go. Before the change, a durable user preference prefixed by a
canonical skill invocation was rejected because the invocation's local path
reached raw-prompt filtering first. The focused fail-first reproduced that
empty result. The implementation now removes only a canonical leading skill invocation
whose label begins with `$` and whose Markdown target ends in `SKILL.md`, then
runs the existing process, raw-prompt, path, noise, sensitive,
temporary, hypothetical, question, quoted-example, and acknowledgement gates.
Ordinary Markdown links, malformed prefixes, body-local paths, and
invocation-only events remain rejected.

The normalized fact excludes the invocation artifact, while the fact source
continues to bind to the original user-event source anchor. The existing
`benchmarks/real_use_recall_utility_gate.py` now carries the additional cohort;
it creates a clean packaged deployment, executes the copied updater, and uses
only `memory_recall_context_package` output from the copied search tool for
answerability. Free-form search output remains excluded.

Two internal packaged runs produced identical aggregate reports. The
aggregate reports match and all 23 synthetic cases passed:

| Metric | Result |
| --- | ---: |
| `canonical_skill_prefixed_preference_recall` | 1.0 |
| `multi_skill_prefix_recall` | 1.0 |
| `prefixed_preference_source_binding_rate` | 1.0 |
| `invocation_only_rejection_rate` | 1.0 |
| `arbitrary_markdown_path_rejection_rate` | 1.0 |
| `malformed_prefix_rejection_rate` | 1.0 |
| `prefixed_non_durable_rejection_rate` | 1.0 |
| `standalone_preference_regression_rate` | 1.0 |
| `invocation_artifact_leak_count` | 0 |
| `privacy_leak_count` | 0 |

### Private regression result: `deployment_no_go`

The candidate was frozen once after the public gates at bundle SHA-256
`338eb45311bdd2047841d32385cee8ce7593544e64329fe17962b8fbd1e3c2c8`.
The one aggregate-only regression reused the previously diagnosed immutable
source prefix; it was a regression check, not an unknown holdout. Candidate
hash verification passed, setup/runtime parity was 19/19, and the shadow did
not mutate the canonical archive.

The source-adapter change behaved as intended: `private_newly_qualified_target_count`
was 1 and `private_newly_qualified_non_target_count` was 0. The end-to-end
criteria nevertheless failed: target preference materialization was 0, source
binding was 0.0, and goal-preference support was 0. Project-history support
remained 1, live-state memory answers remained 0, and wrong-project supported
hits remained 0.

A read-only pure-function diagnosis of that same consumed regression isolated
the loss after successful normalization and summary selection:

| Diagnostic metric | Result |
| --- | ---: |
| `target_qualified_preference_count` | 1 |
| `summary_target_preference_count` | 1 |
| `summary_evidence_limit` | 6 |
| `evidence_slots_consumed_before_fact_phase` | 6 |
| `target_evidence_count` | 0 |
| `target_source_event_binding_count` | 1 |
| `target_fact_source_quote_count` | 0 |
| `target_memory_candidate_source_count` | 0 |
| `target_memory_candidate_anchor_count` | 0 |
| `target_memory_candidate_count` | 0 |

The evidence budget was exhausted by earlier groups before the facts phase.
Although the selected natural-user preference still resolved to its original
user event, it received no evidence quote; the source-anchor completeness gate
then correctly refused to create a memory candidate. A static counterfactual
confirmed that the retained candidate would have been classified as `global`,
so this run did not expose a second scope-classification failure.

The original wrapper's conservative privacy scan also returned 1 because a
generic preference marker collided with a fixed aggregate schema key. The
follow-up diagnosis classified this as a schema-key collision only: neither
report rendered queries, memory text, source content, source paths, raw refs,
or memory IDs. The wrapper result remains fail-closed and was not reinterpreted
as a pass.

No installation was attempted, no private or canonical update transaction was
invoked, and the automation remained `ACTIVE`. The frozen candidate was not
retuned or rerun. A future bounded goal may address evidence/source-anchor
allocation for selected natural-user facts; that change is outside V2.50.

V2.50 proves only canonical invocation normalization in this bounded source
shape. It is not ranking quality, not vector search, not general semantic
memory, not public leaderboard parity, and not LLM answer quality.

## V2.51 Source-Bound Goal Preference Materialization And Real-Use Recall Closure

Date: 2026-07-20

V2.50 qualified the intended durable Goal-writing preference but ended in
`deployment_no_go` because all six evidence slots were consumed before the
facts phase. V2.51 applies bounded evidence reservation to facts that have
already passed the natural-user durability policy. Up to five selected facts
are reserved first, one final-state slot is retained when applicable, and any
remaining slots use the existing deterministic priority order. The evidence count remains at most 6;
the fix does not raise the limit, weaken candidate
source-anchor completeness, relax query support, or bypass package-first
answerability.

`benchmarks/real_use_recall_utility_gate.py` now includes a saturated synthetic
source record with five decisions, eight retrieval literals, a canonical skill
invocation, one durable Goal preference, and a final state. It executes the
updater and search tool copied into a clean packaged archive and uses only
`memory_recall_context_package` output. Two runs produced identical reports,
all 24 synthetic cases passed, and free-form search was never used.

| Public metric | Result |
| --- | ---: |
| `selected_natural_user_fact_evidence_binding_rate` | 1.0 |
| `selected_natural_user_fact_source_anchor_rate` | 1.0 |
| `selected_natural_user_fact_candidate_materialization_rate` | 1.0 |
| `selected_natural_user_fact_active_memory_rate` | 1.0 |
| `goal_preference_context_package_support_rate` | 1.0 |
| `remaining_evidence_priority_regression_rate` | 1.0 |
| `evidence_budget_overflow_count` | 0 |
| `non_target_memory_promotion_count` | 0 |
| `invocation_artifact_leak_count` | 0 |
| `unsupported_claim_count` | 0 |
| `privacy_leak_count` | 0 |

### Private regression result: `deployment_go`

One frozen candidate was evaluated against a known producer-shape regression;
this was not an unseen holdout. A complete-event prefix ending at the durable
preference turn was copied into temporary storage, processed by the packaged
runtime, and discarded. The report retained only aggregate counts. The
canonical archive was unchanged during this shadow run.

| Private regression metric | Result |
| --- | ---: |
| `target_qualification_count` | 1 |
| `target_summary_selection_count` | 1 |
| `target_evidence_binding_count` | 1 |
| `target_source_anchor_binding_count` | 1 |
| `target_candidate_materialization_count` | 1 |
| `target_active_current_memory_count` | 1 |
| `target_supported_package_answer_count` | 1 |
| `context_package_parse_success_rate` | 1.0 |
| `query_variant_count` | 2 |
| `evidence_budget_overflow_count` | 0 |
| `wrong_project_supported_hit_count` | 0 |
| `live_repository_state_memory_answer_count` | 0 |
| `free_form_search_use_count` | 0 |
| `canonical_archive_mutation_count` | 0 |
| `privacy_leak_count` | 0 |

The same candidate was then installed through the reviewed three-layer path.
Source and installed skill bundles matched, and installed-to-deployment runtime
parity was `19/19` in two consecutive checks. The targeted backfill predeclared
an allow-list record count of 1; dry-run selected 1, apply selected and rewrote
1, and the low-signal skip count was 0. Archive audit, publish readiness, search
health, content-noise review, and reviewed sync dry-run all passed before
publication.

After regeneration, the deployment package-first consumer check reported
`consumer_intent_supported_recall=1.0`, one active/current target memory, valid
summary and evidence drill paths, no supported wrong-project answer, and no
memory answer for live repository state. The matching sync helper created and
pushed the archive commit. The private repository finished clean with
`HEAD == origin/main`; the automation definition and schedule were unchanged.
No private source text, identifier, path, query, hash, memory ID, or raw ref is
stored in this document or in the aggregate reports.

V2.51 proves bounded source-bound materialization and retrieval for this real
Goal-preference failure class. It is not ranking quality, not vector search,
not general semantic memory, not public leaderboard parity, and not LLM answer quality.
It also does not claim automatic ontology discovery or universal
recall for every durable preference shape.

## V2.52 Stable Live-Source Batch Closure

Date: 2026-07-23

V2.52 addresses the scheduled failure class in which a large live rollout can
change or disappear after source inventory but before one target child reads
it. Inventory now runs in a short-lived worker and crosses into the runner only
through a private metadata-only manifest. Record preparation distinguishes
only `changed` and `unavailable` as retryable live-source conditions; both are
removed from the mutation set before source-specific removal, write, or
freshness advancement. Stable siblings continue. Unsafe paths, malformed
contracts, target/timestamp mismatch, privacy rejection, and unknown child
output remain blocked.

Final-review closure adds a scoped `index/deferred_sources.jsonl` retry ledger.
It records only the exact pending source path under its archive scope and
source partition, never source content or a source hash. It therefore cannot
advance freshness or prove currentness, but it does reselect a never-archived
record whose timestamp is older than a stable sibling's newly advanced
high-water. The ledger entry is removed only after successful application.
The scheduled default no longer truncates each target at 50 records, JSONL
parsing rejects any malformed non-empty line, and target reports now enforce
status/reason pairing plus selected/processed/deferred count conservation.

The public synthetic closure command is:

```bash
python3 benchmarks/scheduled_live_source_deferral_gate.py
```

| Synthetic metric | Result |
| --- | ---: |
| `live_source_defer_accuracy` | 1.0 |
| `stable_sibling_publish_accuracy` | 1.0 |
| `deferred_retry_recall` | 1.0 |
| `changed_source_partial_mutation_count` | 0 |
| `changed_source_freshness_advance_count` | 0 |
| `unknown_failure_block_accuracy` | 1.0 |
| `aggregate_failure_reason_coverage` | 1.0 |
| `inventory_worker_isolation_accuracy` | 1.0 |
| `manifest_metadata_only_accuracy` | 1.0 |
| `privacy_leak_count` | 0 |

The synthetic retry cohort now includes a never-archived deferred record at
`08:00`, below its stable sibling at `11:00`. It is recalled on the next stable
run after high-water advances. For previously archived changed/unavailable
records, the partial-mutation check hashes every file in each source-owned
archive entry rather than checking only `meta.json`. Reason coverage directly
requires `source_records_deferred`, retry `updated`, and
`child_failure_unclassified` reports.

The scheduled transaction consumes exactly one `memory_update_batch_report`.
`published` may report `source_batch_complete: false`; `deferred` is a
successful zero-exit result when no publication is needed and pending records
remain; `no_op_current` is valid only for a complete batch; and unknown or
malformed child output becomes `blocked/child_failure_unclassified`. Deferred
record and target counts are aggregate-only and persist in reboot-replay state.
Blocked reports retain an allow-listed `failure_stage` and parsed aggregate
processed/child-failure counts; arbitrary child stdout and stderr remain
suppressed.
If the process is interrupted after persisting a clean no-publication
`complete` state, replay verifies base, candidate, staging, and remote equality
and returns the original `no_op_current` or `deferred` terminal result. This
path does not claim a remote receipt and does not rerun the transaction.

Private immutable A/B evidence is generated outside this repository with:

```bash
python3 benchmarks/private_live_source_inventory_ab_gate.py \
  --private-memory-repo /path/to/private/agent-memory \
  --private-source-dir /path/to/immutable/source-cohort \
  --report-file /tmp/my-precious-v252-private-ab.json
```

The final frozen private rerun used four source records totaling 272,940,639 bytes.
Both the V2.51 baseline and V2.52 candidate completed all 74 enabled targets,
and the candidate retained exact archive-output parity. The two sequential
updates shared one test-only frozen wall clock so the volatile `archived_at`
audit instant could not create false inequality; no archive field or file was
excluded or normalized before the byte-for-byte snapshot comparison:

| Private immutable A/B metric | Result |
| --- | ---: |
| `baseline_enabled_target_count` | 74 |
| `baseline_completed_target_count` | 74 |
| `candidate_enabled_target_count` | 74 |
| `candidate_completed_target_count` | 74 |
| `private_enabled_target_completion_rate` | 1.0 |
| `private_full_completion_rate` | 1.0 |
| `private_output_parity_rate` | 1.0 |
| `private_source_immutability_rate` | 1.0 |
| `baseline_parent_post_inventory_rss_kib` | 750128 |
| `candidate_parent_post_inventory_rss_kib` | 29568 |
| `parent_post_inventory_rss_reduction_rate` | 0.9605827272145554 |
| `privacy_leak_count` | 0 |

The result exceeds the required `0.50` post-inventory parent-RSS reduction
without a full source-directory copy. The aggregate report remains outside the
repository and never stores source content, paths, identifiers, or archive
text.

### Controlled live deployment closure

After the public release gate and private immutable A/B passed, the automation
was paused through the Codex automation API, the reviewed three-layer runtime
was deployed, and installed-to-deployment parity reached `19/19`. The automation
was restored active with the four-status transaction contract and passed the
live prompt-alignment gate. Exactly one controlled transaction then replayed
the adapter-owned stale staging state and returned:

| Controlled transaction metric | Result |
| --- | ---: |
| `status` | `published` |
| `failure_stage` | `none` |
| `source_batch_complete` | `false` |
| `update_inventory_worker_count` | 1 |
| `update_project_processed_count` | 74 |
| `source_record_deferred_count` | 3 |
| `source_target_deferred_count` | 3 |
| `update_child_failure_count` | 0 |
| `recovery_count` | 1 |
| `remote_publish_count` | 1 |
| `canonical_mutation_count` | 1 |
| `repair_attempt_count` | 1 |
| `privacy_leak_count` | 0 |

This is the real incident closure: three changing sources no longer blocked
the 74 stable project targets or the receipted publication. It is deliberately
not an archive-current claim. The three deferred records remain eligible for
the next stable scheduled run; the deterministic public gate proves their
retry closure without violating the one-controlled-invocation limit here.
After publication, canonical and staging worktrees were clean, transaction
state was cleared, canonical `HEAD` matched the remote receipt, runtime parity
remained `19/19`, archive audit and search health passed, publish readiness had
zero blockers, and reviewed sync dry-run reported no remaining publishable
changes.

V2.52 proves bounded scheduled live-source progress, retry closure, output
parity, aggregate diagnostics, and parent-memory isolation. It is not LLM answer quality,
not induction quality, not ranking quality, not vector search,
not ontology discovery, not public leaderboard parity, not distributed
scheduling, and not a whole-run rollback transaction.

## V2.53 Copyable Goal Preference Recall Closure

Date: 2026-07-22

V2.53 closes one real-use induction gap: repeated user corrections about a
Markdown goal's formatting and copyability previously remained separate event
fragments, so no durable preference was materialized for package-first recall.
The new rule is deterministic, session-local, and limited to goal artifacts.
It requires explicit goal context followed by at least two user-event format
corrections, or one explicit instruction with durable language such as a
future or default rule. A later contrary instruction wins as the latest explicit correction.
Malformed, quoted, hypothetical, temporary, assistant-only, and non-goal
complaints fail closed. The existing `natural_user_memory_fact()` behavior for
single explicit preferences remains intact.

The induced summary fact is normalized, but it is not rendered as a verbatim
user quote. Instead, its candidate carries the actual bounded user-event
evidence quote IDs and corresponding source anchors. The resulting memory is
global, active/current, and has summary and evidence drill paths. Controlled
retrieval aliases are attached only to this candidate so the four frozen goal
format intents can reach complete lexical query support without a ranking
rewrite.

The public closure command is:

```bash
python3 benchmarks/copyable_goal_preference_recall_gate.py
```

`benchmarks/copyable_goal_preference_recall_gate.py` initializes two clean
packaged archives and runs the same synthetic source through both. The
controlled baseline executes the copied updater with only the goal-correction inducer disabled;
it still archives the source and classifies the observed
failure as `memory_not_materialized`. The candidate then requests
`memory_recall_context_package` with evidence depth and accepts support only
when the package hit has the exact target memory ID and its own summary drill
path resolves the normalized fact. Free-form search output and unrelated supported hits
are never answerability sources.

The source-binding check independently resolves every cited source-map anchor
back to its JSONL event. Each accepted anchor must pair with the cited evidence
quote, carry a distinct event locator, and resolve to an actual user role;
metadata labels alone cannot establish user provenance. The public baseline
archived two synthetic sessions, materialized zero target memories, and
returned zero target-supported queries. The candidate bound four evidence
quotes to four distinct user events.

| Public metric | Result |
| --- | ---: |
| `correction_sequence_qualification_rate` | 1.0 |
| `correction_induced_fact_materialization_rate` | 1.0 |
| `correction_source_anchor_binding_rate` | 1.0 |
| `goal_format_query_supported_recall` | 1.0 |
| `supported_summary_fact_resolution_rate` | 1.0 |
| `global_scope_accuracy` | 1.0 |
| `current_turn_instruction_precedence_accuracy` | 1.0 |
| `copyable_text_block_decision_accuracy` | 1.0 |
| `nested_fence_collision_avoidance_accuracy` | 1.0 |
| `assistant_evidence_promotion_count` | 0 |
| `non_target_memory_promotion_count` | 0 |
| `free_form_answerability_use_count` | 0 |
| `privacy_leak_count` | 0 |

The runtime recipe uses a supported history preference to place the complete
goal in one `text` fence with no prose outside it. A current-turn format
instruction takes precedence even when history is unsupported, inactive, or
malformed. With no supported history and no current instruction, it does not
invent a preference. When the goal contains an inner backtick fence, the
outer fence is deterministically longer.

An optional frozen private A/B accepts the real source record and the prior
installed updater only through external command arguments:

```bash
python3 benchmarks/copyable_goal_preference_recall_gate.py \
  --private-source-record /path/to/external/source.jsonl \
  --private-baseline-updater /path/to/prior/update_memory_archive.py \
  --private-project-path /path/to/matching/project
```

That mode reports aggregate-only materialization and target-bound
supported-query counts.
It does not render source text, source paths, session identifiers, query text,
memory text, or raw refs. The frozen private run passed: the prior updater had
`baseline_no_hit_rate=1.0` and materialized zero target memories, while the
candidate materialized one target memory and reached
`candidate_supported_recall=1.0` across all four query variants.

The reviewed three-layer deployment then matched source and installed skill
bundles. The installed setup skill detected exactly one stale deployment tool,
refreshed that source-owned file, and produced two consecutive `19/19`
`current` parity reports. The targeted backfill dry-run selected one allow-listed
source record; apply selected and rewrote one record, removed its one prior
archive entry, and skipped zero records as low signal. Archive audit, publish
readiness, search health, induction/consolidation review, content-noise review,
and reviewed sync dry-run all passed. Every publish-readiness noise category
remained zero.

Runtime code deployment and generated-memory publication remained separate.
The runtime deployment admitted only the one source-owned tool that matched the
installed setup asset. `sync_memory_archive.py --include-reviewed-memory-nodes`
was the only stage, commit, and push path for generated archive data. After
publication, both the deployment search tool and the installed read skill
returned supported active/current packages for all four query variants. All
four resolved to one global current memory; summary-drill, evidence-drill, and
summary-fact resolution rates were `1.0`, and free-form answerability use and
privacy leaks remained zero. The private repository finished clean with
`HEAD == origin/main`; the automation definition and schedule were unchanged.
No private source text, identifier, path, query, hash, memory ID, or raw ref is
stored in this document or in the aggregate reports.

V2.53 proves this bounded correction-to-delivery path. It is not ranking quality,
not vector search, not general complaint understanding, not ontology discovery,
not public leaderboard parity, and not LLM answer quality.

## V2.54 Structure-Preserving Redaction And Scheduled Recovery Closure

Date: 2026-07-23

V2.54 closes one observed scheduled-update blocker. The prior updater applied
the non-structured `Cookie:` pattern directly to serialized JSONL, so the
pattern could consume the closing quote and object delimiter. Raw records were
valid, but selected-record preparation then rejected the damaged redacted text
as `source_inventory_invalid`.

The updater now distinguishes source formats. JSON is parsed as one value and
JSONL is parsed one physical record at a time; existing secret patterns are
applied recursively only to decoded string values. Each JSONL input record
produces one output record, blank-line positions remain stable, and the
redacted output is parsed again by the tests and gate. Structured output uses
ASCII-safe JSON encoding so escaped `U+0085`, `U+2028`, and `U+2029` values do
not become physical line separators during re-encoding. Non-structured text
continues to use the existing text redaction behavior. Source hashes,
timestamps, inventory validation, and source anchors still derive from the
original source bytes.

All structured callers use the path-aware boundary, including selected-record
preparation, direct archive writes, secret preflight, backfill, source-anchor
upgrade, and the two attribution benchmarks. The template, setup asset, and
update-skill copies remain byte-for-byte synchronized.

The bounded public-data-free gate is:

```bash
python3 benchmarks/structured_redaction_integrity_gate.py
```

It covers JSON and multi-record JSONL, nested string values, Cookie plus
Bearer/GitHub/OpenAI secrets, blank-line and ordinal preservation, actual
`--source-inventory-stdin` materialization, malformed input, automation-source
rejection, and target-metadata rejection.

| Synthetic metric | Result |
| --- | ---: |
| `structured_source_parse_success_rate` | 1.0 |
| `structured_redaction_parse_success_rate` | 1.0 |
| `cookie_redaction_success_rate` | 1.0 |
| `jsonl_boundary_preservation_rate` | 1.0 |
| `selected_record_materialization_success_rate` | 1.0 |
| `malformed_source_fail_closed_rate` | 1.0 |
| `inventory_rejection_boundary_pass_rate` | 1.0 |
| `source_inventory_invalid_count` for valid cases | 0 |
| `expected_source_inventory_rejection_count` | 3 |
| `privacy_leak_count` | 0 |

One frozen aggregate-only private redaction A/B used the same 53-record target
cohort exactly once per implementation. Raw parsing had zero failures. The
pre-fix updater produced five redacted parse failures; the candidate produced
zero.

The A/B harness's isolated materialization substep was invalid because that
temporary harness truncated microseconds from an mtime-derived
`source_updated_at`, producing a separate `source inventory timestamp
mismatch`. It was not rerun and is not counted as a passing materialization
probe. The required single live scheduled transaction subsequently supplied
the actual target-update evidence using the production runner's
precision-preserving inventory payload.

| Aggregate private closure metric | Result |
| --- | ---: |
| `private_source_record_count` | 53 |
| `private_raw_parse_failure_count` | 0 |
| `private_baseline_redaction_parse_failure_count` | 5 |
| `private_candidate_redaction_parse_failure_count` | 0 |
| `private_selected_target_update_success_count` | 1 |
| `private_source_inventory_invalid_count` | 0 |
| `privacy_leak_count` | 0 |

The source skills were installed through a rollback-backed copy. The installed
setup skill then detected and refreshed exactly three stale source-owned
deployment tools. Post-refresh runtime parity was `19/19 current`:
`missing_tool_count=0`, `stale_tool_count=0`, `unsafe_target_count=0`,
`changed_tool_count=0`, equal source/target bundle fingerprints, and
`privacy_leak_count=0`.

Exactly one real scheduled transaction was invoked after clean canonical,
remote-head, parity, and single-writer preflights. Its terminal aggregate
report was:

| Scheduled metric | Result |
| --- | ---: |
| `status` | `published` |
| `reason` | `published` |
| `failure_stage` | `none` |
| `update_project_processed_count` | 74 |
| `update_source_stream_processed_count` | 0 |
| `update_child_failure_count` | 0 |
| `update_inventory_worker_count` | 1 |
| `source_record_deferred_count` | 2 |
| `source_target_deferred_count` | 2 |
| `canonical_mutation_count` | 1 |
| `remote_publish_count` | 1 |
| `recovery_count` | 1 |
| `repair_attempt_count` | 1 |
| `privacy_leak_count` | 0 |

The two live-source deferrals make `source_batch_complete=false`; they do not
change the published terminal status. The prior selected target was processed
within all 74 successful project updates, no child failed, and the original
`project_update/source_inventory_invalid` blocker did not recur. After the
terminal report, the canonical repository was clean, its local and remote
heads matched, runtime parity remained current, and no updater or adapter
process survived.

An independent post-transaction review then found the escaped Unicode line
separator edge case described above. Fail-first helper, CLI, and gate cases
reproduced it before the ASCII-safe encoding change. The focused gates and full
release gate were rerun after the change, and the final runtime bundle was
deployed with current parity. The scheduled transaction was deliberately not
run a second time. Consequently, the live transaction proves recovery for the
observed private Cookie cohort; the escaped-separator hardening has synthetic,
packaged, and deployed-parity evidence, not a second live publication claim.

V2.54 proves structure-preserving redaction for the supported JSON, JSONL, and
non-structured source boundaries; selected-record materialization; and
scheduled recovery from this exact blocker. It does not prove complete secret
detection, a general DLP system, arbitrary structured formats, ranking or
memory-recall improvement, goal-preference improvement, vector search,
ontology discovery, LLM answer quality, public leaderboard parity, or that all
future automation failures are solved.

## V2.55 General Durable Preference Recall Holdout Closure

Date: 2026-07-23

V2.55 evaluates one bounded candidate for recalling durable user preferences
without adding benchmark query strings, per-domain canonical facts, or another
goal-query alias list. The public-data-free gate is:

```bash
python3 benchmarks/general_durable_preference_recall_gate.py --cohort calibration
python3 benchmarks/general_durable_preference_recall_gate.py --cohort holdout
```

The frozen calibration fingerprint is
`9cc208235c44c99a1ad9e13c04662d1907a23a268e249b15ee919b9b2286862b`.
The frozen holdout fingerprint is
`2e0c4b9ab2515c368843d651217487595ab683f4068df7dc57c12ba742b16147`.
Each cohort has nine positive and nine negative cases; their case IDs and
source records are disjoint.

The baseline first-loss distributions were:

| Cohort | First-loss distribution |
| --- | --- |
| calibration | `durable_preference_qualified=2`, `retrieved_at_5=3`, `query_support_accepted=3`, `none=1` |
| holdout | `durable_preference_qualified=2`, `retrieved_at_5=3`, `query_support_accepted=4` |

The single candidate combines only stages identified by that attribution:

- generic repeated-correction induction over user events with source-bound
  evidence and source anchors;
- bounded CJK substantive-unit matching rather than an unbounded token or
  embedding index;
- global preference applicability restricted to active/current, source-backed
  preference memories and rejected for multi-facet queries;
- continued precedence for the existing V2.53 goal-specific inducer so legacy
  behavior remains compatible.

Answerability remains package-first. Every decision consumes
`memory_recall_context_package`; free-form search output is not an
answerability source. The candidate adds no persistent vector or embedding
store. Applicability support is explicitly labeled
`scoped_global_preference_applicability`; it is not mislabeled as the existing
strict query-support policy. The V2.37 packaged parity check therefore remains
strict for strict-policy hits while separately counting non-baseline-policy
hits.

Calibration passed all frozen thresholds. The public holdout was run twice and
reproduced the same quality result. All nine ordinary candidate positives had
no first loss, but the independent generic path failed when the legacy
goal-specific inducer and aliases were ablated.

| Public candidate metric | Calibration | Holdout |
| --- | ---: | ---: |
| `generic_preference_qualification_recall` | 1.0 | 1.0 |
| `generic_preference_materialization_recall` | 1.0 | 1.0 |
| `generic_preference_source_anchor_binding_rate` | 1.0 | 1.0 |
| `generic_preference_scope_accuracy` | 1.0 | 1.0 |
| `unseen_paraphrase_recall_at_5` | 1.0 | 1.0 |
| `unseen_paraphrase_supported_recall` | 1.0 | 1.0 |
| `supported_decision_precision` | 1.0 | 1.0 |
| `hard_negative_rejection_rate` | 1.0 | 1.0 |
| `inactive_preference_rejection_rate` | 1.0 | 1.0 |
| `current_turn_precedence_accuracy` | 1.0 | 1.0 |
| `legacy_goal_preference_regression_rate` | 1.0 | 1.0 |
| `legacy_goal_alias_ablation_supported_recall` | 1.0 | **0.0** |
| `free_form_answerability_use_count` | 0 | 0 |
| `new_case_specific_runtime_literal_count` | 0 | 0 |
| `holdout_query_literal_overlap_count` | 0 | 0 |
| `preference_specific_candidate_branch_count` | 0 | 0 |
| `deterministic_result_ordering_rate` | 1.0 | 1.0 |
| `performance_runtime_ratio` | 1.059 | 1.014 |
| `performance_peak_memory_ratio` | 1.008 | 0.996-1.017 |
| `privacy_leak_count` | 0 | 0 |

The private shadow used one frozen external manifest with six positive and six
negative cases against one immutable archive snapshot. The report is
aggregate-only and excludes queries, memory text, source paths, IDs, raw refs,
and context packages.

| Private candidate metric | Result |
| --- | ---: |
| `private_context_package_parse_success_rate` | 1.0 |
| `private_unseen_preference_supported_recall` | 1.0 |
| `private_supported_decision_precision` | **0.8571428571428571** |
| `private_false_support_count` | **1** |
| `private_wrong_scope_supported_count` | 0 |
| `private_inactive_answer_count` | 0 |
| `private_free_form_answerability_use_count` | 0 |
| `canonical_archive_mutation_count` | 0 |
| `privacy_leak_count` | 0 |

Decision: `no_go`. The public
`legacy_goal_alias_ablation_supported_recall` threshold required at least
`0.75` and observed `0.0`; the private precision threshold required `1.0` and
one of six negative cases was falsely supported. These are quality failures,
not permission to add case-specific cues or a second candidate.

The candidate exists only on the V2.55 evaluation branch. It was not installed
or deployed. The three installed skills remain byte-for-byte equal to V2.54,
and their private deployment bundle remains `19/19 current` with a clean
repository and matching local/remote heads. The canonical release gate does
not execute this known-failing holdout; it compiles the evaluation gate and
continues to protect the active V2.54 release contract. Its final run passed
all 48 checks, including all 853 unit tests, both v1 readiness scorecards,
script compilation, and template synchronization.

This result is evidence for one synthetic durable-preference slice and one
aggregate private shadow only. It is not general LongMemEval quality.
It is not universal semantic memory. It is not LLM answer quality.
It is not vector-search quality. It is not ontology discovery.
It is not unrestricted raw-transcript recall.
It is not distributed scheduler uptime. It is not public leaderboard parity.

## V2.56 Subject-Anchored Hybrid Preference Recall Closure

Date: 2026-07-24

V2.56 evaluates a bounded read-path candidate over already materialized,
active/current, source-bound preference memories. It replaces V2.55's broad
preference override with two explicitly separated stages:

- `normalized_subject_candidate_v1` applies Unicode NFKC, casefolding,
  Latin/CJK boundary normalization, coarse subject-segment coverage, and
  bounded CJK bigram/trigram overlap for candidate retrieval and ranking;
- `source_bound_subject_preference_support_v1` is the only preference-memory
  authorization policy. It requires focused preference intent,
  automatic/explicit provenance, global layer and scope, summary/evidence
  drill paths, stable subject anchors, polarity, currentness, and either an
  independent attribute-support unit or an open-ended subject lookup.

The exact lexical path remains available for retrieval, and exact `matched_tokens`
now contains exact matches only. Exact coverage does not
bypass the preference support policy. Normalized overlap is emitted separately
as aggregate-safe `candidate_match` metadata; candidate retrieval is not answerability:
candidate score, normalized coverage, subject coverage, and
exact lexical coverage alone cannot produce a supported preference package.

The gate now uses pre-materialized source-bound read-path fixtures rather than
calling the V2.55 no-go updater candidate. The final production updater copies
retain V2.54 write-path behavior. The V2.55 calibration fingerprint remains
`9cc208235c44c99a1ad9e13c04662d1907a23a268e249b15ee919b9b2286862b`;
the V2.55 holdout fingerprint remains
`2e0c4b9ab2515c368843d651217487595ab683f4068df7dc57c12ba742b16147`.
Both remain historical `no_go` evidence and are included in the V2.56 report.

The V2.56 calibration fingerprint is
`d44005ef4f618e6344d3465112cab412d4e70291afe348e56b2b73d0c58725d5`.
The regression holdout fingerprint is
`cda9f4d448934636151d27e94fb1f8d3cc316532f7bf7759a01194cad1f20cb3`.
Each contains 13 positive and 16 negative synthetic cases. They returned
`calibration_passed` and `regression_passed`; neither status authorizes
deployment.

The public deployment holdout uses the separate `deployment-holdout` cohort,
which was frozen before execution with fingerprint
`63b837382d0b698daafdbb4f183358a5a62567b73a130f82278b65d305acecaf`.
It contains 8 positive and 13 negative cases. Its first and only execution
returned `status: failed` and `decision: no_go`.

| Public candidate metric | Calibration | Regression | Deployment holdout |
| --- | ---: | ---: | ---: |
| `normalized_surface_variant_recall_at_5` | 1.0 | 1.0 | 0.5 |
| `normalized_surface_variant_supported_recall` | 1.0 | 1.0 | 0.5 |
| `open_ended_subject_preference_supported_recall` | 1.0 | 1.0 | 1.0 |
| `unseen_paraphrase_recall_at_5` | 1.0 | 1.0 | 0.875 |
| `unseen_paraphrase_supported_recall` | 0.9166666666666666 | 0.8333333333333334 | 0.75 |
| `supported_decision_precision` | 1.0 | 1.0 | 1.0 |
| `hard_negative_rejection_rate` | 1.0 | 1.0 | 1.0 |
| `negation_rejection_rate` | 1.0 | 1.0 | 1.0 |
| `inactive_preference_rejection_rate` | 1.0 | 1.0 | 1.0 |
| `wrong_scope_rejection_rate` | 1.0 | 1.0 | 1.0 |
| `current_turn_precedence_accuracy` | 1.0 | 1.0 | 1.0 |
| `legacy_goal_preference_regression_rate` | 1.0 | 1.0 | 0.0 |
| `legacy_goal_alias_ablation_supported_recall` | 0.75 | 0.75 | 0.0 |
| `candidate_only_answer_count` | 0 | 0 | 0 |
| `candidate_only_safety_eligible_rate` | 1.0 | 1.0 | 0.0 |
| `candidate_only_subject_support_count` | 0 | 0 | 0 |
| `bare_subject_rejection_rate` | 1.0 | 1.0 | 1.0 |
| `free_form_answerability_use_count` | 0 | 0 | 0 |
| `new_case_specific_runtime_literal_count` | 0 | 0 | 0 |
| `deterministic_result_ordering_rate` | 1.0 | 1.0 | 1.0 |
| `performance_runtime_ratio` | 1.333 | 1.314 | 1.319 |
| `performance_peak_memory_ratio` | 1.054 | 1.040 | 1.027 |
| `privacy_leak_count` | 0 | 0 | 0 |

The deployment first-loss distribution contains one
`retrieved_at_5` loss and one `query_support_accepted` loss among the eight
positive cases. The two zero-valued legacy metrics also expose a gate
construction defect: the deployment cohort does not contain the legacy
ablation shape even though the shared threshold set requires those metrics.
The candidate-only fixture likewise did not demonstrate the required
safety-eligible near-miss in this cohort. These construction issues do not
convert the result to a pass. The untouched normalized recall failure alone is
sufficient for `no_go`, and the frozen cohort was not changed or rerun.

The frozen private deployment manifest has fingerprint
`f3f0cf92a3afb54c07add2e1f89c411378036e3721ffb7f4afcfc55505313753`
and contains 11 positive and 15 negative cases. The private deployment holdout was not executed
because the public deployment hard gate had already failed.
No private query, memory text, memory ID, source path, raw ref, or context
package was rendered.

The clean packaged runtime gate covers normalized and exact source-bound
preferences, a safety-eligible candidate-only hit, bare subject, wrong scope,
current-turn override, inactive state, weak/no-hit support, and malformed
packages. Supported preference cases map deterministically to
`single_text_fence_no_outer_text`; all negative cases abstain.
Runtime supported-decision, abstention, preference-delivery, and context-package
parse accuracy are 1.0. Candidate-only safety-eligible count is 1, its subject
support count is 0, bare-subject rejection count is 1, and
`privacy_leak_count=0`. Free-form output is not used.

The final decision: `no_go`. The V2.56 candidate was not installed or deployed.
The existing private runtime remains `19/19 current`; its repository is clean
and its local and remote main heads match. V2.54 remains the production
write-path truth. `remaining_semantic_only_failure_count` is not claimed
because the observed residue includes lexical retrieval and gate-construction
failures, not only semantic paraphrases.

The evaluation branch itself remains regression-clean: 863 unit tests passed,
all three skill folders validated, the packaged V1 readiness scorecard passed
6/6 required dimensions, template/runtime copies matched, and the canonical
release-contract runner passed 48/48 checks. Those results protect the existing
release baseline; they do not override the failed V2.56 deployment holdout.

V2.56 is not embedding quality, not vector search, not LLM answer quality,
not ontology discovery, and not public leaderboard parity. It is also not a
ranking overhaul, automatic induction quality, or unrestricted semantic recall.

## V2.57 JSONL Physical-Line Recovery And Dev-Feature Convergence

Date: 2026-07-25

V2.57 closes a distinct record-boundary defect found after V2.54. Valid JSONL
may contain literal U+0085, U+2028, or U+2029 characters inside a JSON string.
Python `str.splitlines()` treats those characters as line boundaries, so the
inventory runner and updater could split a valid physical record in the middle
of a string and fail it as `source_inventory_invalid`.

The JSONL contract is now explicit: only LF and CRLF delimit physical records.
Literal U+0085, U+2028, and U+2029 remain JSON string content. The focused
change covers inventory parsing, updater parsing, structured redaction,
selected-record analysis, value detection, and source-event locators. Ordinary
text and command-output uses of `str.splitlines()` are unchanged. Missing,
truncated, and otherwise malformed JSONL still fails closed.

V2.57 is based on the V2.54 production truth. V2.56 remains `no_go`; its
read-path candidate is retained as evaluation history and is neither installed
nor treated as production authorization.

The bounded public-data-free gate is:

```bash
python3 benchmarks/jsonl_record_boundary_recovery_gate.py
```

It covers LF, CRLF, multi-record input, blank records, all three literal
Unicode separators, an isolated inventory worker, selected-record
materialization, truly malformed JSONL, and stale `phase=updating` transaction
replay.

| Synthetic metric | Result |
| --- | ---: |
| `unicode_separator_inventory_acceptance_rate` | 1.0 |
| `unicode_separator_materialization_rate` | 1.0 |
| `physical_record_count_accuracy` | 1.0 |
| `crlf_compatibility_rate` | 1.0 |
| `malformed_jsonl_fail_closed_rate` | 1.0 |
| `stale_replay_recovery_rate` | 1.0 |
| `valid_case_source_inventory_invalid_count` | 0 |
| `privacy_leak_count` | 0 |

The three production-safe skills were installed through a rollback-backed
copy, after which all three source and installed skill trees matched. The new
installed setup skill reported exactly two stale deployment tools in both its
read-only check and repair dry-run. The transactional refresh changed only the
runner and updater, and the reviewed tool-only deployment was committed and
published. Installed-to-private deployment parity then returned `19/19
current`: missing, stale, unsafe, and extra tool counts were zero, source and
target bundle fingerprints matched, and `privacy_leak_count=0`.

After clean canonical, remote-head, parity, and single-writer preflights,
exactly one controlled transaction was invoked. Its terminal aggregate was:

| Controlled transaction metric | Result |
| --- | ---: |
| `status` | `published` |
| `reason` | `published` |
| `failure_stage` | `none` |
| `recovery_action` | `stale_staging_replayed` |
| `update_inventory_worker_count` | 1 |
| `update_project_processed_count` | 76 |
| `update_source_stream_processed_count` | 0 |
| `update_child_failure_count` | 0 |
| `source_record_deferred_count` | 3 |
| `source_target_deferred_count` | 2 |
| `canonical_mutation_count` | 1 |
| `remote_publish_count` | 1 |
| `recovery_count` | 1 |
| `repair_attempt_count` | 1 |
| `source_batch_complete` | false |
| `privacy_leak_count` | 0 |

The transaction crossed source inventory and published stable source siblings;
the three deferred records across two targets explain
`source_batch_complete=false` and remain eligible for a later scheduled run.
No retry or fallback was used. Postflight found no surviving writer, the
canonical worktree was clean, canonical HEAD matched the freshly fetched
remote receipt, persistent transaction state had been cleared by the adapter,
and runtime parity remained `19/19 current`.

V2.57 proves the bounded JSONL physical-line contract and recovery path. It is
not overall semantic recall closure, ranking quality, vector search, ontology
discovery, public leaderboard parity, or LLM answer quality.

## V2.58 Real-Use Semantic Support Admission And Release-Truth Convergence

Date: 2026-07-28

Decision: `no_go`.

V2.58 evaluated one bounded local semantic verifier for the specific failure
where an active/current memory is already in the context-package top five with
summary and evidence paths, but strict lexical `query_support` remains weak.
It did not evaluate semantic retrieval for a no-hit query.

Release truth was repaired before the candidate was evaluated. The template,
setup asset, and bundled `using-my-precious` search tools were restored to the
approved V2.53/V2.54/V2.57 read path with SHA-256
`e73b7b6600db8a147d667f91f08eef0562b5029e487950a7fa228c4903f8d248`.
The release-truth gate rejects both historical no-go runtimes:

| historical candidate | rejected search SHA-256 |
| --- | --- |
| V2.55 | `3e0715d25cf0d59703774c5e9d41a19155e92ce85fa8f11549516449d3c15875` |
| V2.56 | `29e20ef5f63570d37d09eb878916d66de57ff44e9f8e794bd5f1ec33e25eefed` |

The gate also fails closed with aggregate JSON for missing, unreadable, or
non-UTF-8 release surfaces. It does not render local paths or tracebacks.

The frozen public-data-free case file is
`benchmarks/cases/real_use_semantic_support_synthetic.jsonl`, with SHA-256
`7893a6646c36982be2213f43bac75c8c045e72612d5f4177deb27b26e56172d0`.
Calibration and holdout are disjoint:

| cohort | slice fingerprint | positive | negative | intended weak-hit cases |
| --- | --- | ---: | ---: | ---: |
| calibration | `40477d84e0ac82b26048161a46c784a06821f803d2e557203cf061e7da436edf` | 9 | 9 | 6 |
| holdout | `b44ee705010bfc9de96407a16e7eba2328d435b93fe986e0c9173528a8e88959` | 9 | 13 | 6 |

Both baseline cohorts reproduced the same positive first-loss distribution:

| first-loss stage | count per cohort |
| --- | ---: |
| `memory_not_materialized` | 1 |
| `not_retrieved_at_5` | 1 |
| `retrieved_but_query_support_weak` | 6 |
| `supported` | 1 |

`baseline_support_gap_reproduction_rate` and
`baseline_first_loss_classification_accuracy` were both 1.0. V2.58 was scoped
only to `retrieved_but_query_support_weak`; the other first-loss stages remain
future work.

The single candidate was frozen in commit
`bfc5842bea845dddceb1721a4d47b9155aa21e70`. Its identity was:

| field | frozen value |
| --- | --- |
| model | `intfloat/multilingual-e5-small` |
| model revision | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| model artifact-manifest SHA-256 | `8a945b5d9dde256c5bb6f0274845ac4d7a42e9a02b1e0ac76da66972d32299bb` |
| model/runtime fingerprint | `89c7223e22f226e5142b3ebc9360f0127b436dc88ba8684922b55dbdabcd6437` |
| sentence-transformers | 5.6.0 |
| torch | 2.13.0 |
| transformers | 5.14.1 |
| prefix policy | `query:` / `passage:` |
| threshold | 0.85 |
| maximum candidates | 5 |
| provider deadline | 1.75 seconds |
| query-time network | disabled |

The candidate only inspected eligible weak active/current hits already present
in the first five lexical results. A private mode-0600 Unix socket carried one
bounded query and up to five bounded candidate texts to the local provider.
Provider absence, timeout, fingerprint mismatch, malformed output, unknown or
duplicate IDs, and non-finite scores failed closed to the lexical result. A
semantic score alone could not authorize an answer: active/current lifecycle,
automatic or explicit provenance, matching layer/scope/project context, both
summary and evidence paths, focused single-facet intent, polarity/currentness,
and current-turn precedence were also required.

Calibration passed and froze the threshold:

| calibration metric | result |
| --- | ---: |
| `semantic_support_public_calibration_recall` | 1.0 |
| `supported_decision_precision` | 1.0 |
| `hard_negative_rejection_rate` | 1.0 |
| `wrong_scope_rejection_rate` | 1.0 |
| `inactive_rejection_rate` | 1.0 |
| `provider_failure_fail_closed_rate` | 1.0 |
| `summary_evidence_resolution_rate` | 1.0 |
| `legacy_v253_goal_preference_regression_rate` | 1.0 |
| `semantic_positive_min` | 0.851811 |
| `semantic_negative_max_evaluated` | 0.831818 |
| `public_warm_query_p95_seconds` | 0.121655 |
| `false_support_count` | 0 |
| `case_specific_runtime_literal_count` | 0 |
| `privacy_leak_count` | 0 |

The frozen public holdout then failed the required recall threshold:

| holdout metric | required | result |
| --- | ---: | ---: |
| `semantic_support_public_holdout_recall` | 1.0 | 0.8333333333333334 |
| `summary_evidence_resolution_rate` | 1.0 | 0.8333333333333334 |
| `supported_decision_precision` | 1.0 | 1.0 |
| `hard_negative_rejection_rate` | 1.0 | 1.0 |
| `wrong_scope_rejection_rate` | 1.0 | 1.0 |
| `inactive_rejection_rate` | 1.0 | 1.0 |
| `current_turn_precedence_accuracy` | 1.0 | 1.0 |
| `provider_failure_fail_closed_rate` | 1.0 | 1.0 |
| `legacy_v253_goal_preference_regression_rate` | 1.0 | 1.0 |
| `public_warm_query_p95_seconds` | <= 2.0 | 0.105967 |
| `false_support_count` | 0 | 0 |
| `free_form_answerability_use_count` | 0 | 0 |
| `case_specific_runtime_literal_count` | 0 | 0 |
| `privacy_leak_count` | 0 | 0 |

The aggregate holdout report was written outside this repository. No threshold,
model, rule, or holdout case was changed after observing the result. Because
public holdout failed, the one-shot private holdout was not run, no private
archive was queried by the candidate admission, and no candidate was installed
or deployed. `private_real_use_goal_preference_supported_recall` and
`private_warm_query_p95_seconds` therefore have no V2.58 result and must not be
reported as passing.

The private gate validates the aggregate public-holdout admission and the exact
deployed candidate search-runtime hash before it reads a private manifest or
archive. In the V2.58 no-go release state, the approved lexical runtime therefore
closes the private path before private inputs are accessed.

The no-go candidate runtime was removed from every installable surface. The
evaluation runner now loads the exact candidate scripts only from the frozen
historical commit and verifies their SHA-256 values before replay. Production
continues to use the approved lexical runtime, and the real-use Goal-preference
weak-hit experience remains unresolved.

Baseline taxonomy verification remains part of the canonical release gate:

```bash
python3 benchmarks/real_use_semantic_support_gate.py \
  --cohort calibration --baseline-only
python3 benchmarks/real_use_semantic_support_gate.py \
  --cohort holdout --baseline-only
```

V2.58 proves a frozen public calibration/holdout admission decision and clean
release-truth rollback. It does not prove real Goal-preference recall closure,
private recall, no-hit semantic retrieval, vector search, a persistent
embedding store, ranking quality, automatic induction quality, ontology
discovery, LLM answer quality, or public leaderboard parity.

## V2.59 Mainline Release Truth And Live Runtime Identity Convergence

Date: 2026-07-28

Decision: `go`.

The V2.59 preflight observed `origin/main` as an ancestor of
`origin/dev-feature`, with a left/right commit count of `0/20`. The three
installed skills matched the integration branch, and the private runtime tool
bundle reported `19/19 current`, but those two mutually consistent runtime
layers were not tied to the latest approved release at `origin/main`. Existing
runtime parity explicitly did not claim latest-release discovery.

V2.59 adds the read-only
`tools/audit_release_convergence.py` composition audit and the deterministic
`benchmarks/release_convergence_gate.py`. The audit binds a clean approved Git
ref to the complete three-skill source bundle, installed skill bundle, source
tool bundle, deployed tool bundle, and live automation command contract. It
reports `source_installed_skills_match`, `source_deployed_tools_match`, and
`automation_contract_aligned` without rendering paths, prompt text, archive
content, raw refs, or file contents.

The pre-deployment three-skill source and installed bundle SHA-256 was
`b921ab50355af8650b8b5696278e1b1f9dd6daec2d89973272c6271ddee7d17d`.
The source and deployed runtime-tool bundle SHA-256 was
`6c5535e99b9a568b060b7506bd2a6587e3504ee16fa719854f83d753dc7a6dd9`.
These content identities remain valid across documentation-only integration
commits. The authoritative final source commit is emitted by the live
aggregate report and verified by equal remote refs; it is not self-embedded in
the commit whose identity it would change.

The final live audit at operational source commit
`0c465d9d322d149747dd91322fcde72c542872de` returned status: `current`.
The source, approved, and integration commit identities were equal. All
`source_installed_skills_match`, `source_deployed_tools_match`, and
`automation_contract_aligned` checks were true. Skill-tree, missing-tool,
stale-tool, unsafe-target, automation-contract, and automation-self-update
mismatch counts were zero, with `audit_mutation_count: 0` and
`privacy_leak_count: 0`.

The final mainline skills already matched the installed skills, so deployment
required no file replacement. Private runtime parity remained `19/19 current`,
so no tool refresh or private repository commit was needed. The live
automation was inspected through its automation API and required no mutation.
PR #18 preserved the complete integration history, its merge commit was
fast-forwarded back to `dev-feature`, and the temporary implementation branch
and worktree were removed only after proving they had zero unique commits.

The synthetic gate runs the full case set twice and requires identical
aggregate reports. Its accepted metrics are:

| metric | result |
| --- | ---: |
| `current_release_acceptance_accuracy` | 1.0 |
| `old_but_mutually_consistent_rejection_accuracy` | 1.0 |
| `stale_installed_rejection_accuracy` | 1.0 |
| `stale_private_runtime_rejection_accuracy` | 1.0 |
| `unreleased_source_ref_rejection_accuracy` | 1.0 |
| `automation_path_mismatch_rejection_accuracy` | 1.0 |
| `automation_self_update_rejection_accuracy` | 1.0 |
| `malformed_release_evidence_rejection_accuracy` | 1.0 |
| `approved_search_runtime_acceptance_accuracy` | 1.0 |
| `historical_no_go_runtime_rejection_accuracy` | 1.0 |
| `audit_mutation_count` | 0 |
| `privacy_leak_count` | 0 |

The exact missing case is now fail closed: when installed skills and deployed
tools are mutually consistent but both predate the approved source, the audit
returns `drifted`. A source HEAD that does not equal the approved ref, an
unmerged integration ref, a single stale layer, a wrong automation path, or
malformed release evidence also cannot report `current`.

The release procedure keeps scheduled execution unchanged. Scheduled
automation consumes an explicitly deployed release and still must not pull,
install, refresh, retry, or use direct Git publication. Release freshness is
checked at the release/deployment boundary; scheduled runtime parity remains a
consistency and safety gate.

The final operational audit receipt proved all of the following:

- `origin/main` and `origin/dev-feature` resolve to the same source commit;
- all three installed skills match the approved source bundle;
- private runtime parity is current and matches the source tool bundle;
- the live automation invokes the exact installed setup and transaction
  adapter paths;
- source and private repositories are clean and match their remote receipts.

V2.59 is not Goal-preference recall closure, not semantic retrieval, not
no-hit retrieval, not ranking quality, not vector search, not embedding
storage, not ontology discovery, and not automatic induction quality. It is
not LLM answer quality, not scheduler/network reliability, and not public leaderboard parity.
The observed real-use Goal-preference recall gap remains the next bounded
product-quality problem after release convergence.

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

Baseline date: 2026-07-07

Code point used for the benchmark harness: this document revision

Case file:
`benchmarks/cases/updater_induction_synthetic.jsonl`

Case fingerprint:
`70c9cf786338b362189ff246abfbb5e61ecdf3d35dac45d34d12b909d855ecb3`

Runner fingerprint:
`f9dd2e8590088aa1707f9fc6a6e95725052703ee0f17959c2d80959075797ac7`

Setup script fingerprint:
`d3303d2b061a3568c107cdc6dfadddcf4b254d527ae4c44babbccc5e6f86774d`

Updater script fingerprint:
`0787c964fd662950bb5ad46e5e67972a7ca21b0388baa7f1482b6af3404a73a3`

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
| cases | 30 |
| source_records | 43 |
| expected_automatic_memories | 15 |
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
| contradiction_review_routing_rate | 1.0 |
| scope_shift_review_routing_rate | 1.0 |
| consolidated_duplicate_suppression_rate | 1.0 |
| consolidated_support_merge_rate | 1.0 |
| consolidated_evidence_retention_rate | 1.0 |
| post_consolidation_recall_at_5 | 1.0 |
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
| induction_consolidation | 1 |
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
The induction consolidation case verifies that paraphrased same-fact automatic
memories collapse to one current node with merged support/evidence refs and
remain recallable through a context package at top 5.
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
- Direct explicit-memory writes now have a minimal runtime adapter and governing
  prompt contract for short, evidence-bound facts. The remaining gap is broader
  policy design for bulk explicit-memory governance, deletion, and conflict
  handling.
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

Recorded required v1 gate summary at that code point:

| dimension | status | evidence level | key metrics |
| --- | --- | --- | --- |
| layered_recall | passed | packaged synthetic | `memory_recall_at_5=1.0`, `layer_path_success_rate=1.0`, `drilldown_success_rate=1.0`, `source_ref_reachability=1.0`, `raw_preview_authorization_pass_rate=1.0`, `privacy_leak_count=0` |
| automatic_induction | passed | packaged synthetic | `natural_induction_success_rate=1.0`, `cross_project_generalization_rate=1.0`, `forced_memory_capture_rate=1.0`, `induction_review_routing_rate=1.0`, `privacy_leak_count=0` |
| e2e_induction_to_recall | passed | packaged synthetic | `e2e_memory_recall_at_5=1.0`, `e2e_layer_assignment_accuracy=1.0`, `e2e_session_drilldown_rate=1.0`, `e2e_source_policy_pass_rate=1.0`, `privacy_leak_count=0` |
| source_stream_registry | passed | packaged synthetic | `source_stream_update_rate=1.0`, `project_registry_independence_rate=1.0`, `archive_scope_assignment_rate=1.0`, `source_partition_assignment_rate=1.0`, `source_stream_evidence_reachability_rate=1.0`, `privacy_leak_count=0` |
| generated_answer_eval | passed | private deployment aggregate | `case_pass_rate=1.0`, `answer_normalized_match_rate=1.0`, `abstention_accuracy=1.0`, `answer_scorable_case_rate=1.0`, `privacy_leak_count=0` |

Recorded v1 readiness status at that code point:

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
| Quantified readiness gate | satisfied for v1 | `v1_readiness_gate.py` returned `extended_evidence_ready` with 5/5 required dimensions passed at that code point; the current packaged release contract is summarized in the V1 Readiness Gate section above |
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

## V1.1 Real-Archive Shadow Coverage Expansion

Date: 2026-06-30

Code point: `db85196 Merge pull request #3 from Dsssyc/codex/v1.1-daily-record-content-contract`

This expands the private redacted real-history shadow probe coverage without
changing public benchmark logic or search-ranking behavior. It adds a separate
coverage gate instead of weakening the stricter v1.1 baseline gate:

- `benchmarks/quality-gates/real_archive_shadow_v11_coverage.json`
- `benchmarks/quality-gates/real_archive_shadow_v11_coverage_max.json`

The coverage gate files contain only numeric aggregate thresholds. They do not
contain private probe rows, queries, memory IDs, memory text, source refs,
source paths, raw refs, generated answers, or answer text.

The private coverage probe extends the v2 redacted real-history set from 27 to
34 cases: 31 positive cases and 3 expected-abstain cases. The seven added cases
cover these aggregate categories:

| added category | cases |
| --- | ---: |
| broad_lexical_top_k_noise_variant | 1 |
| scope_mixed_top_k_noise_variant | 1 |
| daily_automation_process_noise | 3 |
| consolidation_lifecycle | 2 |

Command:

```bash
python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v3.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  --fail-under-file benchmarks/quality-gates/real_archive_shadow_v11_coverage.json \
  --fail-over-file benchmarks/quality-gates/real_archive_shadow_v11_coverage_max.json \
  > /tmp/my_precious_v11_shadow_v3_coverage_20260630.json
```

The command emitted aggregate-only JSON and returned success against the
current private deployment archive. The private probe file and report remain
outside this repository.

Coverage gate aggregate result:

| metric | value |
| --- | ---: |
| archive.memory_records | 1402 |
| archive.legacy_session_records | 275 |
| probe_cases.cases | 34 |
| probe_cases.positive_cases | 31 |
| probe_cases.abstain_cases | 3 |
| privacy_pattern_cases | 12 |
| memory_recall_at_5 | 1.0 |
| memory_precision_at_5 | 0.5737704918032787 |
| top_k_noise_at_5 | 0.42622950819672134 |
| noise_sources_at_5.broad_lexical_match | 20 |
| noise_sources_at_5.scope_mixed | 6 |
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
| lifecycle_integrity.checked_refs | 4 |
| lifecycle_integrity.broken_refs | 0 |
| lifecycle_integrity.illegal_state_records | 0 |
| diagnostics.failure_case_count | 11 |
| diagnostics.failure_types.top_k_noise | 11 |
| diagnostics.failure_types.recall_miss | 0 |
| diagnostics.failure_types.abstain_false_positive | 0 |
| diagnostics.failure_types.suppression_failure | 0 |
| diagnostics.failure_types.privacy_failure | 0 |

Claim boundary: this is a coverage expansion, not a ranking improvement.
Compared with the stricter 27-case v1.1 baseline, the broader 34-case probe
keeps recall, abstention, active-memory suppression, privacy, provenance, and
lifecycle integrity at `1.0`, but exposes more top-k noise:

| metric | strict v1.1 baseline | expanded coverage |
| --- | ---: | ---: |
| probe_cases.cases | 27 | 34 |
| memory_precision_at_5 | 0.6086956521739131 | 0.5737704918032787 |
| top_k_noise_at_5 | 0.3913043478260869 | 0.42622950819672134 |
| noise_sources_at_5.broad_lexical_match | 15 | 20 |
| noise_sources_at_5.scope_mixed | 3 | 6 |

The regression bucket is search-quality noise under harder coverage, not a
recall, privacy, provenance, or lifecycle failure. During case design, generic
daily/process-noise no-hit probes were rejected because they legitimately
retrieved durable policy memories about process-noise handling. The retained
daily/automation cases therefore test positive recall of durable process
policy rather than treating all process-related hits as false positives.

## V1.1 Scope-Aware Real-Archive Ranking Reduction

Date: 2026-06-30

Base code point: `f470719 Merge pull request #4 from Dsssyc/codex/v1.1-shadow-coverage-expansion`

This is a bounded ranking change, not a benchmark expansion. The search path now
keeps the strongest memory anchor and prunes same-layer tail hits whose scope
and topic both differ from that anchor after the existing relative-score floor.
It also extends the existing process-memory demotion so automatic process
records with repeated query wording are demoted even when their support count is
above one. These rules are generic search-ranking rules; they do not inspect or
encode private probe queries, memory IDs, memory text, source refs, source
paths, or raw refs.

The stricter v1.1 and expanded-coverage gate files were tightened to the new
aggregate profile:

- `benchmarks/quality-gates/real_archive_shadow_v11.json`
- `benchmarks/quality-gates/real_archive_shadow_v11_max.json`
- `benchmarks/quality-gates/real_archive_shadow_v11_coverage.json`
- `benchmarks/quality-gates/real_archive_shadow_v11_coverage_max.json`

Commands:

```bash
python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v2.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  --fail-under-file benchmarks/quality-gates/real_archive_shadow_v11.json \
  --fail-over-file benchmarks/quality-gates/real_archive_shadow_v11_max.json \
  > /tmp/my_precious_v11_shadow_strict_after_scope_ranking_20260630.json

python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v3.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  --fail-under-file benchmarks/quality-gates/real_archive_shadow_v11_coverage.json \
  --fail-over-file benchmarks/quality-gates/real_archive_shadow_v11_coverage_max.json \
  > /tmp/my_precious_v11_shadow_coverage_after_scope_ranking_20260630.json
```

Both commands emitted aggregate-only JSON and returned success against the
current private deployment archive.

Strict v1.1 27-case gate before/after:

| metric | before | after |
| --- | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.6086956521739131 | 0.8064516129032258 |
| top_k_noise_at_5 | 0.3913043478260869 | 0.19354838709677424 |
| noise_sources_at_5.broad_lexical_match | 15 | 4 |
| noise_sources_at_5.scope_mixed | 3 | 2 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 |
| abstain_pass_rate | 1.0 | 1.0 |
| active_memory_suppression | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 |
| provenance_coverage.score | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |
| diagnostics.failure_types.top_k_noise | 8 | 5 |

Expanded 34-case coverage gate before/after:

| metric | before | after |
| --- | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.5737704918032787 | 0.7804878048780488 |
| top_k_noise_at_5 | 0.42622950819672134 | 0.2195121951219512 |
| noise_sources_at_5.broad_lexical_match | 20 | 6 |
| noise_sources_at_5.scope_mixed | 6 | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 |
| abstain_pass_rate | 1.0 | 1.0 |
| active_memory_suppression | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 |
| provenance_coverage.score | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |
| diagnostics.failure_types.top_k_noise | 11 | 8 |

Claim boundary: this is a ranking/noise reduction for near-tie memory-node
results, not a new recall feature. It intentionally reduces same-layer
cross-scope/cross-topic top-k fill after a stronger anchor exists. It preserves
case-level recall, abstention, active suppression, privacy, provenance, and
lifecycle gates, but it can reduce the number of relevant sibling memories
returned for a case. The benchmark precision metric counts result-level
relevance, while recall remains case-level.

Privacy-safe aggregate diagnostics showed that the remaining expanded
`scope_mixed=3` aligns with expected-layer versus expected-memory layer
mismatch in the private probe/archive data. Treat that residual bucket as a
case/archive-data boundary before adding more ranking rules for it. Further
ranking changes should target the remaining `broad_lexical_match=6` only if
they improve aggregate buckets without reducing the preserved gates above.

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

## V1.1 Shadow Relation Gate Follow-Up

Date: 2026-07-01

Code point: `06b7266 Merge pull request #6 from Dsssyc/codex/v1.1-shadow-noise-relations`

After adding `noise_relation_to_expected_at_5`, the strict and expanded
private real-archive shadow evaluations were rerun with aggregate-only output
written under `/tmp`. The private probe files, raw case rows, queries, memory
IDs, memory text, source refs, source paths, raw refs, and full JSON reports
were not copied into this repository.

Commands:

```bash
python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v2.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  > /tmp/my_precious_shadow_relation_strict_nogate_20260701.json

python3 templates/agent-memory-repo/tools/shadow_eval_memory_archive.py \
  --repo /path/to/private-agent-memory \
  --cases /path/to/private-agent-memory/eval/redacted_real_history_probe_v3.jsonl \
  --audit-script templates/agent-memory-repo/tools/audit_memory_archive.py \
  > /tmp/my_precious_shadow_relation_expanded_nogate_20260701.json
```

Aggregate rerun results:

| metric | strict v2 | expanded v3 |
| --- | ---: | ---: |
| archive.memory_records | 1409 | 1409 |
| archive.legacy_session_records | 277 | 277 |
| probe_cases.cases | 27 | 34 |
| probe_cases.positive_cases | 24 | 31 |
| probe_cases.abstain_cases | 3 | 3 |
| memory_recall_at_5 | 0.9583333333333334 | 0.967741935483871 |
| memory_precision_at_5 | 0.7741935483870968 | 0.7560975609756098 |
| top_k_noise_at_5 | 0.22580645161290325 | 0.24390243902439024 |
| noise_sources_at_5.broad_lexical_match | 5 | 7 |
| noise_sources_at_5.scope_mixed | 2 | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 |
| noise_relation_to_expected_at_5.expected_record_missing | 1 | 1 |
| noise_relation_to_expected_at_5.same_layer_scope_diff_topic | 5 | 7 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic | 1 | 2 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer_same_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer | 0 | 0 |
| abstain_pass_rate | 1.0 | 1.0 |
| abstain_false_positive_results | 0 | 0 |
| active_memory_suppression | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 |
| provenance_coverage.score | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |
| diagnostics.failure_types.recall_miss | 1 | 1 |
| diagnostics.failure_types.top_k_noise | 6 | 9 |

The strict gate command with the current v1.1 thresholds failed with
`memory_recall_at_5=0.9583333333333334`,
`memory_precision_at_5=0.7741935483870968`,
`top_k_noise_at_5=0.22580645161290325`, and
`noise_sources_at_5.broad_lexical_match=5`. The new relation buckets show the
dominant residual top-k noise shape is same-layer/same-scope/different-topic
neighbors, but the run also has `expected_record_missing=1` and one recall
miss. That is a probe/archive integrity blocker: a ranking change would mix
search-quality tuning with stale expected-memory evidence.

Decision: do not loosen the existing precision, recall, top-k noise, or
noise-source thresholds, and do not tune ranking until the private
expected-record drift is resolved. The public v1.1 strict and expanded
fail-over gates now include relation ceilings:

| metric | strict max | expanded max |
| --- | ---: | ---: |
| noise_relation_to_expected_at_5.expected_record_missing | 0 | 0 |
| noise_relation_to_expected_at_5.same_layer_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.same_layer_scope_diff_topic | 5 | 7 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic | 1 | 2 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer_same_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer | 0 | 0 |

This turns the new diagnostic into a gateable stop condition: future private
reruns must first restore `expected_record_missing=0`; only then should a
bounded ranking change target the remaining same-layer/same-scope/different-topic
residual noise.

## V1.1 Private Shadow Coverage Refresh

Date: 2026-07-06

Code point before this documentation update:
`3471b4f docs: align readiness evaluation with release gate`

This refresh reran the private real-archive shadow evaluation against the
existing strict v2 and expanded v3 redacted probes. The run used the read-only
shadow evaluator and wrote aggregate JSON under `/tmp`; the private archive
path, probe paths, raw case rows, queries, memory IDs, memory text, source refs,
source paths, raw refs, and full JSON reports were not copied into this
repository. Because the private deployment repository already had unrelated
archive working-tree changes, this refresh did not run the generated-answer
dogfood orchestrator, which would create private `.tmp`/`eval` artifacts.

Aggregate refresh results:

| metric | strict v2 | expanded v3 |
| --- | ---: | ---: |
| archive.memory_records | 1441 | 1441 |
| archive.legacy_session_records | 285 | 285 |
| probe_cases.cases | 27 | 34 |
| probe_cases.positive_cases | 24 | 31 |
| probe_cases.abstain_cases | 3 | 3 |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.8064516129032258 | 0.7804878048780488 |
| top_k_noise_at_5 | 0.19354838709677424 | 0.2195121951219512 |
| noise_sources_at_5.broad_lexical_match | 4 | 6 |
| noise_sources_at_5.scope_mixed | 2 | 3 |
| noise_sources_at_5.inactive_lifecycle | 0 | 0 |
| noise_sources_at_5.low_signal_memory_node | 0 | 0 |
| noise_relation_to_expected_at_5.expected_record_missing | 0 | 0 |
| noise_relation_to_expected_at_5.same_layer_scope_diff_topic | 5 | 7 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic | 1 | 2 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer_same_scope_topic | 0 | 0 |
| noise_relation_to_expected_at_5.diff_layer | 0 | 0 |
| abstain_pass_rate | 1.0 | 1.0 |
| abstain_false_positive_results | 0 | 0 |
| active_memory_suppression | 1.0 | 1.0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 |
| provenance_coverage.score | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |
| audit.status | passed | passed |
| diagnostics.failure_types.recall_miss | 0 | 0 |
| diagnostics.failure_types.top_k_noise | 5 | 8 |

Threshold audit:

| gate | result |
| --- | --- |
| strict v2 against `real_archive_shadow_v11.json` and `real_archive_shadow_v11_max.json` | passed with 0 threshold failures |
| expanded v3 against `real_archive_shadow_v11_coverage.json` and `real_archive_shadow_v11_coverage_max.json` | passed with 0 threshold failures |

Decision: the single next optimization category is ranking/noise reduction.
This refresh no longer supports probe/archive drift cleanup as the next step:
`expected_record_missing` is 0, `memory_recall_at_5` is 1.0 for both probes,
and there are no recall misses. It also does not point to lifecycle or
provenance repair: `lifecycle_integrity.score`,
`provenance_coverage.score`, privacy, abstention, suppression, and audit are
all green. The remaining measurable issue is top-k noise, concentrated in
broad lexical matches and scope-mixed neighbors, with relation buckets at the
current strict and expanded ceilings.

### Ranking/Noise Reduction Slice

Code point before this ranking change:
`6d4303a docs: refresh private shadow coverage evidence`

Hypothesis tested: once the highest-ranked memory hit has full
layer/scope/topic metadata, same-layer/different-topic tail hits are residual
ranking noise even when they share the anchor scope. The implementation keeps
missing-metadata tails and same-topic supporting memories, but no longer lets
same-scope/different-topic neighbors survive the relation tail pruning step.

Private real-archive aggregate before/after:

| metric | strict v2 before | strict v2 after | expanded v3 before | expanded v3 after |
| --- | ---: | ---: | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.8064516129032258 | 0.9230769230769231 | 0.7804878048780488 | 0.9117647058823529 |
| top_k_noise_at_5 | 0.19354838709677424 | 0.07692307692307687 | 0.2195121951219512 | 0.08823529411764708 |
| noise_sources_at_5.broad_lexical_match | 4 | 1 | 6 | 2 |
| noise_sources_at_5.scope_mixed | 2 | 1 | 3 | 1 |
| noise_relation_to_expected_at_5.same_layer_scope_diff_topic | 5 | 1 | 7 | 1 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic | 1 | 1 | 2 | 2 |
| noise_relation_to_expected_at_5.expected_record_missing | 0 | 0 | 0 | 0 |
| diagnostics.failure_types.top_k_noise | 5 | 2 | 8 | 3 |
| privacy_boundary_pass_rate | 1.0 | 1.0 | 1.0 | 1.0 |
| abstain_pass_rate | 1.0 | 1.0 | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 | 0 | 0 |
| active_memory_suppression | 1.0 | 1.0 | 1.0 | 1.0 |
| provenance_coverage.score | 1.0 | 1.0 | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 | 1.0 | 1.0 |

Decision: keep the ranking patch. It reduces private real-archive top-k noise
on both strict and expanded probes, improves precision, and preserves recall,
privacy, abstention, lifecycle, suppression, and provenance gates. The
remaining residual noise is now concentrated in same-topic cross-scope
neighbors and a small same-layer/same-scope/different-topic tail, so the next
ranking step should not add broader lexical heuristics unless a fresh
aggregate-only run shows a new dominant bucket.

### Residual Top-K Noise Classification Loop

Code point for the current classification pass:
`572b90b fix: prune same-layer memory topic noise`

This pass reran the strict v2 and expanded v3 private real-archive shadow
evaluations from the current implementation. The reports stayed outside this
repository and were used only for aggregate metrics and privacy-safe diagnostic
counts; no private probe cases, queries, memory IDs, memory text, source refs,
source paths, raw refs, or full JSON reports were copied into this repository.

Current residual aggregate:

| metric | strict v2 | expanded v3 |
| --- | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.9230769230769231 | 0.9117647058823529 |
| top_k_noise_at_5 | 0.07692307692307687 | 0.08823529411764708 |
| diagnostics.failure_types.top_k_noise | 2 | 3 |
| noise_sources_at_5.broad_lexical_match | 1 | 2 |
| noise_sources_at_5.scope_mixed | 1 | 1 |
| noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic | 1 | 2 |
| noise_relation_to_expected_at_5.same_layer_scope_diff_topic | 1 | 1 |
| noise_relation_to_expected_at_5.expected_record_missing | 0 | 0 |
| privacy_boundary_pass_rate | 1.0 | 1.0 |
| abstain_pass_rate | 1.0 | 1.0 |
| forbidden_output_violations | 0 | 0 |
| active_memory_suppression | 1.0 | 1.0 |
| provenance_coverage.score | 1.0 | 1.0 |
| lifecycle_integrity.score | 1.0 | 1.0 |

Decision: no implementation change in this pass. The residual failure set is
too small and not dominated by one safe pruning category: strict v2 is split
one-to-one between same-topic/cross-scope and same-scope/different-topic
relations, while expanded v3 has only a two-to-one relation skew. The
diagnostic source buckets are similarly split between broad lexical and
scope-mixed neighbors. The search runtime can see layer, scope, topic, score,
and ranking reasons, but it does not have the evaluator's expected-record
relation labels. A global prune of same-layer/different-scope/same-topic tails
would therefore risk deleting legitimate supporting memories, not just noise.

The next ranking change should wait for stronger aggregate evidence or a public
synthetic fixture that proves a safe runtime signal for same-topic/cross-scope
noise. Until then, the latest implementation remains the current clean cut.

### Same-Topic Cross-Scope Safety Fixture

Code point for the fixture addition:
this documentation update

The repository now includes a public synthetic shadow-eval fixture for
same-topic/cross-scope support and same-topic/cross-scope noise. The fixture
uses generated public marker text only; it does not depend on private archive
records, private probes, private queries, memory IDs from a deployment archive,
source paths, raw refs, or private source content.

Synthetic fixture result:

| scenario | expected aggregate behavior |
| --- | --- |
| same-topic/cross-scope support | two expected memories with the same layer and topic but different scopes are both counted as relevant; `noise_result_count=0` |
| same-topic/cross-scope noise | a same-layer/different-scope/same-topic neighbor that is not expected is counted as one top-k noise result with `noise_relation_to_expected_at_5.same_layer_diff_scope_same_topic=1` |
| abstain/privacy/suppression guard | the fixture keeps recall at 1.0 for positive cases, abstention passing for the negative case, suppression passing for an expected-not memory, and privacy aggregate output passing |

Decision: this fixture proves that the aggregate evaluator can distinguish
expected same-topic/cross-scope support from unexpected same-topic/cross-scope
noise when the case file supplies ground-truth expected memory IDs. This
fixture is not sufficient to justify a production ranking change, because the
search runtime still does not have that expected-record truth label. A future
ranking goal must first identify a runtime-visible signal, such as a stable
score/reason pattern, before pruning same-layer/different-scope/same-topic tail
hits.

### Same-Topic Cross-Scope Runtime-Signal Audit

Code point for the diagnostic addition:
this documentation update

The shadow evaluator now emits `runtime_signal_diagnostics_at_5` as an
aggregate-only diagnostic. For same-topic/cross-scope candidates it counts
support and noise classes separately, but only renders runtime-visible buckets:
relative score band, whitelisted reason-flag counters, source kind, confidence,
and support-count band. It does not render queries, case text, memory IDs,
memory text, source refs, source paths, raw refs, full `why` strings, scopes, or
topics.

Public synthetic fixture aggregate:

| class | count | relative score band | strict-token coverage | confidence | support-count band |
| --- | ---: | --- | ---: | --- | --- |
| support | 2 | `gte_99=2` | 2 | high=2 | `2_4=2` |
| noise | 1 | `gte_99=1` | 1 | high=1 | `2_4=1` |

Private real-archive aggregate rerun:

| metric | strict v2 | expanded v3 |
| --- | ---: | ---: |
| memory_recall_at_5 | 1.0 | 1.0 |
| memory_precision_at_5 | 0.9230769230769231 | 0.9117647058823529 |
| top_k_noise_at_5 | 0.07692307692307687 | 0.08823529411764708 |
| same-topic/cross-scope support count | 0 | 0 |
| same-topic/cross-scope noise count | 1 | 2 |
| noise relative score band | `gte_99=1` | `gte_99=2` |
| noise strict-token coverage | 0 | 0 |
| noise important-token coverage | 1 | 2 |
| noise field:text | 1 | 2 |
| noise field:topic | 1 | 1 |
| noise source kind | automatic=1 | automatic=2 |
| noise confidence | medium confidence=1 | medium confidence=2 |
| noise support-count band | support_count=1 | support_count=1 |

Decision: the private residual noise has a candidate runtime-visible pattern:
same-topic/cross-scope noise is near-tied with the top hit, automatic,
medium-confidence, support_count=1, and lacks strict-token coverage. This is
not yet sufficient for a ranking patch. The public fixture proves the evaluator
can expose the signal safely, but it also shows that same-topic/cross-scope
support can be high-signal and must not be globally pruned. A future ranking
goal would need a public RED/GREEN regression for the stricter candidate
pattern before changing production ranking.

### V1.2 Conservative Same-Topic Cross-Scope Ranking Gate

Date: 2026-07-07

Code points for the ranking patch:
`templates/agent-memory-repo/tools/search_memory.py`,
`skills/using-my-precious/scripts/search_memory.py`, and the synchronized
setup template copy.

Decision: the V1.2 change is accepted as a narrow ranking/noise reduction patch.
The search path now prunes a weak same-topic/cross-scope tail only after the
existing 99% relative-score floor and only when the later tail hit is a memory
hit with the same layer and topic as the top memory anchor, a different scope,
`source:automatic`, `confidence:medium`, `support_count:1`, and no
`strict-token-coverage` reason. It does not globally prune same-topic
cross-scope results: public fixtures keep high-confidence or strict-token
cross-scope support.

Public fail-first fixtures:

| fixture | RED behavior | GREEN behavior |
| --- | --- | --- |
| strong anchor plus weak cross-scope tail | weak tail remained in top-k | weak tail pruned; high/strict support kept |
| weak anchor plus second weak cross-scope tail | second weak tail remained in top-k | second weak tail pruned; high/strict support kept |

Private real-archive aggregate-only rerun after the patch:

| metric | strict v2 before | strict v2 after | expanded v3 before | expanded v3 after |
| --- | ---: | ---: | ---: | ---: |
| `memory_recall_at_5` | 1.0 | 1.0 | 1.0 | 1.0 |
| `memory_precision_at_5` | 0.9230769230769231 | 1.0 | 0.9117647058823529 | 1.0 |
| `top_k_noise_at_5` | 0.07692307692307687 | 0.0 | 0.08823529411764708 | 0.0 |
| same-topic/cross-scope support count | 0 | 0 | 0 | 0 |
| same-topic/cross-scope noise count | 1 | 0 | 2 | 0 |

`memory_recall_at_5` stayed 1.0 in both private shadow suites, while
`top_k_noise_at_5` dropped to 0.0. The private evidence remains aggregate-only:
the report does not render queries, case text, memory IDs, memory text, source
refs, source paths, raw refs, full `why` strings, scopes, or topics.

## V1 Evidence Convergence Snapshot

Date: 2026-07-01

Code point before this documentation update: `20c9380 fix: add archive search
health check`

This is a historical evidence convergence snapshot for the v1 goal. It does
not add new memory features. It records which evidence was green at that code
point, which existing aggregate reports were safe to use with the readiness
gate, and which claim boundaries remained.

Repository baseline before this documentation update:

| command | recorded result |
| --- | --- |
| `git status --short --branch` | `## main...origin/main [ahead 1]` |
| `git log --oneline --decorate -5` | latest local commit before this snapshot `20c9380 fix: add archive search health check`; latest remote commit `f835543 Merge pull request #7 from Dsssyc/codex/v1.1-shadow-relation-gates` |

Packaged core baseline:

```bash
python3 benchmarks/v1_readiness_gate.py --run-packaged
```

Result:

| metric | value |
| --- | ---: |
| overall_status | core_synthetic_ready |
| scorecard.required_dimensions | 4 |
| scorecard.required_passed | 4 |
| scorecard.optional_dimensions | 3 |
| scorecard.optional_passed | 0 |
| layered_recall.status | passed |
| automatic_induction.status | passed |
| e2e_induction_to_recall.status | passed |
| source_stream_registry.status | passed |

Optional evidence inventory:

| dimension | available aggregate evidence | privacy boundary | status | blocker |
| --- | --- | --- | --- | --- |
| packaged generated-answer eval | packaged synthetic fixture via `--run-packaged --require-answer` | aggregate-only; no queries, generated answers, or reference answers rendered | passed | none |
| public benchmark adapter | 100-case LongMemEval adapted layered report under `/tmp` | public-adapter aggregate report; no public raw benchmark records committed | passed in full gate | not a public leaderboard claim |
| private real-archive shadow eval | 2026-07-01 strict real-archive shadow aggregate under `/tmp` | aggregate-only; report declares no private probe cases, queries, memory IDs, memory text, source refs, source paths, raw refs, or source content rendered | passed in full gate | older 2026-06-29 `current` shadow report has passing metrics but lacks the stricter false privacy flags, so the current gate rejects that older report shape |
| private dogfood generated-answer eval | private deployment aggregate generated-answer benchmark report outside this repository | aggregate-only; no private queries, case IDs, reference answers, generated answers, memory IDs, source paths, raw refs, or memory text committed | passed in full gate | none |

Packaged generated-answer gate:

```bash
python3 benchmarks/v1_readiness_gate.py --run-packaged --require-answer
```

Result:

| metric | value |
| --- | ---: |
| overall_status | extended_evidence_ready |
| scorecard.required_dimensions | 5 |
| scorecard.required_passed | 5 |
| generated_answer_eval.status | passed |
| generated_answer_eval.case_pass_rate | 1.0 |
| generated_answer_eval.answer_normalized_match_rate | 1.0 |
| generated_answer_eval.abstention_accuracy | 1.0 |
| generated_answer_eval.answer_scorable_case_rate | 1.0 |
| generated_answer_eval.privacy_leak_count | 0 |

Full convergence gate:

```bash
python3 benchmarks/v1_readiness_gate.py \
  --run-packaged \
  --public-report /tmp/my_precious_public_limit_20260629/layered_report_100_raw_auth_gate.json \
  --shadow-report /tmp/my_precious_shadow_relation_strict_case24_retarget_20260701.json \
  --answer-report /path/to/private-agent-memory/.tmp/generated-answer-private-dogfood-20260630/generated_answer_private_dogfood_abstain_benchmark_20260630.json \
  --require-public \
  --require-shadow \
  --require-answer \
  --require-answer-source-benchmark MyPreciousPrivateDogfood \
  --require-answer-case-origin private_dogfood
```

The local run used the private deployment archive's existing aggregate answer
report at the placeholder path above. The report was not copied into this
repository.

Full convergence result:

| dimension | status | key metrics |
| --- | --- | --- |
| layered_recall | passed | `memory_recall_at_5=1.0`, `layer_path_success_rate=1.0`, `drilldown_success_rate=1.0`, `source_ref_reachability=1.0`, `privacy_leak_count=0` |
| automatic_induction | passed | `natural_induction_success_rate=1.0`, `cross_project_generalization_rate=1.0`, `forced_memory_capture_rate=1.0`, `induction_review_routing_rate=1.0`, `privacy_leak_count=0` |
| e2e_induction_to_recall | passed | `e2e_memory_recall_at_5=1.0`, `e2e_layer_assignment_accuracy=1.0`, `e2e_session_drilldown_rate=1.0`, `e2e_source_policy_pass_rate=1.0`, `privacy_leak_count=0` |
| source_stream_registry | passed | `source_stream_update_rate=1.0`, `project_registry_independence_rate=1.0`, `archive_scope_assignment_rate=1.0`, `source_stream_evidence_reachability_rate=1.0`, `privacy_leak_count=0` |
| public_benchmark_adapter | passed | `case_pass_rate=1.0`, `memory_recall_at_5=1.0`, `failed_case_count=0`, `source_benchmarks.LongMemEval=100`, `case_origins.public_benchmark_adapter=100` |
| real_archive_shadow_eval | passed | `memory_recall_at_5=1.0`, `memory_precision_at_5=0.8064516129032258`, `top_k_noise_at_5=0.19354838709677424`, `scope_mixed=2`, `inactive_lifecycle=0`, `privacy_boundary_pass_rate=1.0` |
| generated_answer_eval | passed | `case_pass_rate=1.0`, `answer_normalized_match_rate=1.0`, `abstention_accuracy=1.0`, `answer_scorable_case_rate=1.0`, `privacy_leak_count=0`, `source_benchmarks.MyPreciousPrivateDogfood=25`, `case_origins.private_dogfood=25` |

Full gate summary:

| metric | value |
| --- | ---: |
| overall_status | extended_evidence_ready |
| scorecard.required_dimensions | 7 |
| scorecard.required_passed | 7 |
| scorecard.optional_dimensions | 0 |
| scorecard.optional_passed | 0 |
| privacy.aggregate_only | true |
| privacy.private_probe_cases_rendered | false |
| privacy.queries_rendered | false |
| privacy.generated_answers_rendered | false |
| privacy.reference_answers_rendered | false |
| privacy.memory_text_rendered | false |
| privacy.source_paths_rendered | false |
| privacy.raw_refs_rendered | false |

This is the strongest current local v1 convergence state: packaged synthetic
core gates, explicit non-project source streams, a bounded public benchmark
adapter probe, private real-archive aggregate shadow evidence, and private
dogfood generated-answer aggregate evidence all pass through the same
readiness gate. The result still does not claim official public benchmark
leaderboard parity, live model answer quality, automatic ontology/source
discovery, multi-principal access governance, or solved long-horizon memory
decay/deletion behavior.

## Next Roadmap After The Minimum Slice

1. Strengthen automatic induction.
   V2.19 now gates the deterministic first slice: repeated/paraphrased
   induction facts can merge, contradictions are preserved, ambiguous scope
   narrowing routes to review, and process-noise promotion is blocked. The
   remaining work is live LLM induction quality and richer long-horizon
   consolidation, not another unbounded pile of convenience heuristics.

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
