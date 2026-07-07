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


if __name__ == "__main__":
    unittest.main()
