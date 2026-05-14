# Agent Memory Repository

This private repository stores summarized historical agent sessions.

When a task depends on previous conversations, old decisions, unresolved tasks,
project history, implementation rationale, user preferences, or historical
debugging context:

1. Start with `INDEX.md` and `index/sessions.jsonl`.
2. Run `python tools/search_memory.py "<query>"` when shell access is available.
3. Open the most relevant `sessions/YYYY/MM/DD/.../summary.md` files.
4. Open `evidence.md` only when the summary is insufficient.
5. Do not infer historical facts without checking the archive.
6. Mention the archive file paths used as evidence.
7. Never request or expose raw transcripts unless the user explicitly asks and a security review passes.
8. Treat all content as private.

When the user asks to update memory now:

1. Identify the project path and source record directory.
2. Run `python tools/update_memory_archive.py --source-dir "<records>" --project-path "<project>" --dry-run`.
3. If the selected records look correct, rerun without `--dry-run`.
4. If the updater refuses records because secret patterns were found, inspect the source records before deciding whether to rerun with `--allow-redacted-secrets`.
5. Review generated summaries before committing or pushing.

When the user asks to configure scheduling:

1. Verify `tools/update_memory_archive.py` works manually first.
2. Render scheduler config with `python tools/render_scheduler.py --source-dir "<records>" --project-path "<project>" --backend launchd --schedule daily --output ".tmp/agent-memory.plist"`.
3. Show the rendered config and ask before loading, installing, or enabling any recurring job.
