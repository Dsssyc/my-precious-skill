# Layered Memory Recall Design

## Purpose

My Precious should evolve from a project-scoped session archive into a layered
memory recall system. Sessions remain the natural event boundary, but they are
not the highest-level memory unit. The system should automatically distill
reusable memories from many events and let agents drill down from broad memory
to supporting sessions, evidence, and source records when needed.

This design is a specification only. It does not implement the new archive
format or migration.

## Current Mismatch

The current implementation is useful but project-first:

- `update_memory_archive.py` uses `project_path` as the write-path scope and
  high-water-mark key.
- `config/projects.jsonl` is the runtime registry for scheduled updates.
- `session_summary.schema.json` requires `project`.
- Search can see cross-project hits, but project context is still a ranking
  boost rather than a lower-level filter or scope.
- `summary.md`, `evidence.md`, and `source-map.json` provide limited drilldown,
  but raw source reachability is not a first-class recall contract.

The desired system is not merely better ranking. It needs a different ontology:
project is one possible memory scope, not the archive's primary boundary.

## Goals

- Preserve sessions as event-level memories.
- Add higher-level memory nodes for global, domain, and project knowledge.
- Make automatic induction the default memory behavior.
- Support explicit memory creation when the user or system prompt says a fact
  should be remembered.
- Retrieve high-level memory first, then drill down to event details only when
  needed.
- Keep all high-level memories traceable to summaries, evidence, or source
  anchors.
- Keep raw transcripts and source records private, gated, and out of the
  default committed archive.
- Maintain compatibility with existing `sessions/` data during migration.

## Non-Goals

- Do not store real session memories in this development repository.
- Do not default to raw transcript ingestion or raw transcript display.
- Do not replace the existing session archive in one large migration.
- Do not require vector search for the first implementation. Lexical and
  structured indexes should remain explainable and dependency-light.
- Do not let automatic induction create untraceable, source-free "facts."

## Memory Layers

The archive should model memory as layered recall:

```text
L4 global
  Long-lived user preferences, collaboration rules, stable working style,
  strong prohibitions, and facts that apply across projects and domains.

L3 domain/topic
  Reusable technical or process knowledge shared by multiple projects, such as
  Python packaging, Codex skill design, GIS, frontend QA, or memory retrieval.

L2 project
  Repository-specific structure, history, decisions, recurring pitfalls,
  incomplete work, and project-local conventions.

L1 session
  Event-level summaries for individual agent sessions, with short evidence,
  source maps, commands, files touched, final state, and unresolved tasks.

L0 raw/source
  Source records or raw transcript anchors. These are reachable only through
  explicit drilldown and safety gates.
```

The session layer remains important because human memory is event-shaped.
Higher-level memory is semantic knowledge induced from one or more events.

## Default And Explicit Memory

Automatic induction is the default memory behavior. After a session is archived,
an induction pass compares the new event with existing memories and decides
whether to promote, merge, or refresh higher-level memories.

Explicit memory is a stronger write path. It is triggered when the user says to
remember something, or when a Codex/system instruction requires a fact to be
persisted. Explicit memory may write directly to L2, L3, or L4, but it must still
attach evidence or source references.

Automatic memory should be conservative. Explicit memory should be sticky unless
it violates privacy, safety, or archive-boundary rules.

## Induction Operations

The induction pass should support three operations:

- Promote: create a higher-level memory from one or more event-level facts.
- Merge: update an existing memory with new support, wording, examples, or
  refined scope.
- Refresh: mark older memory as superseded, contradicted, or weakened when new
  sessions provide better information.

Older memories should not be silently overwritten. They should carry lifecycle
fields such as `first_seen`, `last_seen`, `support_count`, `supersedes`, and
`superseded_by`.

## Proposed Archive Extension

The first migration should extend, not replace, the current repository shape:

```text
agent-memory/
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
  sessions/
    YYYY/MM/DD/<stable-session-directory>/
      summary.md
      evidence.md
      source-map.json
      meta.json
```

`sessions/` remains the event archive. `memories/` stores durable memory nodes.
`index/memories.jsonl` is the primary search index for layered recall.

## Memory Node Contract

Each higher-level memory node should include:

```json
{
  "memory_id": "mem_...",
  "layer": "global",
  "scope": "global",
  "topic": "agent-collaboration",
  "text": "The user prefers that agents avoid repeated permission prompts after permission has already been granted.",
  "rationale": "This affects local workflow and applies across projects.",
  "source": "explicit",
  "confidence": "high",
  "persistence": "sticky",
  "support_count": 1,
  "first_seen": "2026-06-17T00:00:00Z",
  "last_seen": "2026-06-17T00:00:00Z",
  "derived_from": [
    "sessions/2026/06/17/example-session/summary.md"
  ],
  "evidence_refs": [
    {
      "path": "sessions/2026/06/17/example-session/evidence.md",
      "quote_id": "ev_001"
    }
  ],
  "raw_refs": [
    {
      "path": "source-records/example.jsonl",
      "anchor": "message:42"
    }
  ],
  "supersedes": [],
  "superseded_by": null,
  "tags": ["permissions", "agent-workflow"]
}
```

Required conceptual fields are:

- identity: `memory_id`
- placement: `layer`, `scope`, `topic`
- content: `text`, `rationale`
- provenance: `source`, `derived_from`, `evidence_refs`
- lifecycle: `confidence`, `persistence`, `support_count`, `first_seen`,
  `last_seen`, `supersedes`, `superseded_by`
- retrieval: `tags`

`raw_refs` is optional and should be safe-gated.

## Write Flow

The normal update path should become:

```text
source records / raw transcript anchors
        |
        v
L1 session summary, evidence, source map
        |
        v
automatic induction pass
        |
        v
L2 project, L3 domain, L4 global memory nodes
```

The explicit write path should become:

```text
user/system says "remember this"
        |
        v
direct memory node at L2/L3/L4
        |
        v
attach summary, evidence, or raw source references
```

The updater may keep using `project_path` for discovering and incrementally
processing source records, but the generated memory model should no longer treat
project as the top-level archive boundary.

## Retrieval Flow

Search should return a memory stack rather than only session hits.

Default search should prioritize L4, L3, and L2 memories:

```bash
python tools/search_memory.py "avoid repeated permission prompts"
```

Depth controls should allow drilldown:

```bash
python tools/search_memory.py "avoid repeated permission prompts" --depth memory
python tools/search_memory.py "avoid repeated permission prompts" --depth session
python tools/search_memory.py "avoid repeated permission prompts" --depth evidence
python tools/search_memory.py "avoid repeated permission prompts" --depth source
```

Scope controls should filter or boost without hiding cross-scope context:

```bash
python tools/search_memory.py "packaging issue" --scope domain
python tools/search_memory.py "stale closure" --scope project --project-path "$PWD"
```

The default behavior should be:

1. Recall high-level reusable memory.
2. Show why the memory matched.
3. Show supporting sessions and evidence references.
4. Drill into raw/source anchors only after explicit request and safety checks.

This gives agents usable context first and evidence on demand.

## Search Result Shape

Layered search results should include explainable reasons and drilldown paths:

```text
[global] Avoid repeated permission prompts
  The user prefers that agents avoid repeated permission prompts after
  permission has already been granted.
  why: layer:global source:explicit confidence:high support_count:1
  drill:
    summary: sessions/2026/06/17/example-session/summary.md
    evidence: sessions/2026/06/17/example-session/evidence.md#ev_001
```

Session-only search should remain available for compatibility, but it should not
be the default long-term user experience.

## Privacy And Safety

- Redaction must happen before summary, evidence, or memory-node rendering.
- Raw transcripts are not committed by default.
- Source anchors may exist without exposing raw source content.
- `--depth source` should display source references only when safe. Reading raw
  source content should require explicit user intent.
- Secret-like source records should still be refused by default.
- Automatic induction should not promote process noise, search-verification
  snippets, status chatter, credentials, or raw private content.

## Migration Strategy

1. Compatibility extension:
   - Keep writing `sessions/` and existing indexes.
   - Add `memories/` and `index/memories.jsonl`.
   - Keep old session search working.

2. Automatic induction MVP:
   - Generate candidate memories from structured session fields such as
     `reusable_facts`, `decisions`, `problems`, and `unresolved_tasks`.
   - Classify candidates into global, domain, or project layers using
     conservative rules.
   - Merge with existing memory nodes when the topic and meaning match.

3. Layered retrieval:
   - Search `index/memories.jsonl` by default.
   - Add `--depth` and `--scope` controls.
   - Use `derived_from`, `evidence_refs`, and `raw_refs` for drilldown.

4. Benchmark and audit:
   - Add synthetic tests for layered recall.
   - Add archive audit checks for unsupported memory nodes, broken references,
     unsafe raw refs, and noise promotion.

## Benchmark Targets

The benchmark should evaluate layered memory behavior directly:

- `MemoryRecall@K`: the correct high-level memory node appears in top K.
- `SessionDrilldown@K`: the supporting session appears after drilldown.
- `Answerable@K`: returned memory and evidence are enough to answer the query.
- `SourceReachability`: memory nodes have valid paths to evidence and source
  anchors when source anchors are expected.
- `NoiseRejection`: process/status/search-verification text is not promoted to
  high-level memory.
- `ScopeCalibration`: global, domain, project, session, and source memories are
  classified at the intended layer.

LongMemEval-style retrieval can be adapted, but direct comparison to systems
that store verbatim transcript embeddings should be labeled carefully because My
Precious intentionally emphasizes summarized, redacted, source-traceable memory.

## Acceptance Criteria For The Future Implementation

- Existing session archive tests continue to pass during the compatibility
  phase.
- A synthetic archive can store L2, L3, and L4 memory nodes.
- Automatic induction can promote at least one cross-project reusable memory
  from multiple synthetic sessions.
- Explicit memory can write a sticky high-level memory with evidence references.
- Search returns high-level memory by default and exposes session/evidence/source
  drilldown through depth controls.
- Broken `derived_from`, `evidence_refs`, and unsafe `raw_refs` are detected by
  audit tests.
- Project path remains usable as context, but project is not the required
  top-level recall boundary.
