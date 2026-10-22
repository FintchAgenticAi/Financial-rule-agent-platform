import json
from pathlib import Path

from src.state import PlatformState


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

    selected_rule_files = {
        "transformation": "selected_transformation_rules.json",
        "validation": "selected_validation_rules.json",
        "deduplication": "selected_deduplication_rules.json",
    }

    for category, file_name in selected_rule_files.items():
        output_path = output_folder / file_name

        with output_path.open(
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                final_result["selected_rules"][category],
                file,
                indent=2,
                ensure_ascii=False
            )

        print(f"Saved to: {output_path.resolve()}")

    print("[5/5] Final rule package created.")

    return {
        "final_result": final_result
    }
