import asyncio
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.services.r2_service import R2Service, R2ValidationError
from src.services.rule_selection_service import run_rule_selection


def _validate_inputs(
    request_id: str,
    dataset_id: str,
    r2_bucket: str,
    csv_object_key: str,
) -> None:
    R2Service.validate_identifier(request_id, "request ID")
    R2Service.validate_identifier(dataset_id, "dataset ID")
    R2Service.validate_object_key(csv_object_key, require_csv=True)
    if not isinstance(r2_bucket, str) or not r2_bucket:
        raise R2ValidationError("Invalid R2 bucket.")


async def process_r2_dataset(
    request_id: str,
    dataset_id: str,
    r2_bucket: str,
    csv_object_key: str,
) -> dict[str, Any]:
    load_dotenv()
    _validate_inputs(request_id, dataset_id, r2_bucket, csv_object_key)

    r2 = R2Service()
    r2.validate_bucket(r2_bucket)

    output_keys = {
        "transformation": (
            f"rule-results/{dataset_id}/{request_id}/"
            "selected_transformation_rules.json"
        ),
        "validation": (
            f"rule-results/{dataset_id}/{request_id}/"
            "selected_validation_rules.json"
        ),
        "deduplication": (
            f"rule-results/{dataset_id}/{request_id}/"
            "selected_deduplication_rules.json"
        ),
    }
    for object_key in output_keys.values():
        r2.validate_object_key(object_key, require_json=True)

    with tempfile.TemporaryDirectory(
        prefix=f"financial-rule-{request_id}-"
    ) as temporary_root:
        root = Path(temporary_root)
        input_dir = root / "input"
        output_dir = root / "outputs"
        input_dir.mkdir(parents=True)

        input_path = input_dir / "dataset.csv"
        await asyncio.to_thread(
            r2.download_csv,
            csv_object_key,
            input_path,
            False,
            r2_bucket,
        )

        selection_result = await run_rule_selection(
            dataset_path=str(input_path),
            output_dir=str(output_dir),
            request_id=request_id,
        )

        local_paths = selection_result["artifact_paths"]
        required_files = {
            "transformation": Path(
                local_paths["transformation"]
            ),
            "validation": Path(
                local_paths["validation"]
            ),
            "deduplication": Path(
                local_paths["deduplication"]
            ),
        }

        missing_files = [
            category
            for category, path in required_files.items()
            if not path.is_file()
        ]
        if missing_files:
            raise RuntimeError(
                "LangGraph processing did not generate required JSON output; "
                "missing: "
                + ", ".join(missing_files)
            )

        uploaded_keys: dict[str, str] = {}
        for category, local_path in required_files.items():
            await asyncio.to_thread(
                r2.upload_json_file,
                local_path,
                output_keys[category],
                r2_bucket,
            )
            uploaded_keys[category] = output_keys[category]

    return {
        "request_id": request_id,
        "dataset_id": dataset_id,
        "status": "completed",
        "r2_bucket": r2_bucket,
        "transformation_json_key": uploaded_keys["transformation"],
        "validation_json_key": uploaded_keys["validation"],
        "deduplication_json_key": uploaded_keys["deduplication"],
        "rule_selection": selection_result["final_result"],
    }
