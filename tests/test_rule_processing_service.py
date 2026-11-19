import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.r2_service import R2UploadError


class FakeR2Service:
    instances = []

    def __init__(self):
        self.settings = {"R2_BUCKET": "financial-rule-platform-dev"}
        self.download_calls = []
        self.upload_calls = []
        self.upload_failure_count = None
        FakeR2Service.instances.append(self)

    @staticmethod
    def validate_identifier(value, field_name):
        if not value or "/" in value:
            raise ValueError(f"Invalid {field_name}")

    @staticmethod
    def validate_object_key(object_key, require_csv=False, require_json=False):
        if require_csv and not object_key.lower().endswith(".csv"):
            raise ValueError("Invalid CSV key")
        if require_json and not object_key.lower().endswith(".json"):
            raise ValueError("Invalid JSON key")

    def validate_bucket(self, bucket):
        if bucket != "financial-rule-platform-dev":
            raise ValueError("Unauthorized R2 bucket")

    def download_csv(self, object_key, destination, overwrite, bucket):
        self.download_calls.append((object_key, destination, overwrite, bucket))
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("name,value\nalpha,1\n", encoding="utf-8")
        return path

    def upload_json_file(self, local_path, object_key, bucket):
        self.upload_calls.append((Path(local_path), object_key, bucket))
        if len(self.upload_calls) == self.upload_failure_count:
            raise R2UploadError("simulated upload failure")


class RuleProcessingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_download_workflow_and_upload_keys(self):
        from src.services.rule_processing_service import process_r2_dataset

        with patch(
            "src.services.rule_processing_service.R2Service",
            FakeR2Service,
        ), patch(
            "src.services.rule_processing_service.run_rule_selection",
            new=self.fake_selection_success,
        ), patch(
            "src.services.rule_processing_service.load_dotenv"
        ):
            result = await process_r2_dataset(
                request_id="req-001",
                dataset_id="ds-001",
                r2_bucket="financial-rule-platform-dev",
                csv_object_key="datasets/ds-001/input.csv",
            )

        r2 = FakeR2Service.instances[-1]
        self.assertEqual(
            r2.download_calls[0][0],
            "datasets/ds-001/input.csv",
        )
        self.assertEqual(len(r2.upload_calls), 3)
        self.assertEqual(
            result["transformation_json_key"],
            "rule-results/ds-001/req-001/"
            "selected_transformation_rules.json",
        )
        self.assertEqual(
            result["validation_json_key"],
            "rule-results/ds-001/req-001/"
            "selected_validation_rules.json",
        )
        self.assertEqual(
            result["deduplication_json_key"],
            "rule-results/ds-001/req-001/"
            "selected_deduplication_rules.json",
        )
        self.assertEqual(result["status"], "completed")

    async def fake_selection_success(self, **kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        names = {
            "transformation": "selected_transformation_rules.json",
            "validation": "selected_validation_rules.json",
            "deduplication": "selected_deduplication_rules.json",
        }
        paths = {}
        for category, name in names.items():
            path = output_dir / name
            path.write_text("[]", encoding="utf-8")
            paths[category] = str(path)
        return {
            "final_result": {"status": "completed"},
            "artifact_paths": {
                "transformation": paths["transformation"],
                "validation": paths["validation"],
                "deduplication": paths["deduplication"],
            },
        }

    async def test_missing_output_file_is_rejected(self):
        from src.services.rule_processing_service import process_r2_dataset

        async def missing_selection(**kwargs):
            output_dir = Path(kwargs["output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            return {
                "final_result": {"status": "completed"},
                "artifact_paths": {
                    "transformation": str(output_dir / "missing.json"),
                    "validation": str(output_dir / "selected_validation_rules.json"),
                    "deduplication": str(output_dir / "selected_deduplication_rules.json"),
                },
            }

        with patch(
            "src.services.rule_processing_service.R2Service",
            FakeR2Service,
        ), patch(
            "src.services.rule_processing_service.run_rule_selection",
            new=missing_selection,
        ), patch(
            "src.services.rule_processing_service.load_dotenv"
        ):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                await process_r2_dataset(
                    "req-002",
                    "ds-002",
                    "financial-rule-platform-dev",
                    "datasets/ds-002/input.csv",
                )

    async def test_partial_upload_failure_is_not_completed(self):
        from src.services.rule_processing_service import process_r2_dataset

        class PartialFailureR2(FakeR2Service):
            def upload_json_file(self, local_path, object_key, bucket):
                super().upload_json_file(local_path, object_key, bucket)
                if len(self.upload_calls) == 2:
                    raise R2UploadError("simulated upload failure")

        with patch(
            "src.services.rule_processing_service.R2Service",
            PartialFailureR2,
        ), patch(
            "src.services.rule_processing_service.run_rule_selection",
            new=self.fake_selection_success,
        ), patch(
            "src.services.rule_processing_service.load_dotenv"
        ):
            with self.assertRaisesRegex(R2UploadError, "upload failure"):
                await process_r2_dataset(
                    "req-003",
                    "ds-003",
                    "financial-rule-platform-dev",
                    "datasets/ds-003/input.csv",
                )

    async def test_invalid_request_and_bucket_are_rejected(self):
        from src.services.rule_processing_service import process_r2_dataset

        with patch(
            "src.services.rule_processing_service.load_dotenv"
        ):
            with self.assertRaises(ValueError):
                await process_r2_dataset(
                    "../bad",
                    "ds-004",
                    "financial-rule-platform-dev",
                    "datasets/ds-004/input.csv",
                )


if __name__ == "__main__":
    unittest.main()
