import json

from langchain_ollama import ChatOllama

from src.state import PlatformState
from src.utils.json_tools import keep_only_valid_rule_ids, parse_json_response


def make_transformation_selector(llm: ChatOllama):
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

    return transformation_selector
