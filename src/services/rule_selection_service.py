import asyncio
from pathlib import Path
from typing import Any

import httpx

from src.config import create_llm, create_mcp_clients
from src.state import PlatformState
from src.utils.json_tools import load_json_file
from src.workflows.graph import build_graph


CATALOG_PATHS = {
    "transformation": "rules/transformation_rules.json",
    "validation": "rules/validation_rules.json",
    "deduplication": "rules/deduplication_rules.json",
}


async def load_catalog(
    client: Any,
    local_path: str,
    catalog_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        await client.fetch_rules()
        print(f"Loaded {catalog_name} rules from MCP service.")
        return client.get_cached(), {
            "source": "remote",
            "endpoint": client.base_url,
        }
    except (httpx.HTTPError, OSError, ValueError) as error:
        print(
            f"MCP service unavailable for {catalog_name} ({error}). "
            f"Using {local_path}."
        )
        return load_json_file(local_path), {
            "source": "fallback",
            "path": local_path,
        }


async def run_rule_selection(
    dataset_path: str,
    output_dir: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    if not dataset_path:
        raise ValueError("dataset_path is required.")
    if not output_dir:
        raise ValueError("output_dir is required.")

    dataset = Path(dataset_path)
    if not dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset}")

    output_folder = Path(output_dir)
    output_folder.mkdir(parents=True, exist_ok=True)

    clients = create_mcp_clients()

    try:
        catalog_results = await asyncio.gather(
            *(
                load_catalog(
                    clients[name],
                    CATALOG_PATHS[name],
                    name,
                )
                for name in clients
            )
        )

        catalogs = {
            name: catalog_results[index][0]
            for index, name in enumerate(clients)
        }
        catalog_sources = {
            name: catalog_results[index][1]
            for index, name in enumerate(clients)
        }

        initial_state: PlatformState = {
            "dataset_path": str(dataset),
            "output_dir": str(output_folder),
            "transformation_catalog": catalogs["transformation"],
            "validation_catalog": catalogs["validation"],
            "deduplication_catalog": catalogs["deduplication"],
            "catalog_sources": catalog_sources,
        }
        if request_id is not None:
            initial_state["request_id"] = request_id

        llm = create_llm()
        application = build_graph(llm)
        result = await asyncio.to_thread(application.invoke, initial_state)

        selected = result["final_result"]["selected_rules"]
        artifact_paths = {
            "dataset_profile": str(
                (output_folder / "dataset_profile.json").resolve()
            ),
            "transformation": str(
                (output_folder / "selected_transformation_rules.json").resolve()
            ),
            "validation": str(
                (output_folder / "selected_validation_rules.json").resolve()
            ),
            "deduplication": str(
                (output_folder / "selected_deduplication_rules.json").resolve()
            ),
        }

        return {
            "final_result": result["final_result"],
            "selected_rules": selected,
            "catalog_sources": catalog_sources,
            "artifact_paths": artifact_paths,
            "request_id": request_id,
        }
    finally:
        await asyncio.gather(
            *(client.close() for client in clients.values())
        )
