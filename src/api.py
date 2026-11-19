import hmac
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


_BUCKET_PATTERN = re.compile(
    r"^(?!\d{1,3}(?:\.\d{1,3}){3}$)(?!.*\.\.)(?!-)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
)
_OBJECT_KEY_MAX_LENGTH = 1024


class RuleSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1, max_length=128)
    r2_bucket: str = Field(min_length=3, max_length=63)
    csv_object_key: str = Field(min_length=1, max_length=_OBJECT_KEY_MAX_LENGTH)
    callback_url: HttpUrl

    @field_validator("request_id", "batch_id", "dataset_id", "r2_bucket", "csv_object_key")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not have leading or trailing whitespace")
        return value

    @field_validator("r2_bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        if not _BUCKET_PATTERN.fullmatch(value):
            raise ValueError("must be a valid R2 bucket name")
        return value

    @field_validator("csv_object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        if value.startswith("/") or "\x00" in value:
            raise ValueError("must be a relative object key without null bytes")
        if any(part == ".." for part in PurePosixPath(value).parts):
            raise ValueError("must not contain parent-directory segments")
        return value


class JobSubmitter(Protocol):
    def submit(self, request: RuleSelectionRequest) -> None:
        """Submit a request for asynchronous processing."""


@dataclass(frozen=True)
class UnavailableJobSubmitter:
    def submit(self, request: RuleSelectionRequest) -> None:
        raise RuntimeError("job submission is not configured")


def _configured_callback_url() -> str:
    return os.environ.get("RULE_MANAGER_APPROVED_CALLBACK_URL", "").strip()


def _configured_api_token() -> str:
    return os.environ.get("RULE_MANAGER_API_TOKEN", "")


def _authenticate(authorization: str | None = Header(default=None)) -> None:
    expected = _configured_api_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    scheme, separator, token = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not separator
        or not hmac.compare_digest(token, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app(job_submitter: JobSubmitter | None = None) -> FastAPI:
    app = FastAPI(title="Financial Rule Agent Platform API", version="1.0")
    app.state.job_submitter = job_submitter or UnavailableJobSubmitter()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        if not _configured_api_token() or not _configured_callback_url():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API is not configured",
            )
        return {"status": "ready"}

    @app.post(
        "/api/v1/rule-selection-requests",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(_authenticate)],
    )
    def submit_rule_selection_request(
        request: RuleSelectionRequest,
    ) -> dict[str, str]:
        approved_callback = _configured_callback_url()
        if not approved_callback or str(request.callback_url) != approved_callback:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="callback_url is not an approved destination",
            )

        try:
            app.state.job_submitter.submit(request)
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

        return {
            "status": "accepted",
            "request_id": request.request_id,
        }

    return app


app = create_app()
