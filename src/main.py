import pandas as pd

from src.config import create_llm
from src.state import PlatformState
from src.utils.json_tools import load_json_file
from src.workflows.graph import build_graph


def main() -> None:
    print(
        "\nFinancial Data Rule Selection Platform"
    )
    print(
        "--------------------------------------"
    )

    dataset_path = input(
        "Enter CSV path "
        "[sample_financial_data.csv]: "
    ).strip()

    if not dataset_path:
        dataset_path = "data/sample_financial_data.csv"

    initial_state: PlatformState = {
        "dataset_path": dataset_path,

        "transformation_catalog": load_json_file(
            "rules/transformation_rules.json"
        ),

        "validation_catalog": load_json_file(
            "rules/validation_rules.json"
        ),

        "deduplication_catalog": load_json_file(
            "rules/deduplication_rules.json"
        )
    }

    llm = create_llm()
    application = build_graph(llm)

    try:
        result = application.invoke(initial_state)

        print("\nWorkflow completed successfully.")

        selected = result[
            "final_result"
        ]["selected_rules"]

        print(
            "Transformation rules:",
            len(selected["transformation"])
        )

        print(
            "Validation rules:",
            len(selected["validation"])
        )

        print(
            "Deduplication rules:",
            len(selected["deduplication"])
        )

        print(
            "\nOpen outputs/selected_rules.json "
            "to view the complete result."
        )

    except FileNotFoundError as error:
        print(f"\nFile error: {error}")

    except pd.errors.EmptyDataError:
        print("\nThe selected CSV file is empty.")

    except pd.errors.ParserError as error:
        print(f"\nCSV parsing error: {error}")

    except Exception as error:
        print(f"\nUnexpected error: {error}")


if __name__ == "__main__":
    main()
