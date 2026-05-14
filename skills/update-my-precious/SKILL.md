---
name: update-my-precious
description: Immediately scan recent agent session/source records and update the private My Precious memory archive when the user invokes $update-my-precious or asks to capture, archive, summarize, refresh, or update memory now. Use the current project path as the high-water-mark key, process only records newer than the latest archived timestamp for that project, generate summaries/indexes in the deployment repository, and avoid committing raw transcripts or secrets.
---

# Update My Precious

Use this skill for an on-demand memory update. It writes new summarized archive entries.
Use `setup-my-precious` first if no archive repository exists. Use `using-my-precious` later to search.

## Core Boundary

Update the private deployment repository, not this skill development repository.
Do not archive raw transcripts by default.
Do not upload credentials, cookies, private keys, or unredacted source records.

## Required Inputs

Resolve or ask for:

1. `MEMORY_REPO`
   - Prefer `AGENT_SESSION_MEMORY_REPO`, then `AGENT_MEMORY_REPO`, then `~/repos/agent-memory`.

2. `PROJECT_PATH`
   - Default to the current working directory.
   - This is the high-water-mark key.

3. `SOURCE_RECORD_DIR`
   - The folder containing session/source records for the current project.
   - Do not blindly scan the whole project root unless the user explicitly says the records are stored there.

## Update Rule

For each project, process only records newer than the latest timestamp already archived for that same `PROJECT_PATH`.

The updater should:

- read the latest archived timestamp from `index/sessions.jsonl` and `sessions/**/meta.json`
- compare candidate source record timestamps against that value
- create new `sessions/YYYY/MM/DD/.../summary.md`, `meta.json`, `evidence.md`, `redactions.md`, and `source-map.json`
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

4. If the dry run selects the expected records, run the update:

   ```bash
   python "$MEMORY_REPO/tools/update_memory_archive.py" \
     --memory-repo "$MEMORY_REPO" \
     --source-dir "$SOURCE_RECORD_DIR" \
     --project-path "$PROJECT_PATH"
   ```

5. If the updater refuses records because secret patterns were found, inspect the source records before deciding whether to rerun with `--allow-redacted-secrets`.

6. Inspect the generated summaries. If the deterministic summary is too weak, improve the generated `summary.md` and `evidence.md` using only redacted source content.

7. Run search verification:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<project or topic query>"
   ```

8. If the deployment repository is Git-backed, show the diff and ask before committing or pushing unless the user already requested that.

## Privacy Rules

- Redact before writing excerpts.
- Keep evidence short.
- Treat generated summaries as reviewable artifacts.
- Do not store raw source records unless the user explicitly asks and the archive is configured for safe raw storage.
- If a source file appears to contain secrets, stop and ask before proceeding.
