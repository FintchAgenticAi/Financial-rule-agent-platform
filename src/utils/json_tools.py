import json
import re
from pathlib import Path
from typing import Any


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
