# Using My Precious Skill Design

## Purpose

This repository is the development home for reusable agent-session memory
skills and deployment templates. It should not store real session memories.

The separate deployment repository is responsible for private archive data,
scheduled ingestion, summarization, indexes, and Git synchronization.

## Repository Boundary

`my-precious-skill` contains:

- the installable `setup-my-precious` setup-path skill
- the installable `update-my-precious` write-path skill
- the installable `using-my-precious` read-path skill
- generic search tooling
- archive format references
- deployment-repo templates
- tests and examples that use synthetic data only
- reusable utilities and templates that do not contain private memory data

The private deployment repository contains:

- real `sessions/`, `daily/`, `memories/`, and `index/` data
- `config/projects.jsonl`, the runtime project registry used by scheduled
  global updates
- ingestion and summarization configuration
- local scheduling such as launchd or cron
- Git remotes and credentials managed outside source files

`setup-my-precious` performs runtime setup actions against the private
deployment repository. It may create a local folder, initialize Git, connect a
private remote, and prepare scheduling only after a concrete archive command
exists. It must not run recurring jobs from this development repository.

`update-my-precious` performs on-demand write-path actions against the private
deployment repository. It scans a source record directory, uses the current
project path as the project scope and high-water-mark key, archives records
newer than the latest timestamp already archived for that project, refreshes a
previously archived source record when its current source hash changes, and
writes searchable summaries plus short redacted evidence snippets.

## Generality

The skills are intentionally agent-neutral. A compatible archive may be
produced by any runtime that can provide summarized sessions, evidence snippets,
and JSONL indexes.

## Components

- `skills/using-my-precious/SKILL.md`: tells future agents when and how to
  search memory.
- `skills/using-my-precious/scripts/search_memory.py`: dependency-free
  fallback search script bundled with the skill. It uses hybrid lexical ranking
  over JSONL indexes, summaries, and optional evidence files, with explicit
  reasons for structured-field matches, exact phrase coverage, important token
  coverage, and optional current-project context.
- `skills/using-my-precious/references/archive-format.md`: stable archive
  contract for compatible deployment repos.
- `memories/*.jsonl` and `index/memories.jsonl`: layered memory nodes induced
  from sessions or created from explicit memory requests. These nodes make
  global, domain, and project memories first-class recall targets while keeping
  sessions as event-level evidence.
- `skills/setup-my-precious/SKILL.md`: asks the user how to store the archive
  and scaffolds a local or hosted-Git-backed deployment repository.
- `skills/setup-my-precious/scripts/setup_memory_archive.py`: copies the
  bundled archive template and optionally initializes Git/remote hosting.
- `skills/update-my-precious/SKILL.md`: archives new source records for the
  current project into the deployment repository.
- `skills/update-my-precious/scripts/update_memory_archive.py`: generic
  incremental updater keyed by `project_path` and source-record timestamps,
  with deterministic summary rendering, source maps, daily summaries, JSONL
  indexes, and default refusal for source records that match secret patterns.
- `benchmarks/updater_induction_benchmark.py`: synthetic write-path benchmark
  that drives the real setup and updater scripts from temporary source records
  and reports aggregate induction, lifecycle, provenance, and privacy metrics.
- `benchmarks/e2e_induction_recall_benchmark.py`: synthetic end-to-end
  benchmark that drives setup, updater, generated memory indexes, layered
  recall scoring, and the copied search script without rendering private case
  details.
- `templates/agent-memory-repo/tools/render_scheduler.py`: renders reviewable
  launchd or cron scheduler configuration and agent-native automation prompts
  without installing or enabling them.
- `templates/agent-memory-repo/tools/run_memory_updates.py`: global runner that
  bootstraps an empty project registry by scanning source records for project
  paths, then invokes the per-project updater for each enabled project.
- `templates/agent-memory-repo/tools/induction_consolidation_audit.py`:
  privacy-safe read-only audit for automatic induction, lifecycle consolidation,
  evidence reachability, and aggregate real-history output safety.
- `templates/agent-memory-repo/tools/apply_memory_review_decisions.py`:
  aggregate-only dry-run/apply tool that reads private lifecycle review
  decisions and converts approved decisions into reciprocal memory links.
- `templates/agent-memory-repo/tools/sync_memory_archive.py`: safe Git sync
  helper that stages only generated archive paths and refuses unexpected files
  or unredacted key-like values.
- `templates/agent-memory-repo/`: starter private archive repository layout.

## Scheduling Model

Default scheduled updates should call `tools/run_memory_updates.py`, not the
single-project updater. The runner reads `config/projects.jsonl`, scans the
shared source-record directory for project metadata, registers newly discovered
projects, and updates each enabled project. This avoids a bootstrap deadlock
where an empty deployment repository has no project registry and therefore no
scheduled work.

`config/projects.jsonl` is runtime configuration, while `index/projects.jsonl`
is a generated archive index. Disabled projects in `config/projects.jsonl` must
remain disabled even if source records still mention them.

Agent-native automations should use exactly one working directory: the private
deployment repository. Multiple working directories can create multiple
concurrent automation conversations for the same scheduled job.

## Environment Contract

`setup-my-precious` writes the archive location to
`~/.config/my-precious/config.json` by default. Environment variables are
overrides for current shells, automation, or hosted runtimes.
The config file should be written with private file permissions when the local
platform supports them.

GitHub-backed setup should refuse to publish preexisting Git history unless the
user explicitly confirms that history has been reviewed.

Agents locate a deployment repository using these inputs in order:

1. explicit command argument
2. colocated deployment repository when the script runs from one
3. `AGENT_SESSION_MEMORY_REPO`
4. `AGENT_MEMORY_REPO`
5. `MY_PRECIOUS_CONFIG` or `AGENT_SESSION_MEMORY_CONFIG`
6. `~/.config/my-precious/config.json`

If none are set, tools may try `~/repos/agent-memory`.

## Non-Goals

- Do not commit real raw transcripts to this repository.
- Do not run scheduled archive jobs from this repository.
- Do not add vector search before JSONL and Markdown hybrid lexical search are
  reliable and explainable.
- Do not store user-specific scheduler config, credentials, or generated memory
  data in this repository.

## Implementation Phases

1. Build the generic setup, write-path, and read-path skills.
2. Add a deployment repository template with privacy-first defaults.
3. Add synthetic tests for setup, update, search, and archive-format assumptions.
4. Later, implement source-agent-specific archive writers in the deployment
   repository or as optional adapters.

## Acceptance Criteria

- All skills validate as skills.
- The search script works against a synthetic archive.
- The setup script creates a synthetic local archive.
- The update script archives source records newer than the latest timestamp for
  the same project path and refreshes previously archived source records whose
  source hash changed.
- The update script generates searchable summaries and refuses likely-secret
  source records by default.
- The update script can require explicit project metadata when scanning shared
  source record directories.
- The global runner can bootstrap an empty project registry from source records
  and respects disabled registry entries.
- The update script writes `source-map.json`, daily summaries, and JSONL indexes.
- The template can render global-runner and single-project scheduler
  configuration without enabling recurring jobs.
- The template can render agent-native automation prompts that use one working
  directory, run the global updater, verify search, and call the safe Git sync
  helper.
- The safe Git sync helper refuses non-archive changes, unredacted key-like
  values, and whitespace errors before committing or pushing.
- The template repository contains no real memory data.
- The design keeps skill development separate from private deployment.

## Benchmark Evaluation Model

The layered recall benchmark evaluates the read path as a provenance-grounded
memory system, not as a direct leaderboard comparison against systems that
store verbatim transcript embeddings.

Positive cases check whether the correct high-level memory appears at rank 1 or
within the top 5, whether the memory can drill down to the supporting session,
what fraction of returned top-5 memory hits match the expected memory, whether
required evidence paths are reachable from the expected memory, and whether
source refs are available on the expected memory's `source: memory` block at
source depth without rendering raw source paths or content by default. Cases
with `reference_answer` also check whether the exact answer
snippet is reachable in expected-memory memory/source output or the expected
summary session output. These metrics are reported as `memory_recall_at_1`,
`memory_recall_at_5`,
`memory_precision_at_5`, `memory_micro_precision_at_5`,
`memory_result_count_at_5`, `memory_relevant_count_at_5`,
`memory_noise_count_at_5`, `top_k_noise_at_5`, `memory_mrr`,
`memory_ndcg_at_5`, `memory_ranked_cases`, `memory_rank_missing_cases`,
`memory_rank_mean`, `memory_rank_median`, `memory_rank_histogram`,
`memory_explainability_cases`, `memory_explainability`,
`layer_calibration_cases`, `layer_calibration`, `layer_path_success_rate`,
`scope_filter_cases`, `scope_filter_recall`, `wrong_scope_suppression_cases`,
`wrong_scope_suppression`,
`session_drilldown_at_5`, `drilldown_success_rate`, `evidence_reachability`,
`evidence_text_cases`, `evidence_text_reachability`, `source_reachability`,
`source_ref_reachability`, `source_depth_policy_pass_rate`,
`raw_preview_redaction_pass_rate`, `source_drilldown_privacy_pass_rate`,
`answer_reachability`, `answer_normalized_reachability`, `answer_token_f1`,
`lifecycle_supersession_cases`, `lifecycle_supersession_reciprocity`,
`abstain_pass_rate`, `suppression_pass_rate`, `privacy_leak_count`,
`latency_ms`, `latency_mean_ms`, `latency_max_ms`, `failed_case_count`, and
`case_pass_rate`. Exact answer
reachability is strict text reachability. Normalized reachability ignores case
and punctuation. `memory_precision_at_5` is a returned-result purity metric:
for each positive case, the benchmark divides matching expected-memory hits by
the returned memory hits in the top-5 cutoff, then macro-averages those per-case
scores. `memory_micro_precision_at_5` divides summed relevant-memory hits by
summed returned-memory hits. The related count fields report those summed
returned-memory, relevant-memory, and noise hits; `top_k_noise_at_5` is the
aggregate non-relevant top-5 memory-hit ratio. `memory_explainability` measures
whether ranked expected-memory hits carry high-signal `why:` reasons such as
structured field matches, phrase matches, important token coverage, or project
context, while rejecting low-signal-only or broad-field-only explanations.
`source_precision_at_5` counts all top-5 returned source refs in the
denominator, but only available refs on the expected memory's `source: memory`
block are relevant. `source_ref_reachability` checks the stable source ref ID
derived from `expected_source_anchor`; `source_depth_policy_pass_rate` checks
that source-depth output uses `source_ref_id`, `status`, and `reason` fields
instead of legacy raw anchor rendering; `raw_preview_redaction_pass_rate` checks
explicit `--raw-source-preview all` output; and
`source_drilldown_privacy_pass_rate` checks source-depth plus preview output
against forbidden private or secret-like patterns.
`layer_calibration` measures whether cases that declare `expected_layer` return
the expected memory from the requested `global`, `domain`, or `project` layer.
`scope_filter_recall` reruns those `expected_layer` cases with
`search_memory.py --scope <expected_layer>` and checks that the expected memory
is still reachable with a returned memory layer matching the requested scope.
`wrong_scope_suppression` runs the same cases against the other memory layers
and checks that the expected memory is not returned from an incorrect scope.
Token F1 uses the best contiguous output-token window against the reference
answer. `memory_ndcg_at_5` is a rank-sensitive top-5 metric: a rank-1 expected
memory scores 1.0, lower ranks decay by the standard discounted-gain curve, and
misses beyond rank 5 score 0.
The rank distribution fields report how many positive cases were ranked at all,
how many were missing, mean and median rank for ranked hits, and a compact
histogram for ranks 1 through 5, ranks beyond 5, and misses.
These are retrieval-side checks, not generated-answer semantic grading. The
aggregate payload and each category payload also include
denominator counts such as `positive_cases`, `answer_cases`, and `stale_cases`
so zero-denominator metrics can be distinguished from measured failures.
Aggregate payloads include `cases_path`, `cases_sha256`, `search_script_path`,
and `search_script_sha256` so score reports identify the exact case file and
search implementation used for a run.
Search treats source anchors as untrusted display data. Source depth reports
safe status metadata by default; unsafe paths or sensitive-looking anchor text
are rendered as `[unsafe-source-ref]` instead of being printed verbatim. Unsafe
memory metadata fields are rendered as `[unsafe-field]` so archive records
cannot inject extra output lines.

Reliability cases check long-memory behaviors inspired by LongMemEval, LOCoMo,
Memora, and long-context retrieval stress tests:

- `abstention_accuracy`: no memory is returned when a query is unsupported,
  including default memory/session/source search and scoped memory searches for
  each `global`, `domain`, and `project` layer. Abstention outputs must be empty
  or explicit `No memory hits for:` responses; unstructured non-no-hit text fails
  the check even when it contains no parseable hit block.
- `negative_memory_suppression`: explicitly forbidden memory IDs are absent from
  all executed hit blocks, including scoped memory searches.
- `stale_memory_suppression`: superseded memory IDs are absent from all executed
  hit blocks, including scoped memory searches.
- `update_consistency`: the latest expected memory is found while stale memory
  is suppressed.
- `lifecycle_supersession_reciprocity`: the current memory lists every stale
  memory ID in `supersedes`, and each stale memory points back through
  `superseded_by`.
- `reviews/memory_lifecycle_decisions.jsonl` is the private, manually reviewed
  input surface for ambiguous lifecycle candidates. It is not generated by the
  reusable skill repository, and dry-run/apply reports expose aggregate status
  counts rather than memory text or source paths.
- `privacy_boundary_pass_rate`: configured forbidden output patterns, such as
  raw transcript or secret-like snippets, are not printed.

Search treats memory records with a non-empty `superseded_by` field as
inactive. The synthetic archive builder can add superseded distractor records
with strong query overlap so `stale_memory_suppression` and
`update_consistency` exercise that behavior instead of only testing clean
indexes. The packaged synthetic quality gate uses those distractors to measure
`lifecycle_supersession_cases` and `lifecycle_supersession_reciprocity`
directly.

Benchmark case files are JSONL. Positive cases require `query`,
`expected_memory_id`, `expected_summary_path`, and `expected_source_anchor`.
Optional fields include `category`, `source_benchmark`,
`case_id`, `required_evidence_paths`, `reference_answer`,
`reference_evidence`,
`expected_not_memory_id`, `stale_memory_id`, `temporal_scope`, and
`forbidden_output_patterns`.
`forbidden_output_patterns` values are Python regular expressions matched
against combined memory, session, source, and explicit raw-preview output.
`privacy_leak_count` also treats generic secret-like output identifiers as
leaks even when a case does not configure explicit forbidden patterns.
When present, `case_id` must be unique within the case file.
Abstention cases use `expected_abstain: true` and do not require positive
expected fields.

The benchmark can also write per-case details as JSONL, including a
`case_pass` boolean, precision count fields, and `failed_checks` list for each
case, source benchmark, temporal scope, stale or negative memory IDs, stable
case IDs when provided, required evidence paths, and forbidden-pattern counts.
Returned memory ID diagnostics are taken only from `source: memory` hit blocks;
source diagnostics report returned source ref IDs after sanitization.
When present, `reference_evidence` is checked against required evidence files
with exact-text reachability and is counted by `evidence_text_cases`.
Details also include safe returned identifiers such as memory result IDs,
session paths, and source ref IDs, but avoid returned hit titles, snippets, raw
source paths, raw `reference_answer`, raw `reference_evidence`, and
`forbidden_output_patterns` text. Sensitive-looking or
control-character-bearing returned identifiers are rendered as
`[unsafe-result-identifier]`. The benchmark can also write structured
threshold failures with `--failures-json`; that failure file includes the same
case-set and search-script fingerprints as stdout, the aggregate
`failed_case_count` and `case_pass_rate`, plus safe per-case failure summaries
(`case_id`, line number, category, source benchmark, failed check names, memory
rank, recall flags, session drilldown status, and source reachability status)
so CI artifacts remain traceable without copying queries or answer text. The
benchmark can enforce numeric lower-bound thresholds with
`--fail-under` and upper-bound thresholds, such as latency caps, with
`--fail-over`; for example, `--fail-over failed_case_count=0` rejects any case
with one or more failed checks.
Thresholds can target top-level metrics or dotted category paths such as
`categories.knowledge_update.update_consistency=1.0`. `--fail-under-file` and
`--fail-over-file` load thresholds from JSON objects for repeatable CI gates;
direct `--fail-under` or `--fail-over` arguments override duplicate metric keys
from files. All threshold values must be finite numbers; NaN and Infinity are
rejected before comparison. Threshold failures keep the aggregate JSON on
stdout and report the failed metrics on stderr so automated quality gates can
preserve machine-readable scores. Structured threshold failure entries include a
`comparison` field set to `below` or `above`. Each depth-specific search
subprocess has a default timeout of 30 seconds; use finite positive
`--search-timeout-s` values to raise that limit for large local archives or
lower it for CI smoke tests.
The packaged synthetic gates intentionally split lower-bound and upper-bound
checks: `benchmarks/quality-gates/layered_recall_synthetic.json` covers the
synthetic suite dimensions, rank coverage, evidence-text reachability, answer
reachability, lifecycle supersession reciprocity, layer path and drilldown
success, broad lexical noise resistance, pass-rate metrics, and denominator
counts, while
`benchmarks/quality-gates/layered_recall_synthetic_max.json` enforces upper
bounds such as `failed_case_count=0`, `memory_rank_missing_cases=0`,
`top_k_noise_at_5=0`, `privacy_leak_count=0`, and rank mean/median caps.
Additional answer-metric gates should be added to custom threshold files for
case sets with broader `reference_answer` coverage.

## Updater-Driven Induction Benchmark

`benchmarks/updater_induction_benchmark.py` evaluates the write path rather than
the read path. The runner creates temporary synthetic source records, uses
`skills/setup-my-precious/scripts/setup_memory_archive.py` to scaffold a
temporary archive, then invokes the deployed template's
`tools/update_memory_archive.py`. This exercises the same path a deployment
archive uses:

1. `extract_source_events()` reads JSONL source events.
2. `summarize_events()` extracts durable facts, decisions, evidence snippets,
   and explicit memory directives.
3. `write_record()` writes `summary.md`, `evidence.md`, `meta.json`,
   `redactions.md`, and `source-map.json`.
4. `build_memory_nodes()` promotes automatic memories from `reusable_facts`,
   writes explicit memories from source-record directives, assigns
   `global`/`domain`/`project` layers, attaches evidence/source references, and
   applies supersede, contradict, and deprecate lifecycle links.
5. `write_memory_nodes()` and `rebuild_indexes()` write the searchable
   `memories/*.jsonl` and `index/*.jsonl` surfaces.

The synthetic case file is
`benchmarks/cases/updater_induction_synthetic.jsonl`. Each JSONL row is one
scenario with safe `case_id`, `category`, `records`, `expected_memories`, and
optional `expected_lifecycle_links`, `expected_privacy_refusal`, or
`expected_redaction` fields. Natural-induction v2 cases may also set
`natural_induction: true` on expected automatic memories, set
`cross_project_generalization: true` when repeated support across synthetic
projects must become a `domain` memory, set `project_scope_precision: true`
when a single-project rule must remain `project` scoped, provide
`expected_review_candidates` for ambiguous semantic lifecycle candidates, and
provide `expected_noise_rejections` for process chatter that must not become a
memory node. `records` contain synthetic `role`/`content` events and a
synthetic `project_key`; the runner maps those keys to temporary local paths at
runtime. Secret-like fixtures are represented with placeholders such as
`{{OPENAI_KEY}}` or `{{AUTHORIZATION_BEARER}}` and expanded only inside the
temporary source records.

The runner reports aggregate-only JSON. It does not render case details, source
content, memory text, source paths, or raw refs. Core metrics are
`induction_success_rate`, `natural_induction_success_rate`,
`cross_project_generalization_rate`, `project_scope_precision`,
`ambiguous_candidate_review_rate`, `process_noise_rejection_rate`,
`layer_assignment_accuracy`, `evidence_retention_rate`,
`source_ref_policy_pass_rate`,
`lifecycle_link_accuracy`, `forced_memory_capture_rate`,
`privacy_refusal_pass_rate`, `privacy_redaction_pass_rate`,
`privacy_leak_count`, `failed_case_count`, and `case_pass_rate`. The packaged
gates in `benchmarks/quality-gates/updater_induction_synthetic.json` and
`benchmarks/quality-gates/updater_induction_synthetic_max.json` require all
pass-rate metrics to remain at 1.0 and `privacy_leak_count` to remain 0.

## End-To-End Induction-To-Recall Benchmark

`benchmarks/e2e_induction_recall_benchmark.py` evaluates the minimum complete
memory path:

1. write synthetic source records to a temporary source directory;
2. run `setup_memory_archive.py`;
3. run the deployed template's `tools/update_memory_archive.py`;
4. resolve generated memory IDs, summary paths, evidence refs, and source refs
   from `index/memories.jsonl`;
5. derive temporary layered recall cases; and
6. score them with `benchmarks/layered_recall_benchmark.py` and the generated
   archive's copied `tools/search_memory.py`.

The packaged case file is
`benchmarks/cases/e2e_induction_recall_synthetic.jsonl`. It uses the same
source-record shape as the updater-driven benchmark, but each active
`expected_memories` entry must also include:

- `recall_query`: the query used for the read-path check;
- `layer`: the expected generated memory layer;
- `expect_evidence_drilldown: true`; and
- `expect_source_policy: true`.

Lifecycle target memories that should be inactive are represented through
`expected_lifecycle_links`, not as active recall expectations. The e2e runner
turns those links into suppression probes against the real memory search path,
so supersede, contradict, and deprecate behavior are measured without treating
retired nodes as successful active recall targets.

The aggregate JSON report maps the underlying recall benchmark fields into
goal-level metrics:

- `natural_induction_success_rate`
- `cross_project_generalization_rate`
- `project_scope_precision`
- `ambiguous_candidate_review_rate`
- `process_noise_rejection_rate`
- `e2e_memory_recall_at_1` and `e2e_memory_recall_at_5`
- `e2e_layer_assignment_accuracy`
- `e2e_session_drilldown_rate`
- `e2e_evidence_reachability_rate`
- `e2e_source_policy_pass_rate`
- `e2e_lifecycle_active_suppression_rate`
- `e2e_forced_memory_recall_rate`
- `privacy_leak_count`

The quality gates in
`benchmarks/quality-gates/e2e_induction_recall_synthetic.json` and
`benchmarks/quality-gates/e2e_induction_recall_synthetic_max.json` keep every
pass-rate metric at 1.0, `failed_case_count` at 0, and `privacy_leak_count` at
0.

`shadow_eval_memory_archive.py` is the privacy-safe real-archive regression
runner. Its probe case contract is intentionally narrower than the synthetic
benchmark schema: `expected_memory_id` names one acceptable memory node,
`expected_memory_ids` names several acceptable memory nodes for duplicate or
overlapping real-history answers, `expected_layer` acts as a soft preferred
layer, `expected_not_memory_id` checks active-memory suppression,
`expected_abstain: true` checks no-hit behavior, and
`forbidden_output_patterns` names private or secret-like regular expressions
that must not appear in audit or search subprocess output. Abstain cases pass
only when no memory hits are returned; false-positive hit counts are reported
as aggregate metrics. Probe cases may live in a private deployment repository
or another local private path, but private probe files, raw transcripts, memory
text, source paths, and source records must not be committed to this reusable
skill repository. The shadow runner can
enforce aggregate numeric gates with `--fail-under`, `--fail-over`,
`--fail-under-file`, and `--fail-over-file`; metric keys may be top-level
metric names such as `memory_recall_at_5` or dotted paths such as
`metrics.provenance_coverage.score`. Unlike the synthetic benchmark, a shadow
threshold failure does not print the aggregate JSON report; stderr only lists
the failed metric name, actual value, comparison, and threshold.

The public benchmark converter maps locally downloaded LongMemEval, LoCoMo, or
Memora JSON/JSONL files into the same case schema. It generates deterministic
external memory IDs, stable case IDs, and source anchors. Its stdout reports
the converted case count plus input and output SHA-256 fingerprints so dry-run
artifacts can be traced to exact files. It rejects duplicate converted
`case_id` values, non-object question or evaluation rows, and empty converted
case sets before writing output. Evidence lists must contain non-empty strings.
The converter does not download benchmark data or commit external records to
this reusable skill repository.
For adapter dry-runs,
the converter can also build a temporary synthetic archive from the converted
cases with `--build-synthetic-archive`; that archive is then scored by the same
layered recall benchmark and `--fail-under` quality gates as packaged synthetic
cases.

The packaged `benchmarks/cases/layered_recall_synthetic.jsonl` file contains
synthetic cases only. External public benchmark downloads or private archive
records should not be committed to this repository; they can be locally mapped
to the same JSONL schema for evaluation.
