# Agent Memory

Private archive of summarized agent sessions.

This repository is not a raw transcript dump. It stores structured, redacted,
searchable summaries so future agent sessions can recover project decisions,
unresolved work, reusable facts, and user preferences.

## Search

```bash
python tools/search_memory.py "<query>"
```

The setup skill records this repository in
`~/.config/my-precious/config.json` by default. `AGENT_SESSION_MEMORY_REPO` can
still be used as a current-shell or scheduler override.

## Update Now

Run the global updater against a shared source record directory:

```bash
python tools/run_memory_updates.py \
  --source-dir /path/to/session-records
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

The updater uses `project-path` as the high-water-mark key and only archives
source records newer than the latest timestamp already archived for that
project. It prefers timestamps embedded in source records, then timestamps in
file names, and finally file modification time.

If `source-dir` contains records from multiple projects, add
`--require-project-metadata` so records without explicit project path metadata
are skipped.

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

## Archive Data

Expected generated data:

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
- Credentials must never be committed.
- Keep this repository private.
