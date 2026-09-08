import importlib.util
import json
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


SETUP_SCRIPT = Path(
    "skills/setup-my-precious/scripts/setup_semantic_retrieval.py"
).resolve()


def load_setup_module():
    spec = importlib.util.spec_from_file_location(
        "setup_semantic_retrieval_under_test",
        SETUP_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SetupSemanticRetrievalTests(unittest.TestCase):
    def runtime_layout(self, root: Path, setup):
        repo = root / "agent-memory"
        (repo / "tools").mkdir(parents=True)
        return setup.build_layout(
            memory_repo=repo,
            config_path=root / "config.json",
            runtime_root=root / "runtime",
            state_root=root / "state",
            socket_path=root / "s.sock",
            plist_path=root / "LaunchAgents" / f"{setup.SERVICE_LABEL}.plist",
        )

    def test_layout_keeps_runtime_and_state_outside_memory_repo(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            repo.mkdir()

            with self.assertRaisesRegex(
                setup.SetupError,
                "semantic_runtime_must_be_outside_memory_repo",
            ):
                setup.build_layout(
                    memory_repo=repo,
                    runtime_root=repo / ".runtime",
                    state_root=root / "state",
                    config_path=root / "config.json",
                    socket_path=root / "s.sock",
                    plist_path=root / "LaunchAgents" / f"{setup.SERVICE_LABEL}.plist",
                )

    def test_private_config_update_is_atomic_idempotent_and_backed_up(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            repo.mkdir()
            config_path = root / "config" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"memory_repo": str(repo), "version": 1}) + "\n",
                encoding="utf-8",
            )
            config_path.chmod(0o600)
            layout = setup.build_layout(
                memory_repo=repo,
                config_path=config_path,
                runtime_root=root / "runtime",
                state_root=root / "state",
                socket_path=root / "s.sock",
                plist_path=root / "LaunchAgents" / f"{setup.SERVICE_LABEL}.plist",
            )
            provider_block = setup.configured_provider_block(
                layout,
                provider_fingerprint="a" * 64,
                support_threshold=0.90,
                timeout_seconds=5.0,
            )

            changed, backup_created = setup.write_private_config(layout, provider_block)
            changed_again, backup_again = setup.write_private_config(layout, provider_block)

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            backup_path = config_path.with_name(
                f"{config_path.name}.pre-semantic-retrieval"
            )
            self.assertTrue(changed)
            self.assertTrue(backup_created)
            self.assertFalse(changed_again)
            self.assertFalse(backup_again)
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["semantic_retrieval_provider"], provider_block)
            self.assertTrue(backup_path.is_file())
            self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup_path.stat().st_mode), 0o600)

    def test_launchd_definition_uses_absolute_paths_and_offline_environment(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            repo.mkdir()
            layout = setup.build_layout(
                memory_repo=repo,
                config_path=root / "config.json",
                runtime_root=root / "runtime",
                state_root=root / "state",
                socket_path=root / "s.sock",
                plist_path=root / "LaunchAgents" / f"{setup.SERVICE_LABEL}.plist",
            )

            payload = setup.launchd_plist(layout, batch_size=32, device="cpu")

        arguments = payload["ProgramArguments"]
        self.assertTrue(all(Path(value).is_absolute() for value in arguments[:2]))
        self.assertEqual(payload["Label"], setup.SERVICE_LABEL)
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["EnvironmentVariables"]["HF_HUB_OFFLINE"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["TRANSFORMERS_OFFLINE"], "1")

    def test_plan_report_is_aggregate_only(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            (repo / "tools").mkdir(parents=True)
            layout = setup.build_layout(
                memory_repo=repo,
                config_path=root / "config.json",
                runtime_root=root / "runtime",
                state_root=root / "state",
                socket_path=root / "s.sock",
                plist_path=root / "LaunchAgents" / f"{setup.SERVICE_LABEL}.plist",
            )

            report = setup.plan_report(layout, service_backend="launchd")

        rendered = json.dumps(report, sort_keys=True)
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report["planned_mutations"]["service_enable"])
        self.assertNotIn(str(root), rendered)

    def test_provision_environment_uses_uv_without_clearing_existing_data(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                venv_path = Path(command[-1])
                (venv_path / "bin").mkdir(parents=True)
                (venv_path / "bin/python").write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            created = setup.provision_python_environment(
                layout,
                uv_path=Path("/usr/local/bin/uv"),
                python_version="3.12",
                runner=runner,
            )
            created_again = setup.provision_python_environment(
                layout,
                uv_path=Path("/usr/local/bin/uv"),
                python_version="3.12",
                runner=runner,
            )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(len(calls), 1)
        self.assertIn("--no-project", calls[0])
        self.assertNotIn("--clear", calls[0])

    def test_model_downloads_are_revision_pinned_and_file_bounded(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            (layout.venv_path / "bin").mkdir(parents=True)
            (layout.venv_path / "bin/python").write_text("", encoding="utf-8")
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                destination = Path(command[5])
                for relative in json.loads(command[6]):
                    path = destination / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("fixture", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            download_count = setup.provision_models(layout, runner=runner)
            second_download_count = setup.provision_models(layout, runner=runner)

        self.assertEqual(len(calls), 2)
        self.assertEqual(download_count, 2)
        self.assertEqual(second_download_count, 0)
        self.assertEqual(calls[0][3], setup.EMBEDDING_MODEL_ID)
        self.assertEqual(calls[0][4], setup.EMBEDDING_MODEL_REVISION)
        self.assertEqual(tuple(json.loads(calls[0][6])), setup.EMBEDDING_MODEL_FILES)
        self.assertEqual(calls[1][3], setup.RERANKER_MODEL_ID)
        self.assertEqual(calls[1][4], setup.RERANKER_MODEL_REVISION)
        self.assertEqual(tuple(json.loads(calls[1][6])), setup.RERANKER_MODEL_FILES)

    def test_provider_identity_requires_reranker_enabled(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            layout.provider_script.write_text("", encoding="utf-8")
            (layout.venv_path / "bin").mkdir(parents=True)
            (layout.venv_path / "bin/python").write_text("", encoding="utf-8")

            def runner(command, **_kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "report_kind": "memory_semantic_retrieval_provider_identity",
                            "provider_fingerprint": "a" * 64,
                            "reranker_enabled": True,
                        }
                    ),
                    "",
                )

            fingerprint = setup.provider_identity(layout, runner=runner)

        self.assertEqual(fingerprint, "a" * 64)

    def test_semantic_health_verifies_private_socket_and_index_identity(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            index_path = layout.memory_repo / "index" / "memories.jsonl"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text('{"memory_id":"mem_target"}\n', encoding="utf-8")
            socket_path = layout.socket_path
            socket_path.parent.mkdir(parents=True, exist_ok=True)
            ready = threading.Event()
            errors = []

            def serve():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                        server.bind(str(socket_path))
                        socket_path.chmod(0o600)
                        server.listen(1)
                        ready.set()
                        connection, _ = server.accept()
                        with connection:
                            request = connection.recv(65536)
                            self.assertIn(b"memory_semantic_retrieval_health_request", request)
                            connection.sendall(
                                json.dumps(
                                    {
                                        "report_kind": "memory_semantic_retrieval_health_response",
                                        "report_version": 1,
                                        "status": "ready",
                                        "provider_fingerprint": "a" * 64,
                                        "index_sha256": setup.sha256_file(index_path),
                                        "memory_count": 1,
                                        "reranker_enabled": True,
                                    }
                                ).encode("utf-8")
                                + b"\n"
                            )
                except BaseException as exc:
                    errors.append(exc)
                    ready.set()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(2))
            health = setup.semantic_health(
                layout,
                provider_fingerprint="a" * 64,
            )
            thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNotNone(health)
        assert health is not None
        self.assertEqual(health["memory_count"], 1)

    def test_enable_launchd_service_uses_bootstrap_then_kickstart(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            layout.plist_path.parent.mkdir(parents=True, exist_ok=True)
            layout.plist_path.write_text("plist", encoding="utf-8")
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                returncode = 1 if command[1] == "print" else 0
                return subprocess.CompletedProcess(command, returncode, "", "")

            with patch.object(setup.platform, "system", return_value="Darwin"):
                newly_loaded = setup.enable_launchd_service(layout, runner=runner)

        self.assertTrue(newly_loaded)
        self.assertEqual([command[1] for command in calls], ["print", "bootstrap", "kickstart"])

    def test_cli_plan_is_read_only_and_aggregate_only(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            repo.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    str(SETUP_SCRIPT),
                    "--plan",
                    "--memory-repo",
                    str(repo),
                    "--runtime-root",
                    str(root / "runtime"),
                    "--state-root",
                    str(root / "state"),
                    "--socket",
                    str(root / "s.sock"),
                    "--config",
                    str(root / "config.json"),
                    "--plist",
                    str(root / "LaunchAgents" / "semantic.plist"),
                    "--service-backend",
                    "none",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "planned")
        self.assertNotIn(str(root), result.stdout)

    def test_disable_private_config_is_non_destructive_and_idempotent(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            layout.config_path.write_text(
                json.dumps(
                    {
                        "memory_repo": str(layout.memory_repo),
                        "semantic_retrieval_provider": {
                            "enabled": True,
                            "socket": str(layout.socket_path),
                            "provider_fingerprint": "a" * 64,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            layout.config_path.chmod(0o600)

            changed = setup.disable_private_config(layout)
            changed_again = setup.disable_private_config(layout)

            payload = json.loads(layout.config_path.read_text(encoding="utf-8"))
            self.assertTrue(changed)
            self.assertFalse(changed_again)
            self.assertFalse(payload["semantic_retrieval_provider"]["enabled"])
            self.assertEqual(payload["semantic_retrieval_provider"]["socket"], str(layout.socket_path))
            self.assertEqual(stat.S_IMODE(layout.config_path.stat().st_mode), 0o600)
            self.assertFalse(layout.runtime_root.exists())

    def test_check_report_fails_closed_for_incomplete_runtime_without_paths(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)

            report = setup.check_report(
                layout,
                service_backend="none",
                batch_size=32,
                device="cpu",
            )

        self.assertEqual(report["status"], "drifted")
        self.assertFalse(report["checks"]["provider_health_ready"])
        self.assertNotIn(str(root), json.dumps(report, sort_keys=True))

    def test_install_enables_config_only_after_service_health(self):
        setup = load_setup_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layout = self.runtime_layout(root, setup)
            layout.provider_script.write_text("", encoding="utf-8")
            layout.requirements_path.write_text("numpy==1.0\n", encoding="utf-8")
            layout.config_path.write_text(
                json.dumps({"memory_repo": str(layout.memory_repo)}) + "\n",
                encoding="utf-8",
            )
            layout.config_path.chmod(0o600)
            health = {
                "memory_count": 7,
                "provider_fingerprint": "a" * 64,
            }

            with (
                patch.object(setup, "provision_python_environment", return_value=True),
                patch.object(setup, "install_provider_dependencies"),
                patch.object(setup, "provision_models", return_value=2),
                patch.object(setup, "provider_identity", return_value="a" * 64),
                patch.object(setup, "write_launchd_plist", return_value=True),
                patch.object(setup, "enable_launchd_service", return_value=True),
                patch.object(setup, "wait_for_semantic_health", return_value=(health, 1.25)),
            ):
                report = setup.install_runtime(
                    layout,
                    service_backend="launchd",
                    python_version="3.12",
                    support_threshold=0.90,
                    timeout_seconds=5.0,
                    batch_size=32,
                    device="cpu",
                    wait_seconds=180,
                    uv_path=Path("/usr/local/bin/uv"),
                )

            config = json.loads(layout.config_path.read_text(encoding="utf-8"))

        self.assertEqual(report["status"], "installed")
        self.assertEqual(report["metrics"]["provider_health_ready"], 1)
        self.assertEqual(report["metrics"]["provider_memory_count"], 7)
        self.assertTrue(config["semantic_retrieval_provider"]["enabled"])
        self.assertEqual(
            config["semantic_retrieval_provider"]["provider_fingerprint"],
            "a" * 64,
        )


if __name__ == "__main__":
    unittest.main()
