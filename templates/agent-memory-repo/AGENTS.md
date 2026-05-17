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

1. For broad refreshes, run `python tools/run_memory_updates.py --source-dir "<records>" --dry-run`.
2. For a single project, run `python tools/update_memory_archive.py --source-dir "<records>" --project-path "<project>" --dry-run`.
3. If the selected records look correct, rerun without `--dry-run`.
4. If the updater refuses records because secret patterns were found, inspect the source records before deciding whether to rerun with `--allow-redacted-secrets`.
5. Review generated summaries before committing or pushing.
6. If the user requested automatic Git sync, run `python tools/sync_memory_archive.py --push` instead of hand-staging files.

`tools/sync_memory_archive.py` stages only generated archive paths and refuses
unexpected files such as tool/script edits. Commit template or tool updates
separately before running automatic archive sync.

When `config/projects.jsonl` is empty, the global runner should scan source
records for project metadata and register discovered projects before updating.
Disabled projects in `config/projects.jsonl` must stay disabled even if source
records still mention them.

When the user asks to configure scheduling:

1. Verify `tools/run_memory_updates.py` works manually first for global scheduling, or `tools/update_memory_archive.py` for a single-project schedule.
2. Render global scheduler config with `python tools/render_scheduler.py --source-dir "<records>" --backend launchd --schedule daily --output ".tmp/agent-memory.plist"`.
3. Render agent-native automation prompts with `python tools/render_scheduler.py --source-dir "<records>" --backend agent-native --allow-redacted-secrets --push-after-update --output ".tmp/agent-native-update.txt"`.
4. Add `--project-path "<project>"` only when rendering a single-project scheduler.
5. Agent-native automations should use the memory repository as their only working directory.
6. Show the rendered config or prompt and ask before loading, installing, or enabling any recurring job.
