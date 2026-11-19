import asyncio
import pandas as pd

from src.services.rule_selection_service import run_rule_selection


async def run_app() -> None:
    dataset_path = input("Enter CSV path [sample_financial_data.csv]: ").strip() or "data/sample_financial_data.csv"

    try:
        output_dir = "outputs"
        result = await run_rule_selection(
            dataset_path=dataset_path,
            output_dir=output_dir,
        )

        print("\nWorkflow completed successfully.")

        selected = result["selected_rules"]

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


if __name__ == "__main__":
    asyncio.run(run_app())
