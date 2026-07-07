# Agent Memory Repository

This private repository stores summarized historical agent sessions.

When a task depends on previous conversations, old decisions, unresolved tasks,
project history, implementation rationale, user preferences, or historical
debugging context:

1. Run `python tools/search_memory.py "<query>"` to start with high-level memory
   nodes when `index/memories.jsonl` exists.
2. Add `--project-path "$PWD"` when the task is tied to the current local
   project.
3. Read `why:` and `drill:` lines, then open supporting summaries before
   evidence.
4. Use `--depth session` when the high-level memory is insufficient.
5. Use `--depth evidence` when a claim needs supporting snippets.
6. Use `--depth source` only when the user explicitly asks for source
   reachability and a security review passes.
7. Do not infer historical facts without checking the archive. If search
   returns no relevant result, say so.
8. Mention the archive file paths used as evidence.
9. Never request or expose raw transcripts unless the user explicitly asks and a security review passes.
10. Treat all content as private.

When the user asks to update memory now:

1. For broad refreshes, run `python tools/run_memory_updates.py --source-dir "<records>" --dry-run`.
2. For a single project, run `python tools/update_memory_archive.py --source-dir "<records>" --project-path "<project>" --dry-run`.
3. If the selected records look correct, rerun without `--dry-run`.
4. If the updater refuses records because secret patterns were found, inspect the source records before deciding whether to rerun with `--allow-redacted-secrets`.
5. Review generated summaries before committing or pushing.
6. If the user requested automatic Git sync, run `python tools/sync_memory_archive.py --push` instead of hand-staging files.

When the user explicitly asks to remember, force-save, or distill a short fact,
automatic induction is the default for ordinary source records, but explicit
requests should use the `tools/capture_explicit_memory.py` explicit capture path.
Write agent-neutral JSONL with `text` plus optional `layer`, `scope`, and
`source`; then run:

```bash
python tools/capture_explicit_memory.py --input /path/to/explicit-memory.jsonl
```

Do not paste raw chat transcripts, message arrays, source content, tool logs, or
automation run notes into explicit capture. Each row should be a short fact.

`tools/sync_memory_archive.py` stages only `INDEX.md`, `config/projects.jsonl`,
`index/`, `daily/`, `memories/explicit.jsonl`, and `sessions/`. It refuses
unexpected files such as tool/script edits, automatic memory/review node files,
and source-stream registry changes. Commit template or tool updates separately
before running automatic archive sync.

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
