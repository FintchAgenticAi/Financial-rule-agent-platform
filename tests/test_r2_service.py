import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from src.services.r2_service import (
    R2ConfigurationError,
    R2DownloadError,
    R2Service,
    R2UploadError,
    R2ValidationError,
)


class R2ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {
            "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "access-key",
            "R2_SECRET_ACCESS_KEY": "secret-key",
            "R2_BUCKET": "bucket",
            "R2_TEST_OBJECT_KEY": "datasets/input.csv",
            "R2_LOCAL_DOWNLOAD_PATH": "data/output.csv",
        }
        self.client = MagicMock()

    def make_service(self) -> R2Service:
        with patch.dict(os.environ, self.environment, clear=True):
            with patch("src.services.r2_service.boto3.client", return_value=self.client):
                return R2Service()

    def test_missing_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(R2ConfigurationError):
                R2Service()

    def test_placeholder_configuration(self) -> None:
        values = self.environment | {
            "R2_ACCESS_KEY_ID": "YOUR_ACCESS_KEY_ID"
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(R2ConfigurationError):
                R2Service()

    def test_successful_csv_download(self) -> None:
        service = self.make_service()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "download.csv"

            def download(_bucket: str, _key: str, path: str) -> None:
                Path(path).write_text("name,value\nalpha,1\n", encoding="utf-8")

            self.client.download_file.side_effect = download
            result = service.download_csv(destination_path=destination)

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "name,value\nalpha,1\n")
            self.assertFalse(destination.with_name("download.csv.part").exists())

    def test_missing_remote_object(self) -> None:
        service = self.make_service()
        error = ClientError(
            {"Error": {"Code": "NoSuchKey"}}, "GetObject"
        )
        self.client.download_file.side_effect = error
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(R2DownloadError, "not found"):
                service.download_csv(destination_path=Path(directory) / "x.csv")

    def test_access_denied(self) -> None:
        service = self.make_service()
        error = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "GetObject"
        )
        self.client.download_file.side_effect = error
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(R2DownloadError, "access denied"):
                service.download_csv(destination_path=Path(directory) / "x.csv")

    def test_empty_csv(self) -> None:
        service = self.make_service()
        self.client.download_file.side_effect = (
            lambda _bucket, _key, path: Path(path).write_text("", encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(R2DownloadError):
                service.download_csv(destination_path=Path(directory) / "x.csv")

    def test_malformed_csv(self) -> None:
        service = self.make_service()
        self.client.download_file.side_effect = (
            lambda _bucket, _key, path: Path(path).write_text(
                '"unterminated\nvalue', encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(R2DownloadError):
                service.download_csv(destination_path=Path(directory) / "x.csv")

    def test_existing_output_requires_overwrite(self) -> None:
        service = self.make_service()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "x.csv"
            destination.write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(R2DownloadError, "already exists"):
                service.download_csv(destination_path=destination)
            self.client.download_file.assert_not_called()

    def test_partial_file_is_cleaned_up(self) -> None:
        service = self.make_service()

        def partial_download(_bucket: str, _key: str, path: str) -> None:
            Path(path).write_text("header\n", encoding="utf-8")
            raise OSError("connection interrupted")

        self.client.download_file.side_effect = partial_download
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "x.csv"
            with self.assertRaises(R2DownloadError):
                service.download_csv(destination_path=destination)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name("x.csv.part").exists())

    def test_successful_json_upload_and_verification(self) -> None:
        service = self.make_service()
        self.client.head_object.return_value = {"ContentLength": 2}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected_rules.json"
            path.write_text('[{"rule_id": "TR-001"}]', encoding="utf-8")

            result = service.upload_json_file(
                path,
                "rule-results/ds-001/req-001/selected_rules.json",
                bucket="bucket",
            )

            self.assertIsInstance(result, dict)
            self.client.put_object.assert_called_once()
            call = self.client.put_object.call_args.kwargs
            self.assertEqual(call["ContentType"], "application/json")
            self.client.head_object.assert_called_once_with(
                Bucket="bucket",
                Key="rule-results/ds-001/req-001/selected_rules.json",
            )

    def test_invalid_json_upload_is_rejected(self) -> None:
        service = self.make_service()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected_rules.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(R2UploadError):
                service.upload_json_file(
                    path,
                    "rule-results/ds-001/req-001/selected_rules.json",
                )
            self.client.put_object.assert_not_called()

    def test_unauthorized_bucket_is_rejected(self) -> None:
        service = self.make_service()
        with self.assertRaises(R2ValidationError):
            service.validate_bucket("another-bucket")

    def test_invalid_json_object_key_is_rejected(self) -> None:
        service = self.make_service()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "selected_rules.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(R2ValidationError):
                service.upload_json_file(
                    path,
                    "../selected_rules.json",
                )


if __name__ == "__main__":
    unittest.main()
