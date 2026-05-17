---
name: using-my-precious
description: Search a private agent-session memory archive when the user invokes $using-my-precious or when a task refers to previous conversations, prior agent work, historical implementation decisions, unresolved tasks, project history, debugging context, user preferences, or cross-session context recovery. Use with compatible agent archives that expose summary files and JSONL indexes; do not use for self-contained tasks that do not depend on historical context.
---

# Using My Precious

Use this skill to retrieve historical context from a private, summarized agent-session archive.
The archive may contain any compatible agent session summaries, as long as it follows the common summary/index contract.

## Scope

This is a read-path skill. It helps locate and interpret existing memory.
It does not create summaries, schedule archive jobs, upload transcripts, or read raw session logs by default.

## Locate the Archive

Prefer these locations in order:

1. explicit repository path if the user provided one
2. `AGENT_SESSION_MEMORY_REPO`
3. `AGENT_MEMORY_REPO`
4. colocated deployment repository when the script runs from one
5. `MY_PRECIOUS_CONFIG` or `AGENT_SESSION_MEMORY_CONFIG`
6. `~/.config/my-precious/config.json`
7. `~/repos/agent-memory`

If none exists, say that no local agent memory archive was found.

## Search Workflow

After choosing a repository path, refer to it as `MEMORY_REPO` in commands.

1. Run the deployment repo search tool when present:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>"
   ```

2. If the deployment repo has no search tool, use the bundled script:

   ```bash
   python scripts/search_memory.py "<query>" --repo "$MEMORY_REPO"
   ```

3. Open the top matching `summary.md` files first.

4. Open `evidence.md` only when the summary is insufficient or the user asks for stronger support.

5. Answer from the archive evidence, and mention the archive paths used.

6. If search returns no relevant result, say that explicitly instead of inferring historical facts.

## Privacy Rules

- Do not read raw transcripts unless the user explicitly asks and the archive marks them safe to inspect.
- Do not expose secrets, credentials, cookies, private keys, or unredacted customer data.
- Treat the archive as private even if it is stored in a Git repository.
- Prefer summarized facts and evidence snippets over raw logs.
- Do not write new memory entries from this skill; use the deployment archive tooling for that.

## Archive Contract

Expected deployment repositories expose:

- `INDEX.md` for human-readable recent sessions and unresolved work.
- `index/sessions.jsonl` for one row per archived session.
- `index/decisions.jsonl` for durable decisions.
- `index/unresolved.jsonl` for open follow-up tasks.
- `sessions/YYYY/MM/DD/<session>/summary.md` for per-session summaries.
- `sessions/YYYY/MM/DD/<session>/evidence.md` for supporting excerpts.

Read `references/archive-format.md` when implementing or debugging a compatible archive.
