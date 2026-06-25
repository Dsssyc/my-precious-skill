# Using My Precious Archive Format

This reference defines the minimum deployment-repo contract expected by the
`using-my-precious` skill. The format is intentionally agent-neutral.

## Repository Shape

```text
agent-memory/
  AGENTS.md
  INDEX.md
  config/
    projects.jsonl
  memories/
    global.jsonl
    domains.jsonl
    projects.jsonl
    explicit.jsonl
  index/
    memories.jsonl
    sessions.jsonl
    decisions.jsonl
    unresolved.jsonl
    projects.jsonl
    files.jsonl
    tags.jsonl
  sessions/
    YYYY/MM/DD/<stable-session-directory>/
      summary.md
      meta.json
      evidence.md
      redactions.md
      source-map.json
  daily/
    YYYY/YYYY-MM-DD.md
  tools/
    search_memory.py
    update_memory_archive.py
    run_memory_updates.py
    render_scheduler.py
```

`config/projects.jsonl` is runtime configuration for broad scheduled updates.
It is distinct from generated read indexes under `index/`.

`memories/*.jsonl` contains generated or explicit layered memory nodes.
`index/memories.jsonl` is the combined read index searched before session-level
indexes when it exists.

## Stable Fields

`index/sessions.jsonl` should contain one JSON object per session:

```json
{"date":"2026-05-14","session_id":"...","source_agent":"agent","project":"...","title":"...","tags":["..."],"summary_path":"sessions/.../summary.md","evidence_path":"sessions/.../evidence.md","unresolved_count":0}
```

`index/decisions.jsonl` should contain one JSON object per decision:

```json
{"date":"2026-05-14","source_agent":"agent","project":"...","decision":"...","rationale":"...","summary_path":"sessions/.../summary.md","confidence":"high"}
```

`index/unresolved.jsonl` should contain one JSON object per follow-up:

```json
{"date":"2026-05-14","source_agent":"agent","project":"...","task":"...","priority":"medium","summary_path":"sessions/.../summary.md"}
```

## Memory Nodes

Memory nodes are higher-level recall targets induced from session summaries or
created from explicit memory requests. They make global, domain, and project
memories searchable before drilling into event-level session evidence.

Layer files:

- `memories/global.jsonl`: cross-project memory nodes.
- `memories/domains.jsonl`: topic or domain memory nodes.
- `memories/projects.jsonl`: project-scoped memory nodes.
- `memories/explicit.jsonl`: memory nodes created from explicit user requests.
- `index/memories.jsonl`: combined search index for all memory nodes.

Each memory node should contain:

- `memory_id`: stable unique identifier for the memory node.
- `layer`: `global`, `domain`, or `project`.
- `scope`: scope label, such as a project path, repository, domain, or `global`.
- `topic`: short searchable topic.
- `text`: the durable memory statement to recall.
- `rationale`: why the memory should persist.
- `source`: `automatic` for induced nodes or `explicit` for requested memory.
- `confidence`: `low`, `medium`, or `high`.
- `persistence`: `normal` or `sticky`.
- `support_count`: number of supporting sessions or evidence items.
- `first_seen`: first known observation timestamp or date.
- `last_seen`: latest known observation timestamp or date.
- `derived_from`: session summary paths or memory IDs used to derive the node.
- `evidence_refs`: supporting evidence references, usually objects with `path`
  and `quote_id`.
- `raw_refs`: protected source anchors, usually objects with `path` and
  `anchor`.
- `supersedes`: older memory IDs this node replaces.
- `superseded_by`: newer memory ID that replaces this node, or `null`.
- `contradicts`: older memory IDs this node contradicts.
- `contradicted_by`: newer memory IDs that contradict this node.
- `deprecates`: older memory IDs this node retires without replacement.
- `deprecated_by`: newer deprecation marker memory ID that retires this node.
- `tags`: search and filtering tags.

Updater diagnostics may also write internal index sidecars:

- `index/memory_review_candidates.jsonl`: ambiguous semantic lifecycle pairs
  that require manual review before one memory retires another.
- `index/induction_review_candidates.jsonl`: natural induction candidates that
  require manual review before promotion; rows keep aggregate metadata,
  derived-session/evidence/source references, and candidate text hashes rather
  than candidate text.
- `index/memory_consolidation_trace.jsonl`: aggregate decision traces for
  merge, supersede, contradict, deprecate, and skip decisions.

These sidecars should reference memory IDs and decision metadata rather than
raw source content or private natural-language candidate text.

Sessions remain event-level evidence. A memory node should point to session
summaries or evidence snippets for support instead of duplicating the full
event narrative.

`raw_refs` may point to protected source anchors or source-map entries rather
than committed raw files. Compatible archives should not commit raw transcripts
by default. When a `raw_refs` path points at an archive-local `source-map.json`,
the `anchor` must name a key present in that source map. The legacy
`explicit_memory` source-map anchor is treated as a controlled alias for
`source_record`. Search source depth renders stable `source_ref_id`, `status`,
and `reason` fields by default; it does not print raw source content unless an
agent explicitly requests a short redacted preview with
`--raw-source-preview <source_ref_id|all>`.

## Summary Requirements

Each `summary.md` should describe:

- user intent
- context recovered
- reusable facts
- decisions made
- files and code touched
- commands and tools used
- problems encountered
- final state
- unresolved tasks
- search tags

Do not include hidden reasoning chains. Summarize visible interaction, tool
results, decisions, and final outcomes.

## Privacy Requirements

- Raw transcripts are not part of the default committed archive.
- Redaction runs before summarization.
- `redactions.md` records categories and counts, not original secrets.
- Evidence snippets should be short and only support important claims.
- Archives may include multiple source agents, but all entries must state
  `source_agent` when known.
