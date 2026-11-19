import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.rule_selection_service import run_rule_selection


class FakeLLM:
    def invoke(self, _prompt: str):
        class Response:
            content = '{"selected_rules": []}'

        return Response()


class FakeMCPClient:
    def __init__(self, base_url: str, remote: bool = True):
        self.base_url = base_url
        self.remote = remote
        self.closed = False

    async def fetch_rules(self) -> None:
        if not self.remote:
            raise OSError("MCP unavailable")

    def get_cached(self) -> list[dict]:
        return [{
            "rule_id": "REMOTE-001",
            "kind": "test",
            "spec": {},
        }]

    async def close(self) -> None:
        self.closed = True


def fake_clients(remote: bool = True) -> dict[str, FakeMCPClient]:
    return {
        "transformation": FakeMCPClient("http://test/transformation", remote),
        "validation": FakeMCPClient("http://test/validation", remote),
        "deduplication": FakeMCPClient("http://test/deduplication", remote),
    }


class RuleSelectionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_path_and_request_output_directory(self) -> None:
        csv_path = Path("data") / "sample_financial_data.csv"

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "request-a"
            clients = fake_clients(remote=False)

            with patch(
                "src.services.rule_selection_service.create_mcp_clients",
                return_value=clients,
            ), patch(
                "src.services.rule_selection_service.create_llm",
                return_value=FakeLLM(),
            ), patch("builtins.input", side_effect=AssertionError("input() called")):
                result = await run_rule_selection(
                    dataset_path=str(csv_path),
                    output_dir=str(output_dir),
                    request_id="request-a",
                )

            expected_files = [
                "dataset_profile.json",
                "selected_transformation_rules.json",
                "selected_validation_rules.json",
                "selected_deduplication_rules.json",
            ]
            for file_name in expected_files:
                self.assertTrue((output_dir / file_name).is_file())

            self.assertEqual(result["request_id"], "request-a")
            self.assertEqual(
                set(result["catalog_sources"]),
                {"transformation", "validation", "deduplication"},
            )
            self.assertTrue(
                all(
                    source["source"] == "fallback"
                    for source in result["catalog_sources"].values()
                )
            )
            self.assertTrue(all(client.closed for client in clients.values()))

            with (output_dir / "selected_transformation_rules.json").open(
                encoding="utf-8"
            ) as file:
                payload = json.load(file)
            self.assertIsInstance(payload, list)

    async def test_remote_catalog_provenance_and_cleanup(self) -> None:
        csv_path = Path("data") / "sample_financial_data.csv"

        with tempfile.TemporaryDirectory() as directory:
            clients = fake_clients(remote=True)
            output_dir = Path(directory)

            with patch(
                "src.services.rule_selection_service.create_mcp_clients",
                return_value=clients,
            ), patch(
                "src.services.rule_selection_service.create_llm",
                return_value=FakeLLM(),
            ):
                result = await run_rule_selection(
                    dataset_path=str(csv_path),
                    output_dir=str(output_dir),
                    request_id="remote-request",
                )

            self.assertTrue(
                all(
                    source["source"] == "remote"
                    for source in result["catalog_sources"].values()
                )
            )
            self.assertTrue(all(client.closed for client in clients.values()))

    async def test_separate_output_directories_do_not_collide(self) -> None:
        csv_path = Path("data") / "sample_financial_data.csv"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_dir = root / "first"
            second_dir = root / "second"

            first_clients = fake_clients(remote=True)
            second_clients = fake_clients(remote=True)

            with patch(
                "src.services.rule_selection_service.create_mcp_clients",
                side_effect=[first_clients, second_clients],
            ), patch(
                "src.services.rule_selection_service.create_llm",
                return_value=FakeLLM(),
            ):
                await run_rule_selection(
                    str(csv_path), str(first_dir), "first"
                )
                await run_rule_selection(
                    str(csv_path), str(second_dir), "second"
                )

            self.assertTrue((first_dir / "dataset_profile.json").is_file())
            self.assertTrue((second_dir / "dataset_profile.json").is_file())
            self.assertTrue(all(client.closed for client in first_clients.values()))
            self.assertTrue(all(client.closed for client in second_clients.values()))

    async def test_cleanup_and_error_propagation_on_workflow_failure(self) -> None:
        csv_path = Path("data") / "sample_financial_data.csv"
        clients = fake_clients(remote=True)

        class FailingGraph:
            def invoke(self, _state):
                raise RuntimeError("workflow failed")

        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "src.services.rule_selection_service.create_mcp_clients",
                return_value=clients,
            ), patch(
                "src.services.rule_selection_service.create_llm",
                return_value=FakeLLM(),
            ), patch(
                "src.services.rule_selection_service.build_graph",
                return_value=FailingGraph(),
            ):
                with self.assertRaisesRegex(RuntimeError, "workflow failed"):
                    await run_rule_selection(
                        str(csv_path),
                        directory,
                        "failure-request",
                    )

        self.assertTrue(all(client.closed for client in clients.values()))

    async def test_missing_dataset_raises_before_client_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "src.services.rule_selection_service.create_mcp_clients"
            ) as create_clients:
                with self.assertRaises(FileNotFoundError):
                    await run_rule_selection(
                        str(Path(directory) / "missing.csv"),
                        str(Path(directory) / "outputs"),
                        "missing-request",
                    )

        create_clients.assert_not_called()


if __name__ == "__main__":
    unittest.main()
