# My Precious Skill

English | [简体中文](README.zh-CN.md)

`my-precious-skill` is a development repository for generic agent session memory skills.

- `setup-my-precious` initializes or connects a private memory archive.
- `update-my-precious` scans new source records and writes fresh memory entries.
- `using-my-precious` searches an existing private memory archive.
- Layered global, domain, and project memory nodes drill down to sessions,
  evidence, and source anchors.

This repository does not store real historical sessions, run production archive schedules, or push private memory data. It only stores reusable skill files, search tooling, archive-format contracts, deployment templates, and synthetic tests.

## What It Solves

When a future agent task depends on:

- previous conversations
- prior agent work
- historical implementation decisions
- unresolved follow-up tasks
- user preferences and project conventions
- old debugging context

the agent can use `$using-my-precious` to search a private session memory archive instead of guessing from vague context. If no archive exists yet, use `$setup-my-precious` first. To capture new records immediately, use `$update-my-precious`.

## Design

`setup-my-precious` is the setup-path skill. It asks how the archive should be stored, scaffolds a local archive folder, and can connect it to a private hosted Git repository when requested.

`update-my-precious` is the write-path skill. It scans a source record directory, uses the current project path as the project scope, writes records newer than the latest archived timestamp for that project, and refreshes a previously archived source record when its source hash changes.

`using-my-precious` is the read-path skill. It only requires a deployment repository with stable Markdown summaries and JSONL indexes.

The repository includes generic setup, update, search, safe Git-sync, and scheduler-template tooling. Source-specific ingestion adapters, credentials, enabled schedules, and private generated data still belong in the private deployment repository or optional adapters.

## Repository Layout

```text
my-precious-skill/
  AGENTS.md
  README.md
  README.zh-CN.md
  docs/
    design.md
  skills/
    setup-my-precious/
      SKILL.md
      agents/openai.yaml
      assets/agent-memory-repo/
      scripts/setup_memory_archive.py
    update-my-precious/
      SKILL.md
      agents/openai.yaml
      scripts/update_memory_archive.py
    using-my-precious/
      SKILL.md
      agents/openai.yaml
      references/archive-format.md
      scripts/search_memory.py
  templates/
    agent-memory-repo/
      AGENTS.md
      INDEX.md
      README.md
      .gitignore
      config/
      memories/
      index/
      daily/
      sessions/
      prompts/summarize_session.prompt.md
      schemas/memory_node.schema.json
      schemas/session_summary.schema.json
      tools/search_memory.py
      tools/update_memory_archive.py
      tools/induction_consolidation_audit.py
      tools/run_memory_updates.py
      tools/audit_memory_archive.py
      tools/backfill_memory_archive.py
      tools/render_scheduler.py
      tools/sync_memory_archive.py
  tests/
    test_audit_memory_archive.py
    test_search_memory.py
    test_run_memory_updates.py
    test_setup_memory_archive.py
    test_sync_memory_archive.py
    test_update_memory_archive.py
```

## Point An Agent At This Repository

Give this repository URL to an agent that supports skill repositories:

```text
https://github.com/Dsssyc/my-precious-skill
```

The repository contains the `setup-my-precious`, `update-my-precious`, and
`using-my-precious` skills under `skills/`. A capable agent or skill installer
can discover them from the repository URL.

## Use The Skill

Set up an archive:

```text
$setup-my-precious create a local private memory archive
```

```text
$setup-my-precious create a private hosted Git repository for my memory archive
```

Update an archive now:

```text
$update-my-precious scan the current project's new session records and update memory
```

```text
$update-my-precious archive new records from /path/to/session-records for this project
```

Search an archive:

```text
$using-my-precious find prior decisions about the migration strategy
```

```text
$using-my-precious search my historical agent memory for why raw transcripts should not be uploaded by default
```

```text
$using-my-precious find previous context about the production incident investigation
```

`$setup-my-precious` records the archive location in
`~/.config/my-precious/config.json` by default. The environment variable is an
override for current shells and automation, not the primary setup mechanism.
The config file is written with private file permissions when the platform
supports them.

The tools locate the private deployment repository in this order:

1. explicit command argument such as `--repo` or `--memory-repo`
2. a colocated deployment repository when the script runs from one
3. `AGENT_SESSION_MEMORY_REPO`
4. `AGENT_MEMORY_REPO`
5. `MY_PRECIOUS_CONFIG` or `AGENT_SESSION_MEMORY_CONFIG`
6. `~/.config/my-precious/config.json`
7. `~/repos/agent-memory`

Optional current-shell override:

```bash
export AGENT_SESSION_MEMORY_REPO="$HOME/repos/agent-memory"
```

## Create A Private Deployment Repository

The recommended path is to let `$setup-my-precious` ask for the storage mode and scaffold the repository. Manual setup is also possible:

Copy the template into a separate private repository:

```bash
REPO="/path/to/my-precious-skill"
MEMORY_REPO="$HOME/repos/agent-memory"

mkdir -p "$MEMORY_REPO"
rsync -a "$REPO/templates/agent-memory-repo/" "$MEMORY_REPO/"

cd "$MEMORY_REPO"
git init
```

If using a private hosted Git repository, create it with your normal Git hosting workflow and push this deployment repository there. Keep credentials out of repository files, shell history, logs, and generated summaries. If the local archive folder already has Git history, review it before pushing; the setup helper refuses to publish preexisting history unless `--allow-existing-history` is explicitly passed.

The deployment repository is where real memory data belongs:

```text
agent-memory/
  config/projects.jsonl
  memories/*.jsonl
  index/memories.jsonl
  index/*.jsonl
  daily/YYYY/YYYY-MM-DD.md
  sessions/YYYY/MM/DD/<session>/summary.md
  sessions/YYYY/MM/DD/<session>/evidence.md
  sessions/YYYY/MM/DD/<session>/meta.json
  sessions/YYYY/MM/DD/<session>/source-map.json
```

## Use The Deployment Repository Directly

Run a global update from a shared source record directory:

```bash
python ~/repos/agent-memory/tools/run_memory_updates.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --allow-redacted-secrets
```

If `config/projects.jsonl` is empty, the runner scans source records for project
metadata such as `cwd` or `project_path`, registers discovered projects, and
then updates each enabled project.

For a deliberate historical repair pass, add `--rewrite-existing`. That mode
rebuilds matching source records and replaces older archive entries for the
same project/source record; it is not the normal incremental path.

For broad repair of entries already present in the archive, prefer the
meta-driven backfill tool:

```bash
python ~/repos/agent-memory/tools/backfill_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --allow-redacted-secrets
```

`--allow-redacted-secrets` keeps secret detection enabled but permits archive
entries after recognized secret patterns are redacted. Omit it when a human
should inspect secret-like source records before anything is written.

Update memory from a source record directory:

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --project-path /path/to/project
```

For shared source directories that contain records from multiple projects,
require explicit project metadata:

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --require-project-metadata
```

Audit generated archive quality:

```bash
python ~/repos/agent-memory/tools/audit_memory_archive.py \
  --memory-repo ~/repos/agent-memory
```

The audit checks generated text quality, unsafe key-like values, memory-node
drilldown paths, and evidence `quote_id` reachability.

Audit automatic induction and consolidation behavior without rendering private
memory text or source paths:

```bash
python ~/repos/agent-memory/tools/induction_consolidation_audit.py \
  --repo ~/repos/agent-memory
```

The induction report includes candidate, promotion, noise-rejection, review
reason distribution, overlap buckets, low-risk review compression, contradiction,
lifecycle reciprocity, evidence reachability, and privacy-pass metrics.

Run a privacy-safe shadow evaluation without copying private source records
into this development repository:

```bash
python ~/repos/agent-memory/tools/shadow_eval_memory_archive.py \
  --repo ~/repos/agent-memory \
  --cases /path/to/redacted_probe_cases.jsonl \
  --audit-script ~/repos/agent-memory/tools/audit_memory_archive.py \
  --fail-under memory_recall_at_5=1.0 \
  --fail-over top_k_noise_at_5=0.25
```

The shadow report is aggregate JSON only. Probe cases can use the legacy
`expected_memory_id` field or the plural `expected_memory_ids` field when a
query has several acceptable memory-node answers. `expected_layer` is a soft
preferred layer; `expected_not_memory_id` checks active-memory suppression; and
`forbidden_output_patterns` contains private or secret-like regular expressions
that must not appear in audit/search outputs. Top-k precision and noise are
computed against the full relevant-ID set, so another listed relevant memory is
not counted as noise. The report includes recall, active-memory suppression,
lifecycle integrity, top-k noise, provenance coverage, and aggregate
`case_details` count/status fields, plus `noise_sources_at_5` buckets for broad
lexical, scope-mixed, inactive lifecycle, and low-signal memory-node results. It
can also report legacy archives that do not yet have `index/memories.jsonl`, but
memory top-k metrics remain `null` until layered memory nodes exist.
`--fail-under`, `--fail-over`, `--fail-under-file`, and `--fail-over-file`
enforce numeric aggregate metrics or dotted metric paths such as
`metrics.provenance_coverage.score`. Threshold failures print only metric names,
actual values, and thresholds; they do not print the JSON report. It does not
render memory text, evidence text, source paths, raw anchors, returned memory
IDs, queries, or forbidden-pattern text.
Invalid `forbidden_output_patterns` regular expressions fail the run without
rendering the pattern text.

Search without invoking an agent:

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive"
```

Search starts with layered memory nodes when `index/memories.jsonl` exists.
Use depth controls to drill into supporting sessions, evidence, or protected
source anchors. Reserve `--depth source` for explicit source-reachability
requests. Source anchors are treated as untrusted display data and unsafe
anchor text is replaced with `[unsafe-source-ref]`; unsafe metadata fields are
rendered as `[unsafe-field]`. Memory nodes with confirmed `superseded_by`,
`contradicted_by`, or `deprecated_by` lifecycle links are treated as inactive
and skipped by search; deprecation marker nodes are also skipped by default.

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth session
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth evidence
python ~/repos/agent-memory/tools/search_memory.py "private session archive" --depth source
```

Specify a repository path:

```bash
python templates/agent-memory-repo/tools/search_memory.py \
  "access control decision" \
  --repo ~/repos/agent-memory
```

Search evidence files too:

```bash
python ~/repos/agent-memory/tools/search_memory.py \
  "raw transcript upload" \
  --include-evidence
```

Boost records for the current project while keeping cross-project hits visible:

```bash
python ~/repos/agent-memory/tools/search_memory.py \
  "FastDB lifetime boundary" \
  --project-path /path/to/current/project
```

Soft-rank an explicit memory layer without filtering away other layers when no
preferred-layer hit exists:

```bash
python ~/repos/agent-memory/tools/search_memory.py \
  "agent workflow proxy" \
  --preferred-scope domain
```

Search uses dependency-free hybrid lexical ranking over JSONL indexes, summary
files, and optional evidence files. The ranker weights high-signal fields such
as decisions, reusable facts, unresolved tasks, summaries, and user intent;
rewards exact query phrases and important literal tokens; and prints a `why:`
line so agents can tell whether a hit came from a structured field, phrase
match, important token coverage, project context, or scope preference.

### Layered Recall Benchmark

Synthetic layered recall cases can be checked with:

```bash
python benchmarks/layered_recall_benchmark.py \
  --repo /path/to/agent-memory \
  --cases /path/to/cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py
```

The harness reports retrieval and reliability metrics inspired by long-memory
benchmarks such as LongMemEval, LOCoMo, Memora, and RULER-style retrieval
stress tests:

- `memory_recall_at_1`, `memory_recall_at_5`, `memory_mrr`,
  `memory_ndcg_at_5`, `memory_precision_at_5`, and
  `memory_micro_precision_at_5`
- `memory_explainability`, with `memory_explainability_cases`, to check that
  ranked expected-memory hits are backed by high-signal `why:` reasons instead
  of only broad or low-signal matches
- `layer_calibration`, with `layer_calibration_cases`, for cases that require
  the expected memory to be recalled from a specific `global`, `domain`, or
  `project` layer
- `scope_filter_recall`, with `scope_filter_cases`, to verify those layer
  cases still recall the expected memory when search runs with
  `--scope <expected_layer>`
- `wrong_scope_suppression`, with `wrong_scope_suppression_cases`, to verify
  scoped search does not return the expected memory from other layers
- rank distribution fields `memory_ranked_cases`,
  `memory_rank_missing_cases`, `memory_rank_mean`,
  `memory_rank_median`, and `memory_rank_histogram`
- `session_drilldown_at_5`, `source_reachability`,
  `source_ref_reachability`, `source_depth_policy_pass_rate`,
  `raw_preview_redaction_pass_rate`, `source_drilldown_privacy_pass_rate`,
  `evidence_reachability`, and `evidence_text_reachability` with
  `evidence_text_cases`
- `answer_reachability`, `answer_normalized_reachability`, and
  `answer_token_f1` for reference-answer snippets that should be present in
  recalled memory/session/source output
- `abstention_accuracy`, `negative_memory_suppression`,
  `stale_memory_suppression`, `update_consistency`,
  `lifecycle_supersession_cases`, and `lifecycle_supersession_reciprocity`
- `privacy_boundary_pass_rate`, total `latency_ms`, `latency_mean_ms`,
  `latency_max_ms`, and per-category summaries
- denominator counts such as `positive_cases`, `answer_cases`, `stale_cases`,
  and `privacy_cases` so zero-denominator metrics are visible
- input provenance fields `cases_path`, `cases_sha256`, `search_script_path`,
  and `search_script_sha256` so score reports can be reproduced against the
  same case set and search implementation

Positive JSONL cases must include `query`, `expected_memory_id`,
`expected_summary_path`, and `expected_source_anchor`. Optional fields include
`case_id`, `category`, `source_benchmark`, `reference_answer`,
`reference_evidence`, `required_evidence_paths`, `expected_not_memory_id`,
`stale_memory_id`, `temporal_scope`, `expected_layer`, and
`forbidden_output_patterns`.
`forbidden_output_patterns` entries are Python regular expressions matched
against combined memory, session, source, and explicit raw-preview output.
When present, `case_id` must be unique within the case file.
Abstention cases set `expected_abstain` to `true` and do not need positive
expected fields. `answer_reachability` checks exact reference-answer text
reachability; `answer_normalized_reachability` ignores case and punctuation;
`answer_token_f1` reports best-window token overlap. These are retrieval-side
checks, not generated-answer semantic grading. `evidence_text_reachability`
checks that required evidence files contain exact `reference_evidence` snippets,
so source-depth claims are backed by reachable evidence text rather than only
path references.
At source depth, search output reports source refs as stable
`source_ref_id`, `status`, and `reason` fields. It does not print raw source
content by default. A short redacted raw-source snippet is only requested
explicitly with `--raw-source-preview <source_ref_id|all>`, and the benchmark
checks that preview output stays redacted and source-drilldown output remains
inside the privacy boundary.

Locally downloaded public benchmark files can be converted into this case
schema without committing the source data:

```bash
python benchmarks/convert_public_memory_benchmark.py \
  --source longmemeval \
  --input /path/outside/repo/longmemeval.json \
  --output /tmp/longmemeval-cases.jsonl \
  --build-synthetic-archive /tmp/longmemeval-synthetic-archive

python benchmarks/convert_public_memory_benchmark.py \
  --source locomo \
  --input /path/outside/repo/locomo.json \
  --output /tmp/locomo-cases.jsonl

python benchmarks/convert_public_memory_benchmark.py \
  --source memora \
  --input /path/outside/repo/memora-evaluation.json \
  --output /tmp/memora-cases.jsonl
```

The converter supports schema shapes used by the official
[LongMemEval](https://github.com/xiaowu0162/longmemeval),
[LoCoMo](https://github.com/snap-research/locomo), and
[Memora](https://github.com/geniesinc/Memora) releases. It creates deterministic
external memory IDs and protected source anchors for local evaluation; it does
not download, vendor, or commit public benchmark records.
`--build-synthetic-archive` is optional. It creates a temporary synthetic
archive from the converted case targets, which lets you dry-run the adapter
through the real search benchmark before evaluating a real memory archive.
Add `--include-superseded-distractors` with that option to create stale-memory
distractors for converted cases that declare `stale_memory_id`.

Converted public-style cases can be scored with the same quantitative gate:

```bash
python benchmarks/layered_recall_benchmark.py \
  --repo /tmp/longmemeval-synthetic-archive \
  --cases /tmp/longmemeval-cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/longmemeval-details.jsonl \
  --fail-under memory_recall_at_5=0.95 \
  --fail-under answer_normalized_reachability=0.90 \
  --fail-under categories.temporal_reasoning.memory_recall_at_5=0.90
```

The repository also includes a public-benchmark-inspired synthetic case suite:

```bash
benchmarks/cases/layered_recall_synthetic.jsonl
```

To produce a quantitative synthetic score report, build a temporary synthetic
archive and run the benchmark against the real search script:

```bash
python benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors

python benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-synthetic-details.jsonl \
  --failures-json /tmp/my-precious-synthetic-failures.json \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

`--details-jsonl` writes one row per case with rank, drill-down, source,
evidence, abstention, stale-suppression, lifecycle-supersession, privacy
outcomes, safe case metadata, source-depth policy outcomes, and a
`failed_checks` list naming the failed applicable metrics for that case.
The detail rows include benchmark source, temporal scope, expected stale or
negative memory IDs, stable case IDs when provided, required evidence paths,
and forbidden-pattern counts, but they do not render raw `reference_answer` or
`forbidden_output_patterns` text.
They also include safe returned identifiers such as memory result IDs, session
paths, and source ref IDs, without returned hit titles, raw source paths, or
snippets.
Sensitive-looking or control-character-bearing returned identifiers are written
as `[unsafe-result-identifier]`.
`--failures-json`
writes structured quality-gate failures with `metric`, `value`, and `threshold`
fields for CI systems that should not parse stderr. It also includes safe
per-case failure summaries with case ID, line number, category, source
benchmark, failed check names, memory rank, recall flags, session drilldown
status, and source reachability status; it still omits raw queries, expected
memory IDs, reference answers, and returned snippets. `--fail-under` keeps the
aggregate JSON on stdout and exits non-zero when a configured numeric metric
falls below its threshold, which makes the benchmark usable as a CI quality
gate. Thresholds can target top-level metrics or dotted category paths such as
`categories.knowledge_update.update_consistency=1.0`. Threshold values must be
finite numbers; NaN and Infinity are rejected before comparison.
`--fail-under-file` accepts a JSON object using the same metric paths, for
example:

```json
{
  "answer_normalized_reachability": 0.9,
  "categories.knowledge_update.update_consistency": 1.0,
  "lifecycle_supersession_reciprocity": 1.0,
  "memory_recall_at_5": 0.95,
  "privacy_boundary_pass_rate": 1.0,
  "source_depth_policy_pass_rate": 1.0,
  "source_ref_reachability": 1.0
}
```

Direct `--fail-under` arguments override duplicate metric keys loaded from
threshold files. The packaged `benchmarks/quality-gates/layered_recall_synthetic.json`
gate covers the synthetic suite's recall, rank coverage, source/evidence,
evidence-text reachability, answer reachability, abstention, stale/update,
lifecycle reciprocity, source-depth governance, privacy, and denominator-count
checks. The paired
`benchmarks/quality-gates/layered_recall_synthetic_max.json`
uses `--fail-over-file` for upper-bound checks such as `failed_case_count`,
`memory_rank_missing_cases`, `memory_rank_mean`, and `memory_rank_median`. Add
additional answer-metric gates to custom threshold files when an evaluated case
set has broader `reference_answer` coverage. Each memory/session/source search
subprocess has a default 30 second timeout; set finite positive
`--search-timeout-s` values lower for CI smoke tests or higher for large local
archives.

The packaged quality-gate command above includes superseded distractor nodes so
`lifecycle_supersession_cases` has a non-zero denominator. To stress
stale-memory suppression manually, add the same option when building a temporary
archive:

```bash
python benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --include-superseded-distractors
```

Those cases are synthetic templates only. They do not contain private memory
data or copied public benchmark records. External benchmark downloads should be
kept outside this repository and locally converted to the same JSONL case
schema when needed. This benchmark is designed for My Precious layered recall,
not as a direct score comparison against systems that store verbatim transcript
embeddings.

Render a default global scheduler:

```bash
python ~/repos/agent-memory/tools/render_scheduler.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --backend launchd \
  --schedule daily \
  --output ~/repos/agent-memory/.tmp/agent-memory.plist
```

Add `--project-path /path/to/project` only when you want one scheduler per
project instead of the global runner.

Render an agent-native automation prompt:

```bash
python ~/repos/agent-memory/tools/render_scheduler.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --backend agent-native \
  --allow-redacted-secrets \
  --push-after-update \
  --output ~/repos/agent-memory/.tmp/agent-native-update.txt
```

Agent-native automations should use the deployment repository as their only
working directory. Multiple working directories can create multiple concurrent
automation conversations.

Safely commit and push generated archive updates:

```bash
python ~/repos/agent-memory/tools/sync_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --push
```

The sync helper only stages archive paths (`INDEX.md`,
`config/projects.jsonl`, `index/`, `memories/`, `daily/`, and `sessions/`). It refuses
tool/script edits, archive audit findings, unredacted key-like values, and
whitespace errors before committing.

## Archive Contract

A compatible deployment repository should expose:

- `INDEX.md`: overview for humans and agents.
- `config/projects.jsonl`: optional project registry used by the global runner.
- `memories/global.jsonl`, `memories/domains.jsonl`, `memories/projects.jsonl`,
  and `memories/explicit.jsonl`: layered memory nodes.
- `index/memories.jsonl`: combined layered-memory search index.
- `index/memory_review_candidates.jsonl`: ambiguous lifecycle pairs requiring
  manual review before automatic retirement.
- `index/memory_consolidation_trace.jsonl`: explainable merge, supersede,
  contradict, deprecate, and skip decisions from the updater.
- `index/sessions.jsonl`: one row per session.
- `index/decisions.jsonl`: one row per reusable decision.
- `index/unresolved.jsonl`: one row per follow-up task.
- `sessions/YYYY/MM/DD/.../summary.md`: structured per-session summary.
- `sessions/YYYY/MM/DD/.../evidence.md`: short evidence snippets for important claims.

Detailed format:

```text
skills/using-my-precious/references/archive-format.md
```

## Implemented

- `setup-my-precious` skill.
- `update-my-precious` skill.
- `using-my-precious` skill.
- Skill UI metadata in `agents/openai.yaml`.
- Generic archive format reference.
- Layered global, domain, and project memory nodes with drilldown to sessions,
  evidence, and source anchors.
- Dependency-light semantic consolidation for automatic memory nodes, including
  paraphrase support merge, false partial-supersession guards, contradiction
  links, deprecation links, partial supersession, confidence revision for
  retired nodes, and robustness benchmark gates.
- Ambiguity review queue and consolidation decision trace indexes for semantic
  lifecycle cases that should not be auto-retired.
- Privacy-safe real-archive shadow evaluation runner with aggregate recall,
  suppression, lifecycle, noise-source, provenance, multi-relevant precision,
  case-detail count metrics, and numeric quality gates.
- Dependency-free hybrid lexical search script with field weighting, phrase
  coverage, optional project-context boost, low-signal memory-node filtering,
  optional preferred-scope ranking, and explainable result reasons.
- Incremental update script keyed by project path and source/session timestamp.
- Searchable summary, short evidence snippet, source-map, daily summary, and JSONL index generation.
- Secret-pattern detection that refuses risky source records by default.
- Optional project-metadata requirement for shared source record directories.
- Global update runner that bootstraps an empty project registry from source records.
- Backfill mode for deliberately rewriting existing source-record entries.
- Meta-driven backfill tool for repairing existing archive entries without repeated full source scans.
- Archive audit tool for wrapper-field noise, process-update text, and key-like values.
- Reviewable scheduler template generator for launchd and cron formats.
- Agent-native automation prompt rendering with a single working directory.
- Safe Git sync helper for generated archive updates.
- Private deployment repository template.
- Synthetic setup, update, global-runner, and search tests.

## Responsibility Map

This repository should provide reusable, non-private building blocks:

- skills and their bundled scripts/assets
- archive format contracts and schemas
- deployment repository templates
- generic search tools
- reusable setup helpers
- reusable archive pipeline components such as redaction, rendering, indexing, validation, global update running, safe Git sync, scheduler-template generation, and source-adapter interfaces

`$setup-my-precious` should perform runtime setup actions after asking the user:

- choose local-only storage or Git-backed storage
- choose or create the local archive directory
- optionally create/connect a private hosted Git repository
- copy the deployment template
- initialize Git when requested
- write the archive location to `~/.config/my-precious/config.json`
- report an optional `AGENT_SESSION_MEMORY_REPO` current-shell override
- optionally configure a recurring archive job, but only after concrete archive and sync commands exist in the deployment repository

The private deployment repository should contain user-specific state and operations:

- generated `sessions/`, `daily/`, and `index/` data
- project-specific high-water marks and source-record hash freshness state
- local config and logs
- configured remotes
- active scheduled jobs or scheduler config
- source-specific ingestion settings

The deployment repository should not commit raw transcripts, credentials, cookies, private keys, or unredacted data.

Runtime setup work that belongs in `$setup-my-precious`:

- prompt the user for storage mode and path
- prompt for hosted Git repository name when needed
- create/connect the private repository
- ask whether to render and then configure scheduling once the archive command exists
- verify the resulting search command works

## Verification

Validate the skill with your runtime's skill validator, then run the repository tests:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'

python3 -m py_compile \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/update-my-precious/scripts/memory_consolidation.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/memory_consolidation.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/induction_consolidation_audit.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py
```

## Security Boundary

- Do not upload raw transcripts by default.
- Do not commit tokens, cookies, private keys, or `.env` files.
- Keep this repository limited to reusable tooling and synthetic tests.
- Keep the real memory repository private.
- Prefer `summary.md`; read `evidence.md` only when support is needed.
