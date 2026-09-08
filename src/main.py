import asyncio
import pandas as pd

from src.config import create_llm, create_mcp_clients
from src.state import PlatformState
from src.utils.json_tools import load_json_file
from src.workflows.graph import build_graph


async def run_app() -> None:
    dataset_path = input("Enter CSV path [sample_financial_data.csv]: ").strip() or "data/sample_financial_data.csv"

    clients = create_mcp_clients()

    # initial fetch concurrently
    await asyncio.gather(*(c.fetch_rules() for c in clients.values()))

    # start background polling
    for c in clients.values():
        c.start_polling(interval=30.0)

    initial_state: PlatformState = {
        "dataset_path": dataset_path,
        "transformation_catalog": clients["transformation"].get_cached(),
        "validation_catalog": clients["validation"].get_cached(),
        "deduplication_catalog": clients["deduplication"].get_cached(),
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
        print("\nOpen outputs/selected_rules.json to view the complete result.")

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
