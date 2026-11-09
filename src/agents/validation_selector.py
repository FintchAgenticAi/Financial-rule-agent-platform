import json

from langchain_ollama import ChatOllama

from src.state import PlatformState
from src.utils.json_tools import keep_only_valid_rule_ids, parse_json_response


def make_validation_selector(llm: ChatOllama):
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

    return validation_selector
