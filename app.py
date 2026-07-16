import json
import re
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph


# =========================================================
# 1. Shared state
# =========================================================

class PlatformState(TypedDict, total=False):
    dataset_path: str
    dataset_profile: dict[str, Any]

    transformation_catalog: list[dict[str, Any]]
    validation_catalog: list[dict[str, Any]]
    deduplication_catalog: list[dict[str, Any]]

    selected_transformations: list[dict[str, Any]]
    selected_validations: list[dict[str, Any]]
    selected_deduplications: list[dict[str, Any]]

    final_result: dict[str, Any]


# =========================================================
# 2. Local LLM
# =========================================================

llm = ChatOllama(
    model="llama3.2",
    temperature=0
)


# =========================================================
# 3. Utility functions
# =========================================================

def load_json_file(path: str) -> Any:
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_json_response(text: str) -> dict[str, Any]:
    """
    Convert an LLM response into a Python dictionary.
    It also removes Markdown JSON fences if present.
    """

    cleaned = text.strip()

    cleaned = re.sub(
        r"^```json\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)

        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    return {
        "selected_rules": [],
        "error": "The model did not return valid JSON.",
        "raw_response": text
    }


def keep_only_valid_rule_ids(
    agent_result: dict[str, Any],
    catalog: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    The LLM is only allowed to select rules that exist
    in the supplied catalog.
    """

    valid_rules = {
        rule["rule_id"]: rule
        for rule in catalog
    }

    safe_results: list[dict[str, Any]] = []

    for selection in agent_result.get("selected_rules", []):
        selected_id = selection.get("rule_id")

        if selected_id in valid_rules:
            safe_results.append(
                {
                    "rule": valid_rules[selected_id],
                    "recommended_columns": selection.get(
                        "recommended_columns",
                        []
                    ),
                    "reason": selection.get(
                        "reason",
                        ""
                    ),
                    "confidence": selection.get(
                        "confidence",
                        0
                    )
                }
            )

    return safe_results


# =========================================================
# 4. Dataset profiling tool
# =========================================================

def profile_dataset(state: PlatformState) -> PlatformState:
    dataset_path = Path(state["dataset_path"])

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {dataset_path}"
        )

    if dataset_path.suffix.lower() != ".csv":
        raise ValueError(
            "The basic version supports CSV files only."
        )

    dataframe = pd.read_csv(dataset_path)

    column_profiles: list[dict[str, Any]] = []

    for column in dataframe.columns:
        series = dataframe[column]

        column_profiles.append(
            {
                "column_name": column,
                "pandas_type": str(series.dtype),
                "missing_count": int(
                    series.isna().sum()
                ),
                "unique_count": int(
                    series.nunique(dropna=True)
                ),
                "sample_values": [
                    str(value)
                    for value in series.dropna().head(5).tolist()
                ]
            }
        )

    profile = {
        "file_name": dataset_path.name,
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "duplicate_row_count": int(
            dataframe.duplicated().sum()
        ),
        "columns": column_profiles
    }

    print("[1/5] Dataset profiling completed.")

    return {
        "dataset_profile": profile
    }


# =========================================================
# 5. Transformation Rule Selector Agent
# =========================================================

def transformation_selector(
    state: PlatformState
) -> PlatformState:

    profile_text = json.dumps(
        state["dataset_profile"],
        indent=2
    )

    catalog_text = json.dumps(
        state["transformation_catalog"],
        indent=2
    )

    prompt = f"""
You are a Transformation Rule Selection Agent.

Your task is NOT to create new rules.

You must examine the dataset profile and select only
suitable rules from the supplied transformation catalog.

DATASET PROFILE:
{profile_text}

AVAILABLE TRANSFORMATION RULES:
{catalog_text}

Return only valid JSON in this format:

{{
  "selected_rules": [
    {{
      "rule_id": "TR-001",
      "recommended_columns": ["column_name"],
      "reason": "Why this existing rule is relevant",
      "confidence": 0.90
    }}
  ]
}}

Requirements:
- Use only rule IDs present in the catalog.
- Do not create new rule IDs.
- Do not transform the data.
- If no rule applies, return an empty selected_rules list.
"""

    response = llm.invoke(prompt)
    parsed = parse_json_response(response.content)

    safe_selections = keep_only_valid_rule_ids(
        parsed,
        state["transformation_catalog"]
    )

    print(
        "[2/5] Transformation Rule Selector completed."
    )

    return {
        "selected_transformations": safe_selections
    }


# =========================================================
# 6. Validation Rule Selector Agent
# =========================================================

def validation_selector(
    state: PlatformState
) -> PlatformState:

    profile_text = json.dumps(
        state["dataset_profile"],
        indent=2
    )

    transformations_text = json.dumps(
        state["selected_transformations"],
        indent=2
    )

    catalog_text = json.dumps(
        state["validation_catalog"],
        indent=2
    )

    prompt = f"""
You are a Validation Rule Selection Agent.

Your task is NOT to create new rules.

Select suitable validation rules from the supplied catalog.

DATASET PROFILE:
{profile_text}

ALREADY SELECTED TRANSFORMATION RULES:
{transformations_text}

AVAILABLE VALIDATION RULES:
{catalog_text}

Return only valid JSON:

{{
  "selected_rules": [
    {{
      "rule_id": "VR-001",
      "recommended_columns": ["column_name"],
      "reason": "Why this existing rule is relevant",
      "confidence": 0.90
    }}
  ]
}}

Requirements:
- Use only rule IDs from the catalog.
- Do not invent rules.
- Do not validate or modify data yet.
- Consider missing values, invalid dates, currency codes
  and unrealistic financial values.
"""

    response = llm.invoke(prompt)
    parsed = parse_json_response(response.content)

    safe_selections = keep_only_valid_rule_ids(
        parsed,
        state["validation_catalog"]
    )

    print(
        "[3/5] Validation Rule Selector completed."
    )

    return {
        "selected_validations": safe_selections
    }


# =========================================================
# 7. Deduplication Rule Selector Agent
# =========================================================

def deduplication_selector(
    state: PlatformState
) -> PlatformState:

    profile_text = json.dumps(
        state["dataset_profile"],
        indent=2
    )

    transformations_text = json.dumps(
        state["selected_transformations"],
        indent=2
    )

    catalog_text = json.dumps(
        state["deduplication_catalog"],
        indent=2
    )

    prompt = f"""
You are a Deduplication Rule Selection Agent.

Your task is NOT to create new deduplication rules.

Select suitable rules from the provided catalog.

DATASET PROFILE:
{profile_text}

SELECTED TRANSFORMATION RULES:
{transformations_text}

AVAILABLE DEDUPLICATION RULES:
{catalog_text}

Return only valid JSON:

{{
  "selected_rules": [
    {{
      "rule_id": "DR-001",
      "recommended_columns": ["column_name"],
      "reason": "Why this existing rule is relevant",
      "confidence": 0.90
    }}
  ]
}}

Requirements:
- Select only rule IDs available in the catalog.
- Do not delete or merge records.
- Only recommend duplicate-detection rules.
- If no duplicate rule is necessary, return an empty list.
"""

    response = llm.invoke(prompt)
    parsed = parse_json_response(response.content)

    safe_selections = keep_only_valid_rule_ids(
        parsed,
        state["deduplication_catalog"]
    )

    print(
        "[4/5] Deduplication Rule Selector completed."
    )

    return {
        "selected_deduplications": safe_selections
    }


# =========================================================
# 8. Create final package for Data Processing Manager
# =========================================================

def create_final_result(
    state: PlatformState
) -> PlatformState:

    final_result = {
        "status": "completed",
        "dataset": state["dataset_profile"]["file_name"],
        "dataset_profile": state["dataset_profile"],

        "selected_rules": {
            "transformation": state[
                "selected_transformations"
            ],
            "validation": state[
                "selected_validations"
            ],
            "deduplication": state[
                "selected_deduplications"
            ]
        },

        "execution_status": "not_executed",
        "requires_approval": True,

        "message": (
            "Rules were selected from the available "
            "mock catalogs. No data was modified."
        )
    }

    output_folder = Path("outputs")
    output_folder.mkdir(exist_ok=True)

    output_path = output_folder / "selected_rules.json"

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            final_result,
            file,
            indent=2,
            ensure_ascii=False
        )

    print("[5/5] Final rule package created.")
    print(f"Saved to: {output_path.resolve()}")

    return {
        "final_result": final_result
    }


# =========================================================
# 9. Build LangGraph
# =========================================================

def build_graph():
    graph = StateGraph(PlatformState)

    graph.add_node(
        "profile_dataset",
        profile_dataset
    )

    graph.add_node(
        "select_transformations",
        transformation_selector
    )

    graph.add_node(
        "select_validations",
        validation_selector
    )

    graph.add_node(
        "select_deduplication",
        deduplication_selector
    )

    graph.add_node(
        "create_final_result",
        create_final_result
    )

    graph.add_edge(
        START,
        "profile_dataset"
    )

    graph.add_edge(
        "profile_dataset",
        "select_transformations"
    )

    graph.add_edge(
        "select_transformations",
        "select_validations"
    )

    graph.add_edge(
        "select_validations",
        "select_deduplication"
    )

    graph.add_edge(
        "select_deduplication",
        "create_final_result"
    )

    graph.add_edge(
        "create_final_result",
        END
    )

    return graph.compile()


# =========================================================
# 10. Start application
# =========================================================

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
        dataset_path = "sample_financial_data.csv"

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

    application = build_graph()

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