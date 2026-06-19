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
- `templates/agent-memory-repo/tools/render_scheduler.py`: renders reviewable
  launchd or cron scheduler configuration and agent-native automation prompts
  without installing or enabling them.
- `templates/agent-memory-repo/tools/run_memory_updates.py`: global runner that
  bootstraps an empty project registry by scanning source records for project
  paths, then invokes the per-project updater for each enabled project.
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
whether required evidence paths are reachable, and whether source anchors are
available at source depth. Cases with `reference_answer` also check whether the
exact answer snippet is reachable in memory, session, or source output. These
metrics are reported as `memory_recall_at_1`, `memory_recall_at_5`,
`memory_mrr`, `session_drilldown_at_5`, `evidence_reachability`,
`source_reachability`, `answer_reachability`,
`answer_normalized_reachability`, `answer_token_f1`, `latency_ms`,
`latency_mean_ms`, `latency_max_ms`, `failed_case_count`, and
`case_pass_rate`. Exact answer
reachability is strict text reachability. Normalized reachability ignores case
and punctuation. Token F1 uses the best contiguous output-token window against
the reference answer. These are retrieval-side checks, not generated-answer
semantic grading. The aggregate payload and each category payload also include
denominator counts such as `positive_cases`, `answer_cases`, and `stale_cases`
so zero-denominator metrics can be distinguished from measured failures.
Aggregate payloads include `cases_path`, `cases_sha256`, `search_script_path`,
and `search_script_sha256` so score reports identify the exact case file and
search implementation used for a run.

Reliability cases check long-memory behaviors inspired by LongMemEval, LOCoMo,
Memora, and long-context retrieval stress tests:

- `abstention_accuracy`: no memory is returned when a query is unsupported.
- `negative_memory_suppression`: explicitly forbidden memory IDs are absent.
- `stale_memory_suppression`: superseded memory IDs are absent.
- `update_consistency`: the latest expected memory is found while stale memory
  is suppressed.
- `privacy_boundary_pass_rate`: configured forbidden output patterns, such as
  raw transcript or secret-like snippets, are not printed.

Search treats memory records with a non-empty `superseded_by` field as
inactive. The synthetic archive builder can add superseded distractor records
with strong query overlap so `stale_memory_suppression` and
`update_consistency` exercise that behavior instead of only testing clean
indexes.

Benchmark case files are JSONL. Positive cases require `query`,
`expected_memory_id`, `expected_summary_path`, and `expected_source_anchor`.
Optional fields include `category`, `source_benchmark`,
`case_id`, `required_evidence_paths`, `reference_answer`,
`expected_not_memory_id`, `stale_memory_id`, `temporal_scope`, and
`forbidden_output_patterns`.
When present, `case_id` must be unique within the case file.
Abstention cases use `expected_abstain: true` and do not require positive
expected fields.

The benchmark can also write per-case details as JSONL, including a
`failed_checks` list for each case, source benchmark, temporal scope, stale or
negative memory IDs, stable case IDs when provided, required evidence paths,
and forbidden-pattern counts. Details also include safe returned identifiers
such as memory result IDs, session paths, and source anchors, but avoid
returned hit titles, snippets, raw `reference_answer`, and
`forbidden_output_patterns` text. The benchmark can also write structured
threshold failures with `--failures-json`; that failure file includes the same
case-set and search-script fingerprints as stdout plus safe per-case failure
summaries (`case_id`, line number, category, source benchmark, and failed
check names) so CI artifacts remain traceable without copying queries or
answer text. The benchmark can enforce numeric lower-bound thresholds with
`--fail-under` and upper-bound thresholds, such as latency caps, with
`--fail-over`; for example, `--fail-over failed_case_count=0` rejects any case
with one or more failed checks.
Thresholds can target top-level metrics or dotted category paths such as
`categories.knowledge_update.update_consistency=1.0`. `--fail-under-file` and
`--fail-over-file` load thresholds from JSON objects for repeatable CI gates;
direct `--fail-under` or `--fail-over` arguments override duplicate metric keys
from files. Threshold failures keep the aggregate JSON on stdout and report the
failed metrics on stderr so automated quality gates can preserve
machine-readable scores.
The packaged synthetic gates intentionally split lower-bound and upper-bound
checks: `benchmarks/quality-gates/layered_recall_synthetic.json` covers the
synthetic suite dimensions, answer reachability, and denominator counts, while
`benchmarks/quality-gates/layered_recall_synthetic_max.json` enforces upper
bounds such as `failed_case_count=0`. Additional answer-metric gates should be
added to custom threshold files for case sets with broader `reference_answer`
coverage.

The public benchmark converter maps locally downloaded LongMemEval, LoCoMo, or
Memora JSON/JSONL files into the same case schema. It generates deterministic
external memory IDs, stable case IDs, and source anchors. It rejects duplicate
converted `case_id` values and empty converted case sets before writing output,
but does not download benchmark data or commit external records to this reusable
skill repository.
For adapter dry-runs,
the converter can also build a temporary synthetic archive from the converted
cases with `--build-synthetic-archive`; that archive is then scored by the same
layered recall benchmark and `--fail-under` quality gates as packaged synthetic
cases.

The packaged `benchmarks/cases/layered_recall_synthetic.jsonl` file contains
synthetic cases only. External public benchmark downloads or private archive
records should not be committed to this repository; they can be locally mapped
to the same JSONL schema for evaluation.
