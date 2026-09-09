# My Precious Skill

English | [简体中文](README.zh-CN.md)

`my-precious-skill` provides reusable, agent-neutral skills for a private
session-memory archive. It separates memory operations into setup, write, and
read paths while keeping real memories outside this development repository.

> This repository contains skills, tools, templates, and synthetic tests. It
> must not contain real session memories, raw transcripts, credentials, or
> private archive state.

## Skills

| Skill | Role | Use it when |
| --- | --- | --- |
| [`setup-my-precious`](skills/setup-my-precious/SKILL.md) | Setup | Create or connect a local or private Git-backed archive, and optionally provision local semantic retrieval. |
| [`update-my-precious`](skills/update-my-precious/SKILL.md) | Write | Capture explicit facts or incrementally turn new source records into durable, searchable memory. |
| [`using-my-precious`](skills/using-my-precious/SKILL.md) | Read | Retrieve prior decisions, preferences, project history, unresolved work, and supporting evidence. |

## Quick Start

Give this repository to a compatible agent or skill installer:

```text
https://github.com/Dsssyc/my-precious-skill
```

Then use the skills in order.

1. Create or connect a private archive:

   ```text
   $setup-my-precious create a local private memory archive
   ```

   For Git-backed storage or local semantic retrieval, include that request in
   the same setup conversation.

2. Capture new memory:

   ```text
   $update-my-precious archive new session records for the current project
   ```

3. Retrieve historical context:

   ```text
   $using-my-precious find the previous decisions about the migration strategy
   ```

Setup records the private archive location in
`~/.config/my-precious/config.json`. `AGENT_SESSION_MEMORY_REPO` remains an
optional current-shell override.

## How It Works

1. A source adapter supplies session or event records.
2. The write path redacts sensitive values, extracts durable information, and
   creates summaries, short evidence, indexes, and layered memory nodes.
3. Memory is scoped as `global`, `domain`, or `project`, with provenance and
   lifecycle links kept separately from ranking.
4. The read path uses weighted lexical retrieval, SQLite FTS5 BM25, CJK
   trigrams, and reciprocal-rank fusion. An optional local provider adds
   full-index dense retrieval and cross-encoder reranking.
5. Retrieval returns a machine-readable `memory_recall_context_package` with
   `answerability.status`. An agent answers only from supported, active/current
   memories with summary and evidence paths; otherwise it abstains.

Direct retrieval from a deployment archive looks like this:

```bash
python "$AGENT_SESSION_MEMORY_REPO/tools/search_memory.py" \
  "prior decisions about the migration strategy" \
  --retrieval-mode hybrid_v1 \
  --depth evidence \
  --context-json
```

See [ADR-001](docs/decisions/ADR-001-hybrid-memory-retrieval.md) for the
retrieval design and
[ADR-002](docs/decisions/ADR-002-deploy-semantic-runtime-from-setup-skill.md)
for semantic-runtime deployment and rollback.

## Development Repository vs. Private Archive

This repository owns reusable implementation:

- installable Skill folders and bundled scripts
- the deployment-repository template
- archive schemas and format contracts
- synthetic benchmarks and quality gates
- design decisions and aggregate evaluation records

The private deployment repository owns user-specific runtime state:

- generated `sessions/`, `daily/`, `memories/`, and `index/` data
- project and source-stream registries
- review decisions, scheduling configuration, and local state
- private Git remotes and deployment-specific adapters

The template under [`templates/agent-memory-repo`](templates/agent-memory-repo)
is the source deployment layout. Its bundled copy under the setup skill must
remain byte-for-byte synchronized.

## Repository Layout

```text
skills/                         installable setup, write, and read skills
templates/agent-memory-repo/    source template for private deployments
benchmarks/                     synthetic and aggregate-only quality gates
tests/                          synthetic tests
docs/decisions/                 architecture decision records
docs/evaluations/               evaluation history and current limitations
tools/                          validation and release tooling
```

## Documentation

- [System design](docs/design.md)
- [Archive format contract](skills/using-my-precious/references/archive-format.md)
- [Hybrid retrieval decision](docs/decisions/ADR-001-hybrid-memory-retrieval.md)
- [Semantic runtime deployment decision](docs/decisions/ADR-002-deploy-semantic-runtime-from-setup-skill.md)
- [Recall readiness and known limitations](docs/evaluations/layered-memory-readiness.md)
- [Contributor and release rules](AGENTS.md)

The Skill files are the operational source of truth. Design documents explain
why the system is structured this way; evaluation documents record measured
capabilities and limits. The README intentionally does not duplicate either.

## Development

Run the canonical release gate before publishing or opening a release PR:

```bash
python3 tools/run_quality_gates.py
```

Useful focused checks:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/validate_skills.py
```

The full verification matrix and template-sync rules live in
[`AGENTS.md`](AGENTS.md).

## Security Boundary

- Redact before summarization or evidence rendering.
- Refuse likely-secret source records by default.
- Keep evidence snippets short and source access explicitly authorized.
- Keep models, virtual environments, credentials, logs, scheduler state, and
  generated private data outside this repository.
- Treat benchmark success as bounded evidence, not proof of universally strong
  recall across every archive and query shape.
