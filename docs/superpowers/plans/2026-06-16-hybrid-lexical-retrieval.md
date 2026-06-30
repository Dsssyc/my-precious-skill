# Hybrid Lexical Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve My Precious search recall precision by adding a transparent hybrid lexical scorer with stronger field weighting, phrase coverage, project-context boost, and query explanations.

**Architecture:** Keep `search_memory.py` dependency-free and archive-format-compatible. Extend the current JSONL/Markdown search path instead of adding embeddings or SQLite in this slice. Preserve byte-for-byte sync across the template tool, the `using-my-precious` bundled script, and the setup asset copy.

**Tech Stack:** Python standard library, `unittest`, JSONL archive fixtures, existing template sync rules.

---

### Task 1: Add Retrieval Quality Regression Tests

**Files:**
- Modify: `tests/test_search_memory.py`

- [ ] **Step 1: Add failing test for exact phrase and structured-field dominance**

Add a test where a concise `decisions.jsonl` row containing `review-fix-re-review loop` outranks a noisy session row that repeats broad tokens like `review` and `loop`.

- [ ] **Step 2: Add failing test for current project boost**

Add a test where two hits share the same query tokens but `--project-path /repo/c-two` makes the matching `project_path` row rank first.

- [ ] **Step 3: Add failing test for explainable scoring**

Add a test that verifies result output includes a `why:` reason containing phrase coverage, a structured-field reason, and a project-context reason when applicable.

- [ ] **Step 4: Run focused tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_search_memory -v
```

Expected: the new tests fail because `--project-path` and the new `why:` reasons do not exist yet.

### Task 2: Implement Hybrid Lexical Scoring

**Files:**
- Modify: `templates/agent-memory-repo/tools/search_memory.py`

- [ ] **Step 1: Add query analysis helpers**

Add helpers that derive:

- unique lowercase tokens
- important/specific token sets
- adjacent query phrases of length 2-4
- generic noise tokens that should score weakly unless paired with specific tokens

- [ ] **Step 2: Score structured fields with explicit reason codes**

Update index scoring so matches in `decision`, `decisions`, `task`, `summary`, `reusable_facts`, `unresolved_tasks`, and `user_intent` contribute named reasons such as `field:decision` or `field:summary`.

- [ ] **Step 3: Add phrase coverage bonus**

Reward exact adjacent phrase matches in high-signal fields, capped so repetition cannot dominate.

- [ ] **Step 4: Add project-context boost**

Add optional CLI argument:

```bash
--project-path /absolute/project/path
```

Boost records whose `project_path`, `cwd`, or `repository` matches the current project path or basename. Emit `project-context` in `why:`.

- [ ] **Step 5: Penalize broad-only matches**

Down-rank records that only match generic project/tag/path tokens and do not cover any important/specific query token in high-signal fields.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run:

```bash
python3 -m unittest tests.test_search_memory -v
```

Expected: all search tests pass.

### Task 3: Sync Bundled Script Copies And Documentation

**Files:**
- Modify: `skills/using-my-precious/scripts/search_memory.py`
- Modify: `skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py`
- Modify: `skills/using-my-precious/SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/design.md`

- [ ] **Step 1: Copy the updated template search script**

Copy:

```bash
cp templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
cp templates/agent-memory-repo/tools/search_memory.py skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py
```

- [ ] **Step 2: Document retrieval behavior**

Document that search uses transparent hybrid lexical scoring over summaries, evidence when requested, JSONL indexes, field weights, phrase coverage, and optional project-path context. Keep vector/embedding search out of this slice.

- [ ] **Step 3: Verify sync checks**

Run:

```bash
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py
```

Expected: both commands exit 0.

### Task 4: Full Verification And Review

**Files:**
- No additional files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m unittest tests.test_search_memory -v
```

Expected: pass.

- [ ] **Step 2: Run full unit suite**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: pass.

- [ ] **Step 3: Compile changed scripts**

Run:

```bash
python3 -m py_compile \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/search_memory.py \
  skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py
```

Expected: pass.

- [ ] **Step 4: Verify template sync**

Run:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
```

Expected: no diff output and exit 0 for `cmp`.

- [ ] **Step 5: Review diff for scope, privacy, and simplicity**

Check:

- no raw transcript storage added
- no new network dependency
- no embedding/vector provider added
- no unrelated refactors
- explanations remain safe and do not expose raw source beyond existing result metadata

- [ ] **Step 6: Commit verified work**

Run:

```bash
git add docs/superpowers/plans/2026-06-16-hybrid-lexical-retrieval.md tests/test_search_memory.py templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py skills/setup-my-precious/assets/agent-memory-repo/tools/search_memory.py skills/using-my-precious/SKILL.md README.md README.zh-CN.md docs/design.md
git commit -m "feat: improve memory archive search ranking"
```
