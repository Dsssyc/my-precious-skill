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

`update-my-precious` is the write-path skill. It scans a source record
directory, uses the current project path to filter source records, writes into
a selected archive memory domain, and tracks freshness by a source partition.
The default archive scope and source partition are both the resolved project
path for compatibility. Deployments can opt into a stable non-project memory
domain with `--archive-scope` and a stable non-path source stream with
`--source-partition`. The updater archives records newer than the latest
timestamp for the same archive scope plus source partition, and refreshes a
previously archived source record in that same partition when its source hash
changes.

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
  benchmarks/
    e2e_induction_recall_benchmark.py
    updater_induction_benchmark.py
    layered_recall_benchmark.py
    cases/
    quality-gates/
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
Registered project rows may include `archive_scope` to make scheduled updates
write into a stable memory domain that is not the project path. They may also
include `source_partition` to make high-water and source-hash freshness follow
a stable source stream that is independent from `project_path`. When omitted,
the source partition defaults to the resolved project path, so one project path
cannot hide older unarchived records from another path in the same domain
stream.

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

Use an explicit non-project memory domain when needed:

```bash
python ~/repos/agent-memory/tools/update_memory_archive.py \
  --memory-repo ~/repos/agent-memory \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --archive-scope domain:agent-memory
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

Generate aggregate-safe natural induction review decision skeletons:

```bash
python ~/repos/agent-memory/tools/author_induction_review_decisions.py \
  --memory-repo ~/repos/agent-memory \
  --dry-run
```

The recommended flow is: generate the skeleton report with `--dry-run`, append
missing skeleton rows with `--write`, have a reviewer fill the private
`reviews/induction_review_decisions.jsonl` actions, then run
`apply_memory_review_decisions.py --dry-run` followed by `--write`. Skeleton
rows contain `candidate_id`, `candidate_text_sha256`, and
`candidate_fingerprint` only; the authoring report is aggregate JSON and never
prints candidate text, memory text, source paths, queries, raw refs, or
transcripts. This is a safe authoring helper for the private deployment archive,
not an approval UI and not generated private archive data for this development
repository.

Preview or apply lifecycle review decisions without rendering private memory
text:

```bash
python ~/repos/agent-memory/tools/apply_memory_review_decisions.py \
  --memory-repo ~/repos/agent-memory \
  --dry-run
```

Review decisions live in the private deployment archive at
`reviews/memory_lifecycle_decisions.jsonl`. The dry-run report is aggregate
JSON only; it reports decision counts, applied/ignored action counts, and
before/after lifecycle relation counts. Use `--write` only after reviewing the
decision file; it rebuilds archive indexes and applies approved lifecycle
relations.

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
abstain pass rate, abstain false-positive result count, lifecycle integrity,
top-k noise, provenance coverage, and aggregate hashed `case_details`
count/status fields, plus `noise_sources_at_5` buckets for broad lexical, scope-mixed,
inactive lifecycle, and low-signal memory-node results. `expected_abstain:
true` cases pass only when no memory hits are returned. The runner can also
report legacy archives that do not yet have `index/memories.jsonl`, but memory
top-k metrics remain `null` until layered memory nodes exist.
The JSON report also includes a privacy-safe `diagnostics` block that groups
failure cases by `recall_miss`, `abstain_false_positive`,
`suppression_failure`, `privacy_failure`, and `top_k_noise`. Diagnostic entries
use only case ordinals, short case-label hashes, counts, and noise buckets; they
do not render probe queries, memory IDs, source paths, raw refs, or forbidden
patterns.
`--fail-under`, `--fail-over`, `--fail-under-file`, and `--fail-over-file`
enforce numeric aggregate metrics or dotted metric paths such as
`metrics.provenance_coverage.score`. Threshold failures print only metric names,
actual values, and thresholds; they do not print the JSON report. It does not
render memory text, evidence text, source paths, raw anchors, returned memory
IDs, queries, or forbidden-pattern text.
Invalid `forbidden_output_patterns` regular expressions fail the run without
rendering the pattern text.

Run the v1 readiness convergence gate from existing aggregate reports:

```bash
python benchmarks/v1_readiness_gate.py \
  --layered-report /tmp/layered.json \
  --updater-report /tmp/updater.json \
  --e2e-report /tmp/e2e.json
```

Or run the packaged synthetic gates directly:

```bash
python benchmarks/v1_readiness_gate.py --run-packaged
```

The readiness gate emits aggregate-only JSON. It requires the packaged layered
recall, updater induction, and e2e induction-to-recall dimensions to pass before
reporting `core_synthetic_ready`. Optional `--public-report` and
`--shadow-report` inputs can add adapted public-benchmark and private
real-archive aggregate evidence. Optional `--answer-report` can add offline
generated-answer grading evidence. Add `--require-public`, `--require-shadow`,
or `--require-answer` when those optional dimensions should fail the gate if
absent. When `--run-packaged --require-answer` is used without an
`--answer-report`, the gate runs the packaged synthetic generated-answer fixture
and includes that aggregate report automatically. Public reports must be
layered recall reports produced from converted
public benchmark cases, including aggregate `source_benchmarks` counts and
`case_origins.public_benchmark_adapter`; converter-only output or ordinary
synthetic layered reports are not accepted as public evidence. A
`core_synthetic_ready` result is deliberately bounded: it means the core
synthetic gates passed, not that the repository has proven full v1 readiness,
public leaderboard parity, generated-answer accuracy without an answer report,
or long-horizon multi-principal governance.

Score generated answers offline without rendering queries, generated answers,
or reference answers:

```bash
python benchmarks/generated_answer_benchmark.py \
  --cases benchmarks/cases/generated_answer_synthetic.jsonl \
  --answers benchmarks/cases/generated_answer_synthetic_answers.jsonl \
  --details-jsonl /tmp/generated-answer-details.jsonl \
  --fail-under case_pass_rate=1.0 \
  --fail-under answer_normalized_match_rate=1.0 \
  --fail-under abstention_accuracy=1.0 \
  --fail-over privacy_leak_count=0 \
  --fail-over failed_case_count=0 \
  --fail-over missing_answer_count=0 \
  --fail-over duplicate_answer_count=0 \
  --fail-over unknown_answer_count=0
```

The answer benchmark reports aggregate `case_pass_rate`,
`answer_exact_match_rate`, `answer_normalized_match_rate`, `answer_token_f1`,
`abstention_accuracy`, missing/duplicate/unknown answer counts, and privacy
counts. Its claim boundary is narrow: it grades provided answer records against
reference answers; it does not call a model, generate answers, or claim semantic
equivalence beyond exact, normalized, and token-overlap checks.

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
  `memory_micro_precision_at_5`, plus `memory_noise_count_at_5` and
  `top_k_noise_at_5` for top-k result noise
- `memory_explainability`, with `memory_explainability_cases`, to check that
  ranked expected-memory hits are backed by high-signal `why:` reasons instead
  of only broad or low-signal matches
- `layer_calibration`, with `layer_calibration_cases`, for cases that require
  the expected memory to be recalled from a specific `global`, `domain`, or
  `project` layer
- `layer_path_success_rate`, which requires top-5 memory recall, the supporting
  summary path, and any configured expected layer to line up
- `scope_filter_recall`, with `scope_filter_cases`, to verify those layer
  cases still recall the expected memory when search runs with
  `--scope <expected_layer>`
- `wrong_scope_suppression`, with `wrong_scope_suppression_cases`, to verify
  scoped search does not return the expected memory from other layers
- rank distribution fields `memory_ranked_cases`,
  `memory_rank_missing_cases`, `memory_rank_mean`,
  `memory_rank_median`, and `memory_rank_histogram`
- `session_drilldown_at_5`, `drilldown_success_rate`, `source_reachability`,
  `source_ref_reachability`, `source_depth_policy_pass_rate`,
  `raw_preview_redaction_pass_rate`, `raw_preview_authorization_pass_rate`,
  `source_drilldown_privacy_pass_rate`,
  `evidence_reachability`, and `evidence_text_reachability` with
  `evidence_text_cases`
- `answer_reachability`, `answer_normalized_reachability`, and
  `answer_token_f1` for reference-answer snippets that should be present in
  recalled memory/session/source output or in verified local drilldown files
- `abstention_accuracy`, `abstention_answer_cases`,
  `abstention_answer_pass_rate`, `negative_memory_suppression`,
  `stale_memory_suppression`, `update_consistency`,
  `lifecycle_supersession_cases`, `lifecycle_supersession_reciprocity`, and
  aggregate `suppression_pass_rate`
- `privacy_boundary_pass_rate`, `privacy_leak_count`, total `latency_ms`,
  `latency_mean_ms`,
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
The packaged synthetic suite includes explicit `broad_lexical_noise` abstain
cases so broad lexical overlap is measured separately from ordinary abstention.
`forbidden_output_patterns` entries are Python regular expressions matched
against combined memory, session, source, and explicit raw-preview output.
`privacy_leak_count` also treats generic secret-like output identifiers as
leaks even when a case does not configure explicit forbidden patterns.
When present, `case_id` must be unique within the case file.
Abstention cases set `expected_abstain` to `true` and do not need positive
expected fields. Some public-benchmark adapter abstention cases include
reference answers such as "not mentioned" or "not enough information"; those
count toward `abstention_answer_cases` and may pass when structured related
context is reachable while the requested fact is absent. `answer_reachability`
checks exact reference-answer text reachability in expected-memory search output
or in verified local drilldown files; `answer_normalized_reachability` ignores
case and punctuation; `answer_token_f1` reports best-window token overlap.
These are retrieval-side checks, not generated-answer semantic grading. Use
`benchmarks/generated_answer_benchmark.py` when the input is a JSONL file of
already generated answers that need aggregate-only grading.
`evidence_text_reachability`
checks that required evidence files contain exact `reference_evidence` snippets,
so source-depth claims are backed by reachable evidence text rather than only
path references.
At source depth, search output reports source refs as stable
`source_ref_id`, `status`, and `reason` fields. It does not print raw source
content by default. A short redacted raw-source snippet is only requested
explicitly with both `--raw-source-preview <source_ref_id|all>` and
`--authorize-raw-source-preview`, and the benchmark checks that the authorized
preview path is used, preview output stays redacted, and source-drilldown output
remains inside the privacy boundary.

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
Use `--limit N` for bounded adapter probes. For JSONL files and top-level JSON
arrays, the converter stops reading once enough input records are available;
for other JSON shapes it may still need to parse the full local file before
applying the converted-case limit.
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
evidence-text reachability, answer reachability, abstention, broad lexical
noise resistance, stale/update, lifecycle reciprocity, source-depth governance,
layer path and drilldown success, suppression, privacy, and denominator-count
checks. The paired
`benchmarks/quality-gates/layered_recall_synthetic_max.json`
uses `--fail-over-file` for upper-bound checks such as `failed_case_count`,
`memory_rank_missing_cases`, `memory_rank_mean`, `memory_rank_median`,
`top_k_noise_at_5`, and `privacy_leak_count`. Add additional answer-metric
gates to custom threshold files when an evaluated case set has broader
`reference_answer` coverage. Each memory/session/source search
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

The repository also includes an updater-driven synthetic induction benchmark.
Unlike the layered recall benchmark, it does not prebuild `memories/*.jsonl`.
It creates temporary synthetic source records, runs `setup_memory_archive.py`,
then runs the deployed template's `tools/update_memory_archive.py` and scores
the generated archive:

```bash
python benchmarks/updater_induction_benchmark.py \
  --cases benchmarks/cases/updater_induction_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/updater_induction_synthetic.json \
  --fail-over-file benchmarks/quality-gates/updater_induction_synthetic_max.json
```

The induction benchmark reports aggregate-only JSON metrics:
`induction_success_rate`, `natural_induction_success_rate`,
`natural_false_promotion_rate`, `auto_promotion_precision`,
`cross_project_generalization_rate`, `project_scope_precision`,
`ambiguous_candidate_review_rate`, `induction_review_routing_rate`,
`induction_review_decision_apply_rate`,
`induction_review_approve_promotion_rate`,
`induction_review_ignore_suppression_rate`,
`low_confidence_review_rate`, `scope_change_review_rate`,
`conflict_review_rate`,
`review_routing_rate`, `process_noise_rejection_rate`,
`ephemeral_status_rejection_rate`, `hypothetical_rejection_rate`,
`acknowledgement_only_rejection_rate`,
`temporary_local_decision_rejection_rate`, `generic_rule_rejection_rate`,
`evidence_retention_rate`, `source_ref_policy_pass_rate`,
`lifecycle_link_accuracy`, `forced_memory_capture_rate`,
`privacy_refusal_pass_rate`, `privacy_redaction_pass_rate`, and
`privacy_leak_count`. Its packaged synthetic suite covers cross-project
automatic induction, natural-language preference and workflow induction,
project-scoped implementation constraints, ambiguous scope candidates routed to
review, natural induction review calibration, adversarial natural-language
precision cases, process-noise rejection, source-record forced memory,
supersede/contradict/deprecate lifecycle links, redacted source records, and
default refusal of likely-secret source records.
Natural review calibration covers repeated statements with partial support,
conflicting preferences, scope broadening or narrowing, low-confidence one-off
candidates, and candidates that should remain reviewable instead of being
rejected or promoted. Review candidate rows preserve evidence/source refs for
audit, but store `candidate_text_sha256` instead of rendering candidate text.
Synthetic induction review decisions use private
`reviews/induction_review_decisions.jsonl` rows with `approve_promote`,
`reject`, or `noop`; approve decisions are the only path that promotes those
review candidates into memory nodes. Decision-set validation rejects duplicate
`decision_id` values, repeated exact rows, and conflicting actions for the same
candidate or candidate fingerprint. Dry-run reports expose only aggregate
duplicate/conflict/stale/unsafe/unknown counts, never candidate text, memory
text, source paths, or raw refs. The aggregate-safe authoring helper can append
pending skeleton rows for active candidates while preserving existing manual
decisions and skipping already reflected decisions; reviewers still fill the
private action field themselves before apply preflight/write.
The adversarial precision cases cover one-off status or progress updates with
`should`/`must`, acknowledgement-only replies, hypothetical `we could` or
`maybe` statements, temporary local implementation choices, test-result
chatter, quoted prompt-like text, and broad generic rules without distinctive
support. It does not render source content, memory text, source paths, raw refs,
or per-case details.

The end-to-end synthetic benchmark connects the write and read paths. It
creates temporary synthetic source records, runs the real setup and updater,
derives recall cases from the generated `index/memories.jsonl`, then scores
those cases with the real layered recall benchmark and copied
`tools/search_memory.py`:

```bash
python benchmarks/e2e_induction_recall_benchmark.py \
  --cases benchmarks/cases/e2e_induction_recall_synthetic.jsonl \
  --fail-under-file benchmarks/quality-gates/e2e_induction_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/e2e_induction_recall_synthetic_max.json
```

It reports aggregate-only e2e metrics:
`natural_induction_success_rate`, `cross_project_generalization_rate`,
`project_scope_precision`, `ambiguous_candidate_review_rate`,
`process_noise_rejection_rate`, `e2e_memory_recall_at_1`,
`e2e_memory_recall_at_5`,
`e2e_layer_assignment_accuracy`, `e2e_session_drilldown_rate`,
`e2e_evidence_reachability_rate`, `e2e_source_policy_pass_rate`,
`e2e_lifecycle_active_suppression_rate`, `e2e_forced_memory_recall_rate`,
and `privacy_leak_count`. The packaged suite covers cross-project automatic
induction, natural-language preference and workflow induction,
project-scoped implementation constraints, ambiguous scope candidates routed to
review, process-noise rejection, source-record forced memory,
supersede/contradict/deprecate lifecycle suppression, redacted source records,
and default refusal of likely-secret source records without rendering private
case details.

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
`config/projects.jsonl`, `index/`, `memories/`, `reviews/`, `daily/`, and
`sessions/`). It refuses tool/script edits, archive audit findings, unredacted
key-like values, and whitespace errors before committing.

## Archive Contract

A compatible deployment repository should expose:

- `INDEX.md`: overview for humans and agents.
- `config/projects.jsonl`: optional project registry used by the global runner.
  Rows may include `archive_scope` for a memory domain independent from
  `project_path` and `source_partition` for a high-water/source-hash stream
  independent from `project_path`.
- `memories/global.jsonl`, `memories/domains.jsonl`, `memories/projects.jsonl`,
  and `memories/explicit.jsonl`: layered memory nodes.
- `reviews/memory_lifecycle_decisions.jsonl`: private reviewer decisions for
  ambiguous lifecycle candidates.
- `reviews/induction_review_decisions.jsonl`: private reviewer decisions for
  natural induction candidates. Duplicate IDs, exact duplicate rows, and
  conflicting actions for the same candidate or fingerprint are rejected.
- `index/memories.jsonl`: combined layered-memory search index.
- `index/memory_review_candidates.jsonl`: ambiguous lifecycle pairs requiring
  manual review before automatic retirement.
- `index/induction_review_candidates.jsonl`: aggregate-safe natural induction
  candidates that require review before promotion.
- `index/induction_review_decision_results.jsonl`: aggregate-safe applied/ignored
  induction review decision statuses.
- `index/memory_review_decision_results.jsonl`: aggregate-safe applied/ignored
  review decision statuses.
- `index/memory_consolidation_trace.jsonl`: explainable merge, supersede,
  contradict, deprecate, and skip decisions from the updater.
- `index/sessions.jsonl`: one row per session.
- `index/source_partitions.jsonl`: one generated row per archive scope plus
  source partition.
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
- Aggregate-safe natural induction review candidate index for low-confidence,
  conflicting, or scope-changing natural candidates that should not be
  auto-promoted.
- Aggregate-safe induction review decision results for synthetic approve,
  reject, noop, duplicate, conflict, stale, unsafe, and unknown calibration.
- Aggregate-only review-decision dry-run/apply tool for converting approved
  lifecycle review decisions into reciprocal memory links.
- Privacy-safe real-archive shadow evaluation runner with aggregate recall,
  suppression, lifecycle, noise-source, provenance, multi-relevant precision,
  case-detail count metrics, and numeric quality gates.
- End-to-end synthetic induction-to-recall benchmark that runs setup, updater,
  generated layered recall cases, and the copied search script with
  aggregate-only quality gates.
- Updater-driven natural-induction precision gates for adversarial synthetic
  false-promotion cases and review routing, including induction-review routing
  rates for low-confidence, scope-change, and conflict candidates.
- Dependency-free hybrid lexical search script with field weighting, phrase
  coverage, optional project-context boost, low-signal memory-node filtering,
  optional preferred-scope ranking, and explainable result reasons.
- Incremental update script keyed by archive scope, explicit source partition,
  and source/session timestamp, defaulting both archive scope and source
  partition to project path for compatibility.
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
- archive-scope plus source-partition high-water marks and source-record hash
  freshness state
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
  benchmarks/e2e_induction_recall_benchmark.py \
  benchmarks/updater_induction_benchmark.py \
  benchmarks/layered_recall_benchmark.py \
  benchmarks/build_synthetic_recall_archive.py \
  benchmarks/convert_public_memory_benchmark.py \
  benchmarks/v1_readiness_gate.py \
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
