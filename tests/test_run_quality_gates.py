import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("tools/run_quality_gates.py").resolve()


def load_gate_module():
    spec = importlib.util.spec_from_file_location("run_quality_gates_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.25
        return self.value


def v1_report(required_passed: int, required_dimensions: int, *, include_sensitive_dimensions: bool = False) -> str:
    report = {
        "report_kind": "v1_layered_memory_readiness_gate",
        "overall_status": "core_synthetic_ready",
        "scorecard": {
            "required_passed": required_passed,
            "required_dimensions": required_dimensions,
            "optional_passed": 0,
            "optional_dimensions": 3,
        },
    }
    if include_sensitive_dimensions:
        report["dimensions"] = {
            "packaged_lifecycle": {
                "status": "passed",
                "memory_text": "SENSITIVE_SENTINEL raw source path /tmp/private-source",
            }
        }
    return json.dumps(report)


class RunQualityGatesTests(unittest.TestCase):
    def fake_success_runner(self, command, **kwargs):
        command_text = " ".join(str(part) for part in command)
        if "-m py_compile" in command_text:
            stdout = "ok\n"
        elif "v1_readiness_gate.py" in command_text and "--require-answer" in command_text:
            stdout = v1_report(6, 6)
        elif "v1_readiness_gate.py" in command_text:
            stdout = v1_report(5, 5)
        else:
            stdout = "ok\n"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    def test_release_check_commands_cover_required_contract(self):
        module = load_gate_module()

        checks = module.build_release_checks()
        commands = [" ".join(check.command) for check in checks]

        self.assertIn("tools/validate_skills.py", commands[0])
        self.assertTrue(any("benchmarks/packaged_lifecycle_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/using_my_precious_runtime_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/query_support_recall_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/progressive_source_drilldown_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/scope_arbitration_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/scope_answer_handoff_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/generated_answer_scope_adapter_gate.py" in command for command in commands))
        self.assertTrue(any("benchmarks/v1_readiness_gate.py --run-packaged" in command for command in commands))
        self.assertTrue(
            any("benchmarks/v1_readiness_gate.py --run-packaged --require-answer" in command for command in commands)
        )
        self.assertTrue(any("-m py_compile" in command for command in commands))
        self.assertTrue(any(command.startswith("diff -qr ") for command in commands))
        self.assertTrue(any(command.startswith("cmp -s ") for command in commands))
        self.assertTrue(any(command == "git diff --check" for command in commands))
        self.assertIn("benchmarks/using_my_precious_runtime_gate.py", module.PY_COMPILE_TARGETS)
        self.assertIn("benchmarks/query_support_recall_gate.py", module.PY_COMPILE_TARGETS)
        self.assertIn("benchmarks/progressive_source_drilldown_gate.py", module.PY_COMPILE_TARGETS)
        self.assertIn("benchmarks/scope_arbitration_gate.py", module.PY_COMPILE_TARGETS)
        self.assertIn("benchmarks/scope_answer_handoff_gate.py", module.PY_COMPILE_TARGETS)
        self.assertIn("benchmarks/generated_answer_scope_adapter_gate.py", module.PY_COMPILE_TARGETS)

    def test_passing_gate_returns_aggregate_scorecards(self):
        module = load_gate_module()

        report = module.run_quality_gates(
            repo_root=Path("/repo"),
            runner=self.fake_success_runner,
            clock=FakeClock(),
        )

        self.assertEqual(report["report_kind"], "my_precious_release_quality_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertEqual(report["scorecards"]["v1_core"]["required_passed"], 5)
        self.assertEqual(report["scorecards"]["v1_core"]["required_dimensions"], 5)
        self.assertEqual(report["scorecards"]["v1_with_answer"]["required_passed"], 6)
        self.assertEqual(report["scorecards"]["v1_with_answer"]["required_dimensions"], 6)
        self.assertTrue(all(check["status"] == "passed" for check in report["checks"]))
        self.assertTrue(all("stdout" not in check and "stderr" not in check for check in report["checks"]))

    def test_v1_summary_does_not_embed_full_readiness_report(self):
        module = load_gate_module()

        def runner(command, **kwargs):
            command_text = " ".join(str(part) for part in command)
            if "-m py_compile" in command_text:
                stdout = "ok\n"
            elif "v1_readiness_gate.py" in command_text and "--require-answer" in command_text:
                stdout = v1_report(6, 6, include_sensitive_dimensions=True)
            elif "v1_readiness_gate.py" in command_text:
                stdout = v1_report(5, 5, include_sensitive_dimensions=True)
            else:
                stdout = "ok\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        report = module.run_quality_gates(repo_root=Path("/repo"), runner=runner, clock=FakeClock())
        rendered = json.dumps(report, sort_keys=True)

        self.assertNotIn('"dimensions":', rendered)
        self.assertNotIn("SENSITIVE_SENTINEL", rendered)
        self.assertNotIn("/tmp/private-source", rendered)

    def test_failure_output_is_bounded_and_returns_nonzero(self):
        module = load_gate_module()
        sensitive = "SENSITIVE_SENTINEL /tmp/private-source raw_source_preview"

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 2, stdout=sensitive, stderr=sensitive)

        stdout = io.StringIO()
        stderr = io.StringIO()

        return_code = module.main(
            [],
            repo_root=Path("/repo"),
            runner=runner,
            clock=FakeClock(),
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(return_code, 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][0]["status"], "failed")
        self.assertEqual(report["checks"][0]["returncode"], 2)
        self.assertEqual(report["checks"][0]["summary"]["reason"], "command_failed")
        self.assertNotIn("stdout", report["checks"][0])
        self.assertNotIn("stderr", report["checks"][0])
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("SENSITIVE_SENTINEL", combined)
        self.assertNotIn("/tmp/private-source", combined)
        self.assertNotIn("raw_source_preview", combined)

    def test_gate_removes_generated_caches_before_template_sync(self):
        module = load_gate_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "templates/agent-memory-repo/tools/__pycache__"

            def runner(command, **kwargs):
                command_text = " ".join(str(part) for part in command)
                if "-m py_compile" in command_text:
                    cache_dir.mkdir(parents=True)
                    (cache_dir / "generated.pyc").write_bytes(b"pyc")
                    stdout = ""
                elif "v1_readiness_gate.py" in command_text and "--require-answer" in command_text:
                    stdout = v1_report(6, 6)
                elif "v1_readiness_gate.py" in command_text:
                    stdout = v1_report(5, 5)
                elif command_text.startswith("diff -qr "):
                    self.assertFalse(cache_dir.exists())
                    stdout = ""
                else:
                    stdout = "ok\n"
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            report = module.run_quality_gates(repo_root=root, runner=runner, clock=FakeClock())

        self.assertEqual(report["status"], "passed")


if __name__ == "__main__":
    unittest.main()
