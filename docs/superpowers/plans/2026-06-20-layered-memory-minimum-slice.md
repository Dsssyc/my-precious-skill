# Layered Memory Minimum Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest verifiable next-generation layered memory slice: session events can induce traceable high-level memories, explicit memories are sticky and evidence-bound, audits reject broken provenance, and the benchmark proves the behavior quantitatively.

**Architecture:** Extend the existing archive shape instead of replacing it. The current repository already has `memories/*.jsonl`, `index/memories.jsonl`, memory-node schema, automatic candidate extraction in `update_memory_archive.py`, explicit-memory extraction, layered search, and audit checks. This plan tightens those paths into an end-to-end contract: session record -> session summary/meta/evidence -> automatic high-level memory node -> durable memory/index rows -> audited/searchable/benchmarked result.

**Tech Stack:** Python standard library only, `unittest`, JSONL archive files, JSON Schema documents used as contract documentation, existing setup/update/search/audit/benchmark tools.

---

## Source Documents

- `docs/evaluations/layered-memory-readiness.md`
- `docs/superpowers/specs/2026-06-17-layered-memory-recall-design.md`
- `templates/agent-memory-repo/schemas/memory_node.schema.json`
- `templates/agent-memory-repo/tools/update_memory_archive.py`
- `templates/agent-memory-repo/tools/audit_memory_archive.py`
- `benchmarks/layered_recall_benchmark.py`

## File Structure

### Existing Files To Modify

- `templates/agent-memory-repo/schemas/memory_node.schema.json`
  - Tighten memory-node contract for non-empty provenance arrays and timestamp strings.
- `skills/setup-my-precious/assets/agent-memory-repo/schemas/memory_node.schema.json`
  - Synced copy of the template schema.
- `templates/agent-memory-repo/tools/audit_memory_archive.py`
  - Enforce provenance/lifecycle contract and source-depth reference safety.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py`
  - Synced copy of the template audit tool.
- `templates/agent-memory-repo/tools/update_memory_archive.py`
  - Keep or tighten automatic induction, add explicit write support if direct CLI is missing, and ensure generated nodes always carry evidence.
- `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py`
  - Synced copy of the template updater.
- `skills/update-my-precious/scripts/update_memory_archive.py`
  - Bundled updater copy.
- `benchmarks/build_synthetic_recall_archive.py`
  - Add synthetic archive construction for induction/explicit/source-depth cases if the existing case-only builder cannot express them.
- `benchmarks/layered_recall_benchmark.py`
  - Add metrics for induced-memory and explicit-memory cases only if existing fields cannot express those gates.
- `benchmarks/cases/layered_recall_synthetic.jsonl`
  - Add a small number of synthetic cases that prove induction, explicit memory, and broken/source-depth gates.
- `benchmarks/quality-gates/layered_recall_synthetic.json`
  - Add lower-bound gates for new denominator counts and pass metrics.
- `benchmarks/quality-gates/layered_recall_synthetic_max.json`
  - Update upper bounds for rank/source counts only when new cases legitimately change them.
- `tests/test_audit_memory_archive.py`
  - Fail-first audit tests for provenance and broken references.
- `tests/test_update_memory_archive.py`
  - Fail-first automatic induction and explicit-memory write tests.
- `tests/test_layered_recall_benchmark.py`
  - Fail-first benchmark/gate tests for new metrics or cases.
- `docs/evaluations/layered-memory-readiness.md`
  - Update the readiness document only after implementation verifies the next slice.

### New Files To Create If Needed

- `tests/fixtures/layered_memory/README.md`
  - Optional documentation for synthetic-only fixtures if test setup becomes hard to read inline.
- `docs/evaluations/layered-memory-minimum-slice-results.md`
  - Optional final results document if the readiness document becomes too broad.

Do not create or commit real session memories, raw transcripts, credentials, local logs, private archive data, or scheduler state.

## Dependency Graph

```text
memory-node contract
  |
  v
audit validation for provenance and lifecycle
  |
  v
automatic induction generation and explicit write generation
  |
  v
search/index output remains compatible
  |
  v
benchmark cases and gates
  |
  v
readiness/result documentation
```

Implementation order follows this graph. Audit and schema must be tightened before benchmark expansion so failures point to archive correctness instead of retrieval scoring ambiguity.

## Phase 1: Schema And Audit Foundation

### Task 1: Require Evidence-Bound Memory Nodes

**Description:** Tighten the memory node contract so durable high-level memories must have at least one session summary reference and one evidence reference. Raw refs remain optional as an empty array, but when present they must be safe archive-relative source references or safe-gated external source anchors already accepted by audit.

**Files:**
- Modify: `templates/agent-memory-repo/schemas/memory_node.schema.json`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/schemas/memory_node.schema.json`
- Modify: `templates/agent-memory-repo/tools/audit_memory_archive.py`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py`
- Test: `tests/test_audit_memory_archive.py`

- [ ] **Step 1: Write the failing audit test for missing provenance**

Add this test near the existing memory reference tests in `tests/test_audit_memory_archive.py`:

```python
def test_audit_memory_archive_flags_memory_nodes_without_required_provenance(self):
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

        missing_derived = valid_memory_node(
            memory_id="mem_missing_derived",
            derived_from=[],
            evidence_refs=[{"path": "sessions/2026/06/05/provenance/evidence.md", "quote_id": "ev_001"}],
        )
        missing_evidence = valid_memory_node(
            memory_id="mem_missing_evidence",
            derived_from=["sessions/2026/06/05/provenance/summary.md"],
            evidence_refs=[],
        )
        entry_dir = memory_repo / "sessions/2026/06/05/provenance"
        entry_dir.mkdir(parents=True)
        (entry_dir / "summary.md").write_text("Summary for provenance audit.\n", encoding="utf-8")
        (entry_dir / "evidence.md").write_text("ev_001: Evidence for provenance audit.\n", encoding="utf-8")
        (memory_repo / "index/memories.jsonl").write_text(
            json.dumps(missing_derived, sort_keys=True)
            + "\n"
            + json.dumps(missing_evidence, sort_keys=True)
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
        self.assertIn("index/memories.jsonl:1 category=invalid_memory_node", combined)
        self.assertIn("index/memories.jsonl:2 category=invalid_memory_node", combined)
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive.AuditMemoryArchiveTests.test_audit_memory_archive_flags_memory_nodes_without_required_provenance
```

Expected before implementation:

```text
FAIL
```

The failure should show that one or both malformed nodes are not reported as `invalid_memory_node`.

- [ ] **Step 3: Tighten audit shape validation**

In `templates/agent-memory-repo/tools/audit_memory_archive.py`, update `is_valid_memory_node_shape` so `derived_from` and `evidence_refs` must be non-empty:

```python
    derived_from = row.get("derived_from")
    if not is_string_list(derived_from) or not derived_from:
        return False
    for field in MEMORY_NODE_STRING_LIST_FIELDS - {"derived_from"}:
        if not is_string_list(row.get(field)):
            return False
    evidence_refs = row.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs or not all(
        is_valid_evidence_ref_shape(ref) for ref in evidence_refs
    ):
        return False
```

Keep `raw_refs` as an array that may be empty.

- [ ] **Step 4: Tighten schema minItems**

In both schema copies, change:

```json
"derived_from": { "type": "array", "items": { "type": "string" } }
```

to:

```json
"derived_from": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } }
```

and add `"minItems": 1` plus string `minLength` to `evidence_refs`. Leave `raw_refs` without `minItems`.

- [ ] **Step 5: Sync audit tool copies**

Run:

```bash
cp templates/agent-memory-repo/tools/audit_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py
```

- [ ] **Step 6: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive.AuditMemoryArchiveTests.test_audit_memory_archive_flags_memory_nodes_without_required_provenance
python3 -m unittest tests.test_audit_memory_archive -q
```

Expected:

```text
OK
```

- [ ] **Step 7: Commit**

Run:

```bash
git add templates/agent-memory-repo/schemas/memory_node.schema.json \
  skills/setup-my-precious/assets/agent-memory-repo/schemas/memory_node.schema.json \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py \
  tests/test_audit_memory_archive.py
git commit -m "fix: require evidence-bound memory nodes"
```

**Acceptance criteria:**
- Audit rejects memory nodes with empty `derived_from`.
- Audit rejects memory nodes with empty `evidence_refs`.
- Schema documents the same non-empty provenance contract.

**Verification:**
- `python3 -m unittest tests.test_audit_memory_archive -q`
- `diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo`

**Dependencies:** None

**Estimated scope:** Medium

### Task 2: Verify Broken Evidence Quote IDs At Root And Index Depth

**Description:** Confirm audit rejects evidence refs whose file exists but whose `quote_id` is absent. The current audit appears to check `evidence_quote_id_exists`; this task makes that behavior explicit with a focused regression test so later induction work cannot generate ungrounded evidence refs.

**Files:**
- Modify if needed: `templates/agent-memory-repo/tools/audit_memory_archive.py`
- Modify if needed: `skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py`
- Test: `tests/test_audit_memory_archive.py`

- [ ] **Step 1: Write the failing or already-proving test**

Add:

```python
def test_audit_memory_archive_flags_missing_evidence_quote_ids(self):
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

        entry_dir = memory_repo / "sessions/2026/06/05/missing-quote"
        entry_dir.mkdir(parents=True)
        (entry_dir / "summary.md").write_text("Summary for missing quote test.\n", encoding="utf-8")
        (entry_dir / "evidence.md").write_text("ev_present: Existing evidence quote.\n", encoding="utf-8")
        memory_node = valid_memory_node(
            memory_id="mem_missing_quote",
            derived_from=["sessions/2026/06/05/missing-quote/summary.md"],
            evidence_refs=[{"path": "sessions/2026/06/05/missing-quote/evidence.md", "quote_id": "ev_missing"}],
        )
        (memory_repo / "index/memories.jsonl").write_text(
            json.dumps(memory_node, sort_keys=True) + "\n",
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
        self.assertIn("index/memories.jsonl:1 category=broken_memory_ref", combined)
```

- [ ] **Step 2: Run and classify**

Run:

```bash
python3 -m unittest tests.test_audit_memory_archive.AuditMemoryArchiveTests.test_audit_memory_archive_flags_missing_evidence_quote_ids
```

Expected:

- If FAIL: implement the missing audit check.
- If OK immediately: keep the test as coverage and do not change production code.

- [ ] **Step 3: Implement only if RED**

If the test fails, update `audit_memory_references` to call `evidence_quote_id_exists(evidence_path, quote_id)` for every evidence ref and append `broken_memory_ref` when false. Sync the setup asset copy.

- [ ] **Step 4: Commit**

Run:

```bash
git add templates/agent-memory-repo/tools/audit_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/audit_memory_archive.py \
  tests/test_audit_memory_archive.py
git commit -m "test: cover missing memory evidence quote ids"
```

If production code changed, use:

```bash
git commit -m "fix: reject missing memory evidence quote ids"
```

**Acceptance criteria:**
- Missing evidence quote IDs are covered by a test.
- Production code changes only if current audit does not already enforce the behavior.

**Verification:**
- `python3 -m unittest tests.test_audit_memory_archive -q`

**Dependencies:** Task 1

**Estimated scope:** Small

## Phase 2: Automatic Induction MVP

### Task 3: Add End-To-End Automatic Induction From Synthetic Sessions

**Description:** Prove the updater can produce a high-level `domain` memory from two synthetic source records in different projects. This must exercise the real setup and update CLI, not only `build_memory_nodes(rows)`, so the evidence chain starts from source events and session summaries.

**Files:**
- Modify if needed: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify if needed: `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py`
- Modify if needed: `skills/update-my-precious/scripts/update_memory_archive.py`
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Write the failing end-to-end test**

Add a test near the existing update integration tests:

```python
def test_update_memory_archive_induces_domain_memory_from_two_project_sessions(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
    update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        source_dir = root / "records"
        project_alpha = root / "alpha"
        project_beta = root / "beta"
        source_dir.mkdir()
        project_alpha.mkdir()
        project_beta.mkdir()
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        fact = "Layered retrieval should preserve evidence refs for induced memories."
        alpha_record = source_dir / "alpha.jsonl"
        beta_record = source_dir / "beta.jsonl"
        alpha_record.write_text(
            json.dumps({"role": "user", "content": "We need a reusable layered retrieval rule."}) + "\n"
            + json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}"}) + "\n",
            encoding="utf-8",
        )
        beta_record.write_text(
            json.dumps({"role": "user", "content": "Apply the same memory retrieval rule in another project."}) + "\n"
            + json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}"}) + "\n",
            encoding="utf-8",
        )
        set_mtime(alpha_record, "2026-06-20T10:00:00Z")
        set_mtime(beta_record, "2026-06-20T11:00:00Z")

        for project_path in (project_alpha, project_beta):
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
                    "--source-agent",
                    "synthetic-agent",
                    "--rewrite-existing",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        domain_rows = [
            json.loads(line)
            for line in (memory_repo / "memories/domains.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        induced = [row for row in domain_rows if row.get("text") == fact]
        self.assertEqual(len(induced), 1)
        node = induced[0]
        self.assertEqual(node["source"], "automatic")
        self.assertEqual(node["layer"], "domain")
        self.assertEqual(node["support_count"], 2)
        self.assertEqual(len(node["derived_from"]), 2)
        self.assertEqual(len(node["evidence_refs"]), 2)
        for ref in node["evidence_refs"]:
            evidence_text = (memory_repo / ref["path"]).read_text(encoding="utf-8")
            self.assertIn(ref["quote_id"], evidence_text)
        indexed_rows = [
            json.loads(line)
            for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertIn(node["memory_id"], {row.get("memory_id") for row in indexed_rows})
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_induces_domain_memory_from_two_project_sessions
```

Expected before implementation:

```text
FAIL
```

Likely failure modes are `support_count` not reaching 2, evidence refs missing, or the updater not extracting the reusable fact consistently from both source records.

- [ ] **Step 3: Implement minimal induction fix**

If extraction misses the fact, update the existing reusable-fact extraction path in `update_memory_archive.py` so assistant lines starting with `Reusable fact:` produce a reusable fact entry in session meta. Keep the rule conservative:

```python
REUSABLE_FACT_PREFIX = re.compile(r"(?i)^\s*reusable fact\s*[:\uFF1A]\s*(?P<text>.+)$")
```

Use the existing `normalize_memory_text`, `is_noisy_text`, and secret redaction checks before adding the fact.

If evidence refs are missing or quote IDs do not match, adjust evidence rendering so each reusable fact selected into meta has a stable evidence quote ID that appears in `evidence.md`.

- [ ] **Step 4: Sync updater copies**

Run:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_induces_domain_memory_from_two_project_sessions
python3 -m unittest tests.test_update_memory_archive -q
```

Expected:

```text
OK
```

- [ ] **Step 6: Commit**

Run:

```bash
git add templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  tests/test_update_memory_archive.py
git commit -m "feat: induce domain memories from session evidence"
```

**Acceptance criteria:**
- A high-level automatic memory is induced from two synthetic session events.
- The memory is `domain` scoped when support crosses two projects.
- The memory has two summary refs and two evidence refs.
- The memory is written to both durable memory files and `index/memories.jsonl`.

**Verification:**
- `python3 -m unittest tests.test_update_memory_archive -q`
- `python3 -m unittest tests.test_audit_memory_archive -q`

**Dependencies:** Tasks 1 and 2

**Estimated scope:** Medium

### Task 4: Prevent Source-Free Automatic Memory Nodes

**Description:** Automatic induction must not create untraceable facts. This task ensures rows without summary/evidence provenance do not become high-level memory nodes.

**Files:**
- Modify: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/update-my-precious/scripts/update_memory_archive.py`
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Write the failing unit test**

Add:

```python
def test_build_memory_nodes_skips_automatic_candidates_without_summary_or_evidence(self):
    module = load_update_module()
    rows = [
        {
            "session_id": "s1",
            "project": "alpha",
            "project_path": "/tmp/alpha",
            "source_record": "source-records/alpha.jsonl",
            "source_updated_at": "2026-06-20T10:00:00Z",
            "summary_path": "",
            "evidence_path": "sessions/2026/06/20/alpha/evidence.md",
            "reusable_facts": ["Untraceable automatic memories must not be promoted."],
            "decisions": [],
            "unresolved_tasks": [],
            "tags": ["memory"],
        },
        {
            "session_id": "s2",
            "project": "beta",
            "project_path": "/tmp/beta",
            "source_record": "source-records/beta.jsonl",
            "source_updated_at": "2026-06-20T11:00:00Z",
            "summary_path": "sessions/2026/06/20/beta/summary.md",
            "evidence_path": "",
            "reusable_facts": ["Untraceable automatic memories must not be promoted."],
            "decisions": [],
            "unresolved_tasks": [],
            "tags": ["memory"],
        },
    ]

    nodes = module.build_memory_nodes(rows)

    self.assertEqual(nodes, [])
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_build_memory_nodes_skips_automatic_candidates_without_summary_or_evidence
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Implement minimal guard**

In `memory_candidates_from_meta`, skip candidates unless both `summary_path` and `evidence_path` are non-empty strings:

```python
        summary_path = str(row.get("summary_path", ""))
        evidence_path = str(row.get("evidence_path", ""))
        if not summary_path or not evidence_path:
            continue
```

Use those variables when constructing `MemoryCandidate`.

- [ ] **Step 4: Sync updater copies and verify**

Run:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py
python3 -m unittest tests.test_update_memory_archive -q
```

- [ ] **Step 5: Commit**

Run:

```bash
git add templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  tests/test_update_memory_archive.py
git commit -m "fix: skip untraceable automatic memories"
```

**Acceptance criteria:**
- Automatic nodes are not built without summary and evidence refs.
- Existing valid automatic memory tests still pass.

**Verification:**
- `python3 -m unittest tests.test_update_memory_archive -q`

**Dependencies:** Task 3

**Estimated scope:** Small

## Phase 3: Explicit Memory Write Path

### Task 5: Add Direct Explicit Memory CLI

**Description:** Add a minimal explicit-memory write mode to `update_memory_archive.py` so a user or governing prompt can force a sticky high-level memory without waiting for source-record discovery. The command must require a summary path and evidence ref. Raw refs are optional and must pass the same safety checks as existing raw refs.

**Files:**
- Modify: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py`
- Modify: `skills/update-my-precious/scripts/update_memory_archive.py`
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Write failing CLI test**

Add:

```python
def test_update_memory_archive_can_write_direct_explicit_memory_with_evidence(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
    update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        entry_dir = memory_repo / "sessions/2026/06/20/direct-explicit"
        entry_dir.mkdir(parents=True)
        (entry_dir / "summary.md").write_text("Summary supporting direct explicit memory.\n", encoding="utf-8")
        (entry_dir / "evidence.md").write_text("ev_direct_001: User explicitly requested this durable rule.\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(update_script),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(root),
                "--explicit-memory",
                "Prefer evidence-bound memories over unsupported recollection.",
                "--explicit-layer",
                "global",
                "--explicit-scope",
                "global",
                "--explicit-summary-path",
                "sessions/2026/06/20/direct-explicit/summary.md",
                "--explicit-evidence-ref",
                "sessions/2026/06/20/direct-explicit/evidence.md#ev_direct_001",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [
            json.loads(line)
            for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 1)
        node = rows[0]
        self.assertEqual(node["source"], "explicit")
        self.assertEqual(node["persistence"], "sticky")
        self.assertEqual(node["layer"], "global")
        self.assertEqual(node["derived_from"], ["sessions/2026/06/20/direct-explicit/summary.md"])
        self.assertEqual(
            node["evidence_refs"],
            [{"path": "sessions/2026/06/20/direct-explicit/evidence.md", "quote_id": "ev_direct_001"}],
        )
        self.assertIn(node["memory_id"], (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_can_write_direct_explicit_memory_with_evidence
```

Expected:

```text
FAIL
```

The expected failure is an argument parsing error for missing explicit-memory options.

- [ ] **Step 3: Add CLI arguments**

In `parse_args`, add:

```python
    parser.add_argument("--explicit-memory", action="append", default=[], help="Write a sticky high-level explicit memory")
    parser.add_argument("--explicit-layer", choices=("global", "domain", "project"), default="global", help="Layer for --explicit-memory")
    parser.add_argument("--explicit-scope", default="global", help="Scope for --explicit-memory")
    parser.add_argument("--explicit-summary-path", help="Archive-relative summary path supporting --explicit-memory")
    parser.add_argument("--explicit-evidence-ref", action="append", default=[], help="Archive evidence ref PATH#QUOTE_ID for --explicit-memory")
    parser.add_argument("--explicit-raw-ref", action="append", default=[], help="Optional raw/source ref PATH#ANCHOR for --explicit-memory")
```

- [ ] **Step 4: Add explicit-memory writer helpers**

Add helpers near `explicit_memory_node`:

```python
def archive_ref_path(memory_repo: Path, path_text: str) -> Path | None:
    if not path_text.strip() or has_unsafe_raw_ref_path(path_text):
        return None
    candidate = memory_repo / path_text
    try:
        repo_resolved = memory_repo.resolve()
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def existing_archive_ref(memory_repo: Path, path_text: str) -> bool:
    return archive_ref_path(memory_repo, path_text) is not None


def evidence_quote_id_exists(path: Path, quote_id: str) -> bool:
    if not quote_id.strip():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(line.startswith(f"{quote_id}:") for line in text.splitlines())


def parse_archive_ref(value: str, option_name: str) -> tuple[str, str]:
    if "#" not in value:
        raise SystemExit(f"{option_name} must use PATH#ANCHOR")
    path, anchor = value.split("#", 1)
    path = path.strip()
    anchor = anchor.strip()
    if not path or not anchor:
        raise SystemExit(f"{option_name} must use PATH#ANCHOR")
    return path, anchor


def is_safe_direct_raw_ref(ref: dict[str, str]) -> bool:
    return raw_ref_for_source_record(ref["path"], ref["anchor"]) is not None


def direct_explicit_memory_node(
    text: str,
    layer: str,
    scope: str,
    summary_path: str,
    evidence_refs: list[dict],
    raw_refs: list[dict],
    now: str,
) -> dict:
    cleaned = clean_explicit_memory_text(text)
    if not cleaned or is_sensitive_explicit_memory_text(cleaned) or is_noisy_text(cleaned):
        raise SystemExit("explicit memory text is empty, noisy, or sensitive")
    topic = memory_topic(cleaned, [])
    return {
        "memory_id": memory_id_for(layer, scope, cleaned, "explicit"),
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": cleaned,
        "rationale": "Explicit memory requested by the user or governing prompt.",
        "source": "explicit",
        "confidence": "high",
        "persistence": "sticky",
        "support_count": 1,
        "first_seen": now,
        "last_seen": now,
        "derived_from": [summary_path],
        "evidence_refs": evidence_refs,
        "raw_refs": raw_refs,
        "supersedes": [],
        "superseded_by": None,
        "tags": sorted({topic, "explicit-memory"}),
    }
```

- [ ] **Step 5: Validate direct explicit refs before writing**

In `main`, before source discovery exits, if `args.explicit_memory` is non-empty:

```python
    if args.explicit_memory:
        if not args.explicit_summary_path:
            raise SystemExit("--explicit-summary-path is required with --explicit-memory")
        if not args.explicit_evidence_ref:
            raise SystemExit("--explicit-evidence-ref is required with --explicit-memory")
        summary_path = args.explicit_summary_path.strip()
        if not existing_archive_ref(memory_repo, summary_path):
            raise SystemExit("--explicit-summary-path must point to an existing archive file")
        evidence_refs = []
        for value in args.explicit_evidence_ref:
            path, quote_id = parse_archive_ref(value, "--explicit-evidence-ref")
            evidence_path = archive_ref_path(memory_repo, path)
            if evidence_path is None or not evidence_quote_id_exists(evidence_path, quote_id):
                raise SystemExit("--explicit-evidence-ref must point to an existing evidence quote")
            evidence_refs.append({"path": path, "quote_id": quote_id})
        raw_refs = []
        for value in args.explicit_raw_ref:
            path, anchor = parse_archive_ref(value, "--explicit-raw-ref")
            ref = {"path": path, "anchor": anchor}
            if not is_safe_direct_raw_ref(ref):
                raise SystemExit("--explicit-raw-ref is unsafe")
            raw_refs.append(ref)
        now = isoformat(datetime.now(UTC))
        direct_nodes = [
            direct_explicit_memory_node(
                text,
                args.explicit_layer,
                args.explicit_scope,
                summary_path,
                evidence_refs,
                raw_refs,
                now,
            )
            for text in args.explicit_memory
        ]
        existing_rows = collect_meta(memory_repo)
        generated_nodes = build_memory_nodes(existing_rows)
        write_memory_nodes(memory_repo, [*generated_nodes, *direct_nodes])
        rebuild_indexes(memory_repo)
        return 0
```

- [ ] **Step 6: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_can_write_direct_explicit_memory_with_evidence
python3 -m unittest tests.test_update_memory_archive -q
```

- [ ] **Step 7: Sync copies and commit**

Run:

```bash
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py
cp templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py
git add templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  tests/test_update_memory_archive.py
git commit -m "feat: add evidence-bound explicit memory writes"
```

**Acceptance criteria:**
- CLI can write a sticky explicit memory.
- CLI refuses explicit memory without summary and evidence references.
- Written explicit memory is durable and indexed.

**Verification:**
- `python3 -m unittest tests.test_update_memory_archive -q`
- `python3 -m unittest tests.test_search_memory -q`

**Dependencies:** Tasks 1 and 2

**Estimated scope:** Medium

### Task 6: Refuse Direct Explicit Memory Without Evidence

**Description:** Add negative coverage for the explicit write path so future changes cannot create source-free sticky memory nodes.

**Files:**
- Modify if needed: `templates/agent-memory-repo/tools/update_memory_archive.py`
- Modify if needed: synced updater copies
- Test: `tests/test_update_memory_archive.py`

- [ ] **Step 1: Write failing negative test**

Add:

```python
def test_update_memory_archive_refuses_direct_explicit_memory_without_evidence(self):
    setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
    update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        memory_repo = root / "agent-memory"
        subprocess.run(
            [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(update_script),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(root),
                "--explicit-memory",
                "This unsupported memory must be refused.",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--explicit-summary-path is required with --explicit-memory", result.stderr)
        self.assertEqual((memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"), "")
```

- [ ] **Step 2: Run**

Run:

```bash
python3 -m unittest tests.test_update_memory_archive.UpdateMemoryArchiveTests.test_update_memory_archive_refuses_direct_explicit_memory_without_evidence
```

Expected:

- If FAIL: add the guard from Task 5.
- If OK: commit the test only.

- [ ] **Step 3: Commit**

Run:

```bash
git add templates/agent-memory-repo/tools/update_memory_archive.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/update_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  tests/test_update_memory_archive.py
git commit -m "test: cover evidence requirement for explicit memories"
```

Use `fix:` instead of `test:` if production code changed.

**Acceptance criteria:**
- Source-free direct explicit memories are refused.
- No explicit memory file mutation happens on refusal.

**Verification:**
- `python3 -m unittest tests.test_update_memory_archive -q`

**Dependencies:** Task 5

**Estimated scope:** Small

## Phase 4: Benchmark Expansion

### Task 7: Add Quantitative Gates For Induced And Explicit Memory Cases

**Description:** Extend the synthetic benchmark so it proves the new slice: at least one automatic high-level memory is induced from session-layer evidence and at least one explicit sticky memory is retrievable and evidence-bound.

**Files:**
- Modify: `benchmarks/build_synthetic_recall_archive.py`
- Modify: `benchmarks/cases/layered_recall_synthetic.jsonl`
- Modify if needed: `benchmarks/layered_recall_benchmark.py`
- Modify: `benchmarks/quality-gates/layered_recall_synthetic.json`
- Modify: `benchmarks/quality-gates/layered_recall_synthetic_max.json`
- Test: `tests/test_layered_recall_benchmark.py`

- [ ] **Step 1: Add benchmark case fields if necessary**

Prefer existing fields first:

```json
{
  "case_id": "synthetic:induced_domain_memory",
  "query": "What reusable layered retrieval rule was induced across projects?",
  "category": "automatic_induction",
  "source_benchmark": "MyPrecious-layered-synthetic",
  "expected_memory_id": "syn_induced_domain_memory",
  "expected_summary_path": "sessions/synthetic/2026/06/induction-01/summary.md",
  "expected_source_anchor": "records/synthetic-induction.jsonl#message:1",
  "required_evidence_paths": [
    "sessions/synthetic/2026/06/induction-01/evidence.md",
    "sessions/synthetic/2026/06/induction-02/evidence.md"
  ],
  "reference_answer": "Layered retrieval should preserve evidence refs for induced memories.",
  "reference_evidence": "Layered retrieval should preserve evidence refs for induced memories.",
  "expected_layer": "domain"
}
```

and:

```json
{
  "case_id": "synthetic:explicit_sticky_memory",
  "query": "Which explicit memory says evidence-bound memories are preferred?",
  "category": "explicit_memory",
  "source_benchmark": "MyPrecious-layered-synthetic",
  "expected_memory_id": "syn_explicit_sticky_memory",
  "expected_summary_path": "sessions/synthetic/2026/06/explicit-01/summary.md",
  "expected_source_anchor": "records/synthetic-explicit.jsonl#message:1",
  "required_evidence_paths": [
    "sessions/synthetic/2026/06/explicit-01/evidence.md"
  ],
  "reference_answer": "Prefer evidence-bound memories over unsupported recollection.",
  "reference_evidence": "Prefer evidence-bound memories over unsupported recollection.",
  "expected_layer": "global"
}
```

If existing metrics can score these without new fields, do not add new benchmark code.

- [ ] **Step 2: Write failing packaged-case test**

Update `test_packaged_synthetic_cases_cover_public_benchmark_categories` to require:

```python
self.assertIn("automatic_induction", categories)
self.assertIn("explicit_memory", categories)
```

Update `test_packaged_synthetic_cases_produce_quantitative_scores` to expect updated case counts and category metrics:

```python
self.assertGreaterEqual(payload["cases"], 34)
self.assertEqual(payload["categories"]["automatic_induction"]["case_pass_rate"], 1.0)
self.assertEqual(payload["categories"]["explicit_memory"]["case_pass_rate"], 1.0)
self.assertEqual(payload["categories"]["automatic_induction"]["layer_calibration"], 1.0)
self.assertEqual(payload["categories"]["explicit_memory"]["layer_calibration"], 1.0)
```

- [ ] **Step 3: Run and verify RED**

Run:

```bash
python3 -m unittest tests.test_layered_recall_benchmark.LayeredRecallBenchmarkTests.test_packaged_synthetic_cases_cover_public_benchmark_categories
python3 -m unittest tests.test_layered_recall_benchmark.LayeredRecallBenchmarkTests.test_packaged_synthetic_cases_produce_quantitative_scores
```

Expected:

```text
FAIL
```

- [ ] **Step 4: Extend builder and cases**

Update `benchmarks/cases/layered_recall_synthetic.jsonl` with the two cases above.

Update `benchmarks/build_synthetic_recall_archive.py` so those cases create:

- Durable memory node in `memories/domains.jsonl` or `memories/global.jsonl`.
- Matching row in `index/memories.jsonl`.
- `summary.md` and `evidence.md` files.
- Evidence quote IDs referenced by the memory node.
- Source anchors expected by benchmark.

- [ ] **Step 5: Update quality gates**

After running the benchmark once, update threshold files to include:

```json
"categories.automatic_induction.case_pass_rate": 1.0,
"categories.automatic_induction.layer_calibration": 1.0,
"categories.explicit_memory.case_pass_rate": 1.0,
"categories.explicit_memory.layer_calibration": 1.0
```

Update `cases`, `positive_cases`, `answer_cases`, `evidence_text_cases`,
`layer_calibration_cases`, `scope_filter_cases`, and upper-bound rank/source
counts to the measured values only after confirming details JSON has no failed
checks.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
python3 -m unittest tests.test_layered_recall_benchmark -q
python3 benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-layered-final-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl
python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-layered-final-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-layered-final-details.jsonl \
  --failures-json /tmp/my-precious-layered-final-failures.json \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

Expected:

```text
OK
```

and benchmark exit code `0`.

- [ ] **Step 7: Commit**

Run:

```bash
git add benchmarks/build_synthetic_recall_archive.py \
  benchmarks/cases/layered_recall_synthetic.jsonl \
  benchmarks/layered_recall_benchmark.py \
  benchmarks/quality-gates/layered_recall_synthetic.json \
  benchmarks/quality-gates/layered_recall_synthetic_max.json \
  tests/test_layered_recall_benchmark.py
git commit -m "test: benchmark induced and explicit memories"
```

**Acceptance criteria:**
- Benchmark includes automatic induction and explicit memory categories.
- Quality gates fail if either category regresses.
- Baseline remains reproducible with fingerprints in stdout.

**Verification:**
- `python3 -m unittest tests.test_layered_recall_benchmark -q`
- Packaged synthetic benchmark command above.

**Dependencies:** Tasks 3, 5, and 6

**Estimated scope:** Medium

## Phase 5: Documentation And Final Verification

### Task 8: Update Readiness Documentation

**Description:** Update the readiness audit to reflect the implemented minimum slice. The doc must clearly distinguish what is now proven from what remains future architecture.

**Files:**
- Modify: `docs/evaluations/layered-memory-readiness.md`
- Optional create: `docs/evaluations/layered-memory-minimum-slice-results.md`

- [ ] **Step 1: Update verified capabilities**

Add bullets stating:

```markdown
- The updater can induce at least one high-level memory from multiple synthetic session records.
- Direct explicit memory writes require summary and evidence references.
- Audit rejects memory nodes without required provenance.
```

- [ ] **Step 2: Move completed gaps**

Remove or reword gaps that are no longer true. Keep future gaps such as:

```markdown
- The induction prototype is conservative and synthetic; it is not yet a semantic memory consolidation engine.
- Raw/source content rendering is still gated by anchors, not by a full authorization workflow.
- Public benchmark datasets have still not been run unless a later task explicitly performs that evaluation.
```

- [ ] **Step 3: Add final benchmark baseline**

Record final:

- case count
- `cases_sha256`
- `search_script_sha256`
- `memory_recall_at_1`
- `memory_recall_at_5`
- `memory_precision_at_5`
- `source_reachability`
- `evidence_reachability`
- `answer_reachability`
- `abstention_accuracy`
- `privacy_boundary_pass_rate`
- `failed_case_count`

- [ ] **Step 4: Verify documentation**

Run:

```bash
rg -n "TO[D]O|T[B]D|fill[ ]in|implement[ ]later" docs/evaluations/layered-memory-readiness.md
rg -n "[^\x00-\x7F]" docs/evaluations/layered-memory-readiness.md
```

Expected:

- First command has no output.
- Second command has no output unless a deliberate non-ASCII term is present and justified.

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/evaluations/layered-memory-readiness.md docs/evaluations/layered-memory-minimum-slice-results.md
git commit -m "docs: update layered memory readiness after minimum slice"
```

If the optional results file is not created, omit it from `git add`.

**Acceptance criteria:**
- Documentation describes the new minimum slice in reader-facing terms.
- Remaining gaps are accurate and not overstated.

**Verification:**
- Documentation scans above.

**Dependencies:** Task 7

**Estimated scope:** Small

### Task 9: Final Full Verification

**Description:** Run the repository verification bundle required by `AGENTS.md` and the benchmark gate. Clean generated caches before final status.

**Files:**
- No source edits expected.

- [ ] **Step 1: Run full tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected:

```text
OK
```

- [ ] **Step 2: Compile scripts**

Run:

```bash
python3 -m py_compile \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/audit_memory_archive.py \
  templates/agent-memory-repo/tools/backfill_memory_archive.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py \
  templates/agent-memory-repo/tools/sync_memory_archive.py \
  benchmarks/build_synthetic_recall_archive.py \
  benchmarks/convert_public_memory_benchmark.py \
  benchmarks/layered_recall_benchmark.py
```

Expected: exit code `0`.

- [ ] **Step 3: Run benchmark gate**

Run:

```bash
rm -rf /tmp/my-precious-layered-final-audit \
  /tmp/my-precious-layered-final-details.jsonl \
  /tmp/my-precious-layered-final-failures.json
python3 benchmarks/build_synthetic_recall_archive.py \
  --repo /tmp/my-precious-layered-final-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl
python3 benchmarks/layered_recall_benchmark.py \
  --repo /tmp/my-precious-layered-final-audit \
  --cases benchmarks/cases/layered_recall_synthetic.jsonl \
  --search-script templates/agent-memory-repo/tools/search_memory.py \
  --details-jsonl /tmp/my-precious-layered-final-details.jsonl \
  --failures-json /tmp/my-precious-layered-final-failures.json \
  --fail-under-file benchmarks/quality-gates/layered_recall_synthetic.json \
  --fail-over-file benchmarks/quality-gates/layered_recall_synthetic_max.json
```

Expected: benchmark exit code `0`, `failed_case_count` equals `0`.

- [ ] **Step 4: Verify sync**

Run:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
```

Expected: all exit code `0`.

- [ ] **Step 5: Clean caches**

Run:

```bash
rm -rf .uv-cache .uv-cache-setup .uv-cache-update .uv-cache-using \
  tests/__pycache__ templates/agent-memory-repo/tools/__pycache__ \
  skills/setup-my-precious/scripts/__pycache__ \
  skills/setup-my-precious/assets/agent-memory-repo/tools/__pycache__ \
  skills/update-my-precious/scripts/__pycache__ \
  skills/using-my-precious/scripts/__pycache__ \
  benchmarks/__pycache__
```

- [ ] **Step 6: Final git hygiene**

Run:

```bash
git diff --check
git status --short
```

Expected:

- `git diff --check` exits `0`.
- `git status --short` is empty after final commit.

**Acceptance criteria:**
- Full test suite passes.
- Benchmark gate passes.
- Template and bundled script copies are synced.
- Worktree is clean.

**Verification:**
- All commands in this task.

**Dependencies:** Tasks 1-8

**Estimated scope:** Small

## Checkpoints

### Checkpoint A: After Phase 1

- [ ] `python3 -m unittest tests.test_audit_memory_archive -q` passes.
- [ ] Template and setup asset audit/schema copies are synced.
- [ ] Commit history has one or two focused Phase 1 commits.

### Checkpoint B: After Phase 2

- [ ] `python3 -m unittest tests.test_update_memory_archive -q` passes.
- [ ] At least one test proves automatic high-level memory induction from multiple synthetic session events.
- [ ] Generated automatic memory has non-empty `derived_from` and `evidence_refs`.

### Checkpoint C: After Phase 3

- [ ] Direct explicit memory write succeeds with summary and evidence refs.
- [ ] Direct explicit memory write fails without evidence.
- [ ] Explicit memory is sticky, durable, indexed, and audit-clean.

### Checkpoint D: After Phase 4

- [ ] Packaged synthetic benchmark includes automatic induction and explicit memory cases.
- [ ] Benchmark gate exits `0`.
- [ ] Quality-gate thresholds cover new categories.

### Checkpoint E: Complete

- [ ] Full unit suite passes.
- [ ] Script compile passes.
- [ ] Benchmark gate passes.
- [ ] Template sync passes.
- [ ] Readiness docs updated.
- [ ] Worktree clean.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Existing automatic induction already passes some new tests, weakening fail-first proof | Medium | If a test passes immediately, keep it as characterization coverage and do not change production code for that behavior. Add fail-first tests only for missing contract edges. |
| Direct explicit CLI duplicates existing source-record explicit extraction | Medium | Keep direct CLI minimal and evidence-bound; do not remove existing extraction. Both paths should produce the same memory node contract. |
| Tightened provenance rules break existing synthetic builder cases | Medium | Fix builder data to include evidence refs instead of relaxing audit rules. |
| Benchmark case counts shift many thresholds | Low | Update threshold JSON only after reading details JSON and confirming `failed_checks` is empty. |
| Plan expands into full semantic memory consolidation | High | Keep this slice lexical/conservative. No vector store, no LLM summarization dependency, no real private data. |

## Open Questions

- Should direct explicit memory writes default to `global` for all runtimes, or should skill instructions require the caller to choose `global`, `domain`, or `project` explicitly?
- Should raw refs for direct explicit memories allow safe-gated external paths, or only archive-relative source records?
- Should automatic induction require two supporting sessions for every domain/global memory, or allow one high-confidence user-preference session to become global?

The implementation can proceed with conservative defaults: direct explicit memory defaults to `global`, raw refs must pass existing safety checks, and automatic induction keeps the current support-count/layer rules unless a test proves they produce unsupported memories.
