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

Search without invoking an agent:

```bash
python ~/repos/agent-memory/tools/search_memory.py "private session archive"
```

Search starts with layered memory nodes when `index/memories.jsonl` exists.
Use depth controls to drill into supporting sessions, evidence, or protected
source anchors. Reserve `--depth source` for explicit source-reachability
requests. Memory nodes with a non-empty `superseded_by` field are treated as
inactive and skipped by search.

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

Search uses dependency-free hybrid lexical ranking over JSONL indexes, summary
files, and optional evidence files. The ranker weights high-signal fields such
as decisions, reusable facts, unresolved tasks, summaries, and user intent;
rewards exact query phrases and important literal tokens; and prints a `why:`
line so agents can tell whether a hit came from a structured field, phrase
match, important token coverage, or project context.

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

- `memory_recall_at_1`, `memory_recall_at_5`, and `memory_mrr`
- `session_drilldown_at_5`, `source_reachability`, and
  `evidence_reachability`
- `answer_reachability`, `answer_normalized_reachability`, and
  `answer_token_f1` for reference-answer snippets that should be present in
  recalled memory/session/source output
- `abstention_accuracy`, `negative_memory_suppression`,
  `stale_memory_suppression`, and `update_consistency`
- `privacy_boundary_pass_rate`, total `latency_ms`, and per-category summaries

Positive JSONL cases must include `query`, `expected_memory_id`,
`expected_summary_path`, and `expected_source_anchor`. Optional fields include
`category`, `reference_answer`, `required_evidence_paths`, `expected_not_memory_id`,
`stale_memory_id`, `temporal_scope`, and `forbidden_output_patterns`.
Abstention cases set `expected_abstain` to `true` and do not need positive
expected fields. `answer_reachability` checks exact reference-answer text
reachability; `answer_normalized_reachability` ignores case and punctuation;
`answer_token_f1` reports best-window token overlap. These are retrieval-side
checks, not generated-answer semantic grading.

Locally downloaded public benchmark files can be converted into this case
schema without committing the source data:

```bash
python benchmarks/convert_public_memory_benchmark.py \
  --source longmemeval \
  --input /path/outside/repo/longmemeval.json \
  --output /tmp/longmemeval-cases.jsonl

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

The repository also includes a public-benchmark-inspired synthetic case suite:

```bash
benchmarks/cases/layered_recall_synthetic.jsonl
```

To produce a quantitative synthetic score report, build a temporary synthetic
archive and run the benchmark against the real search script:

```bash
python benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl

python benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-synthetic-archive \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-synthetic-details.jsonl \
  --fail-under memory_recall_at_5=0.95 \
  --fail-under privacy_boundary_pass_rate=1.0
```

`--details-jsonl` writes one row per case with rank, drill-down, source,
evidence, abstention, stale-suppression, and privacy outcomes. `--fail-under`
keeps the aggregate JSON on stdout and exits non-zero when a top-level numeric
metric falls below the configured threshold, which makes the benchmark usable as
a CI quality gate.

To stress stale-memory suppression, add superseded distractor nodes that share
the same query terms but must not appear in search output:

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
- Dependency-free hybrid lexical search script with field weighting, phrase
  coverage, optional project-context boost, and explainable result reasons.
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
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py
```

## Security Boundary

- Do not upload raw transcripts by default.
- Do not commit tokens, cookies, private keys, or `.env` files.
- Keep this repository limited to reusable tooling and synthetic tests.
- Keep the real memory repository private.
- Prefer `summary.md`; read `evidence.md` only when support is needed.
