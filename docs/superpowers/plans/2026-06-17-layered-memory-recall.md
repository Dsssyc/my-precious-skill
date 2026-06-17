# Layered Memory Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a compatibility-first layered memory recall system where sessions remain event memories, higher-level memory nodes are induced or explicitly written, and search can recall high-level memory before drilling into sessions, evidence, and source anchors.

**Architecture:** Extend the existing archive rather than replacing it. `sessions/` remains the source of event summaries, while new `memories/*.jsonl` files and `index/memories.jsonl` store durable L2/L3/L4 memory nodes with provenance. The updater writes and indexes memory nodes, search prefers memory nodes by default with depth controls, and audit/sync tools treat `memories/` as generated archive data with reference and quality checks.

**Tech Stack:** Python 3 standard library, JSONL, Markdown, `unittest`, existing dependency-free archive tools.

---

## Scope Check

This plan implements the first layered-recall migration described in
`docs/superpowers/specs/2026-06-17-layered-memory-recall-design.md`.

The work is one coherent subsystem because all tasks serve one compatibility
extension:

- add the new memory node archive shape
- generate memory nodes from existing session metadata
- add explicit memory promotion
- search layered memory first
- audit and sync the new generated paths
- document and benchmark the behavior

It deliberately does not add vector search, external databases, hosted sync
changes, or raw transcript storage.

## File Structure

Create:

- `templates/agent-memory-repo/schemas/memory_node.schema.json`
  Defines the JSON contract for L2/L3/L4 memory nodes.
- `skills/setup-my-precious/assets/agent-memory-repo/schemas/memory_node.schema.json`
  Synced template copy.
- `templates/agent-memory-repo/memories/global.jsonl`
  Generated global memory nodes; starts empty in the template.
- `templates/agent-memory-repo/memories/domains.jsonl`
  Generated domain/topic memory nodes; starts empty in the template.
- `templates/agent-memory-repo/memories/projects.jsonl`
  Generated project memory nodes; starts empty in the template.
- `templates/agent-memory-repo/memories/explicit.jsonl`
  Explicitly requested memory nodes; starts empty in the template.
- Matching empty files under `skills/setup-my-precious/assets/agent-memory-repo/memories/`.
- `benchmarks/layered_recall_benchmark.py`
  Synthetic benchmark harness for layered recall metrics.
- `tests/test_layered_recall_benchmark.py`
  Regression tests for benchmark output.

Modify:

- `templates/agent-memory-repo/tools/update_memory_archive.py`
  Generate explicit and induced memory nodes, write `memories/*.jsonl`, and
  rebuild `index/memories.jsonl`.
- `skills/update-my-precious/scripts/update_memory_archive.py`
  Synced copy of the template updater.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py`
  Synced template copy.
- `templates/agent-memory-repo/tools/search_memory.py`
  Prefer `index/memories.jsonl`, add `--depth`, `--scope`, and drilldown output.
- `skills/using-my-precious/scripts/search_memory.py`
  Synced copy of the template search tool.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py`
  Synced template copy.
- `templates/agent-memory-repo/tools/audit_memory_archive.py`
  Include `memories/`, validate memory node fields, and detect broken references.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py`
  Synced template copy.
- `templates/agent-memory-repo/tools/sync_memory_archive.py`
  Allow generated `memories/` paths.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/sync_memory_archive.py`
  Synced template copy.
- `templates/agent-memory-repo/README.md`
  Document layered recall commands and generated memory paths.
- `templates/agent-memory-repo/AGENTS.md`
  Update agent workflow to search high-level memory first and drill down.
- `README.md`, `README.zh-CN.md`, `docs/design.md`
  Document the new archive model from the reusable skill repository.
- `skills/using-my-precious/SKILL.md`
  Teach agents to use depth and scope controls.
- `skills/using-my-precious/references/archive-format.md`
  Add the memory node archive contract.
- `tests/test_update_memory_archive.py`
  Add updater tests for induced and explicit memory nodes.
- `tests/test_search_memory.py`
  Add layered search and drilldown tests.
- `tests/test_audit_memory_archive.py`
  Add memory node reference and noise checks.
- `tests/test_sync_memory_archive.py`
  Add sync-policy coverage for `memories/`.

## Cross-Cutting Sync Commands

Run these after any template tool or template archive-shape change:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cp templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

Then verify byte-for-byte sync:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
```

## Task 1: Add The Memory Node Archive Shape

**Files:**
- Create: `templates/agent-memory-repo/schemas/memory_node.schema.json`
- Create: `templates/agent-memory-repo/memories/global.jsonl`
- Create: `templates/agent-memory-repo/memories/domains.jsonl`
- Create: `templates/agent-memory-repo/memories/projects.jsonl`
- Create: `templates/agent-memory-repo/memories/explicit.jsonl`
- Modify: `templates/agent-memory-repo/README.md`
- Modify: `templates/agent-memory-repo/AGENTS.md`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/...` via sync
- Test: `tests/test_setup_memory_archive.py`

- [ ] **Step 1: Write the failing setup/template test**

Add this test method to `tests/test_setup_memory_archive.py`:

```python
def test_setup_template_includes_layered_memory_shape(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertTrue((memory_repo / "schemas/memory_node.schema.json").exists())
        self.assertTrue((memory_repo / "memories/global.jsonl").exists())
        self.assertTrue((memory_repo / "memories/domains.jsonl").exists())
        self.assertTrue((memory_repo / "memories/projects.jsonl").exists())
        self.assertTrue((memory_repo / "memories/explicit.jsonl").exists())
        self.assertEqual((memory_repo / "memories/global.jsonl").read_text(encoding="utf-8"), "")
        self.assertEqual((memory_repo / "memories/domains.jsonl").read_text(encoding="utf-8"), "")
        self.assertEqual((memory_repo / "memories/projects.jsonl").read_text(encoding="utf-8"), "")
        self.assertEqual((memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"), "")
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_setup_memory_archive.SetupMemoryArchiveTests.test_setup_template_includes_layered_memory_shape -v
```

Expected: FAIL because `schemas/memory_node.schema.json` and `memories/*.jsonl`
do not exist in the setup template.

- [ ] **Step 3: Create the memory node schema**

Create `templates/agent-memory-repo/schemas/memory_node.schema.json`:

```json
{
  "type": "object",
  "required": [
    "memory_id",
    "layer",
    "scope",
    "topic",
    "text",
    "rationale",
    "source",
    "confidence",
    "persistence",
    "support_count",
    "first_seen",
    "last_seen",
    "derived_from",
    "evidence_refs",
    "raw_refs",
    "supersedes",
    "superseded_by",
    "tags"
  ],
  "additionalProperties": false,
  "properties": {
    "memory_id": { "type": "string" },
    "layer": { "type": "string", "enum": ["project", "domain", "global"] },
    "scope": { "type": "string" },
    "topic": { "type": "string" },
    "text": { "type": "string" },
    "rationale": { "type": "string" },
    "source": { "type": "string", "enum": ["automatic", "explicit"] },
    "confidence": { "type": "string", "enum": ["low", "medium", "high"] },
    "persistence": { "type": "string", "enum": ["normal", "sticky"] },
    "support_count": { "type": "integer", "minimum": 1 },
    "first_seen": { "type": "string" },
    "last_seen": { "type": "string" },
    "derived_from": { "type": "array", "items": { "type": "string" } },
    "evidence_refs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "quote_id"],
        "additionalProperties": false,
        "properties": {
          "path": { "type": "string" },
          "quote_id": { "type": "string" }
        }
      }
    },
    "raw_refs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "anchor"],
        "additionalProperties": false,
        "properties": {
          "path": { "type": "string" },
          "anchor": { "type": "string" }
        }
      }
    },
    "supersedes": { "type": "array", "items": { "type": "string" } },
    "superseded_by": { "type": ["string", "null"] },
    "tags": { "type": "array", "items": { "type": "string" } }
  }
}
```

- [ ] **Step 4: Create empty template memory files**

Create these empty files:

```text
templates/agent-memory-repo/memories/global.jsonl
templates/agent-memory-repo/memories/domains.jsonl
templates/agent-memory-repo/memories/projects.jsonl
templates/agent-memory-repo/memories/explicit.jsonl
```

- [ ] **Step 5: Update template docs**

In `templates/agent-memory-repo/README.md`, replace the `## Search` section
with:

```markdown
## Search

Search starts with high-level memory nodes and can drill down into supporting
sessions and evidence:

```bash
python tools/search_memory.py "<query>"
python tools/search_memory.py "<query>" --depth session
python tools/search_memory.py "<query>" --depth evidence
```

Use `--depth source` only when source anchors are needed and the user has
explicitly asked for raw-source reachability. The command reports source
anchors; it does not copy raw transcripts into the archive.
```

In the same file, replace the `## Archive Data` bullet list with:

```markdown
## Archive Data

Expected generated data:

- `memories/global.jsonl`
- `memories/domains.jsonl`
- `memories/projects.jsonl`
- `memories/explicit.jsonl`
- `index/memories.jsonl`
- `sessions/YYYY/MM/DD/.../summary.md`
- `sessions/YYYY/MM/DD/.../evidence.md`
- `sessions/YYYY/MM/DD/.../meta.json`
- `sessions/YYYY/MM/DD/.../source-map.json`
- `daily/YYYY/YYYY-MM-DD.md`
- `index/*.jsonl`
- `config/projects.jsonl`
```

In `templates/agent-memory-repo/AGENTS.md`, replace the search workflow list
with:

```markdown
1. Run `python tools/search_memory.py "<query>"` to start with high-level memory nodes.
2. Use `--depth session` when the high-level memory is insufficient.
3. Use `--depth evidence` when a claim needs supporting snippets.
4. Use `--depth source` only when the user explicitly asks for source reachability and a security review passes.
5. Do not infer historical facts without checking the archive.
6. Mention the archive file paths used as evidence.
7. Never request or expose raw transcripts unless the user explicitly asks and a security review passes.
8. Treat all content as private.
```

- [ ] **Step 6: Sync the template copy**

Run:

```bash
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 7: Run the focused test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_setup_memory_archive -v
```

Expected: PASS, including `test_setup_template_includes_layered_memory_shape`.

- [ ] **Step 8: Commit**

Run:

```bash
git add templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo tests/test_setup_memory_archive.py
git commit -m "feat: add layered memory archive shape"
```

## Task 2: Generate Automatic Memory Nodes From Session Metadata

**Files:**
- Modify: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/update-my-precious/scripts/update_memory_archive.py` via sync
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py` via sync
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Add import helpers for direct unit tests**

At the top of `tests/test_update_memory_archive.py`, add:

```python
import importlib.util
```

Then add this helper near `set_mtime`:

```python
def load_update_module():
    script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()
    spec = importlib.util.spec_from_file_location("update_memory_archive_under_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 2: Write the failing automatic induction unit test**

Add this test method to `UpdateMemoryArchiveTests`:

```python
def test_build_memory_nodes_promotes_cross_project_reusable_fact_to_domain(self):
    module = load_update_module()
    rows = [
        {
            "session_id": "s1",
            "project": "alpha",
            "project_path": "/tmp/alpha",
            "source_record": "/records/alpha.jsonl",
            "source_updated_at": "2026-06-01T10:00:00Z",
            "summary_path": "sessions/2026/06/01/alpha/summary.md",
            "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
            "reusable_facts": [
                "Hybrid lexical search should explain field matches and important token coverage."
            ],
            "decisions": [],
            "unresolved_tasks": [],
            "tags": ["search", "memory"],
        },
        {
            "session_id": "s2",
            "project": "beta",
            "project_path": "/tmp/beta",
            "source_record": "/records/beta.jsonl",
            "source_updated_at": "2026-06-02T10:00:00Z",
            "summary_path": "sessions/2026/06/02/beta/summary.md",
            "evidence_path": "sessions/2026/06/02/beta/evidence.md",
            "reusable_facts": [
                "Hybrid lexical search should explain field matches and important token coverage."
            ],
            "decisions": [],
            "unresolved_tasks": [],
            "tags": ["search", "memory"],
        },
    ]

    nodes = module.build_memory_nodes(rows)

    self.assertEqual(len(nodes), 1)
    self.assertEqual(nodes[0]["layer"], "domain")
    self.assertEqual(nodes[0]["scope"], "domain:memory-retrieval")
    self.assertEqual(nodes[0]["source"], "automatic")
    self.assertEqual(nodes[0]["confidence"], "high")
    self.assertEqual(nodes[0]["support_count"], 2)
    self.assertEqual(nodes[0]["derived_from"], [
        "sessions/2026/06/01/alpha/summary.md",
        "sessions/2026/06/02/beta/summary.md",
    ])
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_build_memory_nodes_promotes_cross_project_reusable_fact_to_domain -v
```

Expected: FAIL with `AttributeError` because `build_memory_nodes` does not
exist.

- [ ] **Step 4: Add memory node helpers to the updater**

In `templates/agent-memory-repo/tools/update_memory_archive.py`, add this
dataclass after `MemoryEvent`:

```python
@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    rationale: str
    source: str
    topic: str
    project: str
    project_path: str
    summary_path: str
    evidence_path: str
    source_record: str
    source_updated_at: str
    tags: tuple[str, ...]
```

Add these constants after `REDACTION_CATEGORY_LABELS`:

```python
MEMORY_LAYER_FILES = {
    "global": "global.jsonl",
    "domain": "domains.jsonl",
    "project": "projects.jsonl",
}
MEMORY_TOPIC_HINTS = (
    ("memory-retrieval", ("memory", "recall", "retrieval", "search", "index", "archive")),
    ("agent-workflow", ("agent", "codex", "skill", "permission", "authorization", "workflow")),
    ("python-packaging", ("python", "pip", "package", "venv", "wheel", "import")),
    ("frontend-qa", ("frontend", "browser", "playwright", "viewport", "layout", "css")),
    ("git-workflow", ("git", "commit", "branch", "worktree", "merge", "sync")),
)
GLOBAL_MEMORY_HINTS = (
    "user prefers",
    "user wants",
    "the user prefers",
    "the user wants",
    "用户希望",
    "用户偏好",
    "不要反复",
    "强制记忆",
)
```

Add these functions before `collect_meta`:

```python
def normalize_memory_text(text: str) -> str:
    return compact_whitespace(text).strip(" -")


def memory_topic(text: str, tags: Iterable[str]) -> str:
    lowered = " ".join([text, *tags]).lower()
    for topic, hints in MEMORY_TOPIC_HINTS:
        if any(hint in lowered for hint in hints):
            return topic
    return "general"


def automatic_memory_layer(candidate: MemoryCandidate, support_projects: set[str]) -> str:
    lowered = candidate.text.lower()
    if any(hint in lowered for hint in GLOBAL_MEMORY_HINTS):
        return "global"
    if len(support_projects) >= 2:
        return "domain"
    return "project"


def memory_scope(layer: str, candidate: MemoryCandidate) -> str:
    if layer == "global":
        return "global"
    if layer == "domain":
        return f"domain:{candidate.topic}"
    project_key = candidate.project_path or candidate.project
    return f"project:{project_key}"


def memory_id_for(layer: str, scope: str, text: str, source: str) -> str:
    digest = hashlib.sha256(f"{layer}\n{scope}\n{source}\n{normalize_memory_text(text).lower()}".encode("utf-8")).hexdigest()
    return f"mem_{digest[:16]}"


def iter_memory_candidate_texts(row: dict[str, object]) -> Iterable[tuple[str, str]]:
    fields = (
        ("reusable_facts", "Reusable fact from archived session."),
        ("decisions", "Decision captured in archived session."),
        ("unresolved_tasks", "Unresolved task captured in archived session."),
    )
    for key, rationale in fields:
        value = row.get(key)
        if isinstance(value, list):
            for item in value:
                text = normalize_memory_text(str(item))
                if text and not is_noisy_text(text):
                    yield text, rationale


def memory_candidates_from_meta(rows: list[dict]) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    for row in rows:
        tags = tuple(str(tag) for tag in row.get("tags", []) if isinstance(tag, (str, int, float)))
        for text, rationale in iter_memory_candidate_texts(row):
            candidates.append(
                MemoryCandidate(
                    text=text,
                    rationale=rationale,
                    source="automatic",
                    topic=memory_topic(text, tags),
                    project=str(row.get("project", "")),
                    project_path=str(row.get("project_path", "")),
                    summary_path=str(row.get("summary_path", "")),
                    evidence_path=str(row.get("evidence_path", "")),
                    source_record=str(row.get("source_record", "")),
                    source_updated_at=str(row.get("source_updated_at", "")),
                    tags=tags,
                )
            )
    return candidates


def build_memory_nodes(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[MemoryCandidate]] = {}
    for candidate in memory_candidates_from_meta(rows):
        key = normalize_memory_text(candidate.text).lower()
        grouped.setdefault(key, []).append(candidate)

    nodes: list[dict] = []
    for normalized_text in sorted(grouped):
        candidates = grouped[normalized_text]
        first = candidates[0]
        support_projects = {candidate.project_path or candidate.project for candidate in candidates if candidate.project_path or candidate.project}
        layer = automatic_memory_layer(first, support_projects)
        scope = memory_scope(layer, first)
        first_seen = min(candidate.source_updated_at for candidate in candidates if candidate.source_updated_at)
        last_seen = max(candidate.source_updated_at for candidate in candidates if candidate.source_updated_at)
        derived_from = sorted({candidate.summary_path for candidate in candidates if candidate.summary_path})
        evidence_refs = [
            {"path": path, "quote_id": f"ev_{idx:03d}"}
            for idx, path in enumerate(sorted({candidate.evidence_path for candidate in candidates if candidate.evidence_path}), 1)
        ]
        raw_refs = [
            {"path": path, "anchor": "source_record"}
            for path in sorted({candidate.source_record for candidate in candidates if candidate.source_record})
        ]
        confidence = "high" if len(candidates) >= 2 or layer == "global" else "medium"
        tags = sorted({tag for candidate in candidates for tag in candidate.tags if tag})
        if first.topic not in tags:
            tags.append(first.topic)
        text = first.text
        nodes.append(
            {
                "memory_id": memory_id_for(layer, scope, text, first.source),
                "layer": layer,
                "scope": scope,
                "topic": first.topic,
                "text": text,
                "rationale": first.rationale,
                "source": first.source,
                "confidence": confidence,
                "persistence": "normal",
                "support_count": len(candidates),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "derived_from": derived_from,
                "evidence_refs": evidence_refs,
                "raw_refs": raw_refs,
                "supersedes": [],
                "superseded_by": None,
                "tags": tags,
            }
        )
    return nodes
```

Use the existing `compact_whitespace` helper already present in the updater.

- [ ] **Step 5: Run the focused unit test and verify it passes**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_build_memory_nodes_promotes_cross_project_reusable_fact_to_domain -v
```

Expected: PASS.

- [ ] **Step 6: Write the failing integration test for generated memory files**

Add this test method to `UpdateMemoryArchiveTests`:

```python
def test_update_memory_archive_writes_memory_files_and_index(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        source_dir = root / "records"
        project_path = root / "project"
        source_dir.mkdir()
        project_path.mkdir()

        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        source = source_dir / "session.jsonl"
        source.write_text(
            '{"role":"user","content":"Need searchable memory nodes for layered recall."}\n'
            '{"role":"assistant","content":"Decision: Hybrid lexical search should explain field matches and important token coverage."}\n',
            encoding="utf-8",
        )
        set_mtime(source, "2026-06-03T10:00:00Z")

        update_script = Path("skills/update-my-precious/scripts/update_memory_archive.py").resolve()
        subprocess.run(
            [
                sys.executable,
                str(update_script),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(source_dir),
                "--project-path",
                str(project_path),
                "--project",
                "layered",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertTrue((memory_repo / "index/memories.jsonl").exists())
        memory_index = (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8")
        self.assertIn("Hybrid lexical search", memory_index)
        self.assertTrue((memory_repo / "memories/projects.jsonl").exists())
        self.assertIn("Hybrid lexical search", (memory_repo / "memories/projects.jsonl").read_text(encoding="utf-8"))
```

- [ ] **Step 7: Run the integration test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_writes_memory_files_and_index -v
```

Expected: FAIL because `index/memories.jsonl` is not written.

- [ ] **Step 8: Write memory files from `rebuild_indexes`**

In `templates/agent-memory-repo/tools/update_memory_archive.py`, add this
function before `rebuild_indexes`:

```python
def write_memory_nodes(memory_repo: Path, nodes: list[dict]) -> None:
    memories_dir = memory_repo / "memories"
    memories_dir.mkdir(parents=True, exist_ok=True)
    by_layer: dict[str, list[dict]] = {"global": [], "domain": [], "project": []}
    explicit_nodes: list[dict] = []
    for node in nodes:
        layer = str(node.get("layer", "project"))
        if node.get("source") == "explicit":
            explicit_nodes.append(node)
        if layer in by_layer:
            by_layer[layer].append(node)

    for layer, file_name in MEMORY_LAYER_FILES.items():
        lines = [json.dumps(node, sort_keys=True) for node in by_layer[layer]]
        (memories_dir / file_name).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    explicit_lines = [json.dumps(node, sort_keys=True) for node in explicit_nodes]
    (memories_dir / "explicit.jsonl").write_text(
        "\n".join(explicit_lines) + ("\n" if explicit_lines else ""),
        encoding="utf-8",
    )
```

In `rebuild_indexes`, after `rows = collect_meta(memory_repo)`, add:

```python
    memory_nodes = build_memory_nodes(rows)
    write_memory_nodes(memory_repo, memory_nodes)
```

After writing `index/tags.jsonl`, add:

```python
    memory_lines = [json.dumps(node, sort_keys=True) for node in memory_nodes]
    (index_dir / "memories.jsonl").write_text(
        "\n".join(memory_lines) + ("\n" if memory_lines else ""),
        encoding="utf-8",
    )
```

- [ ] **Step 9: Sync updater copies**

Run:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 10: Run update tests**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

Run:

```bash
git add templates/agent-memory-repo skills/update-my-precious/scripts/update_memory_archive.py skills/setup-my-precious/assets/agent-memory-repo tests/test_update_memory_archive.py
git commit -m "feat: generate layered memory nodes"
```

## Task 3: Add Explicit Memory Detection And Sticky Nodes

**Files:**
- Modify: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/update-my-precious/scripts/update_memory_archive.py` via sync
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py` via sync
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Write the failing explicit-memory integration test**

Add this method to `UpdateMemoryArchiveTests`:

```python
def test_update_memory_archive_promotes_explicit_memory_as_sticky_global_node(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        source_dir = root / "records"
        project_path = root / "project"
        source_dir.mkdir()
        project_path.mkdir()

        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        source = source_dir / "explicit.jsonl"
        source.write_text(
            json.dumps({"role": "user", "content": "记住这个：已经授权后不要反复请求权限确认。"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        set_mtime(source, "2026-06-04T10:00:00Z")

        update_script = Path("skills/update-my-precious/scripts/update_memory_archive.py").resolve()
        subprocess.run(
            [
                sys.executable,
                str(update_script),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(source_dir),
                "--project-path",
                str(project_path),
                "--project",
                "layered",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        rows = [
            json.loads(line)
            for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        explicit = [row for row in rows if row["source"] == "explicit"]
        self.assertEqual(len(explicit), 1)
        self.assertEqual(explicit[0]["layer"], "global")
        self.assertEqual(explicit[0]["scope"], "global")
        self.assertEqual(explicit[0]["confidence"], "high")
        self.assertEqual(explicit[0]["persistence"], "sticky")
        self.assertIn("已经授权后不要反复请求权限确认", explicit[0]["text"])
        self.assertIn(explicit[0], [json.loads(line) for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()])
```

- [ ] **Step 2: Run the explicit-memory test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_promotes_explicit_memory_as_sticky_global_node -v
```

Expected: FAIL because explicit memory is not detected or written.

- [ ] **Step 3: Add explicit memory extraction helpers**

In `templates/agent-memory-repo/tools/update_memory_archive.py`, add these
patterns after `GLOBAL_MEMORY_HINTS`:

```python
EXPLICIT_MEMORY_PATTERNS = (
    re.compile(r"(?i)\bremember this\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"(?i)\bplease remember\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"记住这个\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"强制记忆\s*[:：]\s*(?P<text>.+)$"),
)
```

Add these functions before `memory_candidates_from_meta`:

```python
def extract_explicit_memory_texts(events: list[MemoryEvent]) -> list[str]:
    texts: list[str] = []
    for event in events:
        if event.kind != "user":
            continue
        compacted = compact_whitespace(event.text)
        for pattern in EXPLICIT_MEMORY_PATTERNS:
            match = pattern.search(compacted)
            if not match:
                continue
            text = normalize_memory_text(match.group("text"))
            if text and not is_noisy_text(text) and text not in texts:
                texts.append(text)
    return texts


def explicit_memory_node(text: str, row: dict[str, object]) -> dict:
    tags = [str(tag) for tag in row.get("tags", []) if isinstance(tag, (str, int, float))]
    topic = memory_topic(text, tags)
    source_updated_at = str(row.get("source_updated_at", ""))
    summary_path = str(row.get("summary_path", ""))
    evidence_path = str(row.get("evidence_path", ""))
    source_record = str(row.get("source_record", ""))
    layer = "global"
    scope = "global"
    return {
        "memory_id": memory_id_for(layer, scope, text, "explicit"),
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": text,
        "rationale": "Explicit memory requested by the user or governing prompt.",
        "source": "explicit",
        "confidence": "high",
        "persistence": "sticky",
        "support_count": 1,
        "first_seen": source_updated_at,
        "last_seen": source_updated_at,
        "derived_from": [summary_path] if summary_path else [],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_explicit_001"}] if evidence_path else [],
        "raw_refs": [{"path": source_record, "anchor": "explicit_memory"}] if source_record else [],
        "supersedes": [],
        "superseded_by": None,
        "tags": sorted(set([*tags, topic, "explicit-memory"])),
    }
```

- [ ] **Step 4: Persist explicit memories in session metadata**

In `write_record`, after `summary_data = summarize_events(source_events, project_name)`, add:

```python
    explicit_memories = extract_explicit_memory_texts(source_events)
```

In the `meta` dictionary, add:

```python
        "explicit_memories": explicit_memories,
```

- [ ] **Step 5: Include explicit nodes in `build_memory_nodes`**

At the end of `build_memory_nodes`, before `return nodes`, add:

```python
    existing_ids = {str(node["memory_id"]) for node in nodes}
    for row in rows:
        explicit_texts = row.get("explicit_memories", [])
        if not isinstance(explicit_texts, list):
            continue
        for text_value in explicit_texts:
            text = normalize_memory_text(str(text_value))
            if not text:
                continue
            node = explicit_memory_node(text, row)
            if node["memory_id"] in existing_ids:
                continue
            nodes.append(node)
            existing_ids.add(str(node["memory_id"]))
    nodes.sort(key=lambda node: (str(node.get("layer", "")), str(node.get("memory_id", ""))))
```

- [ ] **Step 6: Sync updater copies**

Run:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 7: Run focused and full update tests**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_promotes_explicit_memory_as_sticky_global_node -v
python3 -m unittest tests.test_update_memory_archive -v
```

Expected: both commands PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add templates/agent-memory-repo skills/update-my-precious/scripts/update_memory_archive.py skills/setup-my-precious/assets/agent-memory-repo tests/test_update_memory_archive.py
git commit -m "feat: support explicit layered memories"
```

## Task 4: Search Layered Memory First With Depth And Scope Controls

**Files:**
- Modify: `templates/agent-memory-repo/tools/search_memory.py`
- Modify: `skills/using-my-precious/scripts/search_memory.py` via sync
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py` via sync
- Test: `tests/test_search_memory.py`

- [ ] **Step 1: Write the failing default layered-search test**

Add this method to `SearchMemoryTests`:

```python
def test_search_memory_prefers_memory_nodes_by_default(self):
    script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "agent-memory"
        repo.mkdir()
        (repo / "index").mkdir()
        (repo / "sessions/2026/06/04/source").mkdir(parents=True)
        (repo / "sessions/2026/06/04/source/summary.md").write_text(
            "# Session: explicit permission preference\n",
            encoding="utf-8",
        )
        (repo / "sessions/2026/06/04/source/evidence.md").write_text(
            "# Evidence\n- 用户说：已经授权后不要反复请求权限确认。\n",
            encoding="utf-8",
        )
        (repo / "index/memories.jsonl").write_text(
            json.dumps(
                {
                    "memory_id": "mem_permission",
                    "layer": "global",
                    "scope": "global",
                    "topic": "agent-workflow",
                    "text": "已经授权后不要反复请求权限确认。",
                    "rationale": "Explicit user preference applies across projects.",
                    "source": "explicit",
                    "confidence": "high",
                    "persistence": "sticky",
                    "support_count": 1,
                    "first_seen": "2026-06-04T10:00:00Z",
                    "last_seen": "2026-06-04T10:00:00Z",
                    "derived_from": ["sessions/2026/06/04/source/summary.md"],
                    "evidence_refs": [{"path": "sessions/2026/06/04/source/evidence.md", "quote_id": "ev_001"}],
                    "raw_refs": [{"path": "/records/explicit.jsonl", "anchor": "explicit_memory"}],
                    "supersedes": [],
                    "superseded_by": None,
                    "tags": ["permissions", "agent-workflow"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (repo / "index/sessions.jsonl").write_text(
            '{"date":"2026-06-04","project":"layered","title":"permission session",'
            '"summary":"已经授权后不要反复请求权限确认。",'
            '"summary_path":"sessions/2026/06/04/source/summary.md"}\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(script), "授权后不要反复请求权限", "--repo", str(repo)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    first_hit = result.stdout.split("\n\n", 2)[1]
    self.assertIn("[global]", first_hit)
    self.assertIn("source: explicit", first_hit)
    self.assertIn("drill:", first_hit)
    self.assertIn("sessions/2026/06/04/source/summary.md", first_hit)
```

- [ ] **Step 2: Run the default layered-search test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_search_memory.SearchMemoryTests.test_search_memory_prefers_memory_nodes_by_default -v
```

Expected: FAIL because current search formats only generic index/session hits.

- [ ] **Step 3: Extend `Hit` and memory collection**

In `templates/agent-memory-repo/tools/search_memory.py`, replace the `Hit`
dataclass with:

```python
@dataclass
class Hit:
    path: Path
    score: int
    source: str
    why: list[str]
    title: str = ""
    layer: str = ""
    scope: str = ""
    text: str = ""
    drill_paths: tuple[str, ...] = ()
    raw_refs: tuple[str, ...] = ()
```

Add `"text"`, `"rationale"`, `"topic"`, `"scope"`, `"layer"`, and
`"memory_id"` to the `field_weights` tuple in `score_index_record`:

```python
        ("text", 15),
        ("rationale", 8),
        ("topic", 6),
        ("scope", 6),
        ("layer", 4),
        ("memory_id", 1),
```

Add this function before `collect_index_hits`:

```python
def collect_memory_hits(repo: Path, query_tokens: list[str], context_terms: list[str] | None = None, scope: str = "all") -> list[Hit]:
    index_path = repo / "index" / "memories.jsonl"
    hits: list[Hit] = []
    for record in iter_jsonl(index_path):
        layer = str(record.get("layer", ""))
        if scope != "all" and layer != scope:
            continue
        score, matched, reasons = score_index_record(query_tokens, record, context_terms)
        if not score:
            continue
        derived_from = tuple(str(path) for path in record.get("derived_from", []) if isinstance(path, str))
        evidence_refs = record.get("evidence_refs", [])
        evidence_paths = tuple(
            str(ref.get("path"))
            for ref in evidence_refs
            if isinstance(ref, dict) and isinstance(ref.get("path"), str)
        )
        raw_refs = record.get("raw_refs", [])
        raw_paths = tuple(
            f"{ref.get('path')}#{ref.get('anchor')}"
            for ref in raw_refs
            if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("anchor"), str)
        )
        path = safe_index_record_path(repo, index_path, derived_from[0] if derived_from else "")
        why = [
            "index:memories.jsonl",
            f"layer:{layer}",
            f"source:{record.get('source', '')}",
            f"confidence:{record.get('confidence', '')}",
            f"support_count:{record.get('support_count', '')}",
            *reasons,
            f"matched:{', '.join(matched)}",
        ]
        hits.append(
            Hit(
                path=path,
                score=score + 100,
                source="memory",
                why=why,
                title=clip(str(record.get("text", ""))),
                layer=layer,
                scope=str(record.get("scope", "")),
                text=str(record.get("text", "")),
                drill_paths=(*derived_from, *evidence_paths),
                raw_refs=raw_paths,
            )
        )
    return hits
```

- [ ] **Step 4: Add depth and scope arguments**

In `main`, add parser arguments:

```python
    parser.add_argument(
        "--depth",
        choices=("memory", "session", "evidence", "source"),
        default="memory",
        help="Recall depth: memory, session, evidence, or source anchors",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "global", "domain", "project"),
        default="all",
        help="Memory node layer to prefer or filter",
    )
    parser.add_argument(
        "--legacy-sessions",
        action="store_true",
        help="Search session indexes and markdown as the primary result set",
    )
```

Replace the `hits = merge_hits(...)` block with:

```python
    memory_hits = collect_memory_hits(repo, query_tokens, context_terms, args.scope)
    session_hits = [
        *collect_index_hits(repo, query_tokens, context_terms),
        *collect_markdown_hits(repo, query_tokens, args.include_evidence or args.depth in {"evidence", "source"}),
    ]
    if args.legacy_sessions:
        hits = merge_hits(repo, session_hits)
    elif memory_hits:
        hits = merge_hits(repo, memory_hits)
        if args.depth in {"session", "evidence", "source"}:
            hits = merge_hits(repo, [*memory_hits, *session_hits])
    else:
        hits = merge_hits(repo, session_hits)
```

- [ ] **Step 5: Format memory hits with drilldown**

Update `format_hit` so the first branch handles `hit.source == "memory"`:

```python
def format_hit(repo: Path, hit: Hit, idx: int, depth: str = "memory") -> str:
    if hit.source == "memory":
        header = f"{idx}. [{hit.layer}] {hit.title or hit.text}"
        why = "; ".join(hit.why)
        lines = [
            header,
            f"   score: {hit.score}",
            f"   source: memory",
            f"   scope: {hit.scope}",
            f"   why: {why}",
        ]
        if hit.drill_paths:
            lines.append("   drill:")
            for path in hit.drill_paths:
                if depth == "memory" and path.endswith("evidence.md"):
                    continue
                lines.append(f"     - {path}")
        if depth == "source" and hit.raw_refs:
            lines.append("   source anchors:")
            for raw_ref in hit.raw_refs:
                lines.append(f"     - {raw_ref}")
        lines.append("   next: use drill paths for supporting sessions and evidence")
        return "\n".join(lines)

    try:
        rel = hit.path.relative_to(repo)
    except ValueError:
        rel = hit.path
    title = f"\n   title: {hit.title}" if hit.title else ""
    why = "; ".join(hit.why)
    next_step = "open summary.md first; inspect evidence.md only if needed"
    if rel.name == "evidence.md":
        next_step = "use only to verify a specific claim"
    elif rel.name == "INDEX.md" or str(rel).startswith("daily/"):
        next_step = "use as overview; then open the linked session summary"
    return (
        f"{idx}. {rel}\n"
        f"   score: {hit.score}\n"
        f"   source: {hit.source}{title}\n"
        f"   why: {why}\n"
        f"   next: {next_step}"
    )
```

Update the print loop:

```python
    for idx, hit in enumerate(hits[: args.limit], 1):
        print(format_hit(repo, hit, idx, args.depth))
        print()
```

- [ ] **Step 6: Run the focused default layered-search test**

Run:

```bash
python3 -m unittest tests.test_search_memory.SearchMemoryTests.test_search_memory_prefers_memory_nodes_by_default -v
```

Expected: PASS.

- [ ] **Step 7: Add source-depth test**

Add this method to `SearchMemoryTests`:

```python
def test_search_memory_depth_source_shows_source_anchors_without_raw_content(self):
    script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "agent-memory"
        repo.mkdir()
        (repo / "index").mkdir()
        (repo / "sessions/2026/06/04/source").mkdir(parents=True)
        (repo / "sessions/2026/06/04/source/summary.md").write_text("# Session\n", encoding="utf-8")
        (repo / "index/memories.jsonl").write_text(
            json.dumps(
                {
                    "memory_id": "mem_source",
                    "layer": "global",
                    "scope": "global",
                    "topic": "agent-workflow",
                    "text": "Do not expose raw transcript content by default.",
                    "rationale": "Privacy boundary.",
                    "source": "automatic",
                    "confidence": "high",
                    "persistence": "normal",
                    "support_count": 2,
                    "first_seen": "2026-06-04T10:00:00Z",
                    "last_seen": "2026-06-04T10:00:00Z",
                    "derived_from": ["sessions/2026/06/04/source/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [{"path": "/records/private.jsonl", "anchor": "message:42"}],
                    "supersedes": [],
                    "superseded_by": None,
                    "tags": ["privacy"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(script), "raw transcript", "--repo", str(repo), "--depth", "source"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    self.assertIn("source anchors:", result.stdout)
    self.assertIn("/records/private.jsonl#message:42", result.stdout)
    self.assertNotIn("raw transcript content copied here", result.stdout)
```

- [ ] **Step 8: Run search tests**

Run:

```bash
python3 -m unittest tests.test_search_memory -v
```

Expected: PASS.

- [ ] **Step 9: Sync search copies**

Run:

```bash
cp templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 10: Run search tests again using synced skill script**

Run:

```bash
python3 -m unittest tests.test_search_memory -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

Run:

```bash
git add templates/agent-memory-repo skills/using-my-precious/scripts/search_memory.py skills/setup-my-precious/assets/agent-memory-repo tests/test_search_memory.py
git commit -m "feat: search layered memory by default"
```

## Task 5: Audit And Sync Layered Memory Safely

**Files:**
- Modify: `templates/agent-memory-repo/tools/audit_memory_archive.py`
- Modify: `templates/agent-memory-repo/tools/sync_memory_archive.py`
- Modify: synced files under `skills/setup-my-precious/assets/agent-memory-repo/tools/`
- Test: `tests/test_audit_memory_archive.py`
- Test: `tests/test_sync_memory_archive.py`

- [ ] **Step 1: Write failing audit test for broken memory references**

Add this method to `AuditMemoryArchiveTests`:

```python
def test_audit_memory_archive_flags_broken_memory_references(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        (memory_repo / "index").mkdir(exist_ok=True)
        (memory_repo / "index/memories.jsonl").write_text(
            json.dumps(
                {
                    "memory_id": "mem_broken",
                    "layer": "global",
                    "scope": "global",
                    "topic": "agent-workflow",
                    "text": "Broken reference should be caught.",
                    "rationale": "Audit must validate drilldown paths.",
                    "source": "automatic",
                    "confidence": "medium",
                    "persistence": "normal",
                    "support_count": 1,
                    "first_seen": "2026-06-05T10:00:00Z",
                    "last_seen": "2026-06-05T10:00:00Z",
                    "derived_from": ["sessions/2026/06/05/missing/summary.md"],
                    "evidence_refs": [{"path": "sessions/2026/06/05/missing/evidence.md", "quote_id": "ev_001"}],
                    "raw_refs": [],
                    "supersedes": [],
                    "superseded_by": None,
                    "tags": ["audit"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    combined = result.stdout + result.stderr
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("category=broken_memory_ref", combined)
    self.assertIn("index/memories.jsonl", combined)
```

- [ ] **Step 2: Run the audit test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive.AuditMemoryArchiveTests.test_audit_memory_archive_flags_broken_memory_references -v
```

Expected: FAIL because memory references are not validated.

- [ ] **Step 3: Extend audit allowed roots and quality extraction**

In `templates/agent-memory-repo/tools/audit_memory_archive.py`, add `"memories"`
to `ALLOWED_ROOTS`.

In `extract_quality_text`, add this entry to `keys_by_file`:

```python
        "index/memories.jsonl": (
            "text",
            "rationale",
            "topic",
            "scope",
            "tags",
        ),
```

- [ ] **Step 4: Add memory reference validation**

In `templates/agent-memory-repo/tools/audit_memory_archive.py`, add these
functions before `audit_repo`:

```python
def iter_memory_index_rows(repo: Path) -> Iterable[tuple[int, dict]]:
    path = repo / "index" / "memories.jsonl"
    if not path.exists():
        return
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            yield line_number, {"__invalid_json__": True}
            continue
        if isinstance(value, dict):
            yield line_number, value


def safe_existing_archive_ref(repo: Path, path_text: str) -> bool:
    if not path_text:
        return False
    candidate = repo / path_text
    try:
        relative = candidate.resolve(strict=False).relative_to(repo.resolve())
    except (OSError, ValueError):
        return False
    if ".." in PurePosixPath(relative.as_posix()).parts:
        return False
    return candidate.exists()


def audit_memory_references(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    required_fields = {
        "memory_id",
        "layer",
        "scope",
        "topic",
        "text",
        "rationale",
        "source",
        "confidence",
        "persistence",
        "support_count",
        "first_seen",
        "last_seen",
        "derived_from",
        "evidence_refs",
        "raw_refs",
        "supersedes",
        "superseded_by",
        "tags",
    }
    for line_number, row in iter_memory_index_rows(repo):
        if row.get("__invalid_json__"):
            findings.append(Finding("index/memories.jsonl", line_number, "invalid_json"))
            continue
        missing = required_fields.difference(row)
        if missing:
            findings.append(Finding("index/memories.jsonl", line_number, "invalid_memory_node"))
            continue
        for path_text in row.get("derived_from", []):
            if not isinstance(path_text, str) or not safe_existing_archive_ref(repo, path_text):
                findings.append(Finding("index/memories.jsonl", line_number, "broken_memory_ref"))
        for ref in row.get("evidence_refs", []):
            path_text = ref.get("path") if isinstance(ref, dict) else ""
            if not isinstance(path_text, str) or not safe_existing_archive_ref(repo, path_text):
                findings.append(Finding("index/memories.jsonl", line_number, "broken_memory_ref"))
    return findings
```

In `audit_repo`, before the `return`, add:

```python
    findings.extend(audit_memory_references(repo))
```

- [ ] **Step 5: Run audit tests**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive -v
```

Expected: PASS.

- [ ] **Step 6: Write failing sync test for memories root**

Open `tests/test_sync_memory_archive.py` and add a test matching its existing
repository setup style. The body should create a Git-backed memory repo, write
`memories/global.jsonl`, and assert `tools/sync_memory_archive.py --dry-run`
does not reject that path:

```python
def test_sync_memory_archive_allows_memories_root(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(["git", "init"], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        subprocess.run(["git", "add", "."], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=memory_repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        (memory_repo / "memories/global.jsonl").write_text(
            '{"memory_id":"mem_sync","layer":"global","text":"Generated memory path is allowed."}\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            [sys.executable, str(memory_repo / "tools/sync_memory_archive.py"), "--memory-repo", str(memory_repo), "--dry-run"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertNotIn("unexpected", result.stdout + result.stderr)
```

If existing sync tests configure Git author identity, reuse that helper rather
than duplicating Git config.

- [ ] **Step 7: Run the sync test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_sync_memory_archive -v
```

Expected: FAIL because `memories/global.jsonl` is not an allowed generated path.

- [ ] **Step 8: Allow `memories/` in sync**

In `templates/agent-memory-repo/tools/sync_memory_archive.py`, update
`ALLOWED_ROOTS`:

```python
ALLOWED_ROOTS = (
    "INDEX.md",
    "config/projects.jsonl",
    "index",
    "daily",
    "sessions",
    "memories",
)
```

- [ ] **Step 9: Sync template copy**

Run:

```bash
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 10: Run audit and sync tests**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive tests.test_sync_memory_archive -v
```

Expected: PASS.

- [ ] **Step 11: Commit**

Run:

```bash
git add templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo tests/test_audit_memory_archive.py tests/test_sync_memory_archive.py
git commit -m "feat: audit and sync layered memories"
```

## Task 6: Add Layered Recall Benchmark Harness

**Files:**
- Create: `benchmarks/layered_recall_benchmark.py`
- Create: `tests/test_layered_recall_benchmark.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Write the failing benchmark test**

Create `tests/test_layered_recall_benchmark.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LayeredRecallBenchmarkTests(unittest.TestCase):
    def test_layered_recall_benchmark_reports_memory_and_session_metrics(self):
        script = Path("benchmarks/layered_recall_benchmark.py").resolve()
        search_script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            (repo / "index").mkdir(parents=True)
            (repo / "sessions/2026/06/04/source").mkdir(parents=True)
            (repo / "sessions/2026/06/04/source/summary.md").write_text("# Session\n", encoding="utf-8")
            (repo / "sessions/2026/06/04/source/evidence.md").write_text("# Evidence\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "Avoid repeated permission prompts after permission is granted.",
                        "rationale": "Explicit user preference.",
                        "source": "explicit",
                        "confidence": "high",
                        "persistence": "sticky",
                        "support_count": 1,
                        "first_seen": "2026-06-04T10:00:00Z",
                        "last_seen": "2026-06-04T10:00:00Z",
                        "derived_from": ["sessions/2026/06/04/source/summary.md"],
                        "evidence_refs": [{"path": "sessions/2026/06/04/source/evidence.md", "quote_id": "ev_001"}],
                        "raw_refs": [{"path": "/records/private.jsonl", "anchor": "message:42"}],
                        "supersedes": [],
                        "superseded_by": None,
                        "tags": ["permissions"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            cases = root / "cases.jsonl"
            cases.write_text(
                json.dumps(
                    {
                        "query": "permission prompts after granted",
                        "expected_memory_id": "mem_permission",
                        "expected_summary_path": "sessions/2026/06/04/source/summary.md",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                    "--search-script",
                    str(search_script),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["cases"], 1)
        self.assertEqual(payload["memory_recall_at_5"], 1.0)
        self.assertEqual(payload["session_drilldown_at_5"], 1.0)
        self.assertEqual(payload["source_reachability"], 1.0)
```

- [ ] **Step 2: Run the benchmark test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_layered_recall_benchmark -v
```

Expected: FAIL because `benchmarks/layered_recall_benchmark.py` does not exist.

- [ ] **Step 3: Implement the benchmark harness**

Create `benchmarks/layered_recall_benchmark.py`:

```python
#!/usr/bin/env python3
"""Run a synthetic layered recall benchmark against a memory archive."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                yield value


def run_search(search_script: Path, repo: Path, query: str, depth: str) -> str:
    result = subprocess.run(
        [sys.executable, str(search_script), query, "--repo", str(repo), "--depth", depth, "--limit", "5"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout + result.stderr


def score_cases(repo: Path, cases: list[dict], search_script: Path) -> dict:
    memory_hits = 0
    session_hits = 0
    reachable = 0
    for case in cases:
        query = str(case["query"])
        expected_memory_id = str(case["expected_memory_id"])
        expected_summary_path = str(case["expected_summary_path"])
        memory_output = run_search(search_script, repo, query, "memory")
        session_output = run_search(search_script, repo, query, "session")
        source_output = run_search(search_script, repo, query, "source")
        if expected_memory_id in memory_output:
            memory_hits += 1
        if expected_summary_path in session_output:
            session_hits += 1
        if expected_summary_path in source_output and "source anchors:" in source_output:
            reachable += 1
    total = len(cases) or 1
    return {
        "cases": len(cases),
        "memory_recall_at_5": memory_hits / total,
        "session_drilldown_at_5": session_hits / total,
        "source_reachability": reachable / total,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Path to the memory archive")
    parser.add_argument("--cases", required=True, help="JSONL benchmark cases")
    parser.add_argument(
        "--search-script",
        default="templates/agent-memory-repo/tools/search_memory.py",
        help="Path to search_memory.py",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    cases = list(iter_jsonl(Path(args.cases).expanduser().resolve()))
    search_script = Path(args.search_script).expanduser().resolve()
    print(json.dumps(score_cases(repo, cases, search_script), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run benchmark tests**

Run:

```bash
python3 -m unittest tests.test_layered_recall_benchmark -v
```

Expected: PASS.

- [ ] **Step 5: Document benchmark usage**

In `README.md`, add a `Layered Recall Benchmark` subsection near the search
documentation:

```markdown
### Layered Recall Benchmark

Synthetic layered recall cases can be checked with:

```bash
python benchmarks/layered_recall_benchmark.py \
  --repo /path/to/agent-memory \
  --cases /path/to/cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py
```

The harness reports `memory_recall_at_5`, `session_drilldown_at_5`, and
`source_reachability`. It is designed for My Precious layered recall, not as a
direct score comparison against systems that store verbatim transcript
embeddings.
```

In `README.zh-CN.md`, add:

```markdown
### 分层召回 Benchmark

可以用合成 case 检查分层召回：

```bash
python benchmarks/layered_recall_benchmark.py \
  --repo /path/to/agent-memory \
  --cases /path/to/cases.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py
```

输出包含 `memory_recall_at_5`、`session_drilldown_at_5` 和
`source_reachability`。这个 benchmark 面向 My Precious 的分层召回，不应该直接
等同于使用原文 transcript embedding 的系统分数。
```

- [ ] **Step 6: Run benchmark and README sanity checks**

Run:

```bash
python3 -m unittest tests.test_layered_recall_benchmark -v
python3 -m py_compile benchmarks/layered_recall_benchmark.py
```

Expected: PASS and py_compile exits 0.

- [ ] **Step 7: Commit**

Run:

```bash
git add benchmarks tests/test_layered_recall_benchmark.py README.md README.zh-CN.md
git commit -m "feat: add layered recall benchmark harness"
```

## Task 7: Update Skill Documentation And Archive Format Contract

**Files:**
- Modify: `skills/using-my-precious/SKILL.md`
- Modify: `skills/using-my-precious/references/archive-format.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/design.md`
- Modify: `templates/agent-memory-repo/README.md`
- Modify: `templates/agent-memory-repo/AGENTS.md`
- Modify: synced template copy under `skills/setup-my-precious/assets/agent-memory-repo/`

- [ ] **Step 1: Update `using-my-precious` search workflow**

In `skills/using-my-precious/SKILL.md`, replace the numbered `Search Workflow`
with:

```markdown
1. Run the deployment repo search tool when present:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>"
   ```

   This starts with high-level layered memory nodes when the archive contains
   `index/memories.jsonl`.

2. When the current task is tied to a local project, pass project context:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --project-path "$PWD"
   ```

3. If high-level memory is insufficient, drill down:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth session
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth evidence
   ```

4. Use source depth only when the user explicitly asks for source reachability:

   ```bash
   python "$MEMORY_REPO/tools/search_memory.py" "<query>" --depth source
   ```

5. If the deployment repo has no search tool, use the bundled script:

   ```bash
   python scripts/search_memory.py "<query>" --repo "$MEMORY_REPO"
   ```

6. Read `why:` and `drill:` lines. Prefer high-level memories with strong
   provenance, then open supporting summaries or evidence.

7. If search returns no relevant result, say that explicitly instead of
   inferring historical facts.
```

- [ ] **Step 2: Update archive format reference**

In `skills/using-my-precious/references/archive-format.md`, add `memories/` and
`index/memories.jsonl` to the repository shape:

```text
  memories/
    global.jsonl
    domains.jsonl
    projects.jsonl
    explicit.jsonl
  index/
    memories.jsonl
```

Add a `## Memory Nodes` section with the same conceptual contract as the design
spec: `memory_id`, `layer`, `scope`, `topic`, `text`, `rationale`, `source`,
`confidence`, `persistence`, `support_count`, `first_seen`, `last_seen`,
`derived_from`, `evidence_refs`, `raw_refs`, `supersedes`, `superseded_by`, and
`tags`.

- [ ] **Step 3: Update design docs**

In `docs/design.md`, add a paragraph to `## Components`:

```markdown
- `memories/*.jsonl` and `index/memories.jsonl`: layered memory nodes induced
  from sessions or created from explicit memory requests. These nodes make
  global, domain, and project memories first-class recall targets while keeping
  sessions as event-level evidence.
```

In `README.md` and `README.zh-CN.md`, update the feature list to mention:

```markdown
- Layered global, domain, and project memory nodes with drilldown to sessions,
  evidence, and source anchors.
```

- [ ] **Step 4: Sync template copy**

Run:

```bash
rsync -a --delete templates/agent-memory-repo/ skills/setup-my-precious/assets/agent-memory-repo/
```

- [ ] **Step 5: Validate skills**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/setup-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/update-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/using-my-precious
```

Expected: all three validations report valid skills.

- [ ] **Step 6: Commit**

Run:

```bash
git add README.md README.zh-CN.md docs/design.md skills/using-my-precious templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
git commit -m "docs: document layered memory recall"
```

## Task 8: Full Verification And Final Cleanup

**Files:**
- Verify all modified files.
- Remove generated caches.

- [ ] **Step 1: Run the full unit suite**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: all tests pass.

- [ ] **Step 2: Compile bundled scripts**

Run:

```bash
python3 -m py_compile \
  benchmarks/layered_recall_benchmark.py \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py
```

Expected: command exits 0.

- [ ] **Step 3: Validate skills**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/setup-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/update-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /Users/soku/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/using-my-precious
```

Expected: all three validations report valid skills.

- [ ] **Step 4: Verify template sync**

Run:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
```

Expected: `diff` prints nothing, both `cmp` commands exit 0.

- [ ] **Step 5: Remove generated caches**

Run:

```bash
rm -rf .uv-cache tests/__pycache__ templates/agent-memory-repo/tools/__pycache__ \
  skills/setup-my-precious/scripts/__pycache__ \
  skills/setup-my-precious/assets/agent-memory-repo/tools/__pycache__ \
  skills/update-my-precious/scripts/__pycache__ \
  skills/using-my-precious/scripts/__pycache__ \
  benchmarks/__pycache__
```

- [ ] **Step 6: Check whitespace and status**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0. `git status --short` shows only intended
tracked modifications, or is clean after the final commit.

- [ ] **Step 7: Final commit if verification changes docs or cleanup**

If Task 8 produces tracked changes, commit them:

```bash
git add README.md README.zh-CN.md docs/design.md skills templates tests benchmarks
git commit -m "chore: verify layered memory recall"
```

Expected: either a small verification commit is created, or there are no tracked
changes left to commit.

## Completion Criteria

- `memories/*.jsonl` exists in new archive templates.
- `index/memories.jsonl` is generated from session metadata.
- Automatic induction creates domain or project memory nodes from durable
  reusable facts, decisions, and unresolved tasks.
- Explicit memory requests create sticky global memory nodes.
- Search returns layered memory nodes by default.
- `--depth session`, `--depth evidence`, and `--depth source` expose drilldown
  without copying raw transcripts into the archive.
- Archive audit validates memory node quality and reference reachability.
- Sync allows generated `memories/` files but still rejects tool/script edits.
- Benchmark harness reports layered recall metrics.
- Template copies and bundled scripts remain byte-for-byte synchronized.
- Full unit suite, py_compile, skill validation, sync checks, and whitespace
  checks pass.
