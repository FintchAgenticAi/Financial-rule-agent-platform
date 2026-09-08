import json

from langchain_ollama import ChatOllama

from src.state import PlatformState
from src.utils.json_tools import keep_only_valid_rule_ids, parse_json_response


def make_deduplication_selector(llm: ChatOllama):
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

    return deduplication_selector
