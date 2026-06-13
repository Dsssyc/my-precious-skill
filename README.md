# My Precious Skill

English | [简体中文](README.zh-CN.md)

`my-precious-skill` is a development repository for generic agent session memory skills.

- `setup-my-precious` initializes or connects a private memory archive.
- `update-my-precious` scans new source records and writes fresh memory entries.
- `using-my-precious` searches an existing private memory archive.

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
      index/
      daily/
      sessions/
      prompts/summarize_session.prompt.md
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
`config/projects.jsonl`, `index/`, `daily/`, and `sessions/`). It refuses
tool/script edits, archive audit findings, unredacted key-like values, and
whitespace errors before committing.

## Archive Contract

A compatible deployment repository should expose:

- `INDEX.md`: overview for humans and agents.
- `config/projects.jsonl`: optional project registry used by the global runner.
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
- Dependency-free search script.
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
