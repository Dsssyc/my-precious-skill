import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


def set_mtime(path: Path, stamp: str) -> None:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    os.utime(path, (dt.timestamp(), dt.timestamp()))


def load_update_module():
    script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()
    spec = importlib.util.spec_from_file_location("update_memory_archive_under_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


APPLY_REVIEW_DECISIONS_SCRIPT = Path("templates/agent-memory-repo/tools/apply_memory_review_decisions.py").resolve()
AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT = Path("templates/agent-memory-repo/tools/author_induction_review_decisions.py").resolve()


class UpdateMemoryArchiveTests(unittest.TestCase):
    def synthetic_memory_node(
        self,
        memory_id: str,
        text: str,
        *,
        last_seen: str = "2026-06-02T10:00:00Z",
    ) -> dict:
        return {
            "memory_id": memory_id,
            "layer": "project",
            "scope": "project:/tmp/review",
            "topic": "review",
            "text": text,
            "rationale": "Synthetic review decision fixture.",
            "source": "automatic",
            "confidence": "medium",
            "persistence": "normal",
            "support_count": 1,
            "first_seen": last_seen,
            "last_seen": last_seen,
            "derived_from": ["sessions/synthetic/summary.md"],
            "evidence_refs": [],
            "raw_refs": [],
            "supersedes": [],
            "superseded_by": None,
            "tags": ["review"],
        }

    def synthetic_review_candidate(
        self,
        current_id: str = "mem_current",
        older_id: str = "mem_old",
        *,
        reason: str = "low_confidence_semantic_overlap_requires_review",
    ) -> dict:
        return {
            "candidate_type": "ambiguous_semantic_lifecycle",
            "current_memory_id": current_id,
            "older_memory_id": older_id,
            "reason": reason,
            "recommended_action": "manual_review",
            "current_last_seen": "2026-06-02T10:00:00Z",
            "older_last_seen": "2026-06-01T10:00:00Z",
            "overlap_token_count": 5,
            "overlap_ratio": 0.625,
        }

    def synthetic_review_decision(self, module, candidate: dict, action: str) -> dict:
        return {
            "decision_id": f"decision_{action}",
            "action": action,
            "current_memory_id": candidate["current_memory_id"],
            "older_memory_id": candidate["older_memory_id"],
            "candidate_fingerprint": module.review_candidate_fingerprint(candidate),
            "reviewed_at": "2026-06-23T00:00:00Z",
            "reviewer": "synthetic",
            "rationale": "Synthetic reviewer decision.",
        }

    def write_natural_induction_meta(
        self,
        memory_repo: Path,
        session_id: str,
        fact: str,
        *,
        updated_at: str = "2026-06-26T10:00:00Z",
        project: str = "synthetic-induction-review",
    ) -> None:
        entry_dir = memory_repo / "sessions/2026/06/26" / session_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        (entry_dir / "summary.md").write_text(f"Summary for {session_id}\n", encoding="utf-8")
        (entry_dir / "evidence.md").write_text("ev_001: Synthetic redacted evidence\n", encoding="utf-8")
        row = {
            "session_id": session_id,
            "project": project,
            "project_path": f"/tmp/{project}",
            "source_record": f"source-records/{session_id}.jsonl",
            "source_updated_at": updated_at,
            "summary_path": f"sessions/2026/06/26/{session_id}/summary.md",
            "evidence_path": f"sessions/2026/06/26/{session_id}/evidence.md",
            "reusable_facts": [fact],
            "reusable_fact_sources": [{"text": fact, "source": "natural_assistant"}],
            "decisions": [],
            "unresolved_tasks": [],
            "tags": ["memory", "induction"],
        }
        (entry_dir / "meta.json").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    def synthetic_induction_review_decision(self, module, candidate: dict, action: str) -> dict:
        return {
            "decision_id": f"induction_decision_{action}",
            "action": action,
            "candidate_id": candidate["candidate_id"],
            "candidate_text_sha256": candidate["candidate_text_sha256"],
            "candidate_fingerprint": module.induction_review_candidate_fingerprint(candidate),
            "reviewed_at": "2026-06-26T00:00:00Z",
            "reviewer": "synthetic",
            "rationale": "Synthetic induction reviewer decision.",
        }

    def load_index_jsonl(self, memory_repo: Path, relative: str) -> list[dict]:
        path = memory_repo / relative
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_induction_review_decisions(self, memory_repo: Path, decisions: list[dict]) -> None:
        decision_dir = memory_repo / "reviews"
        decision_dir.mkdir(exist_ok=True)
        (decision_dir / "induction_review_decisions.jsonl").write_text(
            "\n".join(json.dumps(decision, sort_keys=True) for decision in decisions) + "\n",
            encoding="utf-8",
        )

    def test_extract_explicit_memory_texts_trims_task_tail(self):
        module = load_update_module()

        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: prefer concise answers, now review the failing tests",
                    )
                ]
            ),
            ["prefer concise answers"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "记住这个：已经授权后不要反复请求权限确认，然后检查测试",
                    )
                ]
            ),
            ["已经授权后不要反复请求权限确认"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: prefer concise answers. Now review the failing tests",
                    )
                ]
            ),
            ["prefer concise answers"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: prefer concise answers! Then review the failing tests",
                    )
                ]
            ),
            ["prefer concise answers"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: prefer concise answers? Next review the failing tests",
                    )
                ]
            ),
            ["prefer concise answers"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "记住这个：已经授权后不要反复请求权限确认。然后检查测试",
                    )
                ]
            ),
            ["已经授权后不要反复请求权限确认"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "记住这个：已经授权后不要反复请求权限确认。接下来检查测试",
                    )
                ]
            ),
            ["已经授权后不要反复请求权限确认"],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: prefer concise answers. Include rationale when useful.",
                    )
                ]
            ),
            ["prefer concise answers. Include rationale when useful."],
        )

    def test_extract_explicit_memory_texts_rejects_redacted_sensitive_directives(self):
        module = load_update_module()

        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember: Authorization: Bearer [REDACTED_BEARER_TOKEN]",
                    )
                ]
            ),
            [],
        )

    def test_extract_explicit_memory_texts_accepts_natural_directive_forms(self):
        module = load_update_module()

        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "Please remember that I prefer concise answers with rationale when useful.",
                    )
                ]
            ),
            ["I prefer concise answers with rationale when useful."],
        )
        self.assertEqual(
            module.extract_explicit_memory_texts(
                [
                    module.MemoryEvent(
                        "user",
                        "记住：已经授权后不要反复请求权限确认。",
                    )
                ]
            ),
            ["已经授权后不要反复请求权限确认。"],
        )

    def test_extract_explicit_memory_texts_rejects_negated_directives(self):
        module = load_update_module()

        negated_directives = [
            "Do not remember this: my preference is private",
            "don't remember this: private preference",
            "dont remember this: private preference",
            "Never remember this: private preference",
            "do not please remember: private preference",
            "do not remember that my preference is private",
            "不要记住这个：我的偏好是私密的",
            "不要记住：我的偏好是私密的",
            "别记住这个：我的偏好是私密的",
            "别记住：我的偏好是私密的",
            "不要强制记忆：我的偏好是私密的",
            "别强制记忆：我的偏好是私密的",
        ]

        for directive in negated_directives:
            with self.subTest(directive=directive):
                self.assertEqual(
                    module.extract_explicit_memory_texts(
                        [module.MemoryEvent("user", directive)]
                    ),
                    [],
                )

    def test_summarize_events_extracts_reusable_fact_without_literal_prefix(self):
        module = load_update_module()
        fact = "Layered retrieval should preserve evidence refs for induced memories."

        summary = module.summarize_events(
            [
                module.MemoryEvent("user", "Please make the memory archive reliable."),
                module.MemoryEvent("assistant", fact),
            ],
            "agent-memory",
        )

        self.assertIn(fact, summary["facts"])

    def test_summarize_events_induces_user_preference_without_marker(self):
        module = load_update_module()

        summary = module.summarize_events(
            [
                module.MemoryEvent(
                    "user",
                    "I prefer benchmark review summaries to lead with quantified risks before implementation notes.",
                ),
                module.MemoryEvent(
                    "assistant",
                    "Understood; future benchmark reviews will keep that preference visible.",
                ),
            ],
            "synthetic-memory",
        )

        self.assertIn(
            "The user prefers benchmark review summaries to lead with quantified risks before implementation notes.",
            summary["facts"],
        )
        self.assertIn(
            {
                "text": "The user prefers benchmark review summaries to lead with quantified risks before implementation notes.",
                "source": "natural_user",
            },
            summary["fact_sources"],
        )

    def test_summarize_events_rejects_process_noise_without_marker(self):
        module = load_update_module()

        summary = module.summarize_events(
            [
                module.MemoryEvent("assistant", "I checked the failing tests and will now inspect the archive."),
                module.MemoryEvent("assistant", "Now I will rerun the benchmark gates and report status."),
            ],
            "synthetic-memory",
        )

        self.assertEqual(summary["facts"], [])
        self.assertEqual(summary["decisions"], [])
        self.assertEqual(summary["evidence"], [])

    def test_summarize_events_rejects_adversarial_natural_false_promotions(self):
        module = load_update_module()
        adversarial_lines = [
            "This one-off archive status should be checked after the temporary update finishes.",
            "Understood; I will keep it in mind for this edit.",
            "We could maybe route synthetic archive summaries through a second review pass if the heuristic becomes noisy.",
            "For this local dry run, the temporary induction fixture must stay in the scratch workspace.",
            "The benchmark gate should pass after rerun, and the current test status is green.",
            'Quoted prompt text: "The assistant must always save this generic instruction."',
            "Memory systems should be reliable and useful.",
        ]

        for line in adversarial_lines:
            with self.subTest(line=line):
                summary = module.summarize_events(
                    [module.MemoryEvent("assistant", line)],
                    "synthetic-memory",
                )

                self.assertEqual(summary["facts"], [])
                self.assertEqual(summary["decisions"], [])
                self.assertEqual(summary["evidence"], [])

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

    def test_build_memory_nodes_filters_low_signal_reusable_facts(self):
        module = load_update_module()
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [
                    "DONE",
                    "Layered migration should preserve durable memory facts.",
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "migration"],
            },
        ]

        nodes = module.build_memory_nodes(rows)

        self.assertEqual([node["text"] for node in nodes], ["Layered migration should preserve durable memory facts."])

    def test_build_memory_nodes_rejects_process_update_candidates(self):
        module = load_update_module()
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [
                    "I checked the failing tests and will now inspect the archive.",
                    "现在我检查 Cargo workspace 边界。",
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory"],
            },
        ]

        nodes = module.build_memory_nodes(rows)

        self.assertEqual(nodes, [])

    def test_rebuild_indexes_routes_natural_induction_candidates_to_review_surface(self):
        module = load_update_module()
        low_confidence = "Synthetic induction review candidate should wait for repeated support before promotion."
        conflict_keep = "The user prefers synthetic review summaries to include benchmark counts before conclusions."
        conflict_avoid = "The user prefers synthetic review summaries to exclude benchmark counts before conclusions."
        scoped = "Synthetic induction review calibration should preserve evidence refs for project-specific natural memories."
        broader = "Synthetic induction review calibration should preserve evidence refs for natural memories."
        rows = [
            ("low", low_confidence, "synthetic-low", "2026-06-26T10:00:00Z"),
            ("conflict-a", conflict_keep, "synthetic-conflict-a", "2026-06-26T11:00:00Z"),
            ("conflict-b", conflict_avoid, "synthetic-conflict-b", "2026-06-26T12:00:00Z"),
            ("scope-a", scoped, "synthetic-scope-a", "2026-06-26T13:00:00Z"),
            ("scope-b", broader, "synthetic-scope-b", "2026-06-26T14:00:00Z"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            for session_id, fact, project, updated_at in rows:
                entry_dir = memory_repo / "sessions/2026/06/26" / session_id
                entry_dir.mkdir(parents=True, exist_ok=True)
                (entry_dir / "summary.md").write_text(f"Summary for {session_id}\n", encoding="utf-8")
                (entry_dir / "evidence.md").write_text("ev_001: Synthetic redacted evidence\n", encoding="utf-8")
                row = {
                    "session_id": session_id,
                    "project": project,
                    "project_path": f"/tmp/{project}",
                    "source_record": f"source-records/{session_id}.jsonl",
                    "source_updated_at": updated_at,
                    "summary_path": f"sessions/2026/06/26/{session_id}/summary.md",
                    "evidence_path": f"sessions/2026/06/26/{session_id}/evidence.md",
                    "reusable_facts": [fact],
                    "reusable_fact_sources": [{"text": fact, "source": "natural_assistant"}],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["memory", "induction"],
                }
                (entry_dir / "meta.json").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            module.rebuild_indexes(memory_repo)

            memory_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertFalse({low_confidence, conflict_keep, conflict_avoid, scoped, broader} & {row["text"] for row in memory_rows})

            review_rows = [
                json.loads(line)
                for line in (memory_repo / "index/induction_review_candidates.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            reasons = {row["reason"] for row in review_rows}
            self.assertIn("low_confidence_natural_induction_requires_review", reasons)
            self.assertIn("conflicting_natural_induction_requires_review", reasons)
            self.assertIn("scope_change_natural_induction_requires_review", reasons)
            for row in review_rows:
                self.assertEqual(row["candidate_type"], "natural_induction_review")
                self.assertEqual(row["recommended_action"], "manual_review")
                self.assertRegex(row["candidate_id"], r"^indrev_[0-9a-f]{16}$")
                self.assertRegex(row["candidate_text_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotIn("text", row)
                self.assertNotIn("candidate_text", row)
                self.assertTrue(row["derived_from"])
                self.assertTrue(row["evidence_refs"])
                self.assertTrue(row["raw_refs"])

    def test_rebuild_indexes_applies_induction_review_approve_promote_decision(self):
        module = load_update_module()
        fact = "Synthetic induction approval candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "approve", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            (decision_dir / "induction_review_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            module.rebuild_indexes(memory_repo)

            memory_rows = self.load_index_jsonl(memory_repo, "index/memories.jsonl")
            active_candidates = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")
            result_rows = self.load_index_jsonl(memory_repo, "index/induction_review_decision_results.jsonl")

        self.assertIn(fact, {row["text"] for row in memory_rows})
        self.assertEqual(active_candidates, [])
        self.assertEqual(result_rows[0]["status"], "applied")
        self.assertEqual(result_rows[0]["action"], "approve_promote")
        self.assertEqual(result_rows[0]["candidate_id"], candidate["candidate_id"])
        self.assertEqual(result_rows[0]["candidate_text_sha256"], candidate["candidate_text_sha256"])
        self.assertNotIn("text", result_rows[0])
        self.assertNotIn("candidate_text", result_rows[0])

    def test_rebuild_indexes_keeps_rejected_and_noop_induction_reviews_non_mutating(self):
        module = load_update_module()

        for action in ("reject", "noop"):
            with self.subTest(action=action):
                fact = f"Synthetic induction {action} candidate should wait for repeated support before promotion."
                with tempfile.TemporaryDirectory() as tmpdir:
                    memory_repo = Path(tmpdir) / "agent-memory"
                    self.write_natural_induction_meta(memory_repo, action, fact)
                    module.rebuild_indexes(memory_repo)
                    candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
                    decision_dir = memory_repo / "reviews"
                    decision_dir.mkdir()
                    decision = self.synthetic_induction_review_decision(module, candidate, action)
                    (decision_dir / "induction_review_decisions.jsonl").write_text(
                        json.dumps(decision, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    module.rebuild_indexes(memory_repo)

                    memory_rows = self.load_index_jsonl(memory_repo, "index/memories.jsonl")
                    active_candidates = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")
                    result_rows = self.load_index_jsonl(memory_repo, "index/induction_review_decision_results.jsonl")

                self.assertNotIn(fact, {row["text"] for row in memory_rows})
                self.assertEqual(active_candidates, [])
                self.assertEqual(result_rows[0]["status"], "ignored")
                self.assertEqual(result_rows[0]["action"], action)

    def test_rebuild_indexes_refuses_stale_induction_review_decision(self):
        module = load_update_module()
        fact = "Synthetic induction stale candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "stale", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            decision["candidate_fingerprint"] = "sha256:stale"
            (decision_dir / "induction_review_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "stale induction review decision"):
                module.rebuild_indexes(memory_repo)

    def test_rebuild_indexes_refuses_unsafe_induction_review_decision(self):
        module = load_update_module()
        fact = "Synthetic induction unsafe candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "unsafe", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            decision["decision_id"] = "induction token=SHOULD_NOT_RENDER"
            (decision_dir / "induction_review_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "unsafe induction review decision"):
                module.rebuild_indexes(memory_repo)

    def test_rebuild_indexes_refuses_duplicate_induction_review_decision_id(self):
        module = load_update_module()
        fact = "Synthetic induction duplicate decision candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "duplicate", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            duplicate = dict(decision)
            duplicate["action"] = "reject"
            self.write_induction_review_decisions(memory_repo, [decision, duplicate])

            with self.assertRaisesRegex(SystemExit, "invalid induction review decision set"):
                module.rebuild_indexes(memory_repo)

    def test_rebuild_indexes_refuses_conflicting_induction_review_actions(self):
        module = load_update_module()
        fact = "Synthetic induction conflicting decision candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "conflict", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            approve = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            reject = self.synthetic_induction_review_decision(module, candidate, "reject")
            reject["decision_id"] = "induction_decision_reject_distinct"
            self.write_induction_review_decisions(memory_repo, [approve, reject])

            with self.assertRaisesRegex(SystemExit, "invalid induction review decision set"):
                module.rebuild_indexes(memory_repo)

    def test_rebuild_indexes_refuses_exact_duplicate_induction_review_decision_rows(self):
        module = load_update_module()
        fact = "Synthetic induction exact duplicate candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "exact-duplicate", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            self.write_induction_review_decisions(memory_repo, [decision, dict(decision)])

            with self.assertRaisesRegex(SystemExit, "invalid induction review decision set"):
                module.rebuild_indexes(memory_repo)

    def test_apply_memory_review_decisions_tool_preflights_invalid_induction_decisions_aggregate_only(self):
        module = load_update_module()
        fact = "PRIVATE INDUCTION INVALID CANDIDATE TEXT SHOULD NOT RENDER before promotion."
        private_path = "/Users/soku/private/archive/source.jsonl"

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "invalid-tool", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            approve = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            exact_duplicate = dict(approve)
            conflicting = self.synthetic_induction_review_decision(module, candidate, "reject")
            conflicting["decision_id"] = "induction_decision_conflicting_reject"
            stale = self.synthetic_induction_review_decision(module, candidate, "noop")
            stale["decision_id"] = "induction_decision_stale"
            stale["candidate_fingerprint"] = "sha256:stale"
            unknown = self.synthetic_induction_review_decision(module, candidate, "noop")
            unknown["decision_id"] = "induction_decision_unknown"
            unknown["candidate_id"] = "indrev_0000000000000000"
            unsafe = self.synthetic_induction_review_decision(module, candidate, "noop")
            unsafe["decision_id"] = "induction token=PRIVATE"
            unsafe["rationale"] = fact
            unsafe["reviewer"] = private_path
            self.write_induction_review_decisions(
                memory_repo,
                [approve, exact_duplicate, conflicting, stale, unknown, unsafe],
            )

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            write_run = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotIn("PRIVATE INDUCTION INVALID CANDIDATE TEXT", dry_run.stdout)
        self.assertNotIn("PRIVATE INDUCTION INVALID CANDIDATE TEXT", dry_run.stderr)
        self.assertNotIn("PRIVATE INDUCTION INVALID CANDIDATE TEXT", write_run.stdout)
        self.assertNotIn("PRIVATE INDUCTION INVALID CANDIDATE TEXT", write_run.stderr)
        self.assertNotIn(private_path, dry_run.stdout)
        self.assertNotIn(private_path, dry_run.stderr)
        self.assertNotIn(private_path, write_run.stdout)
        self.assertNotIn(private_path, write_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertFalse(dry_payload["induction_decision_preflight_passed"])
        self.assertEqual(
            dry_payload["induction_decision_error_counts"],
            {
                "conflicting_candidate_action": 1,
                "conflicting_fingerprint_action": 1,
                "duplicate_decision_id": 1,
                "exact_duplicate": 1,
                "stale": 1,
                "unknown": 1,
                "unsafe": 1,
            },
        )
        self.assertEqual(dry_payload["induction_result_status_counts"], {})
        self.assertEqual(dry_payload["induction_promoted_count"], 0)
        self.assertNotEqual(write_run.returncode, 0)

    def test_apply_memory_review_decisions_tool_handles_induction_reviews_aggregate_only(self):
        module = load_update_module()
        fact = "PRIVATE INDUCTION CANDIDATE TEXT SHOULD NOT RENDER before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "tool", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            (decision_dir / "induction_review_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            write_run = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            memory_rows = self.load_index_jsonl(memory_repo, "index/memories.jsonl")

        self.assertNotIn("PRIVATE INDUCTION CANDIDATE TEXT", dry_run.stdout)
        self.assertNotIn("PRIVATE INDUCTION CANDIDATE TEXT", dry_run.stderr)
        self.assertNotIn("PRIVATE INDUCTION CANDIDATE TEXT", write_run.stdout)
        self.assertNotIn("PRIVATE INDUCTION CANDIDATE TEXT", write_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        write_payload = json.loads(write_run.stdout)
        self.assertEqual(dry_payload["induction_decision_count"], 1)
        self.assertTrue(dry_payload["induction_decision_preflight_passed"])
        self.assertEqual(dry_payload["induction_decision_error_counts"], {})
        self.assertEqual(dry_payload["induction_result_status_counts"], {"applied": 1})
        self.assertEqual(dry_payload["induction_result_action_counts"], {"approve_promote": 1})
        self.assertEqual(dry_payload["induction_promoted_count"], 1)
        self.assertFalse(dry_payload["write_enabled"])
        self.assertEqual(write_payload["induction_decision_count"], 1)
        self.assertTrue(write_payload["induction_decision_preflight_passed"])
        self.assertEqual(write_payload["induction_decision_error_counts"], {})
        self.assertEqual(write_payload["induction_result_status_counts"], {"applied": 1})
        self.assertEqual(write_payload["induction_result_action_counts"], {"approve_promote": 1})
        self.assertEqual(write_payload["induction_promoted_count"], 1)
        self.assertTrue(write_payload["write_enabled"])
        self.assertIn(fact, {row["text"] for row in memory_rows})

    def test_author_induction_review_decisions_tool_writes_pending_skeleton_aggregate_safe(self):
        module = load_update_module()
        fact = "PRIVATE AUTHOR SKELETON CANDIDATE TEXT SHOULD NOT RENDER before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-skeleton", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            review_file = memory_repo / "reviews/induction_review_decisions.jsonl"
            self.assertFalse(review_file.exists())
            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rows = self.load_index_jsonl(memory_repo, "reviews/induction_review_decisions.jsonl")

        self.assertNotIn("PRIVATE AUTHOR SKELETON CANDIDATE TEXT", dry_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR SKELETON CANDIDATE TEXT", dry_run.stderr)
        self.assertNotIn("PRIVATE AUTHOR SKELETON CANDIDATE TEXT", write_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR SKELETON CANDIDATE TEXT", write_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        write_payload = json.loads(write_run.stdout)
        self.assertFalse(dry_payload["write_enabled"])
        self.assertTrue(write_payload["write_enabled"])
        self.assertEqual(dry_payload["skeleton_count"], 1)
        self.assertEqual(dry_payload["would_append_count"], 1)
        self.assertEqual(write_payload["appended_count"], 1)
        self.assertEqual(write_payload["decision_error_counts"], {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "noop")
        self.assertEqual(rows[0]["candidate_id"], candidate["candidate_id"])
        self.assertEqual(rows[0]["candidate_text_sha256"], candidate["candidate_text_sha256"])
        self.assertEqual(rows[0]["candidate_fingerprint"], module.induction_review_candidate_fingerprint(candidate))
        self.assertNotIn("text", rows[0])
        self.assertNotIn("candidate_text", rows[0])
        self.assertNotIn("source_path", rows[0])
        self.assertNotIn("raw_refs", rows[0])

    def test_author_induction_review_decisions_tool_preserves_existing_manual_decisions(self):
        module = load_update_module()
        fact = "Synthetic author existing decision candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-existing", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            existing = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            existing["decision_id"] = "manual_existing_decision"
            self.write_induction_review_decisions(memory_repo, [existing])

            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rows = self.load_index_jsonl(memory_repo, "reviews/induction_review_decisions.jsonl")

        payload = json.loads(write_run.stdout)
        self.assertEqual(payload["existing_decision_count"], 1)
        self.assertEqual(payload["skeleton_count"], 0)
        self.assertEqual(payload["appended_count"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_id"], "manual_existing_decision")
        self.assertEqual(rows[0]["action"], "approve_promote")

    def test_author_induction_review_decisions_tool_rejects_mutating_default_action(self):
        module = load_update_module()
        fact = "PRIVATE AUTHOR MUTATING DEFAULT SHOULD NOT RENDER before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-mutating-default", fact)
            module.rebuild_indexes(memory_repo)
            review_file = memory_repo / "reviews/induction_review_decisions.jsonl"

            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--default-action",
                    "approve_promote",
                    "--write",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            review_file_exists = review_file.exists()

        self.assertNotEqual(write_run.returncode, 0)
        self.assertFalse(review_file_exists)
        self.assertNotIn("PRIVATE AUTHOR MUTATING DEFAULT", write_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR MUTATING DEFAULT", write_run.stderr)

    def test_author_induction_review_decisions_tool_skips_reflected_candidates(self):
        module = load_update_module()
        fact = "Synthetic author reflected candidate should wait for repeated support before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-reflected", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            reflected = self.synthetic_induction_review_decision(module, candidate, "reject")
            reflected["decision_id"] = "manual_reflected_reject"
            self.write_induction_review_decisions(memory_repo, [reflected])
            module.rebuild_indexes(memory_repo)

            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rows = self.load_index_jsonl(memory_repo, "reviews/induction_review_decisions.jsonl")

        payload = json.loads(write_run.stdout)
        self.assertEqual(payload["reflected_decision_count"], 1)
        self.assertEqual(payload["pending_candidate_count"], 0)
        self.assertEqual(payload["skeleton_count"], 0)
        self.assertEqual(payload["appended_count"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_id"], "manual_reflected_reject")

    def test_author_induction_review_decisions_tool_refuses_reflected_decision_id_collision(self):
        module = load_update_module()
        old_fact = "PRIVATE AUTHOR OLD REFLECTED CANDIDATE TEXT SHOULD NOT RENDER before promotion."
        new_fact = "PRIVATE AUTHOR NEW PENDING CANDIDATE TEXT SHOULD NOT RENDER before promotion."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-reflected-old", old_fact)
            self.write_natural_induction_meta(memory_repo, "author-reflected-new", new_fact)
            module.rebuild_indexes(memory_repo)
            candidates = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")
            old_candidate = next(
                candidate
                for candidate in candidates
                if candidate["derived_from"] == ["sessions/2026/06/26/author-reflected-old/summary.md"]
            )
            new_candidate = next(
                candidate
                for candidate in candidates
                if candidate["derived_from"] == ["sessions/2026/06/26/author-reflected-new/summary.md"]
            )
            reflected = self.synthetic_induction_review_decision(module, old_candidate, "reject")
            reflected["decision_id"] = f"induction_review_{new_candidate['candidate_id']}"
            self.write_induction_review_decisions(memory_repo, [reflected])
            module.rebuild_indexes(memory_repo)

            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rows = self.load_index_jsonl(memory_repo, "reviews/induction_review_decisions.jsonl")

        self.assertNotEqual(write_run.returncode, 0)
        self.assertNotIn("PRIVATE AUTHOR OLD REFLECTED", write_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR OLD REFLECTED", write_run.stderr)
        self.assertNotIn("PRIVATE AUTHOR NEW PENDING", write_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR NEW PENDING", write_run.stderr)
        payload = json.loads(write_run.stdout)
        self.assertFalse(payload["preflight_passed"])
        self.assertEqual(payload["decision_error_counts"], {"duplicate_decision_id": 1})
        self.assertEqual(payload["appended_count"], 0)
        self.assertEqual(len(rows), 1)

    def test_author_induction_review_decisions_tool_refuses_invalid_existing_decisions_before_write(self):
        module = load_update_module()
        fact = "PRIVATE AUTHOR INVALID CANDIDATE TEXT SHOULD NOT RENDER before promotion."
        private_path = "/example/private/author/source.jsonl"

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            self.write_natural_induction_meta(memory_repo, "author-invalid", fact)
            module.rebuild_indexes(memory_repo)
            candidate = self.load_index_jsonl(memory_repo, "index/induction_review_candidates.jsonl")[0]
            approve = self.synthetic_induction_review_decision(module, candidate, "approve_promote")
            reject = self.synthetic_induction_review_decision(module, candidate, "reject")
            reject["decision_id"] = "manual_conflicting_reject"
            stale = self.synthetic_induction_review_decision(module, candidate, "noop")
            stale["decision_id"] = "manual_stale_noop"
            stale["candidate_fingerprint"] = "sha256:stale"
            unsafe = self.synthetic_induction_review_decision(module, candidate, "noop")
            unsafe["decision_id"] = "manual token=PRIVATE"
            unsafe["reviewer"] = private_path
            unsafe["rationale"] = fact
            self.write_induction_review_decisions(memory_repo, [approve, reject, stale, unsafe])

            dry_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            write_run = subprocess.run(
                [
                    sys.executable,
                    str(AUTHOR_INDUCTION_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--write",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rows = self.load_index_jsonl(memory_repo, "reviews/induction_review_decisions.jsonl")

        self.assertNotIn("PRIVATE AUTHOR INVALID CANDIDATE TEXT", dry_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR INVALID CANDIDATE TEXT", dry_run.stderr)
        self.assertNotIn("PRIVATE AUTHOR INVALID CANDIDATE TEXT", write_run.stdout)
        self.assertNotIn("PRIVATE AUTHOR INVALID CANDIDATE TEXT", write_run.stderr)
        self.assertNotIn(private_path, dry_run.stdout)
        self.assertNotIn(private_path, dry_run.stderr)
        self.assertNotIn(private_path, write_run.stdout)
        self.assertNotIn(private_path, write_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertFalse(dry_payload["preflight_passed"])
        self.assertEqual(
            dry_payload["decision_error_counts"],
            {
                "conflicting_candidate_action": 1,
                "conflicting_fingerprint_action": 1,
                "stale": 1,
                "unsafe": 1,
            },
        )
        self.assertNotEqual(write_run.returncode, 0)
        self.assertEqual(len(rows), 4)

    def test_build_memory_nodes_semantically_merges_paraphrased_reusable_facts(self):
        module = load_update_module()
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [
                    "Layered retrieval must preserve evidence refs for induced memories."
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [
                    "Induced layered memories should retain their evidence references during retrieval."
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)

        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node["text"], "Layered retrieval must preserve evidence refs for induced memories.")
        self.assertEqual(node["layer"], "domain")
        self.assertEqual(node["confidence"], "high")
        self.assertEqual(node["support_count"], 2)
        self.assertEqual(node["last_seen"], "2026-06-02T10:00:00Z")
        self.assertEqual(
            node["derived_from"],
            [
                "sessions/2026/06/01/alpha/summary.md",
                "sessions/2026/06/02/beta/summary.md",
            ],
        )
        self.assertEqual(
            node["evidence_refs"],
            [
                {"path": "sessions/2026/06/01/alpha/evidence.md", "quote_id": "ev_001"},
                {"path": "sessions/2026/06/02/beta/evidence.md", "quote_id": "ev_001"},
            ],
        )

    def test_build_memory_nodes_links_semantic_contradictions(self):
        module = load_update_module()
        old_fact = "Layered retrieval must preserve evidence refs for induced memories."
        current_fact = "Layered retrieval must not preserve evidence refs for induced memories."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [old_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [current_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}
        old_node = by_text[old_fact]
        current_node = by_text[current_fact]

        self.assertEqual(current_node["contradicts"], [old_node["memory_id"]])
        self.assertEqual(old_node["contradicted_by"], [current_node["memory_id"]])
        self.assertEqual(current_node["support_count"], 2)
        self.assertEqual(current_node["last_seen"], "2026-06-02T10:00:00Z")
        self.assertEqual(len(current_node["evidence_refs"]), 2)

    def test_build_memory_nodes_links_semantic_partial_supersession(self):
        module = load_update_module()
        old_fact = "Layered retrieval should preserve evidence refs and raw source anchors for induced memories."
        current_fact = "Layered retrieval should preserve evidence refs for induced memories."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [old_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [current_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}
        old_node = by_text[old_fact]
        current_node = by_text[current_fact]

        self.assertEqual(current_node["supersedes"], [old_node["memory_id"]])
        self.assertEqual(old_node["superseded_by"], current_node["memory_id"])
        self.assertEqual(current_node["support_count"], 2)
        self.assertEqual(current_node["last_seen"], "2026-06-02T10:00:00Z")
        self.assertEqual(len(current_node["derived_from"]), 2)
        self.assertEqual(len(current_node["evidence_refs"]), 2)

    def test_build_memory_nodes_does_not_partially_supersede_scope_narrowing(self):
        module = load_update_module()
        old_fact = "Layered retrieval should preserve evidence refs for project-specific induced memories."
        current_fact = "Layered retrieval should preserve evidence refs for induced memories."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [old_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [current_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}

        self.assertEqual(len(nodes), 2)
        self.assertEqual(by_text[current_fact]["supersedes"], [])
        self.assertIsNone(by_text[old_fact]["superseded_by"])

    def test_rebuild_indexes_writes_ambiguity_review_queue_and_skip_trace(self):
        module = load_update_module()
        old_fact = "Layered retrieval should preserve evidence refs for project-specific induced memories."
        current_fact = "Layered retrieval should preserve evidence refs for induced memories."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            rows = [
                {
                    "session_id": "s1",
                    "project": "alpha",
                    "project_path": "/tmp/alpha",
                    "source_record": "source-records/alpha.jsonl",
                    "source_updated_at": "2026-06-01T10:00:00Z",
                    "summary_path": "sessions/2026/06/01/alpha/summary.md",
                    "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                    "reusable_facts": [old_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["memory", "retrieval"],
                },
                {
                    "session_id": "s2",
                    "project": "beta",
                    "project_path": "/tmp/beta",
                    "source_record": "source-records/beta.jsonl",
                    "source_updated_at": "2026-06-02T10:00:00Z",
                    "summary_path": "sessions/2026/06/02/beta/summary.md",
                    "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                    "reusable_facts": [current_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["memory", "retrieval"],
                },
            ]
            for row in rows:
                entry_dir = memory_repo / Path(row["summary_path"]).parent
                entry_dir.mkdir(parents=True, exist_ok=True)
                (entry_dir / "summary.md").write_text(f"Summary for {row['session_id']}\n", encoding="utf-8")
                (entry_dir / "evidence.md").write_text("ev_001: Redacted evidence\n", encoding="utf-8")
                (entry_dir / "meta.json").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            module.rebuild_indexes(memory_repo)

            nodes = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_text = {node["text"]: node for node in nodes}
            old_node = by_text[old_fact]
            current_node = by_text[current_fact]
            self.assertEqual(current_node["supersedes"], [])
            self.assertIsNone(old_node["superseded_by"])

            review_candidates = [
                json.loads(line)
                for line in (memory_repo / "index/memory_review_candidates.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(review_candidates), 1)
            self.assertEqual(review_candidates[0]["candidate_type"], "ambiguous_semantic_lifecycle")
            self.assertEqual(review_candidates[0]["current_memory_id"], current_node["memory_id"])
            self.assertEqual(review_candidates[0]["older_memory_id"], old_node["memory_id"])
            self.assertEqual(review_candidates[0]["recommended_action"], "manual_review")

            trace_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memory_consolidation_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(
                any(
                    row.get("decision") == "skip"
                    and row.get("reason") == "ambiguous_scope_narrowing_requires_review"
                    and row.get("current_memory_id") == current_node["memory_id"]
                    and row.get("target_memory_id") == old_node["memory_id"]
                    for row in trace_rows
                )
            )

    def test_review_candidates_compress_same_scope_low_confidence_overlap(self):
        module = load_update_module()
        nodes = [
            {
                "memory_id": "mem_current",
                "source": "automatic",
                "layer": "project",
                "scope": "project:/tmp/alpha",
                "text": "Cache backend snapshot archive compact policy should stay reviewable.",
                "last_seen": "2026-06-03T10:00:00Z",
                "supersedes": [],
                "superseded_by": None,
            },
            {
                "memory_id": "mem_old_a",
                "source": "automatic",
                "layer": "project",
                "scope": "project:/tmp/alpha",
                "text": "Cache backend snapshot archive rebuild metadata should stay reviewable.",
                "last_seen": "2026-06-01T10:00:00Z",
                "supersedes": [],
                "superseded_by": None,
            },
            {
                "memory_id": "mem_old_b",
                "source": "automatic",
                "layer": "project",
                "scope": "project:/tmp/alpha",
                "text": "Snapshot archive compact policy refresh summaries should stay reviewable.",
                "last_seen": "2026-06-02T10:00:00Z",
                "supersedes": [],
                "superseded_by": None,
            },
        ]

        candidates = module.build_memory_review_candidates(nodes)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["candidate_type"], "compressed_low_risk_semantic_lifecycle")
        self.assertEqual(candidates[0]["current_memory_id"], "mem_current")
        self.assertEqual(candidates[0]["older_memory_id"], "mem_old_a")
        self.assertEqual(candidates[0]["compressed_candidate_count"], 2)
        self.assertEqual(candidates[0]["compressed_older_memory_ids"], ["mem_old_a", "mem_old_b"])
        self.assertEqual(
            candidates[0]["compression_reason"],
            "same_scope_low_confidence_semantic_overlap",
        )

    def test_review_candidates_suppress_low_overlap_scope_narrowing_noise(self):
        module = load_update_module()
        nodes = [
            {
                "memory_id": "mem_current",
                "source": "automatic",
                "layer": "project",
                "scope": "project:/tmp/alpha",
                "text": "Cache backend snapshot archive.",
                "last_seen": "2026-06-03T10:00:00Z",
                "supersedes": [],
                "superseded_by": None,
            },
            {
                "memory_id": "mem_old",
                "source": "automatic",
                "layer": "project",
                "scope": "project:/tmp/beta",
                "text": (
                    "Cache backend snapshot archive sandbox relay validator metadata source "
                    "reference policy should stay reviewable."
                ),
                "last_seen": "2026-06-01T10:00:00Z",
                "supersedes": [],
                "superseded_by": None,
            },
        ]

        detail = module.semantic_relation_detail(nodes[0]["text"], nodes[1]["text"])
        candidates = module.build_memory_review_candidates(nodes)

        self.assertEqual(
            detail["review_reason"],
            "ambiguous_scope_narrowing_requires_review",
        )
        self.assertLess(detail["overlap_ratio"], 0.45)
        self.assertEqual(candidates, [])

    def test_rebuild_indexes_handles_legacy_meta_without_quote_refs(self):
        module = load_update_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            entry_dir = memory_repo / "sessions/2026/06/21/legacy"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for legacy session\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text(
                "Legacy evidence has no explicit quote label.\n",
                encoding="utf-8",
            )
            (entry_dir / "source-map.json").write_text("{}\n", encoding="utf-8")
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "session_id": "legacy-session",
                        "project": "legacy",
                        "project_path": "/tmp/legacy",
                        "source_record": "/records/legacy.jsonl",
                        "source_updated_at": "2026-06-21T10:00:00Z",
                        "summary_path": "sessions/2026/06/21/legacy/summary.md",
                        "evidence_path": "sessions/2026/06/21/legacy/evidence.md",
                        "reusable_facts": [
                            "Layered migration should preserve reachable session refs without invented quote ids."
                        ],
                        "decisions": [],
                        "unresolved_tasks": [],
                        "tags": ["layered-migration"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            module.rebuild_indexes(memory_repo)

            session_rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            memory_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            source_map = json.loads((entry_dir / "source-map.json").read_text(encoding="utf-8"))

        self.assertEqual(
            session_rows[0]["source_map_path"],
            "sessions/2026/06/21/legacy/source-map.json",
        )
        self.assertEqual(source_map["summary_path"], "sessions/2026/06/21/legacy/summary.md")
        self.assertEqual(source_map["evidence_path"], "sessions/2026/06/21/legacy/evidence.md")
        self.assertEqual(source_map["source_map_path"], "sessions/2026/06/21/legacy/source-map.json")
        self.assertEqual(memory_rows[0]["derived_from"], ["sessions/2026/06/21/legacy/summary.md"])
        self.assertEqual(memory_rows[0]["evidence_refs"], [])

    def test_memory_consolidation_trace_explains_lifecycle_decisions(self):
        module = load_update_module()
        nodes = [
            {
                "memory_id": "mem_merge",
                "source": "automatic",
                "support_count": 2,
                "supersedes": [],
                "contradicts": [],
                "deprecates": [],
            },
            {
                "memory_id": "mem_current",
                "source": "automatic",
                "support_count": 1,
                "supersedes": ["mem_old"],
                "contradicts": ["mem_conflict"],
                "deprecates": ["mem_deleted"],
            },
        ]
        review_candidates = [
            {
                "reason": "ambiguous_scope_narrowing_requires_review",
                "current_memory_id": "mem_current",
                "older_memory_id": "mem_scope_specific",
            }
        ]

        traces = module.build_memory_consolidation_traces(nodes, review_candidates)
        decisions = {(row.get("decision"), row.get("reason")) for row in traces}

        self.assertIn(("merge", "same_consolidation_key_support_merge"), decisions)
        self.assertIn(("supersede", "confirmed_supersession_link"), decisions)
        self.assertIn(("contradict", "confirmed_contradiction_link"), decisions)
        self.assertIn(("deprecate", "confirmed_deprecation_link"), decisions)
        self.assertIn(("skip", "ambiguous_scope_narrowing_requires_review"), decisions)

    def test_apply_memory_review_decisions_approves_lifecycle_links(self):
        module = load_update_module()
        action_expectations = {
            "approve_supersedes": ("supersedes", "superseded_by"),
            "approve_contradicts": ("contradicts", "contradicted_by"),
            "approve_deprecates": ("deprecates", "deprecated_by"),
        }

        for action, (current_field, older_field) in action_expectations.items():
            with self.subTest(action=action):
                current = self.synthetic_memory_node(
                    "mem_current",
                    "Layered review decisions should confirm memory lifecycle links.",
                    last_seen="2026-06-02T10:00:00Z",
                )
                old = self.synthetic_memory_node(
                    "mem_old",
                    "Layered review candidates should confirm memory lifecycle links.",
                    last_seen="2026-06-01T10:00:00Z",
                )
                candidate = self.synthetic_review_candidate()
                decision = self.synthetic_review_decision(module, candidate, action)

                results = module.apply_memory_review_decisions([current, old], [candidate], [decision])

                self.assertEqual(results[0]["status"], "applied")
                self.assertEqual(results[0]["action"], action)
                if current_field == "contradicts":
                    self.assertEqual(current[current_field], [old["memory_id"]])
                    self.assertEqual(old[older_field], [current["memory_id"]])
                else:
                    self.assertEqual(current[current_field], [old["memory_id"]])
                    self.assertEqual(old[older_field], current["memory_id"])
                self.assertEqual(old["confidence"], "low")

    def test_apply_memory_review_decisions_keeps_reject_and_noop_non_mutating(self):
        module = load_update_module()
        for action in ("reject", "noop"):
            with self.subTest(action=action):
                current = self.synthetic_memory_node("mem_current", "Current synthetic review memory.")
                old = self.synthetic_memory_node("mem_old", "Older synthetic review memory.")
                candidate = self.synthetic_review_candidate()
                decision = self.synthetic_review_decision(module, candidate, action)

                results = module.apply_memory_review_decisions([current, old], [candidate], [decision])

                self.assertEqual(results[0]["status"], "ignored")
                self.assertEqual(results[0]["action"], action)
                self.assertEqual(current["supersedes"], [])
                self.assertEqual(current.get("contradicts", []), [])
                self.assertEqual(current.get("deprecates", []), [])
                self.assertIsNone(old["superseded_by"])
                self.assertNotIn("contradicted_by", old)
                self.assertNotIn("deprecated_by", old)

    def test_apply_memory_review_decisions_refuses_unknown_candidate(self):
        module = load_update_module()
        current = self.synthetic_memory_node("mem_current", "Current synthetic review memory.")
        old = self.synthetic_memory_node("mem_old", "Older synthetic review memory.")
        candidate = self.synthetic_review_candidate()
        decision = self.synthetic_review_decision(module, candidate, "approve_supersedes")
        decision["older_memory_id"] = "mem_missing"

        with self.assertRaisesRegex(SystemExit, "unknown memory review candidate"):
            module.apply_memory_review_decisions([current, old], [candidate], [decision])

    def test_apply_memory_review_decisions_refuses_stale_candidate_fingerprint(self):
        module = load_update_module()
        current = self.synthetic_memory_node("mem_current", "Current synthetic review memory.")
        old = self.synthetic_memory_node("mem_old", "Older synthetic review memory.")
        candidate = self.synthetic_review_candidate()
        decision = self.synthetic_review_decision(module, candidate, "approve_supersedes")
        decision["candidate_fingerprint"] = "sha256:stale"

        with self.assertRaisesRegex(SystemExit, "stale memory review decision"):
            module.apply_memory_review_decisions([current, old], [candidate], [decision])

    def test_apply_memory_review_decisions_refuses_unsafe_decision_ids(self):
        module = load_update_module()
        current = self.synthetic_memory_node("mem_current", "Current synthetic review memory.")
        old = self.synthetic_memory_node("mem_old", "Older synthetic review memory.")
        candidate = self.synthetic_review_candidate()
        decision = self.synthetic_review_decision(module, candidate, "approve_supersedes")
        decision["current_memory_id"] = "mem_current token=SHOULD_NOT_RENDER"

        with self.assertRaisesRegex(SystemExit, "unsafe memory review decision"):
            module.apply_memory_review_decisions([current, old], [candidate], [decision])

    def test_rebuild_indexes_applies_memory_review_decision_file(self):
        module = load_update_module()
        current_fact = "Cache backend snapshot archive compact policy should stay reviewable."
        old_fact = "Cache backend snapshot archive rebuild metadata should stay reviewable."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            rows = [
                {
                    "session_id": "old-session",
                    "project": "alpha",
                    "project_path": "/tmp/alpha",
                    "source_record": "source-records/old.jsonl",
                    "source_updated_at": "2026-06-01T10:00:00Z",
                    "summary_path": "sessions/2026/06/01/old/summary.md",
                    "evidence_path": "sessions/2026/06/01/old/evidence.md",
                    "reusable_facts": [old_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["cache", "archive"],
                },
                {
                    "session_id": "current-session",
                    "project": "alpha",
                    "project_path": "/tmp/alpha",
                    "source_record": "source-records/current.jsonl",
                    "source_updated_at": "2026-06-02T10:00:00Z",
                    "summary_path": "sessions/2026/06/02/current/summary.md",
                    "evidence_path": "sessions/2026/06/02/current/evidence.md",
                    "reusable_facts": [current_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["cache", "archive"],
                },
            ]
            for row in rows:
                entry_dir = memory_repo / Path(row["summary_path"]).parent
                entry_dir.mkdir(parents=True, exist_ok=True)
                (entry_dir / "summary.md").write_text(f"Summary for {row['session_id']}\n", encoding="utf-8")
                (entry_dir / "evidence.md").write_text("ev_001: Synthetic evidence\n", encoding="utf-8")
                (entry_dir / "meta.json").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            module.rebuild_indexes(memory_repo)
            candidate = json.loads((memory_repo / "index/memory_review_candidates.jsonl").read_text(encoding="utf-8"))
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = {
                "decision_id": "review_confirm_supersession",
                "action": "approve_supersedes",
                "current_memory_id": candidate["current_memory_id"],
                "older_memory_id": candidate["older_memory_id"],
                "candidate_fingerprint": module.review_candidate_fingerprint(candidate),
                "reviewed_at": "2026-06-23T00:00:00Z",
                "reviewer": "synthetic",
                "rationale": "Synthetic reviewer confirmed the newer memory supersedes the older one.",
            }
            (decision_dir / "memory_lifecycle_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            module.rebuild_indexes(memory_repo)

            nodes = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_id = {node["memory_id"]: node for node in nodes}
            current_node = by_id[candidate["current_memory_id"]]
            old_node = by_id[candidate["older_memory_id"]]
            trace_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memory_consolidation_trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(current_node["supersedes"], [old_node["memory_id"]])
        self.assertEqual(old_node["superseded_by"], current_node["memory_id"])
        self.assertTrue(
            any(
                row.get("decision") == "supersede"
                and row.get("reason") == "confirmed_supersession_link"
                and row.get("current_memory_id") == current_node["memory_id"]
                and row.get("target_memory_id") == old_node["memory_id"]
                for row in trace_rows
            )
        )

    def test_apply_memory_review_decisions_tool_dry_run_outputs_aggregate_only(self):
        module = load_update_module()
        current = self.synthetic_memory_node(
            "mem_current",
            "PRIVATE CURRENT MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-02T10:00:00Z",
        )
        old = self.synthetic_memory_node(
            "mem_old",
            "PRIVATE OLD MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-01T10:00:00Z",
        )
        candidate = self.synthetic_review_candidate()
        decision = self.synthetic_review_decision(module, candidate, "approve_supersedes")

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "reviews").mkdir()
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(current, sort_keys=True) + "\n" + json.dumps(old, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memory_review_candidates.jsonl").write_text(
                json.dumps(candidate, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "reviews/memory_lifecycle_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotIn("PRIVATE CURRENT MEMORY TEXT", result.stdout)
        self.assertNotIn("PRIVATE OLD MEMORY TEXT", result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision_count"], 1)
        self.assertEqual(payload["result_status_counts"], {"applied": 1})
        self.assertEqual(payload["result_action_counts"], {"approve_supersedes": 1})
        self.assertEqual(payload["relation_record_counts_before"]["supersedes"], 0)
        self.assertEqual(payload["relation_record_counts_after"]["supersedes"], 1)
        self.assertFalse(payload["write_enabled"])

    def test_apply_memory_review_decisions_tool_dry_run_handles_already_applied_decisions(self):
        module = load_update_module()
        current_fact = "Cache backend snapshot archive compact policy should stay reviewable."
        old_fact = "Cache backend snapshot archive rebuild metadata should stay reviewable."

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            rows = [
                {
                    "session_id": "old-session",
                    "project": "alpha",
                    "project_path": "/tmp/alpha",
                    "source_record": "source-records/old.jsonl",
                    "source_updated_at": "2026-06-01T10:00:00Z",
                    "summary_path": "sessions/2026/06/01/old/summary.md",
                    "evidence_path": "sessions/2026/06/01/old/evidence.md",
                    "reusable_facts": [old_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["cache", "archive"],
                },
                {
                    "session_id": "current-session",
                    "project": "alpha",
                    "project_path": "/tmp/alpha",
                    "source_record": "source-records/current.jsonl",
                    "source_updated_at": "2026-06-02T10:00:00Z",
                    "summary_path": "sessions/2026/06/02/current/summary.md",
                    "evidence_path": "sessions/2026/06/02/current/evidence.md",
                    "reusable_facts": [current_fact],
                    "decisions": [],
                    "unresolved_tasks": [],
                    "tags": ["cache", "archive"],
                },
            ]
            for row in rows:
                entry_dir = memory_repo / Path(row["summary_path"]).parent
                entry_dir.mkdir(parents=True, exist_ok=True)
                (entry_dir / "summary.md").write_text(f"Summary for {row['session_id']}\n", encoding="utf-8")
                (entry_dir / "evidence.md").write_text("ev_001: Synthetic evidence\n", encoding="utf-8")
                (entry_dir / "meta.json").write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

            module.rebuild_indexes(memory_repo)
            candidate = json.loads((memory_repo / "index/memory_review_candidates.jsonl").read_text(encoding="utf-8"))
            decision_dir = memory_repo / "reviews"
            decision_dir.mkdir()
            decision = {
                "decision_id": "review_confirm_supersession",
                "action": "approve_supersedes",
                "current_memory_id": candidate["current_memory_id"],
                "older_memory_id": candidate["older_memory_id"],
                "candidate_fingerprint": module.review_candidate_fingerprint(candidate),
                "reviewed_at": "2026-06-23T00:00:00Z",
                "reviewer": "synthetic",
                "rationale": "Synthetic reviewer confirmed the newer memory supersedes the older one.",
            }
            (decision_dir / "memory_lifecycle_decisions.jsonl").write_text(
                json.dumps(decision, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            module.rebuild_indexes(memory_repo)

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision_count"], 1)
        self.assertEqual(payload["result_status_counts"], {"applied": 1})
        self.assertEqual(payload["result_action_counts"], {"approve_supersedes": 1})
        self.assertEqual(payload["relation_record_counts_after"]["supersedes"], 1)
        self.assertEqual(payload["relation_record_counts_after"]["superseded_by"], 1)
        self.assertFalse(payload["write_enabled"])

    def test_apply_memory_review_decisions_tool_dry_run_handles_mixed_applied_and_pending_decisions(self):
        module = load_update_module()
        current = self.synthetic_memory_node(
            "mem_current_applied",
            "PRIVATE APPLIED CURRENT MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-04T10:00:00Z",
        )
        old = self.synthetic_memory_node(
            "mem_old_applied",
            "PRIVATE APPLIED OLD MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-03T10:00:00Z",
        )
        module.add_supersession_link(current, old)
        applied_candidate = self.synthetic_review_candidate("mem_current_applied", "mem_old_applied")
        applied_decision = self.synthetic_review_decision(module, applied_candidate, "approve_supersedes")
        applied_result = {
            "decision_id": applied_decision["decision_id"],
            "action": applied_decision["action"],
            "current_memory_id": applied_decision["current_memory_id"],
            "older_memory_id": applied_decision["older_memory_id"],
            "candidate_fingerprint": applied_decision["candidate_fingerprint"],
            "status": "applied",
        }

        pending_current = self.synthetic_memory_node(
            "mem_current_pending",
            "PRIVATE PENDING CURRENT MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-02T10:00:00Z",
        )
        pending_old = self.synthetic_memory_node(
            "mem_old_pending",
            "PRIVATE PENDING OLD MEMORY TEXT SHOULD NOT RENDER",
            last_seen="2026-06-01T10:00:00Z",
        )
        pending_candidate = self.synthetic_review_candidate("mem_current_pending", "mem_old_pending")
        pending_decision = self.synthetic_review_decision(module, pending_candidate, "approve_supersedes")

        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "reviews").mkdir()
            (memory_repo / "index/memories.jsonl").write_text(
                "\n".join(
                    json.dumps(node, sort_keys=True)
                    for node in (current, old, pending_current, pending_old)
                )
                + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memory_review_candidates.jsonl").write_text(
                json.dumps(pending_candidate, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memory_review_decision_results.jsonl").write_text(
                json.dumps(applied_result, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "reviews/memory_lifecycle_decisions.jsonl").write_text(
                json.dumps(applied_decision, sort_keys=True)
                + "\n"
                + json.dumps(pending_decision, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(APPLY_REVIEW_DECISIONS_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--dry-run",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotIn("PRIVATE APPLIED CURRENT MEMORY TEXT", result.stdout)
        self.assertNotIn("PRIVATE PENDING CURRENT MEMORY TEXT", result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision_count"], 2)
        self.assertEqual(payload["result_status_counts"], {"applied": 2})
        self.assertEqual(payload["result_action_counts"], {"approve_supersedes": 2})
        self.assertEqual(payload["relation_record_counts_before"]["supersedes"], 1)
        self.assertEqual(payload["relation_record_counts_after"]["supersedes"], 2)
        self.assertEqual(payload["relation_record_counts_after"]["superseded_by"], 2)
        self.assertFalse(payload["write_enabled"])

    def test_build_memory_nodes_lowers_confidence_for_contradicted_memory(self):
        module = load_update_module()
        old_fact = "Layered retrieval must preserve evidence refs for induced memories."
        current_fact = "Layered retrieval must not preserve evidence refs for induced memories."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [old_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [
                    "Induced layered memories should retain their evidence references during retrieval."
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s3",
                "project": "gamma",
                "project_path": "/tmp/gamma",
                "source_record": "source-records/gamma.jsonl",
                "source_updated_at": "2026-06-03T10:00:00Z",
                "summary_path": "sessions/2026/06/03/gamma/summary.md",
                "evidence_path": "sessions/2026/06/03/gamma/evidence.md",
                "reusable_facts": [current_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}
        old_node = by_text[old_fact]
        current_node = by_text[current_fact]

        self.assertEqual(old_node["confidence"], "low")
        self.assertEqual(current_node["confidence"], "high")
        self.assertEqual(current_node["contradicts"], [old_node["memory_id"]])
        self.assertEqual(old_node["contradicted_by"], [current_node["memory_id"]])
        self.assertEqual(len(current_node["evidence_refs"]), 3)

    def test_build_memory_nodes_preserves_current_side_of_multi_hop_contradiction_chain(self):
        module = load_update_module()
        first_fact = "Layered retrieval must preserve evidence refs for induced memories."
        contradicted_fact = "Layered retrieval must not preserve evidence refs for induced memories."
        final_fact = "Induced layered memories should retain their evidence references during retrieval."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-05-01T10:00:00Z",
                "summary_path": "sessions/2026/05/01/alpha/summary.md",
                "evidence_path": "sessions/2026/05/01/alpha/evidence.md",
                "reusable_facts": [first_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/beta/summary.md",
                "evidence_path": "sessions/2026/06/01/beta/evidence.md",
                "reusable_facts": [contradicted_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s3",
                "project": "gamma",
                "project_path": "/tmp/gamma",
                "source_record": "source-records/gamma.jsonl",
                "source_updated_at": "2026-07-01T10:00:00Z",
                "summary_path": "sessions/2026/07/01/gamma/summary.md",
                "evidence_path": "sessions/2026/07/01/gamma/evidence.md",
                "reusable_facts": [final_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}
        current_node = by_text[first_fact]
        contradicted_node = by_text[contradicted_fact]

        self.assertEqual(current_node["support_count"], 3)
        self.assertEqual(current_node["last_seen"], "2026-07-01T10:00:00Z")
        self.assertEqual(current_node["contradicts"], [contradicted_node["memory_id"]])
        self.assertEqual(contradicted_node["contradicted_by"], [current_node["memory_id"]])
        self.assertEqual(contradicted_node["confidence"], "low")
        self.assertEqual(len(current_node["evidence_refs"]), 3)

    def test_build_memory_nodes_links_deprecated_memory_without_losing_evidence(self):
        module = load_update_module()
        deprecated_fact = "Layered retrieval should keep raw transcript uploads disabled by default."
        rows = [
            {
                "session_id": "s1",
                "project": "alpha",
                "project_path": "/tmp/alpha",
                "source_record": "source-records/alpha.jsonl",
                "source_updated_at": "2026-06-01T10:00:00Z",
                "summary_path": "sessions/2026/06/01/alpha/summary.md",
                "evidence_path": "sessions/2026/06/01/alpha/evidence.md",
                "reusable_facts": [deprecated_fact],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": [
                    "Deprecated fact: Layered retrieval should keep raw transcript uploads disabled by default."
                ],
                "decisions": [],
                "unresolved_tasks": [],
                "tags": ["memory", "retrieval"],
            },
        ]

        nodes = module.build_memory_nodes(rows)
        by_text = {node["text"]: node for node in nodes}
        deprecated_node = by_text[deprecated_fact]
        deprecation_node = next(node for node in nodes if node.get("deprecates"))

        self.assertEqual(deprecation_node["deprecates"], [deprecated_node["memory_id"]])
        self.assertEqual(deprecated_node["deprecated_by"], deprecation_node["memory_id"])
        self.assertEqual(deprecated_node["confidence"], "low")
        self.assertEqual(len(deprecation_node["evidence_refs"]), 2)

    def test_update_memory_archive_induces_domain_memory_from_two_project_sessions(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()
        search_script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            alpha_source_dir = root / "records-alpha"
            beta_source_dir = root / "records-beta"
            project_alpha = root / "alpha"
            project_beta = root / "beta"
            alpha_source_dir.mkdir()
            beta_source_dir.mkdir()
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
            alpha_record = alpha_source_dir / "alpha.jsonl"
            beta_record = beta_source_dir / "beta.jsonl"
            alpha_record.write_text(
                json.dumps({"role": "user", "content": "We need a reusable layered retrieval rule."})
                + "\n"
                + json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}"})
                + "\n",
                encoding="utf-8",
            )
            beta_record.write_text(
                json.dumps({"role": "user", "content": "Apply the same memory retrieval rule in another project."})
                + "\n"
                + json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}"})
                + "\n",
                encoding="utf-8",
            )
            set_mtime(alpha_record, "2026-06-20T10:00:00Z")
            set_mtime(beta_record, "2026-06-20T11:00:00Z")

            for source_dir, project_path in ((alpha_source_dir, project_alpha), (beta_source_dir, project_beta)):
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

            search_result = subprocess.run(
                [
                    sys.executable,
                    str(search_script),
                    "preserve evidence refs induced memories",
                    "--repo",
                    str(memory_repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn("source: memory", search_result.stdout)
            self.assertIn(f"memory_id: {node['memory_id']}", search_result.stdout)
            self.assertIn("evidence:", search_result.stdout)
            for ref in node["evidence_refs"]:
                self.assertIn(f"{ref['path']}#{ref['quote_id']}", search_result.stdout)

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
            (entry_dir / "evidence.md").write_text(
                "ev_direct_001: User explicitly requested this durable rule.\n",
                encoding="utf-8",
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
            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_update_memory_archive_merges_repeated_direct_explicit_memory_evidence(self):
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

            text = "Prefer evidence-bound memories over unsupported recollection."
            support_refs = [
                (
                    "sessions/2026/06/20/direct-explicit-a/summary.md",
                    "sessions/2026/06/20/direct-explicit-a/evidence.md",
                    "ev_direct_a",
                ),
                (
                    "sessions/2026/06/21/direct-explicit-b/summary.md",
                    "sessions/2026/06/21/direct-explicit-b/evidence.md",
                    "ev_direct_b",
                ),
            ]
            for summary_rel, evidence_rel, quote_id in support_refs:
                summary_path = memory_repo / summary_rel
                evidence_path = memory_repo / evidence_rel
                summary_path.parent.mkdir(parents=True)
                summary_path.write_text(f"Summary supporting {text}\n", encoding="utf-8")
                evidence_path.write_text(f"{quote_id}: Evidence supporting {text}\n", encoding="utf-8")
                subprocess.run(
                    [
                        sys.executable,
                        str(update_script),
                        "--memory-repo",
                        str(memory_repo),
                        "--source-dir",
                        str(root),
                        "--explicit-memory",
                        text,
                        "--explicit-layer",
                        "global",
                        "--explicit-scope",
                        "global",
                        "--explicit-summary-path",
                        summary_rel,
                        "--explicit-evidence-ref",
                        f"{evidence_rel}#{quote_id}",
                    ],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            rows = [
                json.loads(line)
                for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            node = rows[0]
            self.assertEqual(node["text"], text)
            self.assertEqual(node["support_count"], 2)
            self.assertEqual(
                node["derived_from"],
                [summary_rel for summary_rel, _, _ in support_refs],
            )
            self.assertEqual(
                node["evidence_refs"],
                [
                    {"path": evidence_rel, "quote_id": quote_id}
                    for _, evidence_rel, quote_id in support_refs
                ],
            )

            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_update_memory_archive_refreshes_automatic_memory_with_supersession_links(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()
        search_script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            old_source_dir = root / "records-old"
            new_source_dir = root / "records-new"
            project_old = root / "old-project"
            project_new = root / "new-project"
            old_source_dir.mkdir()
            new_source_dir.mkdir()
            project_old.mkdir()
            project_new.mkdir()
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            old_fact = "Layered retrieval may omit evidence refs for induced memories."
            new_fact = "Layered retrieval must preserve evidence refs for induced memories."
            old_record = old_source_dir / "old.jsonl"
            new_record = new_source_dir / "new.jsonl"
            old_record.write_text(
                json.dumps({"role": "user", "content": "Record the early layered retrieval behavior."})
                + "\n"
                + json.dumps({"role": "assistant", "content": f"Reusable fact: {old_fact}"})
                + "\n",
                encoding="utf-8",
            )
            new_record.write_text(
                json.dumps({"role": "user", "content": "Refresh the layered retrieval behavior."})
                + "\n"
                + json.dumps({"role": "assistant", "content": f"Reusable fact: Updated fact: {old_fact} => {new_fact}"})
                + "\n",
                encoding="utf-8",
            )
            set_mtime(old_record, "2026-06-20T10:00:00Z")
            set_mtime(new_record, "2026-06-21T10:00:00Z")

            for source_dir, project_path in ((old_source_dir, project_old), (new_source_dir, project_new)):
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

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            old_node = next(row for row in rows if row.get("text") == old_fact)
            current_node = next(row for row in rows if row.get("text") == new_fact)
            self.assertEqual(current_node["supersedes"], [old_node["memory_id"]])
            self.assertEqual(old_node["superseded_by"], current_node["memory_id"])
            self.assertEqual(current_node["support_count"], 2)
            self.assertEqual(len(current_node["derived_from"]), 2)
            self.assertEqual(len(current_node["evidence_refs"]), 2)

            search = subprocess.run(
                [
                    sys.executable,
                    str(search_script),
                    "preserve evidence refs induced memories",
                    "--repo",
                    str(memory_repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertIn(f"memory_id: {current_node['memory_id']}", search.stdout)
            self.assertNotIn(f"memory_id: {old_node['memory_id']}", search.stdout)
            self.assertNotIn(old_fact, search.stdout)
            for ref in current_node["evidence_refs"]:
                self.assertIn(f"{ref['path']}#{ref['quote_id']}", search.stdout)

            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

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

    def test_build_memory_nodes_omits_unsafe_raw_ref_paths(self):
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
                "reusable_facts": ["Layered memories should not leak local source record paths."],
                "decisions": [],
                "unresolved_tasks": [],
                "explicit_memories": ["Prefer concise answers."],
                "tags": ["memory"],
            },
            {
                "session_id": "s2",
                "project": "beta",
                "project_path": "/tmp/beta",
                "source_record": "source-records/beta.jsonl",
                "source_updated_at": "2026-06-02T10:00:00Z",
                "summary_path": "sessions/2026/06/02/beta/summary.md",
                "evidence_path": "sessions/2026/06/02/beta/evidence.md",
                "reusable_facts": ["Safe archive-relative source anchors may be preserved."],
                "decisions": [],
                "unresolved_tasks": [],
                "explicit_memories": ["Use durable benchmark gates."],
                "tags": ["memory"],
            },
            {
                "session_id": "s3",
                "project": "gamma",
                "project_path": "/tmp/gamma",
                "source_record": "../outside/gamma.jsonl",
                "source_updated_at": "2026-06-03T10:00:00Z",
                "summary_path": "sessions/2026/06/03/gamma/summary.md",
                "evidence_path": "sessions/2026/06/03/gamma/evidence.md",
                "reusable_facts": [],
                "decisions": [],
                "unresolved_tasks": [],
                "explicit_memories": ["Use source anchors only when safe."],
                "tags": ["memory"],
            },
        ]

        nodes = module.build_memory_nodes(rows)

        by_text = {node["text"]: node for node in nodes}
        self.assertEqual(by_text["Layered memories should not leak local source record paths."]["raw_refs"], [])
        self.assertEqual(
            by_text["Safe archive-relative source anchors may be preserved."]["raw_refs"],
            [{"path": "source-records/beta.jsonl", "anchor": "source_record"}],
        )
        self.assertEqual(by_text["Prefer concise answers."]["raw_refs"], [])
        self.assertEqual(
            by_text["Use durable benchmark gates."]["raw_refs"],
            [{"path": "source-records/beta.jsonl", "anchor": "explicit_memory"}],
        )
        self.assertEqual(by_text["Use source anchors only when safe."]["raw_refs"], [])

    def test_collect_meta_skips_symlinked_meta_outside_archive(self):
        module = load_update_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            entry_dir = memory_repo / "sessions/2026/05/14/symlink-meta"
            outside_meta = root / "outside-meta.json"
            entry_dir.mkdir(parents=True)
            outside_meta.write_text(
                json.dumps(
                    {
                        "session_id": "outside",
                        "source_updated_at": "2026-05-14T10:00:00Z",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (entry_dir / "meta.json").symlink_to(outside_meta)

            self.assertEqual(module.collect_meta(memory_repo), [])

    def test_write_record_refuses_symlinked_record_file_write_outside_archive(self):
        module = load_update_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_summary = root / "outside-summary.md"
            source_dir.mkdir()
            project_path.mkdir()
            outside_summary.write_text("unchanged\n", encoding="utf-8")

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive record file boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: generated session record files must stay inside the archive.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            source_text = module.read_record_text(source)
            record = module.SourceRecord(
                path=source,
                updated_at=module.source_timestamp(source, source_text),
                sha256=module.sha256_file(source),
            )
            destination = module.record_dir(memory_repo, module.slugify("project"), record)
            destination.mkdir(parents=True)
            (destination / "summary.md").symlink_to(outside_summary)

            with self.assertRaises(SystemExit) as caught:
                module.write_record(
                    memory_repo=memory_repo,
                    project_path=project_path,
                    project_name="project",
                    source_agent="agent",
                    record=record,
                )

            self.assertIn("Refusing to write unsafe archive record file path:", str(caught.exception))
            self.assertEqual(outside_summary.read_text(encoding="utf-8"), "unchanged\n")

    def test_update_memory_archive_creates_searchable_summary(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            config_path = root / "my-precious-config.json"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [
                    sys.executable,
                    str(setup_script),
                    "--path",
                    str(memory_repo),
                    "--mode",
                    "local",
                    "--config-path",
                    str(config_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "session.jsonl"
            source.write_text(
                '{"role":"user","content":"Need migration plan for the archive updater."}\n'
                '{"role":"assistant","content":"Decision: summarize source records before indexing."}\n',
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            update_script = Path("skills/update-my-precious/scripts/update_memory_archive.py").resolve()
            env = os.environ.copy()
            env["MY_PRECIOUS_CONFIG"] = str(config_path)
            env.pop("AGENT_SESSION_MEMORY_REPO", None)
            env.pop("AGENT_MEMORY_REPO", None)
            subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            search_result = subprocess.run(
                [sys.executable, str(Path("skills/using-my-precious/scripts/search_memory.py").resolve()), "migration plan"],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertIn("Top memory hits for: migration plan", search_result.stdout)
            self.assertIn("summary.md", search_result.stdout)

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("migration plan", rows[0]["summary"].lower())
            self.assertIn("migration plan", rows[0]["title"].lower())
            self.assertIn("session.jsonl", rows[0]["source_record"])
            self.assertEqual(rows[0]["archive_status"], "summarized")

            summary_path = memory_repo / rows[0]["summary_path"]
            summary_text = summary_path.read_text(encoding="utf-8")
            self.assertIn("Need migration plan", summary_text)
            self.assertNotIn("Draft summary generated", summary_text)
            self.assertTrue((summary_path.parent / "source-map.json").exists())
            self.assertTrue((memory_repo / "daily/2026/2026-05-14.md").exists())

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
            memory_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            memory_index = "\n".join(json.dumps(row, sort_keys=True) for row in memory_rows)
            self.assertIn("Hybrid lexical search", memory_index)
            self.assertTrue((memory_repo / "memories/projects.jsonl").exists())
            self.assertIn("Hybrid lexical search", (memory_repo / "memories/projects.jsonl").read_text(encoding="utf-8"))
            automatic_node = next(row for row in memory_rows if "Hybrid lexical search" in row["text"])
            expected_source_map = str(Path(automatic_node["derived_from"][0]).with_name("source-map.json"))
            self.assertEqual(
                automatic_node["raw_refs"],
                [{"path": expected_source_map, "anchor": "source_record"}],
            )
            meta = json.loads((memory_repo / Path(automatic_node["derived_from"][0]).parent / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source_map_path"], expected_source_map)

    def test_update_memory_archive_preserves_existing_explicit_memory_nodes(self):
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

            explicit_node = {
                "memory_id": "mem_explicit_preserve_001",
                "layer": "global",
                "scope": "global",
                "topic": "agent-workflow",
                "text": "Prefer concise synthetic release notes for demo projects.",
                "rationale": "Synthetic explicit memory seeded for preservation regression.",
                "source": "explicit",
                "confidence": "high",
                "persistence": "sticky",
                "support_count": 1,
                "first_seen": "2026-06-01T10:00:00Z",
                "last_seen": "2026-06-01T10:00:00Z",
                "derived_from": ["sessions/synthetic/summary.md"],
                "evidence_refs": [{"path": "sessions/synthetic/evidence.md", "quote_id": "ev_explicit_001"}],
                "raw_refs": [{"path": "synthetic/source.jsonl", "anchor": "explicit_memory"}],
                "supersedes": [],
                "superseded_by": None,
                "tags": ["agent-workflow", "synthetic"],
            }
            (memory_repo / "memories/explicit.jsonl").write_text(
                json.dumps(explicit_node, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            source = source_dir / "session.jsonl"
            source.write_text(
                '{"role":"user","content":"Need searchable memory nodes for layered recall."}\n'
                '{"role":"assistant","content":"Decision: Hybrid lexical search should explain field matches and important token coverage."}\n',
                encoding="utf-8",
            )
            set_mtime(source, "2026-06-05T10:00:00Z")

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

            explicit_rows = [
                json.loads(line)
                for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(explicit_rows, [explicit_node])

            index_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn(explicit_node, index_rows)
            self.assertTrue(any("Hybrid lexical search" in row["text"] for row in index_rows))

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
            self.assertIn(
                explicit[0],
                [
                    json.loads(line)
                    for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
                ],
            )
            layer_rows = [
                json.loads(line)
                for name in ("global.jsonl", "domains.jsonl", "projects.jsonl")
                for line in (memory_repo / "memories" / name).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row for row in layer_rows if row["source"] == "explicit"], [])

    def test_update_memory_archive_dedupes_existing_explicit_node_by_text(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        module = load_update_module()

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

            text = "Prefer concise answers."
            preserved_node = {
                "memory_id": "mem_manual_duplicate_text",
                "layer": "global",
                "scope": "global",
                "topic": "agent-workflow",
                "text": text,
                "rationale": "Manual explicit memory with a legacy id.",
                "source": "explicit",
                "confidence": "high",
                "persistence": "sticky",
                "support_count": 1,
                "first_seen": "2026-06-01T10:00:00Z",
                "last_seen": "2026-06-01T10:00:00Z",
                "derived_from": ["sessions/synthetic/summary.md"],
                "evidence_refs": [{"path": "sessions/synthetic/evidence.md", "quote_id": "ev_explicit_001"}],
                "raw_refs": [{"path": "synthetic/source.jsonl", "anchor": "explicit_memory"}],
                "supersedes": [],
                "superseded_by": None,
                "tags": ["agent-workflow", "synthetic"],
            }
            (memory_repo / "memories/explicit.jsonl").write_text(
                json.dumps(preserved_node, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            source = source_dir / "explicit.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": f"Please remember: {text}"}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-06-06T10:00:00Z")

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

            expected_id = module.memory_id_for("global", "global", text, "explicit")
            explicit_rows = [
                json.loads(line)
                for line in (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            explicit_matches = [
                row
                for row in explicit_rows
                if module.normalize_memory_text(row["text"]).lower() == module.normalize_memory_text(text).lower()
            ]
            self.assertEqual(len(explicit_matches), 1)
            self.assertEqual(explicit_matches[0]["memory_id"], expected_id)

            index_rows = [
                json.loads(line)
                for line in (memory_repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            index_matches = [
                row
                for row in index_rows
                if row["source"] == "explicit"
                and module.normalize_memory_text(row["text"]).lower() == module.normalize_memory_text(text).lower()
            ]
            self.assertEqual(len(index_matches), 1)
            self.assertEqual(index_matches[0]["memory_id"], expected_id)

    def test_update_memory_archive_extracts_codex_sessions_without_event_noise(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "gridmen"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "rollout.jsonl"
            events = [
                {
                    "timestamp": "2026-06-02T21:20:47Z",
                    "content": "<permissions instructions> sandbox and network policy injected by the runtime.",
                },
                {
                    "type": "session_meta",
                    "timestamp": "2026-06-02T21:20:48Z",
                    "payload": {
                        "cwd": str(project_path),
                        "base_instructions": {"text": "You are Codex, a coding agent based on GPT-5."},
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-06-02T21:20:49Z",
                    "payload": {"message": "I am checking backend startup logs before changing code."},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:50Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "# AGENTS.md instructions for /repo\n"
                                    "<INSTRUCTIONS>Repository policy injected by the harness.</INSTRUCTIONS>"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:50Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "<turn_aborted> The user interrupted the previous turn on purpose. "
                                    "Any running unified exec processes may still be running in the background."
                                    " </turn_aborted>"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:50Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Gridmen backend crashes on GDAL import; figure out what is going on.",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:50Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<skill><name>update-my-precious</name> injected skill body</skill>",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:51Z",
                    "payload": {
                        "type": "function_call",
                        "name": "update_plan",
                        "arguments": json.dumps({"plan": [{"step": "internal planning noise"}]}),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:51Z",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": "python - <<'PY'\nfrom osgeo import _gdal\nPY"}),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:52Z",
                    "payload": {
                        "type": "function_call_output",
                        "output": (
                            "Chunk ID: abc123\n"
                            "Wall time: 4.89 seconds\n"
                            "Process exited with code 1\n"
                            "Original token count: 436\n"
                            "Output:\n"
                            "Traceback (most recent call last): ImportError: dlopen(... libx265.215.dylib)"
                        ),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:52Z",
                    "payload": {
                        "type": "function_call_output",
                        "output": "write_stdin failed: stdin is closed for this session",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:52Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "I confirmed the branch and commit range, so I’m drilling into "
                                    "the runnable entry points and README commands next."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:52Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "One search command failed because the regex used a lookahead "
                                    "unsupported by the default matcher; I’m rerunning that check."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:53Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    ("Diagnostic context before the durable finding. " * 12)
                                    + "\nKey chain:\n"
                                    "- osgeo loads _gdal\n"
                                    "- Root cause: Homebrew libheif still expected "
                                    "`/opt/homebrew/opt/x265/lib/libx265.215.dylib`; "
                                    "reinstalling Python packages will not fix the GDAL startup crash. "
                                    "**Command Status** - `python -c from osgeo import _gdal`: exit 1"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:53Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Some of what we're working on might be easier to explain if I can show "
                                    "it to you in a web browser. Want me to open one?"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:53Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "I’ll use systematic-debugging if verification exposes a failure.",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-02T21:20:54Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Final state: verified with direct osgeo._gdal import and Homebrew linkage checks.",
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-02T21:20:54Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "gridmen",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("gdal import", row["user_intent"].lower())
            self.assertIn("libx265.215.dylib", row["summary"])
            self.assertIn("homebrew", " ".join(row["tags"]).lower())
            self.assertNotIn("session_meta", json.dumps(row))
            self.assertNotIn("response_item", json.dumps(row))
            self.assertNotIn("event_msg", json.dumps(row))
            self.assertNotIn("base_instructions", json.dumps(row))
            self.assertNotIn("permissions instructions", json.dumps(row))
            self.assertNotIn("AGENTS.md instructions", json.dumps(row))
            self.assertNotIn("<skill>", json.dumps(row))
            self.assertNotIn("update_plan", json.dumps(row))

            summary_path = memory_repo / row["summary_path"]
            combined = "\n".join(
                (summary_path.parent / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("Gridmen backend crashes on GDAL import", combined)
            self.assertIn("Homebrew libheif still expected libx265.215.dylib", combined)
            self.assertNotIn("/opt/homebrew/opt/x265/lib/libx265.215.dylib", combined)
            self.assertNotIn("Command Status", combined)
            self.assertNotIn("python -c from osgeo", combined)
            self.assertIn("direct osgeo._gdal import", combined)
            self.assertNotIn("session_meta", combined)
            self.assertNotIn("response_item", combined)
            self.assertNotIn("event_msg", combined)
            self.assertNotIn("base_instructions", combined)
            self.assertNotIn("permissions instructions", combined)
            self.assertNotIn("AGENTS.md instructions", combined)
            self.assertNotIn("<skill>", combined)
            self.assertNotIn("<turn_aborted>", combined)
            self.assertNotIn("update_plan", combined)
            self.assertNotIn("I’ll use systematic-debugging", combined)
            self.assertNotIn("I confirmed the branch", combined)
            self.assertNotIn("One search command failed", combined)
            self.assertNotIn("Chunk ID", combined)
            self.assertNotIn("Wall time", combined)
            self.assertNotIn("Process exited with code", combined)
            self.assertNotIn("Original token count", combined)
            self.assertNotIn("write_stdin failed", combined)
            self.assertNotIn("Some of what we're working on", combined)
            for noisy_tag in ("task", "you", "are", "run", "using-superpowers", "worktree", "codex_home"):
                self.assertNotIn(noisy_tag, row["tags"])
            for name in ("summary.md", "evidence.md", "redactions.md"):
                text = (summary_path.parent / name).read_text(encoding="utf-8")
                self.assertFalse(text.endswith("\n\n"))
                for line in text.splitlines():
                    self.assertEqual(line, line.rstrip())

            decision_index = (memory_repo / "index/decisions.jsonl").read_text(encoding="utf-8")
            self.assertIn("Homebrew libheif", decision_index)
            self.assertNotIn("response_item", decision_index)

    def test_update_memory_archive_prefers_colocated_repo_over_configured_repo(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_repo = root / "local-agent-memory"
            configured_repo = root / "configured-agent-memory"
            config_path = root / "my-precious-config.json"
            source_dir = root / "records"
            project_path = root / "project"
            source_dir.mkdir()
            project_path.mkdir()

            for repo in (local_repo, configured_repo):
                subprocess.run(
                    [sys.executable, str(setup_script), "--path", str(repo), "--mode", "local", "--skip-config"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

            config_path.write_text(json.dumps({"memory_repo": str(configured_repo)}) + "\n", encoding="utf-8")
            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Archive this in the colocated repository."}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            env = os.environ.copy()
            env["MY_PRECIOUS_CONFIG"] = str(config_path)
            env.pop("AGENT_SESSION_MEMORY_REPO", None)
            env.pop("AGENT_MEMORY_REPO", None)
            subprocess.run(
                [
                    sys.executable,
                    str(local_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertTrue((local_repo / "index/sessions.jsonl").exists())
            self.assertFalse((configured_repo / "index/sessions.jsonl").exists())

    def test_update_memory_archive_refuses_secret_records_by_default(self):
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

            source = source_dir / "leaky.jsonl"
            fake_key = "sk-" + "test-notreal" + ("0" * 20)
            source.write_text(json.dumps({"role": "user", "content": f"secret {fake_key}"}) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to archive", result.stderr)
            self.assertFalse(any((memory_repo / "sessions").glob("**/summary.md")))

    def test_update_memory_archive_sanitizes_secret_record_paths_in_diagnostics(self):
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

            path_secret = "sk-" + "pathnotreal" + ("0" * 20)
            content_secret = "sk-" + "contentnotreal" + ("0" * 20)
            source = source_dir / f"leaky-{path_secret}.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": f"secret {content_secret}"}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to archive", result.stderr)
            self.assertIn("[REDACTED_OPENAI_KEY]", output)
            self.assertNotIn(path_secret, output)

    def test_update_memory_archive_sanitizes_configured_paths_in_diagnostics(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path_secret = "sk-" + "diagnosticpath" + ("0" * 20)
            memory_repo = root / f"agent-memory-{path_secret}"
            source_dir = root / f"records-{path_secret}"
            project_path = root / f"project-{path_secret}"
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
                json.dumps({"role": "assistant", "content": "Decision: keep diagnostics private."}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--dry-run",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertIn("Memory repo:", output)
            self.assertIn("Project path:", output)
            self.assertIn("Source dir:", output)
            self.assertIn("[REDACTED_OPENAI_KEY]", output)
            self.assertNotIn(path_secret, output)

    def test_update_memory_archive_sanitizes_missing_source_dir_errors(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            project_path = root / "project"
            path_secret = "sk-" + "missingsource" + ("0" * 20)
            missing_source_dir = root / f"records-{path_secret}"
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            project_path.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(missing_source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source directory not found:", output)
            self.assertIn("[REDACTED_OPENAI_KEY]", output)
            self.assertNotIn(path_secret, output)

    def test_update_memory_archive_sanitizes_slugged_missing_source_dir_errors(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            project_path = root / "project"
            missing_source_dir = root / "records-cookie_should_not_render"
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            project_path.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(missing_source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source directory not found:", output)
            self.assertIn("[unsafe-path]", output)
            self.assertNotIn("cookie_should_not_render", output)
            self.assertNotIn("cookie", output.lower())

    def test_update_memory_archive_sanitizes_unsafe_archive_entry_errors(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            path_secret = "sk-" + "unsafeentry" + ("0" * 20)
            source_dir.mkdir()
            project_path.mkdir()
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "assistant", "content": "Decision: rewrite matching source records."}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            unsafe_entry_dir = memory_repo / "sessions" / f"unsafe-{path_secret}"
            unsafe_entry_dir.mkdir()
            (unsafe_entry_dir / "meta.json").write_text(
                json.dumps({"project_path": str(project_path.resolve()), "source_record": str(source.resolve())}),
                encoding="utf-8",
            )

            result = subprocess.run(
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
                    "project",
                    "--rewrite-existing",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to remove unsafe archive entry path:", output)
            self.assertIn("[REDACTED_OPENAI_KEY]", output)
            self.assertNotIn(path_secret, output)

    def test_update_memory_archive_refuses_symlinked_session_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_sessions = root / "outside-sessions"
            source_dir.mkdir()
            project_path.mkdir()
            outside_sessions.mkdir()
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "sessions" / "2026").symlink_to(outside_sessions, target_is_directory=True)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive write boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow session symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive entry path:", output)
            self.assertFalse(any(outside_sessions.glob("**/summary.md")))

    def test_update_memory_archive_refuses_symlinked_index_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_index = root / "outside-index"
            source_dir.mkdir()
            project_path.mkdir()
            outside_index.mkdir()
            memory_repo.mkdir()
            (memory_repo / "index").symlink_to(outside_index, target_is_directory=True)
            (memory_repo / "sessions").mkdir()

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive index boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow index symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive index path:", output)
            self.assertFalse((outside_index / "sessions.jsonl").exists())

    def test_update_memory_archive_refuses_symlinked_index_file_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_index_file = root / "outside-sessions.jsonl"
            source_dir.mkdir()
            project_path.mkdir()
            outside_index_file.write_text("unchanged\n", encoding="utf-8")
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "index" / "sessions.jsonl").symlink_to(outside_index_file)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive index file boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow generated index file symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive index file path:", output)
            self.assertEqual(outside_index_file.read_text(encoding="utf-8"), "unchanged\n")

    def test_update_memory_archive_refuses_symlinked_index_overview_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_index = root / "outside-index.md"
            source_dir.mkdir()
            project_path.mkdir()
            outside_index.write_text("unchanged\n", encoding="utf-8")
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "INDEX.md").symlink_to(outside_index)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive overview boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow overview symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive index overview path:", output)
            self.assertEqual(outside_index.read_text(encoding="utf-8"), "unchanged\n")

    def test_update_memory_archive_refuses_symlinked_memories_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_memories = root / "outside-memories"
            source_dir.mkdir()
            project_path.mkdir()
            outside_memories.mkdir()
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "memories").symlink_to(outside_memories, target_is_directory=True)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive memories boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow memories symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive memories path:", output)
            self.assertFalse((outside_memories / "projects.jsonl").exists())

    def test_update_memory_archive_refuses_symlinked_memory_node_file_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_memory_file = root / "outside-global.jsonl"
            source_dir.mkdir()
            project_path.mkdir()
            outside_memory_file.write_text("unchanged\n", encoding="utf-8")
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "memories").mkdir()
            (memory_repo / "memories" / "global.jsonl").symlink_to(outside_memory_file)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "role": "user",
                        "content": "Please remember: avoid writing generated memory files through symlinks.",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: generated memory node files must stay inside the archive.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive memory node file path:", output)
            self.assertEqual(outside_memory_file.read_text(encoding="utf-8"), "unchanged\n")

    def test_update_memory_archive_refuses_symlinked_daily_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_daily = root / "outside-daily"
            source_dir.mkdir()
            project_path.mkdir()
            outside_daily.mkdir()
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "daily").symlink_to(outside_daily, target_is_directory=True)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive daily boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: archive updates must not follow daily symlinks outside the repo.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive daily path:", output)
            self.assertFalse(any(outside_daily.glob("**/*.md")))

    def test_update_memory_archive_refuses_symlinked_daily_file_write_outside_archive(self):
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "project"
            outside_daily_file = root / "outside-daily.md"
            source_dir.mkdir()
            project_path.mkdir()
            outside_daily_file.write_text("unchanged\n", encoding="utf-8")
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "sessions").mkdir()
            (memory_repo / "daily" / "2026").mkdir(parents=True)
            (memory_repo / "daily" / "2026" / "2026-05-14.md").symlink_to(outside_daily_file)

            source = source_dir / "session.jsonl"
            source.write_text(
                json.dumps({"role": "user", "content": "Need a safe archive daily file boundary."}) + "\n"
                + json.dumps(
                    {
                        "role": "assistant",
                        "content": "Decision: generated daily files must not follow symlinks outside the archive.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to write unsafe archive daily file path:", output)
            self.assertEqual(outside_daily_file.read_text(encoding="utf-8"), "unchanged\n")

    def test_update_memory_archive_redacts_secrets_when_explicitly_allowed(self):
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

            source = source_dir / "leaky.jsonl"
            fake_bearer = "abcdefghijklmnopqrstuvwxyz" + "0123456789"
            source.write_text(
                json.dumps({"role": "user", "content": "Authorization: " + "Bearer " + fake_bearer}) + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--allow-redacted-secrets",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = next((memory_repo / "sessions").glob("**/summary.md")).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json", "redactions.md")
            )
            self.assertIn("[REDACTED_BEARER_TOKEN]", combined)
            self.assertIn("bearer_token", combined)
            self.assertNotIn(fake_bearer, combined)

    def test_update_memory_archive_processes_only_new_records_for_project(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

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

            first = source_dir / "first.jsonl"
            second = source_dir / "second.jsonl"
            first.write_text('{"message":"first session"}\n', encoding="utf-8")
            second.write_text('{"message":"second session"}\n', encoding="utf-8")
            set_mtime(first, "2026-05-14T10:00:00Z")
            set_mtime(second, "2026-05-14T11:00:00Z")

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
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            sessions_path = memory_repo / "index/sessions.jsonl"
            rows = [json.loads(line) for line in sessions_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)

            old = source_dir / "old.jsonl"
            newest = source_dir / "newest.jsonl"
            old.write_text('{"message":"older than high water"}\n', encoding="utf-8")
            newest.write_text('{"message":"new newest session"}\n', encoding="utf-8")
            set_mtime(old, "2026-05-14T10:30:00Z")
            set_mtime(newest, "2026-05-14T12:00:00Z")

            result = subprocess.run(
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
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rows = [json.loads(line) for line in sessions_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertIn("Records selected: 1", result.stdout)
            self.assertTrue(any("newest.jsonl" in row["source_record"] for row in rows))
            self.assertFalse(any("old.jsonl" in row["source_record"] for row in rows))

    def test_update_memory_archive_can_rewrite_existing_source_record_entries(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

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

            source = source_dir / "rollout.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Need clean rewrite of the historical memory summary.",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:01Z",
                        "cwd": str(project_path),
                        "role": "assistant",
                        "content": "Decision: rewritten archives must not keep session_meta wrapper text.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T10:00:01Z")

            stale_dir = memory_repo / "sessions/2026/05/14/stale-wrapper-noise"
            stale_dir.mkdir(parents=True)
            stale_meta = {
                "session_id": stale_dir.name,
                "source_agent": "agent",
                "project": "project",
                "project_path": str(project_path.resolve()),
                "source_record": str(source.resolve()),
                "source_record_sha256": "oldhash",
                "source_updated_at": "2026-05-14T09:00:00Z",
                "summary_path": "sessions/2026/05/14/stale-wrapper-noise/summary.md",
                "evidence_path": "sessions/2026/05/14/stale-wrapper-noise/evidence.md",
                "archive_status": "summarized",
                "redaction_status": "none",
                "contains_raw_transcript": False,
                "evidence_policy": "short_redacted_snippets",
                "user_intent": "session_meta: wrapper noise",
                "summary": "response_item: wrapper noise",
                "reusable_facts": ["base_instructions"],
                "tags": ["agent-memory", "session_meta"],
                "decisions": [],
                "unresolved_tasks": [],
                "redaction_counts": {},
            }
            (stale_dir / "meta.json").write_text(json.dumps(stale_meta, sort_keys=True) + "\n", encoding="utf-8")
            (stale_dir / "summary.md").write_text("session_meta: wrapper noise\n", encoding="utf-8")
            (stale_dir / "evidence.md").write_text("response_item: wrapper noise\n", encoding="utf-8")
            (stale_dir / "redactions.md").write_text("- No redactions were applied.\n", encoding="utf-8")
            (stale_dir / "source-map.json").write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
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
                    "project",
                    "--rewrite-existing",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Existing entries removed: 1", result.stdout)
            self.assertFalse(stale_dir.exists())
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (memory_repo / rows[0]["summary_path"]).parent.glob("*.md")
            )
            self.assertIn("Need clean rewrite", combined)
            self.assertNotIn("response_item", combined)
            self.assertNotIn("base_instructions", json.dumps(rows[0]))

    def test_update_memory_archive_uses_record_timestamp_and_project_filter(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir()
            project_a.mkdir()
            project_b.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            a_record = source_dir / "a.jsonl"
            b_record = source_dir / "b.jsonl"
            a_record.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Need project alpha memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            b_record.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T11:00:00Z",
                        "cwd": str(project_b),
                        "role": "user",
                        "content": "Need project beta memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(a_record, "2026-05-14T12:00:00Z")
            set_mtime(b_record, "2026-05-14T12:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("a.jsonl", rows[0]["source_record"])
            self.assertIn("project alpha memory", rows[0]["title"].lower())
            self.assertEqual(rows[0]["source_updated_at"], "2026-05-14T10:00:00Z")

            filename_timestamp_record = source_dir / "2026-05-14T10-30-00Z-project-a.jsonl"
            filename_timestamp_record.write_text(
                json.dumps(
                    {
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Filename timestamp should drive this record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(filename_timestamp_record, "2026-05-14T08:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(row["source_updated_at"] == "2026-05-14T10:30:00Z" for row in rows))

            old_record = source_dir / "old-with-new-mtime.jsonl"
            old_record.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T09:00:00Z",
                        "cwd": str(project_a),
                        "role": "user",
                        "content": "Old source timestamp with newer file mtime.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(old_record, "2026-05-14T13:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 0", result.stdout)

    def test_update_memory_archive_refreshes_changed_source_older_than_project_latest(self):
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

            old_source = source_dir / "old-source.jsonl"
            old_source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Original old source memory.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(old_source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            newer_source = source_dir / "newer-source.jsonl"
            newer_source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T12:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Newer source moves the project high-water mark forward.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(newer_source, "2026-05-14T12:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            old_source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Refreshed old source memory after the later run.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(old_source, "2026-05-14T13:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            rows_with_meta = []
            for row in rows:
                meta_path = memory_repo / Path(row["summary_path"]).parent / "meta.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                rows_with_meta.append((row, meta))
            old_rows = [row for row, meta in rows_with_meta if meta["source_record"].endswith("old-source.jsonl")]
            self.assertEqual(len(old_rows), 1)
            self.assertIn("Refreshed old source", json.dumps(old_rows[0]))
            self.assertNotIn("Original old source", json.dumps(rows))

    def test_update_memory_archive_strips_embedded_process_clauses(self):
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

            source = source_dir / "process-clauses.jsonl"
            events = [
                {
                    "timestamp": "2026-05-14T10:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "Fix linkedProjects after the workspace migration.",
                },
                {
                    "timestamp": "2026-05-14T10:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Using `using-superpowers` as requested. "
                        "This is architectural discussion, so I’ll also use `brainstorming` lightly."
                    ),
                },
                {
                    "timestamp": "2026-05-14T10:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "根因已经比较明确：`.vscode/settings.json` 还指向旧布局。"
                        "现在我检查 Cargo workspace 边界，决定 linkedProjects 应该列哪些 manifest。"
                    ),
                },
                {
                    "timestamp": "2026-05-14T10:00:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "文档本身已经把长期记忆库的目标说得很清楚。"
                        "接下来我会做几项低风险探测。"
                    ),
                },
                {
                    "timestamp": "2026-05-14T10:00:04Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "我现在加一个集成回归测试，专门覆盖 relay URL 注册路径。",
                },
                {
                    "timestamp": "2026-05-14T10:00:05Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "grid smoke 被跳过了，原因是 examples 依赖被移掉了。我会恢复 examples group 后重跑。",
                },
                {
                    "timestamp": "2026-05-14T10:00:06Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "Decision: linkedProjects should list the active workspace manifests.",
                },
                {
                    "timestamp": "2026-05-14T10:00:07Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Ninja 实际存在，所以找不到 Ninja 是 vcpkg configure 中断后的附带错误，"
                        "主阻塞是 GitHub DNS 无法解析。"
                        "接下来我会看仓库内现有 lib 目录。"
                        "Final state: keep vcpkg-side verification marked failed until DNS is available."
                    ),
                },
                {
                    "timestamp": "2026-05-14T10:00:08Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "当前我会按证据先行的顺序走：看未提交测试内容、跑针对性验证。"
                        "现在先定位 cli.py 的 dev command。"
                        "最后一轮我会只使用新鲜的验证结果。"
                    ),
                },
                {
                    "timestamp": "2026-05-14T10:00:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "--- name: systematic-debugging description: Use when encountering any bug, "
                        "test failure, or unexpected behavior --- # Systematic Debugging"
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("根因已经比较明确", combined)
            self.assertIn("grid smoke 被跳过了，原因是 examples 依赖被移掉了", combined)
            self.assertIn("linkedProjects should list the active workspace manifests", combined)
            self.assertIn("主阻塞是 GitHub DNS 无法解析", combined)
            self.assertIn("keep vcpkg-side verification marked failed", combined)
            self.assertNotIn("Using `using-superpowers`", combined)
            self.assertNotIn("I’ll also use", combined)
            self.assertNotIn("现在我检查", combined)
            self.assertNotIn("接下来我会", combined)
            self.assertNotIn("我现在加", combined)
            self.assertNotIn("我会恢复", combined)
            self.assertNotIn("当前我会", combined)
            self.assertNotIn("现在先定位", combined)
            self.assertNotIn("最后一轮我会", combined)
            self.assertNotIn("systematic-debugging", combined)

    def test_update_memory_archive_excludes_process_updates_from_structured_summary(self):
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

            source = source_dir / "process-updates.jsonl"
            events = [
                {
                    "timestamp": "2026-05-14T10:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "Improve My Precious summaries so the archive works as a retrieval index.",
                },
                {
                    "timestamp": "2026-05-14T10:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在我会继续检查摘要器的边界。",
                },
                {
                    "timestamp": "2026-05-14T10:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "第二轮已经接近上一轮耗时，继续等最终输出。",
                },
                {
                    "timestamp": "2026-05-14T10:00:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "这里 process_update 不是旧 wrapper 污染，而是摘要器还把“我接下来会...”这类过程句放进 reusable/problem/unresolved。",
                },
                {
                    "timestamp": "2026-05-14T10:00:04Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在按 TDD 规则只跑这个新测试，确认它确实在旧实现上失败。",
                },
                {
                    "timestamp": "2026-05-14T10:00:05Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在 dry run 然后重写 my-precious 条目，验证刚修的过程句不会再进 Final State/Decisions。",
                },
                {
                    "timestamp": "2026-05-14T10:00:06Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在按顺序执行实际 rewrite，避免两个进程同时重建同一套索引。",
                },
                {
                    "timestamp": "2026-05-14T10:00:07Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在实现最小修复：标题候选改成先用 user intent/decision/fact。",
                },
                {
                    "timestamp": "2026-05-14T10:00:08Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "执行 rewrite。",
                },
                {
                    "timestamp": "2026-05-14T10:00:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "重写时有两个 source record 的 hash 变了，因为对应 JSONL 在后续对话中继续增长。",
                },
                {
                    "timestamp": "2026-05-14T10:00:10Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "顶层文档的测试目录也补上新 audit 测试，方便后续维护者看出它是正式覆盖面。",
                },
                {
                    "timestamp": "2026-05-14T10:00:11Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "现在同步真实工具并再次重写目标条目，检查这次 Final State 和 Unresolved Tasks。",
                },
                {
                    "timestamp": "2026-05-14T10:00:12Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "按上一轮耗时估计还需要几分钟",
                },
                {
                    "timestamp": "2026-05-14T10:00:13Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "同步后重跑刚才两个测试；如果还失败，就说明实现逻辑还需要修。",
                },
                {
                    "timestamp": "2026-05-14T10:00:14Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Decision: reusable facts must contain durable project decisions, "
                        "verification results, or root causes, not live progress narration."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:04Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            summary_path = memory_repo / row["summary_path"]
            combined = "\n".join(
                (summary_path.parent / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("durable project decisions", combined)
            self.assertNotIn("继续等最终输出", combined)
            self.assertNotIn("process_update", combined)
            self.assertNotIn("我接下来会", combined)
            self.assertNotIn("现在我会", combined)
            self.assertNotIn("现在按 TDD", combined)
            self.assertNotIn("现在 dry run", combined)
            self.assertNotIn("现在按顺序执行", combined)
            self.assertNotIn("现在实现最小修复", combined)
            self.assertNotIn("执行 rewrite", combined)
            self.assertNotIn("现在同步真实工具", combined)
            self.assertNotIn("按上一轮耗时估计", combined)
            self.assertNotIn("同步后重跑刚才两个测试", combined)
            self.assertEqual(row["unresolved_count"], 0)
            self.assertNotIn("后续对话中继续增长", combined)
            self.assertNotIn("后续维护者", combined)

    def test_update_memory_archive_writes_retrieval_first_summary_quality(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "cc-switch"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "cc-switch-proxy.jsonl"
            events = [
                {
                    "timestamp": "2026-06-11T21:47:06Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "cc switch这个软件是否能设置代理？",
                },
                {
                    "timestamp": "2026-06-11T21:47:07Z",
                    "cwd": str(project_path),
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps({"cmd": "sed -n '1,180p' README.md"}),
                },
                {
                    "timestamp": "2026-06-11T21:47:08Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "CC Switch supports two proxy concepts: global outbound proxy for CC Switch itself "
                        "and Local Routing for tools routed through CC Switch."
                    ),
                },
                {
                    "timestamp": "2026-06-11T21:47:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Use Settings > Proxy > Global Outbound Proxy with http://127.0.0.1:7890 "
                        "or socks5://127.0.0.1:7890 when CC Switch's own external API traffic needs a proxy."
                    ),
                },
                {
                    "timestamp": "2026-06-11T21:47:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "是的，你要设置的是 CC Switch 自己的出站代理，不是它的“本地代理 / Local Routing”。\n"
                        "在 CC Switch 里进：设置 -> 代理 -> 全局出站代理。\n"
                        "HTTP proxy: http://127.0.0.1:7890\n"
                        "SOCKS5 proxy: socks5://127.0.0.1:7890\n"
                        "关键点：“本地代理”是让 Claude Code/Codex/Gemini 走 CC Switch；"
                        "“全局出站代理”才是让 CC Switch 走你本机代理。"
                    ),
                },
                {
                    "timestamp": "2026-06-11T21:47:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "`libx265 libheif _gdal` 这种精确诊断型查询表现较好，能命中 Gridmen/GDAL 的真实根因。",
                },
                {
                    "timestamp": "2026-06-11T21:47:10Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "subagent_notification agent_path "
                        "019eb5cf-b3a5-7f81-b54d-0f6befad9c3a runtime metadata marker."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-11T21:47:09Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "cc-switch",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            title = row["title"]
            self.assertLessEqual(len(title), 120)
            self.assertIn("cc switch", title.lower())
            self.assertNotIn("```", title)
            self.assertEqual(row["unresolved_count"], 0)
            self.assertEqual(row["tags"][:1], ["cc-switch"])
            for tag in ("proxy", "127.0.0.1", "7890", "socks5"):
                self.assertIn(tag, row["tags"])
            for noisy_tag in ("agent-memory", "my-precious", "users", "soku"):
                self.assertNotIn(noisy_tag, row["tags"])
            for noisy_tag in ("subagent_notification", "agent_path", "019", "019eb5cf-b3a5-7f81-b54d-0f6befad9c3a"):
                self.assertNotIn(noisy_tag, row["tags"])

            entry_dir = memory_repo / Path(row["summary_path"]).parent
            summary_text = (entry_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Global Outbound Proxy", summary_text)
            self.assertIn("Local Routing", summary_text)
            self.assertIn("全局出站代理", summary_text)
            self.assertIn("本地代理", summary_text)
            self.assertIn("127.0.0.1:7890", summary_text)
            self.assertIn("socks5://127.0.0.1:7890", summary_text)
            self.assertNotIn("查询表现", summary_text)
            self.assertNotIn("## Commands And Tools Used", summary_text)
            self.assertNotIn("exec_command", summary_text)
            self.assertNotIn("No source commands were detected automatically", summary_text)
            self.assertNotIn("Review this generated summary", summary_text)

    def test_update_memory_archive_preserves_protocol_example_literals_from_long_answers(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "cc-switch"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "cc-switch-real-proxy-answer.jsonl"
            events = [
                {
                    "timestamp": "2026-06-11T21:47:06Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "cc switch这个软件是否能设置代理？",
                },
                {
                    "timestamp": "2026-06-11T21:47:06Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "我是手让cc-switch走本地代理",
                },
                {
                    "timestamp": "2026-06-11T21:47:07Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "可以。按官方文档看，CC Switch 有两类代理：\n"
                        "1. 全局出站代理：让 CC Switch 自己访问外部 API 时走代理。\n"
                        "路径是：设置 -> 代理 Tab -> 全局出站代理。\n"
                        "2. 本地代理 / Local Routing：让 Claude、Codex、Gemini 等请求先走 CC Switch 的本地代理。\n"
                        "版本上，v3.10.0 已加入全局出站代理。"
                    ),
                },
                {
                    "timestamp": "2026-06-11T21:47:08Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "是的，你要设置的是 CC Switch 自己的出站代理，不是它的本地代理 / Local Routing。\n"
                        "在 CC Switch 里进：设置 -> 代理 -> 全局出站代理。\n"
                        "然后填你的本地代理地址，例如：\n"
                        "http://127.0.0.1:7890\n"
                        "或者如果你的代理软件提供的是 HTTP/Mixed 端口：\n"
                        "http://localhost:7890\n"
                        "常见对应关系：\n"
                        "Clash / Mihomo mixed-port: 7890\n"
                        "Surge HTTP proxy: 通常是 6152 或你自己设置的端口\n"
                        "HTTP proxy: http://127.0.0.1:端口\n"
                        "SOCKS5 proxy: socks5://127.0.0.1:端口\n"
                        "关键点：全局出站代理才是让 CC Switch 走你本机代理。"
                    ),
                },
                {
                    "timestamp": "2026-06-11T21:47:09Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "来源：https://github.com/farion1231/cc-switch 和 "
                        "https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/1-getting-started/1.5-settings.md"
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-11T21:47:09Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "cc-switch",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["title"], "全局出站代理：让 CC Switch 自己访问外部 API 时走代理")
            self.assertIn("socks5", row["tags"])
            self.assertNotIn("github.com", row["tags"])
            self.assertNotIn("user-manual", row["tags"])

            entry_dir = memory_repo / Path(row["summary_path"]).parent
            evidence_text = (entry_dir / "evidence.md").read_text(encoding="utf-8")
            self.assertIn("socks5://127.0.0.1:端口", evidence_text)
            self.assertNotIn("github.com/farion1231", evidence_text)

    def test_update_memory_archive_strips_numbered_answer_prefix_from_retrieval_titles(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "cc-switch"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "numbered-title.jsonl"
            events = [
                {
                    "timestamp": "2026-06-11T21:47:06Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "cc switch这个软件是否能设置代理？",
                },
                {
                    "timestamp": "2026-06-11T21:47:07Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "1. **全局出站代理**：让 CC Switch 自己访问外部 API 时走代理。",
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-11T21:47:07Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "cc-switch",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["title"], "全局出站代理：让 CC Switch 自己访问外部 API 时走代理")

    def test_update_memory_archive_skips_codex_commentary_phase_messages(self):
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

            source = source_dir / "codex-phase.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-05-14T10:00:00Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Improve archive summaries."}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "commentary",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "再同步真实工具并重写一次目标条目；这次重点看 Unresolved Tasks。",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:03Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Decision: skip Codex commentary-phase status messages when archiving durable memory.",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:04Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    '<subagent_notification> {"agent_path":"019eb5cf-b3a5-7f81-b54d-0f6befad9c3a",'
                                    '"status":{"completed":"Decision: Actual update completed."}}'
                                ),
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("skip Codex commentary-phase status messages", combined)
            self.assertNotIn("再同步真实工具", combined)
            self.assertNotIn("subagent_notification", combined)
            self.assertNotIn("agent_path", combined)
            self.assertNotIn("019eb5cf-b3a5-7f81-b54d-0f6befad9c3a", combined)
            self.assertEqual(row["unresolved_count"], 0)

    def test_update_memory_archive_skips_codex_commentary_channel_messages(self):
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

            source = source_dir / "codex-channel.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-05-14T10:00:00Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:01Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Improve archive summaries."}],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:02Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "channel": "commentary",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Decision: channel-commentary-marker should not become durable memory."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-14T10:00:03Z",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "channel": "final",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Decision: skip Codex commentary-channel messages when archiving durable memory.",
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("skip Codex commentary-channel messages", combined)
            self.assertNotIn("channel-commentary-marker", combined)

    def test_update_memory_archive_rejects_placeholder_index_noise(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "quality.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T11:42:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": (
                        "这个skill总结的记忆摘要在/Users/soku/Desktop/agents/agent-memory这个目录下，"
                        "但我感觉写的非常草率，这真能做到我目标的记忆索引的功能吗"
                    ),
                },
                {
                    "timestamp": "2026-06-12T11:42:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "当前版本只能做增量归档和粗略全文搜索，还没有达到高质量记忆索引。"
                        "Decision: add audit gates for placeholder summaries and noisy tags before publishing archive updates."
                    ),
                },
                {
                    "timestamp": "2026-06-12T11:42:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "secret-pattern 扫描无命中；subagent 提到 templates/agent-memory-repo、"
                        "tests/test_update_memory_archive.py 和 update_memory_archive.py。"
                    ),
                },
                {
                    "timestamp": "2026-06-12T11:42:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "流程上做对了 validator、py_compile、template sync；示例搜索 "
                        "`cc-switch 127.0.0.1:7890 socks5 proxy` 和 `libx265 libheif _gdal osgeo` 能排第一。"
                    ),
                },
                {
                    "timestamp": "2026-06-12T11:42:04Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "The implementation has meaningful improvements: unit tests pass, archive audit passes, "
                        "skill validators pass, py_compile passed, template/script sync checks passed.\n"
                        "<oai-mem-citation>\n"
                        "<citation_entries>\n"
                        "MEMORY.md:30-51|note=[memory archive workflow gates and expected archive surfaces]\n"
                        "</citation_entries>\n"
                        "<rollout_ids>\n"
                        "019eb6ef-c1d5-7970-8ebd-bb499cc0dd69\n"
                        "</rollout_ids>\n"
                        "</oai-mem-citation>"
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T11:42:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertLessEqual(len(row["title"]), 120)
            self.assertIn("高质量记忆索引", row["title"])
            self.assertNotIn("/Users/soku/Desktop/agents/agent-memory", row["title"])
            self.assertEqual(row["unresolved_count"], 0)
            for noisy_tag in (
                "secret-pattern",
                "subagent",
                "codespace",
                "mememe",
                "templates",
                "agent-memory-repo",
                "test_update_memory_archive.py",
                "update_memory_archive.py",
                "validator",
                "validators",
                "py_compile",
                "template",
                "sync",
                "implementation",
                "meaningful",
                "improvements",
                "unit",
                "tests",
                "pass",
                "passes",
                "passed",
                "audit",
                "script",
                "checks",
                "cc-switch",
                "libx265",
                "libheif",
                "gdal",
                "osgeo",
            ):
                self.assertNotIn(noisy_tag, row["tags"])

            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertNotIn("No reusable facts were detected automatically", combined)
            self.assertNotIn("No decisions were detected automatically", combined)
            self.assertNotIn("No problems were detected automatically", combined)
            self.assertNotIn("No unresolved tasks were detected automatically", combined)
            self.assertNotIn("No specific evidence snippets were selected automatically", combined)
            self.assertNotIn("secret-pattern 扫描无命中", combined)
            self.assertNotIn("/Users/soku/Desktop/agents/agent-memory这个目录", row["summary"])
            self.assertNotIn("validator", row["summary"])
            self.assertNotIn("validators", row["summary"])
            self.assertNotIn("py_compile", row["summary"])
            self.assertNotIn("cc-switch 127.0.0.1:7890", row["summary"])
            self.assertNotIn("oai-mem-citation", row["summary"])
            self.assertNotIn("MEMORY.md:30-51", row["summary"])
            evidence_text = (entry_dir / "evidence.md").read_text(encoding="utf-8")
            self.assertIn("高质量记忆索引", evidence_text)
            self.assertNotIn("/Users/soku/Desktop/agents/agent-memory这个目录", evidence_text)
            self.assertNotIn("oai-mem-citation", evidence_text)
            self.assertNotIn("MEMORY.md:30-51", evidence_text)

    def test_update_memory_archive_filters_low_signal_fragments_and_run_status(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "low-signal.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T13:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "继续修 my-precious-skill，让它真能做高信噪比记忆索引。",
                },
                {
                    "timestamp": "2026-06-12T13:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "验证结果：",
                },
                {
                    "timestamp": "2026-06-12T13:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "但阻塞点很明确：",
                },
                {
                    "timestamp": "2026-06-12T13:00:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "但这次 subagent 的 `$update-my-precious` 没有产生新写入："
                        "dry run 选中 1 条记录，live update 被默认 secret gate 拒绝，"
                        "原因是 source record 命中 `cookie=33`。"
                    ),
                },
                {
                    "timestamp": "2026-06-12T13:00:04Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Decision: memory summaries must keep durable retrieval facts, "
                        "not one-turn updater status reports."
                    ),
                },
                {
                    "timestamp": "2026-06-12T13:00:05Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Root cause: low-signal heading fragments and run-status details were being indexed "
                        "as reusable facts and decisions."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T13:00:05Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            decisions_index = (memory_repo / "index/decisions.jsonl").read_text(encoding="utf-8")

            self.assertIn("durable retrieval facts", combined)
            self.assertIn("low-signal heading fragments", combined)
            for bad_text in (
                "验证结果：",
                "但阻塞点很明确：",
                "没有产生新写入",
                "dry run 选中",
                "live update",
                "secret gate",
                "cookie=33",
            ):
                self.assertNotIn(bad_text, combined)
                self.assertNotIn(bad_text, decisions_index)
            for noisy_tag in ("dry", "live", "update", "secret", "gate", "cookie", "meta", "user", "intent", "facts"):
                self.assertNotIn(noisy_tag, row["tags"])

    def test_update_memory_archive_filters_operation_status_but_keeps_durable_dry_run_command(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "operation-status.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T14:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "修复 my-precious 的运行状态污染。",
                },
                {
                    "timestamp": "2026-06-12T14:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "**Commands**",
                },
                {
                    "timestamp": "2026-06-12T14:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "I stopped there and did not use `--allow-redacted-secrets`.",
                },
                {
                    "timestamp": "2026-06-12T14:00:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "`git status --short` in project repo: exit 0, clean.",
                },
                {
                    "timestamp": "2026-06-12T14:00:04Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Global memory update completed and pushed from "
                        "::inbox-item{title=\"Memory archive updated\" summary=\"Committed and pushed c02e274\"}"
                    ),
                },
                {
                    "timestamp": "2026-06-12T14:00:05Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "Dry run found 47 discovered projects, 0 new registrations, and 50 enabled projects.",
                },
                {
                    "timestamp": "2026-06-12T14:00:06Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Decision: use `npx rule-porter --from copilot --to agents-md --dry-run` "
                        "to preview rule migration before writing files."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T14:00:06Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )

            self.assertIn("rule-porter", combined)
            self.assertIn("--dry-run", combined)
            for bad_text in (
                "**Commands**",
                "stopped there",
                "allow-redacted-secrets",
                "git status --short",
                "exit 0, clean",
                "Global memory update completed",
                "inbox-item",
                "Dry run found",
                "enabled projects",
            ):
                self.assertNotIn(bad_text, combined)

    def test_update_memory_archive_skips_placeholder_only_source_records(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "placeholder-only.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T15:00:00Z",
                    "cwd": str(project_path),
                    "type": "event_msg",
                    "payload": {"message": "live status only"},
                },
                {
                    "timestamp": "2026-06-12T15:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "phase": "commentary",
                    "content": "我现在检查记忆库。",
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T15:00:01Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Records skipped as low-signal: 1", result.stdout)
            self.assertFalse(any((memory_repo / "sessions").glob("**/summary.md")))
            self.assertFalse((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").strip())

    def test_update_memory_archive_skips_redaction_category_only_source_records(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "redaction-categories.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T15:30:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "Archive source record for my-precious-skill.",
                },
                {
                    "timestamp": "2026-06-12T15:30:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "**Refusal**\nbearer_token, cookie, openai_key\nstayed clean",
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T15:30:01Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Records skipped as low-signal: 1", result.stdout)
            self.assertFalse(any((memory_repo / "sessions").glob("**/summary.md")))
            self.assertFalse((memory_repo / "index/tags.jsonl").read_text(encoding="utf-8").strip())

    def test_update_memory_archive_filters_cross_project_search_verification_examples(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "search-verification-example.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T16:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "评价 my-precious-skill 的记忆索引质量。",
                },
                {
                    "timestamp": "2026-06-12T16:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "结论：当前版本只能算部分符合，还不能算合格的高信噪比记忆索引。"
                        "比如 CC Switch 条目能恢复“全局出站代理 vs Local Routing”的区别，"
                        "Gridmen 条目能恢复 `libheif` 找 `libx265.215.dylib` 的根因。"
                        "4 个关键检索都能把目标条目排第一。"
                        "C-Two top hit 排名正确，但展示标题仍偏 review 语境。"
                        "已验证："
                        "部分 tags 还有 `http/python/cli` 这类偏泛词。"
                    ),
                },
                {
                    "timestamp": "2026-06-12T16:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Decision: memory quality reviews should keep durable critique "
                        "without indexing cross-project search verification examples."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T16:00:02Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("高信噪比记忆索引", combined)
            self.assertIn("cross-project search verification examples", combined)
            for example_text in (
                "CC Switch",
                "Gridmen",
                "libheif",
                "libx265",
                "Local Routing",
                "关键检索",
                "排第一",
                "C-Two top hit",
                "排名正确",
                "已验证：",
                "http/python/cli",
            ):
                self.assertNotIn(example_text, combined)
            for noisy_tag in (
                "cc-switch",
                "gridmen",
                "libheif",
                "libx265.215.dylib",
                "local",
                "routing",
                "top",
                "hit",
                "http",
                "python",
                "cli",
                "c-two",
            ):
                self.assertNotIn(noisy_tag, row["tags"])

    def test_update_memory_archive_filters_incomplete_fragments_and_broken_markdown(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "broken-fragments.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-06-12T14:53:33Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T14:53:34Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "这个skill总结的记忆摘要在/Users/soku/Desktop/agents/agent-memory"
                                    "这个目录下，但我感觉写得草率。"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T14:53:35Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "它更像会话摘要归档器，还不是稳定的高信噪比记忆索引器。",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T14:53:36Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "结论：**只能算部分符合；按你的记忆索引目标，不能算最终验收通过。",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T14:53:37Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Decision: add audit gates for incomplete path fragments before publishing "
                                    "archive updates."
                                ),
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T14:53:37Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertNotIn("这个skill总结的记忆摘要在", combined)
            self.assertNotIn("结论：**", combined)
            self.assertIn("会话摘要归档器", combined)
            self.assertIn("incomplete path fragments", combined)

    def test_update_memory_archive_strips_skill_prefixes_and_heading_noise(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "gridmen"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "skill-prefixes.jsonl"
            events = [
                {
                    "timestamp": "2026-04-24T04:22:41Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "$using-superpowers $doc 我正在为这个仓库对应的论文写4.4节。",
                },
                {
                    "timestamp": "2026-04-24T04:22:42Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "Future messages should adhere to the following personality:\n"
                        "原因很直接：\n"
                        "**方案选择**\n"
                        "**在 4.3 已验证的香港黑雨基线情景上，快速构造一个减灾干预情景。\n"
                        "Decision: Section 4.4 should stay case-specific and explain the Gei Wai intervention."
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-04-24T04:22:42Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "gridmen",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("我正在为这个仓库对应的论文写4.4节", combined)
            self.assertIn("case-specific", combined)
            self.assertNotIn("$using-superpowers", combined)
            self.assertNotIn("$doc", combined)
            self.assertNotIn("Future messages should adhere", combined)
            self.assertNotIn("原因很直接：", combined)
            self.assertNotIn("**方案选择**", combined)
            self.assertNotIn("**在 4.3", combined)

    def test_update_memory_archive_ignores_agents_and_permissions_injected_context(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "c-two"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "agents-context.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-05-08T14:52:00Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-08T14:52:01Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "# AGENTS.md\n"
                                    "Editing files in other directories requires approval.\n"
                                    "Commands are run outside the sandbox if they are approved by the user.\n"
                                    "</permissions instructions>"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-08T14:52:01Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "<environment_context>\n"
                                    "  <cwd>/Users/soku/Desktop/codespace/WorldInProgress/c-two</cwd>\n"
                                    "  <shell>zsh</shell>\n"
                                    "  <timezone>Asia/Shanghai</timezone>\n"
                                    "</environment_context>"
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-08T14:52:02Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Fix concurrent reconnect losers returning spurious 502 in C-Two.",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-08T14:52:03Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "Decision: add a router-level concurrent reconnect integration test before "
                                    "calling the spurious 502 loser path fixed."
                                ),
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-05-08T14:52:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "c-two",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("spurious 502", row["title"])
            self.assertIn("concurrent reconnect", combined)
            self.assertNotIn("# AGENTS.md", combined)
            self.assertNotIn("Editing files in other directories requires approval", combined)
            self.assertNotIn("approved by the user", combined)
            self.assertNotIn("</permissions instructions>", combined)
            self.assertNotIn("<shell>zsh</shell>", combined)
            self.assertNotIn("Asia/Shanghai", combined)

    def test_update_memory_archive_uses_durable_fact_over_status_and_skill_descriptions_for_title(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "c-two"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "status-title-noise.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-27T17:47:06Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:07Z",
                    "payload": {"role": "user", "content": [{"type": "input_text", "text": "<cwd>"}]},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:08Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "APPROVED\n"
                                    "Use when Codex should create a brand-new image or transform an existing image.\n"
                                    "Residual test gap: coverage is mostly ConnectionPool unit-level; there is still "
                                    "no router-level concurrent reconnect integration test proving the loser path "
                                    "avoids a spurious 502 under real call_handler scheduling."
                                ),
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-04-27T17:47:08Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "c-two",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("spurious 502", row["title"])
            self.assertIn("concurrent reconnect", row["title"])
            self.assertNotEqual(row["title"], "APPROVED")
            self.assertNotIn("\n- APPROVED\n", combined)
            self.assertNotIn("Use when Codex should create", combined)
            evidence_text = (entry_dir / "evidence.md").read_text(encoding="utf-8")
            self.assertIn(
                "- Residual test gap: coverage is mostly ConnectionPool unit-level; there is still no router-level "
                "concurrent reconnect integration test proving the loser path avoids a spurious 502",
                evidence_text,
            )

    def test_update_memory_archive_evidence_includes_final_state_that_drives_title(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "c-two"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "final-state-title-evidence.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-27T17:47:06Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:07Z",
                    "payload": {
                        "role": "user",
                        "content": "Final code quality review for Task 1 after reconnect loser fixes.",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:08Z",
                    "payload": {
                        "role": "assistant",
                        "content": "No remaining correctness findings in the current diff for the three requested files.",
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:09Z",
                    "payload": {
                        "role": "assistant",
                        "content": (
                            "Residual test gap: coverage is mostly ConnectionPool unit-level; there is still no "
                            "router-level concurrent reconnect integration test proving the loser path avoids a "
                            "spurious 502 under real call_handler scheduling."
                        ),
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-04-27T17:47:09Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "c-two",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            evidence_text = (entry_dir / "evidence.md").read_text(encoding="utf-8")
            self.assertIn("spurious 502", row["title"])
            self.assertIn("- Residual test gap:", evidence_text)

    def test_update_memory_archive_filters_verifier_prompt_titles_and_generic_tags(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "verifier-prompt.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-06-12T20:32:57Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T20:32:58Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "You are a read-only verifier for the My Precious memory skill work. "
                                    "Do not edit files, stage, commit, or push."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-06-12T20:32:59Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "结论：部分符合，但还不能算合格的高信噪比记忆索引。"
                                    "当前主要是 secret 类别名被索引的低价值噪声问题，不是明文泄漏。"
                                    " RuntimeSession.unregister_route removes stale slots and accepts relay_address calls."
                                ),
                            }
                        ],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T20:32:59Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("高信噪比记忆索引", row["title"])
            self.assertNotIn("read-only verifier", row["title"])
            self.assertNotIn("read-only verifier", combined)
            for noisy_tag in ("accepts", "calls", "removes"):
                self.assertNotIn(noisy_tag, row["tags"])

    def test_update_memory_archive_filters_objective_wrapper_and_search_verification_status(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "my-precious-skill"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "wrapper-and-search-status.jsonl"
            events = [
                {
                    "timestamp": "2026-06-12T21:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "The objective below is user-provided data.",
                },
                {
                    "timestamp": "2026-06-12T21:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "<objective>",
                },
                {
                    "timestamp": "2026-06-12T21:00:00Z",
                    "cwd": str(project_path),
                    "role": "user",
                    "content": "## My request for Codex:",
                },
                {
                    "timestamp": "2026-06-12T21:00:01Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "验证已跑：unit tests pass, archive audit passed, pollution scan clean.",
                },
                {
                    "timestamp": "2026-06-12T21:00:02Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": "`libx265 libheif _gdal osgeo` 第一命中是 Gridmen/GDAL 根因 summary。",
                },
                {
                    "timestamp": "2026-06-12T21:00:03Z",
                    "cwd": str(project_path),
                    "role": "assistant",
                    "content": (
                        "高信噪比记忆索引需要按事件语义抽取事实，避免保存包装 prompt、"
                        "检索验证流水账和纯运行状态。"
                    ),
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-06-12T21:00:03Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "my-precious-skill",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            entry_dir = memory_repo / Path(row["summary_path"]).parent
            combined = "\n".join(
                (entry_dir / name).read_text(encoding="utf-8")
                for name in ("summary.md", "evidence.md", "meta.json")
            )
            self.assertIn("高信噪比记忆索引", row["title"])
            self.assertNotIn("The objective below is user-provided data", combined)
            self.assertNotIn("<objective>", combined)
            self.assertNotIn("My request for Codex", combined)
            self.assertNotIn("验证已跑", combined)
            self.assertNotIn("第一命中是", combined)
            self.assertNotIn("unit tests pass", combined)

    def test_update_memory_archive_prefers_high_specific_final_state_over_review_prompt_title(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "c-two"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "approved-review-gap.jsonl"
            events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-27T17:47:09Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:10Z",
                    "payload": {
                        "role": "user",
                        "content": (
                            "Final code quality review for Task 1 after all stale generation "
                            "and reconnect loser fixes in worktree /Users/soku/work/c-two."
                        ),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:47:11Z",
                    "payload": {
                        "role": "assistant",
                        "content": (
                            "APPROVED\n"
                            "No remaining correctness findings in the current diff for the three requested files.\n"
                            "Residual test gap: coverage is mostly ConnectionPool unit-level; there is still no "
                            "router-level concurrent reconnect integration test proving the loser path avoids "
                            "a spurious 502 under real call_handler scheduling."
                        ),
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")
            set_mtime(source, "2026-04-27T17:47:11Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "c-two",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            row = json.loads((memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("spurious 502", row["title"])
            self.assertIn("concurrent reconnect", row["title"])
            self.assertIn("Missing router-level", row["title"])
            self.assertNotIn("Final code quality review", row["title"])

    def test_update_memory_archive_can_require_project_metadata(self):
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

            scoped = source_dir / "scoped.jsonl"
            unscoped = source_dir / "unscoped.jsonl"
            scoped.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": "Scoped record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            unscoped.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T11:00:00Z",
                        "role": "user",
                        "content": "Unscoped record.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(scoped, "2026-05-14T10:00:00Z")
            set_mtime(unscoped, "2026-05-14T11:00:00Z")

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertIn("scoped.jsonl", rows[0]["source_record"])

    def test_update_memory_archive_ignores_nested_dates_for_source_timestamp(self):
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

            source = source_dir / "nested-date.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-14T10:00:00Z",
                        "cwd": str(project_path),
                        "role": "user",
                        "content": {"date": "2030-01-01T00:00:00Z", "text": "nested date is domain content"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            set_mtime(source, "2026-05-14T08:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(rows[0]["source_updated_at"], "2026-05-14T10:00:00Z")

    def test_update_memory_archive_does_not_skip_same_timestamp_after_max_records(self):
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

            for idx in range(3):
                source = source_dir / f"same-{idx}.jsonl"
                source.write_text(
                    json.dumps(
                        {
                            "timestamp": "2026-05-14T10:00:00Z",
                            "cwd": str(project_path),
                            "role": "user",
                            "content": f"same timestamp {idx}",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                    "--max-records",
                    "2",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/update_memory_archive.py"),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_path),
                    "--project",
                    "project",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Records selected: 1", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 3)

    def test_update_memory_archive_keeps_project_high_water_separate(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_a = root / "project-a"
            project_b = root / "project-b"
            source_dir.mkdir()
            project_a.mkdir()
            project_b.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            source = source_dir / "record.jsonl"
            source.write_text('{"message":"shared record"}\n', encoding="utf-8")
            set_mtime(source, "2026-05-14T10:00:00Z")

            subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_a),
                    "--project",
                    "project-a",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(update_script),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-dir",
                    str(source_dir),
                    "--project-path",
                    str(project_b),
                    "--project",
                    "project-b",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            self.assertIn("Latest archived timestamp: <none>", result.stdout)
            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            project_paths = {row["project_path"] for row in rows}
            self.assertEqual(project_paths, {str(project_a.resolve()), str(project_b.resolve())})

    def test_update_memory_archive_sanitizes_worktree_path_titles(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
        update_script = Path("templates/agent-memory-repo/tools/update_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            source_dir = root / "records"
            project_path = root / "c-two"
            source_dir.mkdir()
            project_path.mkdir()

            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            review = source_dir / "review.jsonl"
            worktree = project_path / ".worktrees" / "issue2-relay-independence"
            review_events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-27T17:39:20Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:39:21Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Final combined spec and code quality review for Task 1 "
                                    f"in worktree {worktree}."
                                ),
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-04-27T17:39:22Z",
                    "payload": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": (
                                    "CHANGES_REQUESTED **Finding** - **Concurrent reconnect losers return "
                                    f"spurious 502**: [router.rs]({worktree}/core/transport/c2-http/src/relay/router.rs:288) "
                                    "treats a lost reconnect race as a failed upstream request."
                                ),
                            }
                        ],
                    },
                },
            ]
            review.write_text("\n".join(json.dumps(event) for event in review_events) + "\n", encoding="utf-8")
            set_mtime(review, "2026-04-27T17:39:22Z")

            prompt_only = source_dir / "prompt-only.jsonl"
            prompt_only_events = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-05-05T21:12:00Z",
                    "payload": {"cwd": str(project_path)},
                },
                {
                    "type": "response_item",
                    "timestamp": "2026-05-05T21:12:01Z",
                    "payload": {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    f"Review the current worktree `{project_path}/.worktrees/route-concurrency-rust-authority-impl` "
                                    "for Phase 4 of `docs/plans/2026-05-05-runtime-session-rust-authority.md`."
                                ),
                            }
                        ],
                    },
                },
            ]
            prompt_only.write_text(
                "\n".join(json.dumps(event) for event in prompt_only_events) + "\n",
                encoding="utf-8",
            )
            set_mtime(prompt_only, "2026-05-05T21:12:01Z")

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
                    "c-two",
                    "--require-project-metadata",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rows = [
                json.loads(line)
                for line in (memory_repo / "index/sessions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            review_row = next(row for row in rows if row["source_record"].endswith("review.jsonl"))
            prompt_row = next(row for row in rows if row["source_record"].endswith("prompt-only.jsonl"))

            self.assertIn("Concurrent reconnect losers return spurious 502", review_row["title"])
            self.assertNotIn("/Users/", review_row["title"])
            self.assertNotIn("worktree", review_row["title"].lower())
            self.assertIn("Review Phase 4", prompt_row["title"])
            self.assertIn("runtime-session-rust-authority", prompt_row["summary"])
            self.assertNotIn("/Users/", prompt_row["title"])
            self.assertNotEqual(prompt_row["summary"], "")


if __name__ == "__main__":
    unittest.main()
