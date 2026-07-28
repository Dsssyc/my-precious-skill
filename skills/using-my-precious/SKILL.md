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
Automatic induction is the default write path for ordinary source records. If
the user explicitly asks to remember, force-save, or distill a short fact, do
not write from this read-path skill; use the deployment repository's
`tools/capture_explicit_memory.py` explicit capture path through
`update-my-precious`.
If the user explicitly corrects or withdraws an earlier explicit memory, use
that same explicit revision path through `update-my-precious`; `operation:
replace` takes `replaces_memory_id`, and `operation: withdraw` takes
`deprecates_memory_id`.

## Locate the Archive

Prefer these locations in order:

1. explicit repository path if the user provided one
2. colocated deployment repository when the script runs from one
3. `AGENT_SESSION_MEMORY_REPO`
4. `AGENT_MEMORY_REPO`
5. `MY_PRECIOUS_CONFIG` or `AGENT_SESSION_MEMORY_CONFIG`
6. `~/.config/my-precious/config.json`
7. `~/repos/agent-memory`

If none exists, say that no local agent memory archive was found.

## Search Workflow

After choosing a repository path, refer to it as `MEMORY_REPO` in commands.

Before searching, divide the requested claims into bounded facets:

- Global user preferences are historical facets. Query them in the user's
  original language, retaining stable technical identifiers, and do not pass
  project context.
- Project history is a historical facet. Query it in the user's original
  language, retaining stable technical identifiers, and pass project context.
- Live repository state is not a memory facet. Inspect the repository for the
  current HEAD, current tests, and current reviewed-code state; never answer
  those claims from memory.

Use at most two context-package queries for each historical facet. An
unsupported broad package with `query.decomposition_recommended: true` is a
bounded split signal, not answer support: split it into the applicable facets
above and retry only within that limit. Do not add unlimited paraphrases or
cross-language translations.

1. Before answering a historical fact, run the machine-readable context package
   first:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth evidence --context-json
   ```

   The package must have `report_kind: memory_recall_context_package`,
   `answerability.status`, and per-hit `query_support.status`. Do not use free-form search output as the answerability source.
   Use free-form search output only for exploration or drilldown after the package decision.

2. For a project-history facet tied to a local project, pass project context:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --project-path "$PWD" --depth evidence --context-json
   ```

   This boosts matching `project_path`, `cwd`, `repository`, or project
   records without hiding cross-project hits. Do not use `--project-path` for
   a global-preference facet.

3. Apply the context-package decision recipe:

   | package state | agent action |
   | --- | --- |
   | supported package -> answer | Answer only from supported active/current memory hits with `query_support.status: supported` plus `summary_drill_paths` and `evidence_drill_paths`. |
   | unsupported package -> abstain | Abstain for that facet. If and only if a broad package recommends decomposition, apply the bounded facet split above; do not infer from related context. |
   | inactive/superseded-only package -> abstain | Treat `answerability.reason: no_active_current_support` as stale support only; prefer current replacements when they are separately supported. |
   | malformed or missing package -> abstain | The agent must fail closed to abstain rather than falling back to free-form output for answerability. |

   Treat active/current hits with weak or missing `query_support` as unsupported
   near-misses even when they have drill paths. For project-tied questions,
   treat `--project-path` as context, not a filter: answer only from supported
   active/current hits whose `layer` and `scope` match the requested
   global/domain/project context. Same-topic project hits from another project
   scope, and project-only support when no project context was provided, are
   unsupported near-misses. A supported package is not
   permission to expose private query text, memory text,
   raw refs, source paths, raw source content, credentials, scheduler state, or
   local private paths. Keep answers bounded to summarized evidence and
   archive-relative summary/evidence drill paths.

   Decide each historical facet independently: answer a supported facet and
   abstain on an unsupported facet without promoting one facet's evidence into
   another. `query.decomposition_recommended` never changes package or per-hit
   answerability. Free-form output never determines answerability.

4. If package-supported evidence needs human-readable exploration, use
   free-form search after the decision:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>"
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth session
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth evidence
   ```

5. Use source depth only when the user explicitly asks for source reachability:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth source --context-json
   ```

   Apply the same package-first decision boundary. For source reachability,
   use `source_refs` status metadata from supported active/current hits; do not
   use free-form source-depth output as source reachability evidence. This
   renders safe source ref status metadata (`source_ref_id`, `status`, and
   `reason`) rather than raw source content.

   A source preview is a separate, explicitly authorized operation after the
   package decision. Select exactly one `source_ref_id` from a supported
   active/current hit, use the explicitly allowed external source root, and
   invoke the resolver:

   ```bash
   python "$MEMORY_REPO/tools/resolve_memory_source.py" "<query>" \
     --repo "$MEMORY_REPO" \
     --source-ref-id "src_<exact-id>" \
     --allow-source-root "/path/to/authorized/source-root" \
     --authorize-source-preview \
     --preview-json
   ```

   Require `report_kind: memory_source_preview_package` and `status: resolved`
   before using its bounded redacted `preview`. Missing authorization, no-hit,
   inactive-only support, a wrong ref, malformed context, path/root or symlink
   escape, source/event hash mismatch, unsupported format, and legacy source
   maps must return no preview. The resolver does not accept `all`, does not
   copy source records into the archive, and must not be bypassed by reading a
   source-map path directly.

6. If the deployment repo has no search tool, use the bundled script:

   ```bash
   python scripts/search_memory.py "<query>" --repo "$MEMORY_REPO" --depth evidence --context-json
   ```

   If the deployment repo has no resolver but does have a compatible copied
   search/updater pair, the bundled resolver may be used with the same exact-ref
   and authorization contract:

   ```bash
   python scripts/resolve_memory_source.py "<query>" --repo "$MEMORY_REPO" \
     --source-ref-id "src_<exact-id>" \
     --allow-source-root "/path/to/authorized/source-root" \
     --authorize-source-preview --preview-json
   ```

7. Read `why:` and `drill:` lines. Prefer high-level memories with strong
   provenance, such as `confidence:high`, `support_count:<n>`,
   `source:explicit`, high-signal `field:<name>` reasons,
   `important-token-coverage`, or `project-context`.
   When lifecycle links show a replacement, prefer the current fact; the old
   fact is superseded rather than deleted, and provenance remains traceable
   through drilldown.

8. Open supporting summaries from `drill:` first. Open `evidence.md` only when
   the summary is insufficient or the user asks for stronger support.

9. Answer from the archive evidence, and mention the archive paths used.
   For a source-grounded answer handoff, Answer from archive evidence only:
   use active/current memory hits, cite supporting summaries or evidence, and
   abstain when support is missing or when the supported hit fails the same
   layer/scope/project-context checks used for the context-package decision.
   A valid handoff carries `support_refs`
   that connect the answer to memory, summary, and evidence layers. Do not
   expose raw refs, raw transcripts, source content, scheduler state,
   credentials, or local private paths.
   The contract phrase is do not expose raw refs.

10. If search returns no relevant result, say that explicitly instead of
   inferring historical facts.

11. Apply supported delivery preferences only after the package decision.
    For a supported copyable goal artifact preference, return the complete
    artifact first inside a single `text` code fence, with no explanatory preamble or epilogue outside the fence.
    Choose an outer fence longer than every backtick run inside the goal so
    nested code examples remain part of one copyable artifact.
    current-turn format instructions take precedence over historical
    preferences: archive abstention does not erase a current-turn instruction.
    If history is unsupported and the current turn
    gives no format instruction, do not invent a historical preference.

## Privacy Rules

- Do not read source events unless the user explicitly asks and the exact-ref
  resolver returns an authorized, integrity-verified, bounded redacted preview.
- Do not paste raw chat transcripts into explicit memory capture; explicit
  capture accepts a short fact through agent-neutral JSONL.
- Do not expose secrets, credentials, cookies, private keys, or unredacted customer data.
- Treat the archive as private even if it is stored in a Git repository.
- Prefer summarized facts and evidence snippets over raw logs.
- Do not write new memory entries from this skill; use the deployment archive tooling for that.

## Archive Contract

Expected deployment repositories expose:

- `INDEX.md` for human-readable recent sessions and unresolved work.
- `memories/global.jsonl`, `memories/domains.jsonl`, `memories/projects.jsonl`,
  and `memories/explicit.jsonl` for layered memory nodes.
- `index/memories.jsonl` for the combined layered-memory search index.
- `index/sessions.jsonl` for one row per archived session.
- `index/decisions.jsonl` for durable decisions.
- `index/unresolved.jsonl` for open follow-up tasks.
- `sessions/YYYY/MM/DD/<session>/summary.md` for per-session summaries.
- `sessions/YYYY/MM/DD/<session>/evidence.md` for supporting excerpts.
- `sessions/YYYY/MM/DD/<session>/source-map.json` for versioned quote-to-source
  locator metadata without raw event text.
- `tools/resolve_memory_source.py` for exact-ref authorized JSONL event preview.

Read `references/archive-format.md` when implementing or debugging a compatible archive.
