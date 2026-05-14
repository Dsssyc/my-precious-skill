# Agent Memory

Private archive of summarized agent sessions.

This repository is not a raw transcript dump. It stores structured, redacted,
searchable summaries so future agent sessions can recover project decisions,
unresolved work, reusable facts, and user preferences.

## Search

```bash
python tools/search_memory.py "<query>"
```

## Update Now

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

## Render Scheduler Config

Generate reviewable scheduler configuration without installing it:

```bash
python tools/render_scheduler.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --backend launchd \
  --schedule daily \
  --output .tmp/agent-memory.plist
```

## Archive Data

Expected generated data:

- `sessions/YYYY/MM/DD/.../summary.md`
- `sessions/YYYY/MM/DD/.../evidence.md`
- `sessions/YYYY/MM/DD/.../meta.json`
- `sessions/YYYY/MM/DD/.../source-map.json`
- `daily/YYYY/YYYY-MM-DD.md`
- `index/*.jsonl`

## Security

- Raw transcripts are not committed by default.
- Source records matching secret patterns are refused by default.
- Redaction runs before summarization and evidence rendering.
- Credentials must never be committed.
- Keep this repository private.
