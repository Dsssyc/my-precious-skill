# Agent Memory

Private archive of summarized agent sessions.

This repository is not a raw transcript dump. It stores structured, redacted,
searchable summaries so future agent sessions can recover project decisions,
unresolved work, reusable facts, and user preferences.

## Search

Search starts with high-level memory nodes and can drill down into supporting
sessions and evidence when `index/memories.jsonl` exists:

```bash
python tools/search_memory.py "<query>"
python tools/search_memory.py "<query>" --project-path /path/to/current/project
python tools/search_memory.py "<query>" --depth session
python tools/search_memory.py "<query>" --depth evidence
```

Use `--depth source` only when source anchors are needed and the user has
explicitly asked for raw-source reachability. The command reports source
anchors; it does not copy raw transcripts into the archive.

Read `why:` and `drill:` lines in search output. Prefer high-level memories
with provenance, then open the supporting summaries or evidence. If no relevant
result exists, say so instead of inferring historical facts.

## Update Now

Run the global updater against a shared source record directory:

```bash
python tools/run_memory_updates.py \
  --source-dir /path/to/session-records \
  --allow-redacted-secrets
```

The global updater reads `config/projects.jsonl`, scans the source directory
for project metadata, registers newly discovered projects, and then runs the
per-project updater for each enabled project. An empty project registry is
valid; the first run bootstraps it from source records that contain project
paths such as `cwd` or `project_path`.

Archive new source records for a project:

```bash
python tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project
```

The updater uses `project-path` as the project scope and high-water-mark key. It
archives source records newer than the latest timestamp already archived for
that project, and also refreshes a previously archived source record when its
current source hash differs from the hash stored in the archive. It prefers
timestamps embedded in source records, then timestamps in file names, and
finally file modification time.

Records with no durable content after filtering are skipped instead of being
archived as placeholder summaries such as `Archive source record for ...`.

`--allow-redacted-secrets` keeps secret detection enabled but allows records to
be archived after recognized patterns have been redacted. Omit it when a human
should inspect secret-like source records before any archive entry is written.

If `source-dir` contains records from multiple projects, add
`--require-project-metadata` so records without explicit project path metadata
are skipped.

Repair old generated summaries for a project by replacing existing entries for
the same source records:

```bash
python tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --require-project-metadata \
  --rewrite-existing \
  --allow-redacted-secrets \
  --max-records -1
```

For broad repair of entries already present in the archive, prefer the
meta-driven backfill tool. It rewrites from existing `sessions/**/meta.json`
source pointers instead of repeatedly scanning the full source directory for
every registered project:

```bash
python tools/backfill_memory_archive.py \
  --memory-repo . \
  --allow-redacted-secrets
```

`--rewrite-existing` on `tools/run_memory_updates.py` is still available for
small repositories, but it can be slower on large shared source directories.
Both modes are repair paths, not the normal incremental path.

## Audit

Check generated archive files for wrapper-field noise, first-person process
updates, and unredacted key-like values:

```bash
python tools/audit_memory_archive.py --memory-repo .
```

## Render Scheduler Config

Generate reviewable scheduler configuration without installing it:

```bash
python tools/render_scheduler.py \
  --source-dir /path/to/session-records \
  --backend launchd \
  --schedule daily \
  --output .tmp/agent-memory.plist
```

Omit `--project-path` for the global runner. Add `--project-path` only when
rendering a scheduler for one specific project.

Render an agent-native automation prompt with a single working directory:

```bash
python tools/render_scheduler.py \
  --source-dir /path/to/session-records \
  --backend agent-native \
  --allow-redacted-secrets \
  --push-after-update \
  --output .tmp/agent-native-update.txt
```

Agent-native automation should use the memory repository as its only working
directory. Multiple working directories may create multiple concurrent
automation conversations.

## Safe Git Sync

After an update, commit and optionally push generated archive changes:

```bash
python tools/sync_memory_archive.py --push
```

The sync helper refuses to proceed when non-archive paths changed, when
generated archive files still contain recognized key-like values, when archive
audit finds low-quality index text, or when `git diff --cached --check` fails.
Expected archive paths are limited to
`INDEX.md`, `config/projects.jsonl`, `index/`, `memories/`, `daily/`, and
`sessions/`.

## Archive Data

Expected generated data:

- `index/memories.jsonl`
- `memories/global.jsonl`
- `memories/domains.jsonl`
- `memories/projects.jsonl`
- `memories/explicit.jsonl`
- `sessions/YYYY/MM/DD/.../summary.md`
- `sessions/YYYY/MM/DD/.../evidence.md`
- `sessions/YYYY/MM/DD/.../meta.json`
- `sessions/YYYY/MM/DD/.../source-map.json`
- `daily/YYYY/YYYY-MM-DD.md`
- `index/*.jsonl`
- `config/projects.jsonl`

## Security

- Raw transcripts are not committed by default.
- Source records matching secret patterns are refused by default.
- Redaction runs before summarization and evidence rendering.
- Git sync refuses tool/script changes and unredacted key-like values.
- Archive audit refuses wrapper-field noise and first-person process updates in generated files.
- Credentials must never be committed.
- Keep this repository private.
