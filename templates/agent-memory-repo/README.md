# Agent Memory

Private archive of summarized agent sessions.

This repository is not a raw transcript dump. It stores structured, redacted,
searchable summaries so future agent sessions can recover project decisions,
unresolved work, reusable facts, and user preferences.

## Search

Search starts with high-level memory nodes and can drill down into supporting
sessions and evidence when `index/memories.jsonl` exists:

```bash
python tools/search_memory.py "<query>"
python tools/search_memory.py "<query>" --project-path /path/to/current/project
python tools/search_memory.py "<query>" --preferred-scope domain
python tools/search_memory.py "<query>" --depth session
python tools/search_memory.py "<query>" --depth evidence
```

Use `--depth source` only when source reachability is needed and the user has
explicitly asked for it. The command reports safe source ref metadata
(`source_ref_id`, `status`, and `reason`); it does not print raw source content
or copy raw transcripts into the archive. A short redacted raw-source snippet
requires an explicit preview request:

```bash
python tools/search_memory.py "<query>" --depth source --raw-source-preview all
```
Use `--preferred-scope global|domain|project` when the current task has an
explicit memory layer but cross-layer fallback should remain possible.

Read `why:` and `drill:` lines in search output. Prefer high-level memories
with provenance, then open the supporting summaries or evidence. If no relevant
result exists, say so instead of inferring historical facts.

## Update Now

Run the global updater against a shared source record directory:

```bash
python tools/run_memory_updates.py \
  --source-dir /path/to/session-records \
  --allow-redacted-secrets
```

The global updater reads `config/projects.jsonl`, scans the source directory
for project metadata, registers newly discovered projects, and then runs the
per-project updater for each enabled project. An empty project registry is
valid; the first run bootstraps it from source records that contain project
paths such as `cwd` or `project_path`.

Archive new source records for a project:

```bash
python tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project
```

The updater uses `project-path` as the project scope and high-water-mark key. It
archives source records newer than the latest timestamp already archived for
that project, and also refreshes a previously archived source record when its
current source hash differs from the hash stored in the archive. It prefers
timestamps embedded in source records, then timestamps in file names, and
finally file modification time.

Records with no durable content after filtering are skipped instead of being
archived as placeholder summaries such as `Archive source record for ...`.

`--allow-redacted-secrets` keeps secret detection enabled but allows records to
be archived after recognized patterns have been redacted. Omit it when a human
should inspect secret-like source records before any archive entry is written.

If `source-dir` contains records from multiple projects, add
`--require-project-metadata` so records without explicit project path metadata
are skipped.

Repair old generated summaries for a project by replacing existing entries for
the same source records:

```bash
python tools/update_memory_archive.py \
  --source-dir /path/to/session-records \
  --project-path /path/to/project \
  --require-project-metadata \
  --rewrite-existing \
  --allow-redacted-secrets \
  --max-records -1
```

For broad repair of entries already present in the archive, prefer the
meta-driven backfill tool. It rewrites from existing `sessions/**/meta.json`
source pointers instead of repeatedly scanning the full source directory for
every registered project:

```bash
python tools/backfill_memory_archive.py \
  --memory-repo . \
  --allow-redacted-secrets
```

`--rewrite-existing` on `tools/run_memory_updates.py` is still available for
small repositories, but it can be slower on large shared source directories.
Both modes are repair paths, not the normal incremental path.

## Audit

Check generated archive files for wrapper-field noise, first-person process
updates, unredacted key-like values, broken memory drilldown paths, and
unreachable evidence `quote_id` references:

```bash
python tools/audit_memory_archive.py --memory-repo .
```

Run a privacy-safe induction/consolidation audit against generated metadata:

```bash
python tools/induction_consolidation_audit.py --repo .
```

The induction report is aggregate JSON only. It includes candidate, promotion,
process-noise rejection, review reason distribution, overlap buckets, low-risk
review compression, contradiction, supersession reciprocity, evidence
reachability, and real-history privacy-pass metrics without rendering memory
text, source paths, raw refs, or evidence snippets.

Preview lifecycle review decisions without rendering memory text:

```bash
python tools/apply_memory_review_decisions.py --memory-repo . --dry-run
```

Reviewer decisions live in `reviews/memory_lifecycle_decisions.jsonl`. The
dry-run output is aggregate JSON with decision counts, applied/ignored action
counts, and before/after lifecycle relation counts. Use `--write` only after
reviewing the decision file; it rebuilds archive indexes and applies approved
supersession, contradiction, or deprecation links.

Run an aggregate, privacy-safe shadow evaluation against this archive:

```bash
python tools/shadow_eval_memory_archive.py \
  --repo . \
  --cases /path/to/redacted_probe_cases.jsonl \
  --audit-script tools/audit_memory_archive.py \
  --fail-under memory_recall_at_5=1.0 \
  --fail-over top_k_noise_at_5=0.25
```

The shadow report is JSON and intentionally omits memory text, evidence text,
source paths, raw anchors, returned memory IDs, queries, and forbidden-pattern
text. Probe cases can use the legacy `expected_memory_id` field or the plural
`expected_memory_ids` field when a query has several acceptable memory-node
answers. `expected_layer` is a soft preferred layer; `expected_not_memory_id`
checks active-memory suppression; and `forbidden_output_patterns` contains
private or secret-like regular expressions that must not appear in audit/search
outputs. Top-k precision and noise are computed against the full relevant-ID
set, so another listed relevant memory is not counted as noise. Use the report
to inspect recall, active-memory suppression, abstain pass rate, abstain
false-positive result count, lifecycle integrity, top-k noise, noise-source
buckets, provenance coverage, and aggregate case-detail count/status fields
without copying private transcripts or source records elsewhere.
`expected_abstain: true` cases pass only when no memory hits are returned.
`--fail-under`, `--fail-over`, `--fail-under-file`, and
`--fail-over-file` enforce numeric aggregate metrics or dotted metric paths.
Threshold failures print only metric names, actual values, and thresholds; they
do not print the JSON report. Legacy archives without `index/memories.jsonl`
still produce a structural report, but memory top-k metrics remain `null` until
layered memory nodes exist. Invalid `forbidden_output_patterns` regular
expressions fail the run without rendering the pattern text.

## Render Scheduler Config

Generate reviewable scheduler configuration without installing it:

```bash
python tools/render_scheduler.py \
  --source-dir /path/to/session-records \
  --backend launchd \
  --schedule daily \
  --output .tmp/agent-memory.plist
```

Omit `--project-path` for the global runner. Add `--project-path` only when
rendering a scheduler for one specific project.

Render an agent-native automation prompt with a single working directory:

```bash
python tools/render_scheduler.py \
  --source-dir /path/to/session-records \
  --backend agent-native \
  --allow-redacted-secrets \
  --push-after-update \
  --output .tmp/agent-native-update.txt
```

Agent-native automation should use the memory repository as its only working
directory. Multiple working directories may create multiple concurrent
automation conversations.

## Safe Git Sync

After an update, commit and optionally push generated archive changes:

```bash
python tools/sync_memory_archive.py --push
```

The sync helper refuses to proceed when non-archive paths changed, when
generated archive files still contain recognized key-like values, when archive
audit finds low-quality index text, or when `git diff --cached --check` fails.
Expected archive paths are limited to
`INDEX.md`, `config/projects.jsonl`, `index/`, `memories/`, `reviews/`,
`daily/`, and `sessions/`.

## Archive Data

Expected archive data:

- `index/memories.jsonl`
- `index/memory_review_candidates.jsonl`
- `index/induction_review_candidates.jsonl`
- `index/induction_review_decision_results.jsonl`
- `index/memory_consolidation_trace.jsonl`
- `memories/global.jsonl`
- `memories/domains.jsonl`
- `memories/projects.jsonl`
- `memories/explicit.jsonl`
- `reviews/memory_lifecycle_decisions.jsonl` (private review input)
- `reviews/induction_review_decisions.jsonl` (private review input)
- `sessions/YYYY/MM/DD/.../summary.md`
- `sessions/YYYY/MM/DD/.../evidence.md`
- `sessions/YYYY/MM/DD/.../meta.json`
- `sessions/YYYY/MM/DD/.../source-map.json`
- `daily/YYYY/YYYY-MM-DD.md`
- `index/*.jsonl`
- `config/projects.jsonl`

## Security

- Raw transcripts are not committed by default.
- Source records matching secret patterns are refused by default.
- Redaction runs before summarization and evidence rendering.
- Git sync refuses tool/script changes and unredacted key-like values.
- Archive audit refuses wrapper-field noise, first-person process updates, broken memory drilldown paths, and unreachable evidence quote IDs in generated files.
- Shadow evaluation emits aggregate metrics only and should not render raw source content, source paths, returned memory IDs, queries, or forbidden-pattern text.
- Credentials must never be committed.
- Keep this repository private.
