---
name: setup-my-precious
description: Configure or create a private agent-session memory archive when the user invokes $setup-my-precious or asks to set up, initialize, create, configure, or connect a My Precious memory repository. Guide the user to choose local-only storage or Git-backed/GitHub-backed storage, ask for the needed path or repository name, scaffold the archive template, and keep credentials and raw transcripts out of committed files.
---

# Setup My Precious

Use this skill to configure the storage side of My Precious. This is a setup-path skill.
Use `using-my-precious` later to search the archive.

## Core Boundary

Set up the archive repository, location-discovery contract, and optional local
read-path runtimes. Do not summarize sessions, schedule recurring archive
updates, upload raw transcripts, or create memory entries in this skill. A
semantic retrieval provider is an optional local read service, not an archive
writer or update scheduler.

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

6. Ask whether the user wants optional local semantic retrieval after the
   archive tools are current. Explain that it downloads roughly 1 GB of pinned
   model files plus an isolated Python environment outside the archive. Ask for
   the service backend: `launchd` on macOS or `none` for manual startup. Do not
   enable a persistent service without explicit approval.

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

6. Verify the search CLI is installed and runnable:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" --help
   ```

   A new empty archive may not have searchable memory records yet; this step only
   confirms the copied tool runs.

7. Before updater, audit, search, or sync work in an existing deployment,
   check the complete reusable runtime tool bundle against this setup skill:

   ```bash
   python scripts/setup_memory_archive.py \
     --path "$MEMORY_REPO" \
     --check-tools \
     --report-json \
     --skip-config
   ```

   `current` is the only safe no-op result. If the report is `drifted`, first
   review a non-mutating repair plan, then refresh only the missing or stale
   source-owned tool files:

   ```bash
   python scripts/setup_memory_archive.py \
     --path "$MEMORY_REPO" \
     --refresh-tools \
     --dry-run \
     --report-json \
     --skip-config
   ```

   ```bash
   python scripts/setup_memory_archive.py \
     --path "$MEMORY_REPO" \
     --refresh-tools \
     --report-json \
     --skip-config
   ```

   Re-run `--check-tools` and require `current`. Use this for tool drift repair,
   not archive content repair. It must preserve matching tools, extra
   user-owned tools, archive data, indexes, daily records, session summaries,
   source records, and user-owned config. A `blocked` result requires manual
   investigation. Do not use `--force` for this narrow repair.

8. If the user requests local semantic retrieval, require current runtime-tool
   parity, then render the aggregate-only deployment plan:

   ```bash
   python scripts/setup_semantic_retrieval.py \
     --plan \
     --memory-repo "$MEMORY_REPO" \
     --service-backend launchd
   ```

   Review the plan before installation. With explicit approval, install the
   pinned environment, model artifacts, private config, and service:

   ```bash
   python scripts/setup_semantic_retrieval.py \
     --install \
     --memory-repo "$MEMORY_REPO" \
     --service-backend launchd
   ```

   The runtime root defaults to
   `~/.local/share/my-precious/semantic-retrieval`; socket and logs default to
   `~/.local/state/my-precious/semantic-retrieval`; the private config remains
   `~/.config/my-precious/config.json`. All are outside the deployment archive.
   The installer uses a pinned Python dependency set and pinned Hugging Face
   model revisions, downloads only the required model files, writes config and
   launchd definitions atomically with private permissions, and waits for an
   identity-bound health response before enabling the config.

   Verify the complete runtime after installation or repair:

   ```bash
   python scripts/setup_semantic_retrieval.py \
     --check \
     --memory-repo "$MEMORY_REPO" \
     --service-backend launchd
   ```

   `current` is the only enabled-ready result. The provider automatically
   rebuilds its in-memory embeddings after `index/memories.jsonl` changes. A
   query during refresh safely falls back to lexical/FTS retrieval.

   Roll back without deleting models or environments:

   ```bash
   python scripts/setup_semantic_retrieval.py \
     --disable \
     --memory-repo "$MEMORY_REPO" \
     --service-backend launchd
   ```

   Disable unloads the service and marks the private provider config disabled;
   it removes no archive, runtime, or model files.

9. If the user requests scheduling, first verify the archive command exists and runs manually.
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

## Semantic Retrieval Runtime Rules

- Treat semantic retrieval as an optional read-path runtime and keep it outside
  both the reusable source repository and private deployment archive.
- Always run `--plan` before `--install`; enable a launchd service only after
  explicit user approval.
- Refresh the deployment tool bundle before provisioning so the service points
  at the approved provider implementation.
- Keep dependency versions, model revisions, allowed model files, provider
  fingerprint, and current memory-index SHA-256 verifiable.
- Require a user-owned mode-`0600` socket inside a mode-`0700` parent directory.
- Keep model downloads and query-time provider execution separate: installation
  may use the network, while the running provider must force offline mode.
- Do not treat dense similarity alone as answer support. A configured reranker
  score and the normal scope, lifecycle, provenance, summary, and evidence
  checks remain mandatory.
- Provider failure, refresh, timeout, or identity mismatch must fall back to
  lexical/FTS retrieval rather than breaking archive search.

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
- `INDEX.md`, `AGENTS.md`, `config/`, `index/`, `sessions/`, `daily/`, `schemas/`, `tools/search_memory.py`, `tools/update_memory_archive.py`, `tools/capture_explicit_memory.py`, `tools/induction_consolidation_audit.py`, `tools/run_memory_updates.py`, `tools/render_scheduler.py`, `tools/audit_publish_readiness.py`, `tools/repair_publish_surfaces.py`, and `tools/sync_memory_archive.py`
- a Git repository when requested
- an optional private remote when requested and supported
- a local archive-location config at `~/.config/my-precious/config.json` unless skipped
- an optional `AGENT_SESSION_MEMORY_REPO` current-shell override
- when approved, an optional repository-external semantic runtime with pinned
  models, private config, a health-checked service, and a non-destructive
  disable path
