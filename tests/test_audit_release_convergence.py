import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


AUDIT = Path("tools/audit_release_convergence.py").resolve()


class AuditReleaseConvergenceTests(unittest.TestCase):
    def test_missing_release_evidence_fails_closed_without_rendering_paths(self):
        with tempfile.TemporaryDirectory(prefix="my-precious-release-audit-test-") as tmpdir:
            root = Path(tmpdir)
            source = root / "missing-source"
            installed = root / "missing-installed"
            deployment = root / "missing-deployment"
            automation = root / "missing-automation.toml"

            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT),
                    "--source-repo",
                    str(source),
                    "--approved-ref",
                    "refs/heads/main",
                    "--integration-ref",
                    "refs/heads/dev-feature",
                    "--installed-root",
                    str(installed),
                    "--deployment-repo",
                    str(deployment),
                    "--automation-config",
                    str(automation),
                    "--report-json",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "my_precious_release_convergence")
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["failure"]["reason"], "source_repository_unavailable")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["absolute_paths_rendered"])
        self.assertNotIn(str(root), result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
