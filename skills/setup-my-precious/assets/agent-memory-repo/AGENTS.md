# Agent Memory Repository

This private repository stores summarized historical agent sessions.

When a task depends on previous conversations, old decisions, unresolved tasks,
project history, implementation rationale, user preferences, or historical
debugging context:

1. Run `python tools/search_memory.py "<query>" --depth evidence --context-json`
   before answering. The JSON must have
   `report_kind: memory_recall_context_package`; use `answerability.status` as
   the answerability boundary.
2. Add `--project-path "$PWD"` to the same context-package command when the
   task is tied to the current local project.
3. Answer only from supported active/current hits and cite listed summary or
   evidence drill paths. If the package is unsupported,
   inactive/superseded-only, malformed, or missing, abstain instead of
   inferring a historical fact.
4. Do not use free-form search output as the answerability source. Use
   free-form search only for exploration or drilldown after the package
   decision.
5. For exploration after the package decision, read `why:` and `drill:` lines,
   then open supporting summaries before evidence.
6. Use `--depth session` when high-level memory exploration is insufficient.
7. Use `--depth evidence` when a package-supported claim needs supporting
   snippets.
8. Use `--depth source` only when the user explicitly asks for source
   reachability and a security review passes.
9. Do not infer historical facts without checking the archive. If search
   returns no relevant result, say so.
10. Mention the archive file paths used as evidence.
11. Never request or expose raw transcripts unless the user explicitly asks and a security review passes.
12. Do not render private query text, memory text, raw refs, source paths,
    credentials, scheduler state, or local private paths.
13. Treat all content as private.

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

When the user explicitly corrects or retracts an earlier explicit memory, use
the explicit revision path in the same adapter. Use `operation: replace` with
`replaces_memory_id` when there is a new current fact. Use `operation:
withdraw` with `deprecates_memory_id` when the old fact should stop being
active without a replacement. Search should prefer the current fact after
replacement; the old fact is superseded rather than deleted, and provenance
remains traceable through memory lifecycle links and evidence drilldown.

`tools/sync_memory_archive.py` stages only `INDEX.md`, `config/projects.jsonl`,
`index/`, `daily/`, `memories/explicit.jsonl`, and `sessions/`. It refuses
unexpected files such as tool/script edits, automatic memory/review node files,
and source-stream registry changes. It also runs
`tools/audit_publish_readiness.py` before staging to reject command progress,
prompt/environment blocks, permission/sandbox chatter, raw source paths/raw
refs/full queries, secret-like values, and generic automation narration in
`daily/` or text-bearing indexed summary fields. The readiness report must stay
aggregate-only: archive-relative paths, categories, and counts, with no matched
private text. Commit template or tool updates separately before running
automatic archive sync.

If readiness blocks on generated `daily/` or text-bearing `index/*.jsonl`
noise derived from structured session metadata, run
`python tools/repair_publish_surfaces.py --apply` before retrying sync. The
repair helper edits only `sessions/**/meta.json`, regenerates derived archive
surfaces through the updater, emits aggregate counts only, and fails closed on
malformed metadata or ambiguous scalar text.

If `tools/search_memory.py "<query>" --depth evidence --context-json` cannot
emit `report_kind: memory_recall_context_package` because the bundled archive
tool is stale, refresh reusable tools from the installed setup skill instead
of using archive sync:

```bash
python /path/to/setup-my-precious/scripts/setup_memory_archive.py \
  --path . \
  --refresh-tools \
  --skip-config
```

This repair updates only `tools/**`. It must not mutate archive data, indexes,
source records, daily records, session summaries, or user-owned config. Commit
tool refreshes separately from automatic archive sync.

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
