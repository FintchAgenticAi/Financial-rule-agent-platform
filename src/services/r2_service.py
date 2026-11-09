import csv
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
)
from dotenv import load_dotenv


class R2ConfigurationError(ValueError):
    """Raised when required R2 settings are missing or still placeholders."""


class R2DownloadError(RuntimeError):
    """Raised when an R2 download or local CSV validation fails."""


class R2Service:
    required_settings = (
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_TEST_OBJECT_KEY",
        "R2_LOCAL_DOWNLOAD_PATH",
    )

    def __init__(self) -> None:
        load_dotenv()
        self.settings = self._load_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings["R2_ENDPOINT_URL"],
            aws_access_key_id=self.settings["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=self.settings["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def _load_settings(self) -> dict[str, str]:
        settings = {
            name: os.environ.get(name, "").strip()
            for name in self.required_settings
        }
        missing = [
            name for name, value in settings.items() if not value
        ]
        placeholders = [
            name
            for name, value in settings.items()
            if self._is_placeholder(value)
        ]
        if missing:
            raise R2ConfigurationError(
                "Missing required R2 configuration: "
                + ", ".join(missing)
            )
        if placeholders:
            raise R2ConfigurationError(
                "Replace placeholder R2 configuration values: "
                + ", ".join(placeholders)
            )
        endpoint = settings["R2_ENDPOINT_URL"].lower()
        if not endpoint.startswith("https://"):
            raise R2ConfigurationError(
                "R2_ENDPOINT_URL must be an HTTPS Cloudflare R2 endpoint."
            )
        if ".r2.cloudflarestorage.com" not in endpoint:
            raise R2ConfigurationError(
                "R2_ENDPOINT_URL must be a Cloudflare R2 S3-compatible endpoint."
            )
        return settings

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        upper_value = value.upper()
        return (
            "YOUR_" in upper_value
            or "PLACEHOLDER" in upper_value
            or "ACCOUNT_ID" in upper_value
            or value in {
                "VALIDATION_SERVER_IP",
                "DEDUPLICATION_SERVER_IP",
            }
        )

    def validate_csv_file(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8", newline="") as file:
                reader = csv.reader(file, strict=True)
                header = next(reader, None)
                if not header or not any(cell.strip() for cell in header):
                    raise R2DownloadError(
                        "Downloaded CSV is empty or has no header."
                    )
                for _ in reader:
                    pass
        except UnicodeDecodeError as error:
            raise R2DownloadError(
                "Downloaded file is not readable as UTF-8 CSV."
            ) from error
        except csv.Error as error:
            raise R2DownloadError(
                "Downloaded file is not a valid CSV."
            ) from error

    def download_csv(
        self,
        object_key: str | None = None,
        destination_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        key = object_key or self.settings["R2_TEST_OBJECT_KEY"]
        destination = Path(
            destination_path or self.settings["R2_LOCAL_DOWNLOAD_PATH"]
        )
        if destination.exists() and not overwrite:
            raise R2DownloadError(
                f"Local destination already exists: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path = destination.with_name(destination.name + ".part")
        if part_path.exists():
            part_path.unlink()
        try:
            self.client.download_file(
                self.settings["R2_BUCKET"],
                key,
                str(part_path),
            )
            if not part_path.exists() or part_path.stat().st_size == 0:
                raise R2DownloadError("Downloaded file is empty.")
            self.validate_csv_file(part_path)
            if destination.exists() and not overwrite:
                raise R2DownloadError(
                    f"Local destination already exists: {destination}"
                )
            part_path.replace(destination)
            return destination
        except R2DownloadError:
            raise
        except ClientError as error:
            raise R2DownloadError(
                self._client_error_message(error)
            ) from error
        except (
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
            TimeoutError,
            OSError,
        ) as error:
            raise R2DownloadError(
                f"R2 download failed due to a network or local file error: "
                f"{type(error).__name__}."
            ) from error
        except NoCredentialsError as error:
            raise R2DownloadError(
                "R2 credentials were rejected or are unavailable."
            ) from error
        finally:
            if part_path.exists():
                part_path.unlink()

    @staticmethod
    def _client_error_message(error: ClientError) -> str:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "404", "NotFound"}:
            return "R2 object was not found."
        if code in {"AccessDenied", "Forbidden"}:
            return "R2 access denied. Check the bucket permissions."
        if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            return "R2 credentials are invalid."
        return "R2 request failed. Check the endpoint, bucket, and permissions."

    def head_object(self, object_key: str | None = None) -> dict[str, Any]:
        key = object_key or self.settings["R2_TEST_OBJECT_KEY"]
        try:
            return self.client.head_object(
                Bucket=self.settings["R2_BUCKET"],
                Key=key,
            )
        except ClientError as error:
            raise R2DownloadError(
                self._client_error_message(error)
            ) from error
        except (
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
            TimeoutError,
        ) as error:
            raise R2DownloadError(
                "R2 object check failed due to a network timeout or connection error."
            ) from error
