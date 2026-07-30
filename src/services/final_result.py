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
