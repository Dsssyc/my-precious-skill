---
name: update-my-precious
description: Use when the user invokes $update-my-precious or asks to immediately capture, archive, summarize, refresh, or update the private My Precious memory archive from recent agent session/source records.
---

# Update My Precious

Use this skill for an on-demand memory update. It writes new summarized archive entries.
Use `setup-my-precious` first if no archive repository exists. Use `using-my-precious` later to search.
For scheduled or broad multi-project refreshes, prefer the deployment
repository's `tools/run_memory_updates.py`; this skill is the single-project
on-demand path.

## Core Boundary

Update the private deployment repository, not this skill development repository.
Do not archive raw transcripts by default.
Do not upload credentials, cookies, private keys, or unredacted source records.

## Required Inputs

Resolve or ask for:

1. `MEMORY_REPO`
   - Prefer an explicit path, then the colocated deployment repository when the tool runs from one, then `AGENT_SESSION_MEMORY_REPO`, then `AGENT_MEMORY_REPO`, then setup config (`MY_PRECIOUS_CONFIG`, `AGENT_SESSION_MEMORY_CONFIG`, or `~/.config/my-precious/config.json`), then `~/repos/agent-memory`.

2. `PROJECT_PATH`
   - Default to the current working directory.
   - This is the source-record filtering key and the default archive scope.

3. `ARCHIVE_SCOPE`
   - Optional stable high-water-mark key.
   - Default to the resolved `PROJECT_PATH` for compatibility.
   - Use this only when the archive should treat project as one source context
     rather than the storage boundary, for example `domain:agent-memory`.

4. `SOURCE_RECORD_DIR`
   - The folder containing session/source records for the current project.
   - Do not blindly scan the whole project root unless the user explicitly says the records are stored there.
   - If this folder is shared by multiple projects, add `--require-project-metadata` so unscoped records are skipped.

## Update Rule

Use `ARCHIVE_SCOPE` as the high-water-mark key and `PROJECT_PATH` as the
source-record filtering context. When no explicit `ARCHIVE_SCOPE` is supplied,
the updater uses the resolved `PROJECT_PATH`, preserving the original
single-project behavior. Process records newer than the latest timestamp
already archived for that same archive scope; also refresh a previously
archived source record in that scope when its current source hash differs from
the hash stored in the archive, even if that source record's timestamp is older
than the scope latest timestamp.
Use `--rewrite-existing` only for deliberate backfill/repair runs; it rebuilds
matching source records and replaces older archive entries for the same
archive scope/source record.

The updater should:

- read the latest archived timestamp from `index/sessions.jsonl` and `sessions/**/meta.json`
- compare candidate source record timestamps against that value
- compare each previously archived source record's current hash against the hash in `meta.json`
- create new `sessions/YYYY/MM/DD/.../summary.md`, `meta.json`, `evidence.md`, `redactions.md`, and `source-map.json`
- skip source records that contain no durable user intent, reusable fact, decision, problem, evidence, or follow-up after filtering; do not create placeholder summaries for them
- rebuild `INDEX.md`, `daily/YYYY/YYYY-MM-DD.md`, and JSONL indexes
- leave the archive in a searchable state

## Workflow

1. Locate the deployment repository.

2. Locate the source records folder for the current project.

3. Run a dry run first:

   ```bash
   python "$MEMORY_REPO/tools/update_memory_archive.py" \
     --memory-repo "$MEMORY_REPO" \
     --source-dir "$SOURCE_RECORD_DIR" \
     --project-path "$PROJECT_PATH" \
     --dry-run
   ```

   Add `--archive-scope "$ARCHIVE_SCOPE"` when an explicit non-project scope
   should own the high-water mark.

4. If the dry run selects the expected records, run the update:

   ```bash
   python "$MEMORY_REPO/tools/update_memory_archive.py" \
     --memory-repo "$MEMORY_REPO" \
     --source-dir "$SOURCE_RECORD_DIR" \
     --project-path "$PROJECT_PATH"
   ```

5. If the updater refuses records because secret patterns were found, inspect the source records before deciding whether to rerun with `--allow-redacted-secrets`.

6. Inspect the generated summaries. If the deterministic summary is too weak, improve the generated `summary.md` and `evidence.md` using only redacted source content.

7. Check summary/index quality before treating the update as successful:

   - `title`, `summary`, `reusable_facts`, `decisions`, and `unresolved_tasks` should describe durable user intent, decisions, user-relevant verification outcomes, root causes, constraints, or follow-up work.
   - `title` should be a compact retrieval title, not a long answer excerpt, numbered answer fragment such as `1. ...`, source filename, attachment wrapper, or raw user prompt containing local paths such as `/Users/...`; keep it short enough to scan in search results.
   - `evidence.md` must contain short snippets that support the chosen retrieval title and final state; if a title says a specific test gap, root cause, constraint, or decision exists, at least one evidence bullet should include that same durable claim or its specific entity/error terms.
   - Preserve high-value literal retrieval tokens such as `socks5://127.0.0.1:端口`, `127.0.0.1:7890`, `spurious 502`, `libx265.215.dylib`, `_gdal`, and `osgeo` in summary context, evidence, and tags when they are part of the durable finding.
   - Do not promote source/citation-only lines such as `来源: https://...`, `Sources: ...`, README/doc links, or final-answer citation lists into final state, evidence, or search tags.
   - If a useful finding contains a markdown link to a local path, keep the finding phrase and strip the local link target; do not drop the whole finding or promote the raw worktree prompt.
   - They must not contain wrapper/runtime fields such as `session_meta`, `response_item`, `event_msg`, `base_instructions`, `update_plan`, or injected `AGENTS.md`/`<skill>` text.
   - They must not treat injected environment or policy context as memory: reject `# AGENTS.md`, `<permissions instructions>`, `<environment_context>` and its child tags such as `<cwd>`, `<shell>`, `<timezone>`, and `<filesystem>`, `Approval policy is currently...`, sandbox policy text, and skill descriptions such as `Use when Codex should...`.
   - They must not promote verifier/delegation task prompts such as `You are a read-only verifier...` or continuation scaffolding such as `Continue working toward the active thread goal` into titles, user intent, reusable facts, evidence, decisions, unresolved tasks, or search tags.
   - Standalone review/status labels such as `APPROVED`, `CHANGES_REQUESTED`, `DONE_WITH_CONCERNS`, or `DONE` are not retrieval titles or reusable facts unless attached to a concrete finding.
   - When a durable finding contains a specific entity/error phrase such as `spurious 502`, `libx265.215.dylib`, `_gdal`, `127.0.0.1:7890`, `socks5`, `Local Routing`, or `全局出站代理`, the title should preserve that phrase rather than clipping it away.
   - They must not contain live progress narration such as `process_update`, `I will...`, `I’m checking...`, `我接下来会...`, `现在我会...`, or `继续等最终输出`.
   - They must not contain empty heading fragments such as `验证结果：`, `但阻塞点很明确：`, `Command Status`, or `Tool Calls`; either attach a durable result to the sentence or omit the fragment.
   - They must not promote one-turn updater run status such as `dry run selected records`, `live update`, `secret gate refused`, `source record matched cookie`, or `没有产生新写入` into durable facts, decisions, evidence, titles, or search tags unless the lasting memory is the policy itself.
   - They must not promote operational completion notes such as `git status --short ... clean`, `archive updated`, `committed and pushed`, `repo clean`, `inbox-item`, or `I stopped there...` into durable facts, decisions, evidence, titles, or search tags.
   - They must not create or keep placeholder entries such as `Archive source record for ...` or `Archived source record for ...`; a low-signal source record should be skipped rather than summarized.
   - Redaction category labels such as `private_key`, `bearer_token`, `cookie`, `github_token`, `openai_key`, or `aws_access_key` may appear in `redactions.md` counts, but not in titles, summaries, reusable facts, evidence snippets, decisions, unresolved tasks, or search tags.
   - Search-verification examples such as `CC Switch entry captures...`, `Gridmen 条目能恢复...`, `关键检索排第一`, or `top hit ranked...` should not become durable facts, decisions, evidence, titles, or search tags for the memory-quality session being evaluated.
   - They must not contain final-answer memory citation markup or citation entries such as `<oai-mem-citation>`, `<citation_entries>`, `<rollout_ids>`, or `MEMORY.md:30-51|note=[...]`.
   - They must not promote routine verification checklists such as `unit tests pass`, `archive audit passes`, `skill validators pass`, `py_compile passed`, or `template/script sync checks passed` into reusable facts or search tags.
   - For Codex-style source records, assistant messages marked `phase: commentary` are live status narration and should not be archived as durable memory.
   - Generated summaries should not list source-session tool calls such as `exec_command` or include a `Commands And Tools Used` section unless those commands are themselves the durable fact being remembered.
   - Search tags should be topical/entity/error tokens. Generic archive/runtime/path/test/status tags such as `agent-memory`, `my-precious`, `users`, `soku`, `codespace`, `templates`, `agent-memory-repo`, `subagent`, `secret-pattern`, `validator`, `py_compile`, `unit`, `tests`, `passed`, `latest`, `generic`, `entry`, `usable`, `done`, `changed`, `accepts`, `calls`, `removes`, `until`, `open`, `stronger`, `standalone`, `support`, `setup`, `update_memory_archive.py`, or `test_*.py` are broad tag noise.
   - Empty sections should be omitted, not filled with fallback text such as `No decisions were detected automatically`, `No unresolved tasks were detected automatically`, or `No specific evidence snippets were selected automatically`.
   - `unresolved_tasks` should contain only real follow-up work from the source record; do not create default review placeholders or report zero-work placeholders as memory.
   - If search results are dominated by source filenames like `project: rollout-...jsonl`, long answer excerpts, or broad tag noise instead of meaningful summary text, treat that as a failed update and repair the archive before publishing.

8. Run archive quality verification:

   ```bash
   python "$MEMORY_REPO/tools/audit_memory_archive.py" \
     --memory-repo "$MEMORY_REPO"
   ```

9. Run search verification:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<project or topic query>"
   ```

10. If the deployment repository is Git-backed, show the diff and ask before committing or pushing unless the user already requested that. If automatic commit/push was requested and the deployment repository includes it, run:

   ```bash
   python "$MEMORY_REPO/tools/sync_memory_archive.py" --push
   ```

   This helper should stage only generated archive paths and refuse tool/script
   edits, unredacted key-like values, archive audit findings, or whitespace errors.
   If it reports `README.md` or `tools/` changes, stop the archive publish path.
   Review and commit those reusable tool or documentation changes separately
   before rerunning archive sync.

## Backfill And Repair

When search results are polluted by old generated summaries, run a deliberate
rewrite pass instead of editing index files by hand. If the archive already has
`sessions/**/meta.json`, prefer the deployment repository's meta-driven
backfill tool because it rewrites exactly the recorded source-backed entries:

```bash
python "$MEMORY_REPO/tools/backfill_memory_archive.py" \
  --memory-repo "$MEMORY_REPO" \
  --allow-redacted-secrets
```

For a single polluted source record, scope the repair:

```bash
python "$MEMORY_REPO/tools/backfill_memory_archive.py" \
  --memory-repo "$MEMORY_REPO" \
  --source-record "$SOURCE_RECORD" \
  --allow-redacted-secrets
```

Use the updater's rewrite path when repairing from a known source directory and
project scope:

```bash
python "$MEMORY_REPO/tools/update_memory_archive.py" \
  --memory-repo "$MEMORY_REPO" \
  --source-dir "$SOURCE_RECORD_DIR" \
  --project-path "$PROJECT_PATH" \
  --require-project-metadata \
  --rewrite-existing \
  --allow-redacted-secrets \
  --max-records -1
```

For broad multi-project repair, use the deployment repository runner with the
same `--rewrite-existing` flag. Always run `audit_memory_archive.py` and a
targeted `search_memory.py` query afterward.

## Privacy Rules

- Redact before writing excerpts.
- Keep evidence short.
- Use `--require-project-metadata` for shared source record directories.
- Treat generated summaries as reviewable artifacts.
- Do not store raw source records unless the user explicitly asks and the archive is configured for safe raw storage.
- If a source file appears to contain secrets, stop and ask before proceeding.
