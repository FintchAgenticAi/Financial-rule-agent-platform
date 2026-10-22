import asyncio
import pandas as pd
import httpx

from src.config import create_llm, create_mcp_clients
from src.state import PlatformState
from src.utils.json_tools import load_json_file
from src.workflows.graph import build_graph


async def load_catalog(
    client,
    local_path: str,
    catalog_name: str
) -> tuple[list[dict], bool]:
    try:
        await client.fetch_rules()
        print(f"Loaded {catalog_name} rules from MCP service.")
        return client.get_cached(), True
    except (httpx.HTTPError, OSError) as error:
        print(
            f"MCP service unavailable for {catalog_name} ({error}). "
            f"Using {local_path}."
        )
        return load_json_file(local_path), False


async def run_app() -> None:
    dataset_path = input("Enter CSV path [sample_financial_data.csv]: ").strip() or "data/sample_financial_data.csv"

    clients = create_mcp_clients()

    catalog_paths = {
        "transformation": "rules/transformation_rules.json",
        "validation": "rules/validation_rules.json",
        "deduplication": "rules/deduplication_rules.json",
    }

    catalog_results = await asyncio.gather(
        *(
            load_catalog(
                clients[name],
                catalog_paths[name],
                name
            )
            for name in clients
        )
    )

    catalogs = {
        name: result[0]
        for name, result in zip(clients, catalog_results)
    }

    # start background polling
    for name, result in zip(clients, catalog_results):
        if result[1]:
            clients[name].start_polling(interval=30.0)

    initial_state: PlatformState = {
        "dataset_path": dataset_path,
        "transformation_catalog": catalogs["transformation"],
        "validation_catalog": catalogs["validation"],
        "deduplication_catalog": catalogs["deduplication"],
    }

    llm = create_llm()
    application = build_graph(llm)

    try:
        result = await asyncio.to_thread(application.invoke, initial_state)

        print("\nWorkflow completed successfully.")

        selected = result["final_result"]["selected_rules"]

        print("Transformation rules:", len(selected["transformation"]))
        print("Validation rules:", len(selected["validation"]))
        print("Deduplication rules:", len(selected["deduplication"]))
        print("\nSelected rules saved in the outputs folder by category.")

    except FileNotFoundError as error:
        print(f"\nFile error: {error}")

    except pd.errors.EmptyDataError:
        print("\nThe selected CSV file is empty.")

    except pd.errors.ParserError as error:
        print(f"\nCSV parsing error: {error}")

    except Exception as error:
        print(f"\nUnexpected error: {error}")

    finally:
        await asyncio.gather(*(c.close() for c in clients.values()))


if __name__ == "__main__":
    asyncio.run(run_app())
