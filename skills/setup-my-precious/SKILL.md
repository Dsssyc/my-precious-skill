---
name: setup-my-precious
description: Configure or create a private agent-session memory archive when the user invokes $setup-my-precious or asks to set up, initialize, create, configure, or connect a My Precious memory repository. Guide the user to choose local-only storage or Git-backed/GitHub-backed storage, ask for the needed path or repository name, scaffold the archive template, and keep credentials and raw transcripts out of committed files.
---

# Setup My Precious

Use this skill to configure the storage side of My Precious. This is a setup-path skill.
Use `using-my-precious` later to search the archive.

## Core Boundary

Set up the archive repository and location-discovery contract only.
Do not summarize sessions, schedule recurring jobs, upload raw transcripts, or create memory entries in this skill.

## Required Questions

Ask only what is needed, one step at a time:

1. Ask the storage mode:
   - local folder only
   - Git-backed folder with a remote repository

2. Ask for the local archive path.
   - Recommended default: `~/repos/agent-memory`

3. If the user chose a remote repository, ask for the repository name.
   - Accept either `name` or `owner/name`.
   - Default visibility should be private.
   - If the target folder already has Git history, review that history before
     allowing it to be pushed to a hosted repository.

4. Ask before overwriting a non-empty existing directory unless the user explicitly asks to reuse it.

5. Ask whether the user wants scheduling only after a concrete archive command exists.
   - If no archive command exists yet, explain that scheduling can be prepared later but should not be enabled now.
   - If an archive command exists, ask for frequency and scheduler backend.

## Setup Workflow

1. Resolve the path to this skill directory.

2. Scaffold the deployment archive from bundled assets:

   ```bash
   python scripts/setup_memory_archive.py \
     --path "$MEMORY_REPO" \
     --mode local
   ```

3. For a Git-backed remote repository, use:

   ```bash
   python scripts/setup_memory_archive.py \
     --path "$MEMORY_REPO" \
     --mode github \
     --github-repo "$OWNER_OR_REPO" \
     --private
   ```

   If the target already has reviewed Git history that should be published,
   rerun with `--allow-existing-history`. Do not use that flag unless the
   existing commits were inspected for raw transcripts and secrets.

4. Confirm that setup wrote the archive location config. The default config path is:

   ```text
   ~/.config/my-precious/config.json
   ```

   This config is the default persistent discovery mechanism for future
   `using-my-precious` and `update-my-precious` runs.

5. Tell the user the current-shell override only when useful:

   ```bash
   export AGENT_SESSION_MEMORY_REPO="$MEMORY_REPO"
   ```

   Do not edit shell startup files or agent runtime config unless the user
   explicitly asks for persistent environment-variable configuration.

6. Verify search works:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "memory"
   ```

   A new empty archive may return no hits; that is acceptable if the command runs.

7. If the user requests scheduling, first verify the archive command exists and runs manually.
   Then render reviewable scheduler configuration:

   ```bash
   python "$MEMORY_REPO/tools/render_scheduler.py" \
     --source-dir "$SOURCE_RECORD_DIR" \
     --backend launchd \
     --schedule daily \
     --output "$MEMORY_REPO/.tmp/agent-memory.plist"
   ```

   This renders a global runner by default. Add `--project-path "$PROJECT_PATH"`
   only for a single-project schedule.
   For agent-native recurring tasks, render a prompt instead:

   ```bash
   python "$MEMORY_REPO/tools/render_scheduler.py" \
     --source-dir "$SOURCE_RECORD_DIR" \
     --backend agent-native \
     --allow-redacted-secrets \
     --push-after-update \
     --output "$MEMORY_REPO/.tmp/agent-native-update.txt"
   ```

   Agent-native recurring tasks should use the deployment repository as their
   only working directory. Do not configure multiple working directories for
   one recurring memory update.

   Install or enable scheduler configuration only with explicit user approval.

## Scheduling Rules

- Treat scheduling as a runtime setup action, not as a development-repo side effect.
- Do not enable a recurring job unless the deployment repository has a concrete archive command.
- Ask for the scheduler backend: local timer system, cron-like scheduler, or a compatible agent-native recurring task when the runtime supports one.
- Prefer global scheduling through `tools/run_memory_updates.py`; it can
  bootstrap an empty `config/projects.jsonl` by scanning source records for
  project metadata, and it can run explicit non-project streams from
  `config/source_streams.jsonl` when a deployment should schedule a stable
  domain/global source stream.
- Prefer generating a reviewable scheduler file or command before loading/enabling it.
- Use `tools/render_scheduler.py` when the deployment repository includes it.
- Use `tools/sync_memory_archive.py --push` for requested automatic Git upload
  instead of hand-staging files in automation prompts.
- Logs should go outside the skill development repository.
- Do not place credentials in scheduler files; rely on the user's existing environment or credential helper.

## Remote Repository Rules

- Prefer private repositories.
- Do not write tokens, passwords, cookies, or private keys into files.
- Use the user's existing Git authentication, Git credential helper, hosted-Git CLI, or available repository tools.
- Refuse to push preexisting Git history unless the user explicitly confirms
  it has been reviewed; the setup script requires `--allow-existing-history`
  for that case.
- If no remote creation tool is available, create the local repository and tell the user the exact remote-add command to run after creating the remote manually.
- Do not push raw transcripts by default.

## Expected Result

A successful setup leaves the user with:

- a local archive directory
- `INDEX.md`, `AGENTS.md`, `config/`, `index/`, `sessions/`, `daily/`, `schemas/`, `tools/search_memory.py`, `tools/update_memory_archive.py`, `tools/induction_consolidation_audit.py`, `tools/run_memory_updates.py`, `tools/render_scheduler.py`, and `tools/sync_memory_archive.py`
- a Git repository when requested
- an optional private remote when requested and supported
- a local archive-location config at `~/.config/my-precious/config.json` unless skipped
- an optional `AGENT_SESSION_MEMORY_REPO` current-shell override
