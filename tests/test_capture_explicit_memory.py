import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SETUP_SCRIPT = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def setup_archive(root: Path) -> Path:
    memory_repo = root / "agent-memory"
    subprocess.run(
        [sys.executable, str(SETUP_SCRIPT), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return memory_repo


class CaptureExplicitMemoryTests(unittest.TestCase):
    def test_capture_explicit_memory_jsonl_writes_evidence_bound_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            input_path = root / "explicit-capture.jsonl"
            memory_text = "Prefer explicit memory capture adapter over unsupported recollection."
            input_path.write_text(
                json.dumps(
                    {
                        "text": memory_text,
                        "layer": "domain",
                        "scope": "domain:agent-memory",
                        "source": "explicit_request",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["records_read"], 1)
            self.assertEqual(report["captured"], 1)
            self.assertEqual(report["refused"], 0)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertNotIn(memory_text, result.stdout + result.stderr)

            explicit_rows = read_jsonl(memory_repo / "memories/explicit.jsonl")
            self.assertEqual(len(explicit_rows), 1)
            node = explicit_rows[0]
            self.assertEqual(node["source"], "explicit")
            self.assertEqual(node["persistence"], "sticky")
            self.assertEqual(node["layer"], "domain")
            self.assertEqual(node["scope"], "domain:agent-memory")
            self.assertEqual(node["raw_refs"], [])
            self.assertEqual(len(node["derived_from"]), 1)
            self.assertEqual(len(node["evidence_refs"]), 1)
            self.assertIn(node, read_jsonl(memory_repo / "index/memories.jsonl"))

            search = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/search_memory.py"),
                    "explicit memory capture adapter",
                    "--repo",
                    str(memory_repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertIn(f"memory_id: {node['memory_id']}", search.stdout)
            self.assertNotIn("raw_source_preview", search.stdout)
            self.assertNotIn("raw transcript", search.stdout.lower())

            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_capture_explicit_memory_replace_supersedes_old_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            input_path = root / "explicit-capture.jsonl"
            old_text = "Prefer the legacy explicit revision policy for conflict handling."
            current_text = "Prefer the current explicit revision policy for conflict handling."
            input_path.write_text(
                json.dumps(
                    {
                        "text": old_text,
                        "layer": "domain",
                        "scope": "domain:agent-memory",
                        "source": "explicit_request",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            old_node = read_jsonl(memory_repo / "memories/explicit.jsonl")[0]

            input_path.write_text(
                json.dumps(
                    {
                        "operation": "replace",
                        "text": current_text,
                        "layer": "domain",
                        "scope": "domain:agent-memory",
                        "source": "explicit_request",
                        "replaces_memory_id": old_node["memory_id"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["captured"], 1)
            self.assertEqual(report["revised"], 1)
            self.assertEqual(report["withdrawn"], 0)
            self.assertNotIn(old_text, result.stdout + result.stderr)
            self.assertNotIn(current_text, result.stdout + result.stderr)

            rows = read_jsonl(memory_repo / "memories/explicit.jsonl")
            by_text = {row["text"]: row for row in rows}
            old_node = by_text[old_text]
            current_node = by_text[current_text]
            self.assertEqual(current_node["supersedes"], [old_node["memory_id"]])
            self.assertEqual(old_node["superseded_by"], current_node["memory_id"])
            self.assertIn(old_node["memory_id"], current_node["derived_from"])
            self.assertEqual(len(current_node["evidence_refs"]), 2)

            search = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/search_memory.py"),
                    "explicit revision policy conflict handling",
                    "--repo",
                    str(memory_repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertIn(f"memory_id: {current_node['memory_id']}", search.stdout)
            self.assertNotIn(f"memory_id: {old_node['memory_id']}", search.stdout)
            self.assertNotIn(old_text, search.stdout)
            for ref in current_node["evidence_refs"]:
                self.assertIn(f"{ref['path']}#{ref['quote_id']}", search.stdout)

            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_capture_explicit_memory_withdraw_deprecates_old_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            input_path = root / "explicit-capture.jsonl"
            old_text = "Prefer the obsolete explicit withdrawal policy for conflict handling."
            withdrawal_text = "Withdraw obsolete explicit withdrawal policy for conflict handling."
            input_path.write_text(json.dumps({"text": old_text}, sort_keys=True) + "\n", encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            old_node = read_jsonl(memory_repo / "memories/explicit.jsonl")[0]

            input_path.write_text(
                json.dumps(
                    {
                        "operation": "withdraw",
                        "text": withdrawal_text,
                        "deprecates_memory_id": old_node["memory_id"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["captured"], 1)
            self.assertEqual(report["revised"], 0)
            self.assertEqual(report["withdrawn"], 1)
            rows = read_jsonl(memory_repo / "memories/explicit.jsonl")
            by_text = {row["text"]: row for row in rows}
            old_node = by_text[old_text]
            withdrawal_node = by_text[withdrawal_text]
            self.assertEqual(withdrawal_node["deprecates"], [old_node["memory_id"]])
            self.assertEqual(old_node["deprecated_by"], withdrawal_node["memory_id"])
            self.assertIn(old_node["memory_id"], withdrawal_node["derived_from"])

            search = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/search_memory.py"),
                    "obsolete explicit withdrawal policy conflict handling",
                    "--repo",
                    str(memory_repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotIn(f"memory_id: {old_node['memory_id']}", search.stdout)
            self.assertNotIn(old_text, search.stdout)

            audit = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)

    def test_capture_explicit_memory_refuses_raw_transcript_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            input_path = root / "explicit-capture.jsonl"
            raw_text = "RAW TRANSCRIPT SHOULD NOT BE PRINTED"
            input_path.write_text(
                json.dumps(
                    {
                        "text": "Prefer short explicit memory facts.",
                        "raw_transcript": raw_text,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("raw transcript fields are not accepted", result.stderr)
            self.assertNotIn(raw_text, result.stdout + result.stderr)
            self.assertEqual((memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"), "")

    def test_capture_explicit_memory_missing_input_does_not_leak_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            missing_path = root / "missing-explicit-capture.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(missing_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit memory capture I/O failed", result.stderr)
            self.assertNotIn(str(missing_path), result.stdout + result.stderr)
            self.assertEqual((memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"), "")

    def test_capture_explicit_memory_refuses_unsafe_revision_target_without_leaking_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = setup_archive(root)
            input_path = root / "explicit-capture.jsonl"
            unsafe_id = "mem_cookie_SHOULD_NOT_RENDER"
            input_path.write_text(
                json.dumps(
                    {
                        "operation": "replace",
                        "text": "Prefer safe explicit memory revision targets.",
                        "replaces_memory_id": unsafe_id,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(memory_repo / "tools/capture_explicit_memory.py"),
                    "--memory-repo",
                    str(memory_repo),
                    "--input",
                    str(input_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit memory revision target is unsafe", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stdout + result.stderr)
            self.assertNotIn("cookie", result.stdout + result.stderr)
            self.assertEqual((memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
