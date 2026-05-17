# My Precious Skill Development

This repository develops reusable, agent-neutral skills for private session
memory archives. It is not the private archive itself.

## Repository Boundary

Keep this repository limited to reusable building blocks:

- `skills/`: installable skill folders.
- `templates/agent-memory-repo/`: deployment repository template.
- `tests/`: synthetic tests only.
- `docs/`: design notes for the reusable implementation.

Do not store real session memories, raw transcripts, credentials, cookies,
private keys, scheduler state, local logs, or generated private archive data in
this repository.

## Skill Set

- `setup-my-precious`: setup-path skill for local or Git-backed private archive
  repositories.
- `update-my-precious`: write-path skill for on-demand incremental archive
  updates.
- `using-my-precious`: read-path skill for searching an existing archive.

Keep skill language and examples agent-neutral. Do not make the skills depend
on one specific runtime unless a runtime-specific adapter is isolated and
optional.

## Template Sync Rule

`templates/agent-memory-repo/` is the source template. The bundled copy under
`skills/setup-my-precious/assets/agent-memory-repo/` must stay byte-for-byte in
sync with it.

When changing shared tools:

- Copy `templates/agent-memory-repo/tools/update_memory_archive.py` to
  `skills/update-my-precious/scripts/update_memory_archive.py`.
- Copy `templates/agent-memory-repo/tools/search_memory.py` to
  `skills/using-my-precious/scripts/search_memory.py`.
- Copy all template changes into
  `skills/setup-my-precious/assets/agent-memory-repo/`.

Verify sync with:

```bash
diff -qr templates/agent-memory-repo skills/setup-my-precious/assets/agent-memory-repo
cmp -s templates/agent-memory-repo/tools/update_memory_archive.py skills/update-my-precious/scripts/update_memory_archive.py
cmp -s templates/agent-memory-repo/tools/search_memory.py skills/using-my-precious/scripts/search_memory.py
```

## Privacy And Security

- Redact before summarization or evidence rendering.
- Keep evidence snippets short.
- Refuse likely-secret source records by default.
- Do not commit raw transcript files or unredacted source records.
- Keep deployment repository examples generic; do not reference user-specific
  repositories or real incidents.

## Verification

Run the focused test suite after changes:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Validate skill folders with the runtime's skill validator. If the validator
needs PyYAML and the system Python does not provide it, use an isolated uv run:

```bash
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /path/to/skill-creator/scripts/quick_validate.py skills/setup-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /path/to/skill-creator/scripts/quick_validate.py skills/update-my-precious
UV_CACHE_DIR=.uv-cache uv run --with pyyaml python /path/to/skill-creator/scripts/quick_validate.py skills/using-my-precious
```

Compile bundled scripts when implementation code changes:

```bash
python3 -m py_compile \
  skills/setup-my-precious/scripts/setup_memory_archive.py \
  skills/update-my-precious/scripts/update_memory_archive.py \
  skills/using-my-precious/scripts/search_memory.py \
  templates/agent-memory-repo/tools/run_memory_updates.py \
  templates/agent-memory-repo/tools/update_memory_archive.py \
  templates/agent-memory-repo/tools/search_memory.py \
  templates/agent-memory-repo/tools/render_scheduler.py
```

Remove generated caches before committing:

```bash
rm -rf .uv-cache tests/__pycache__ templates/agent-memory-repo/tools/__pycache__ \
  skills/setup-my-precious/scripts/__pycache__ \
  skills/setup-my-precious/assets/agent-memory-repo/tools/__pycache__ \
  skills/update-my-precious/scripts/__pycache__ \
  skills/using-my-precious/scripts/__pycache__
```

## Git Hygiene

Before committing, check:

```bash
git diff --check
git status --short
```

If untracked original planning/spec artifacts exist under `docs/`, do not
commit them unless the user explicitly asks to keep original planning material
in the repository.
