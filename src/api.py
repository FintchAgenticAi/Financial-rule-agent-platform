import hmac
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.jobs.database import (
    JobDatabaseError,
    JobIdConflict,
    JobRecordNotFound,
    JobStore,
)


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


bearer_security = HTTPBearer(
    auto_error=False,
)


def _authenticate(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_security),
) -> None:
    expected = _configured_api_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app(job_submitter: JobSubmitter | None = None) -> FastAPI:
    app = FastAPI(title="Financial Rule Agent Platform API", version="1.0")
    app.state.job_submitter = job_submitter or UnavailableJobSubmitter()
    app.state.job_store = getattr(job_submitter, "store", None)

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
        submitter = app.state.job_submitter
        if isinstance(submitter, UnavailableJobSubmitter):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Durable job submission is unavailable",
            )
        store = getattr(submitter, "store", None)
        queue = getattr(submitter, "queue", None)
        if os.environ.get("JOB_RECOVERY_ENABLED", "false").lower() not in {
            "1",
            "true",
            "yes",
        }:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Pending-job recovery is not enabled",
            )
        if store is not None:
            try:
                store.ping()
                if queue is not None:
                    queue.ping()
            except Exception as error:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Durable job acceptance is unavailable",
                ) from error
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
        except JobIdConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        except JobDatabaseError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Durable job persistence is unavailable",
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

        return {
            "request_id": request.request_id,
            "batch_id": request.batch_id,
            "dataset_id": request.dataset_id,
            "status": "queued",
            "message": "Rule selection request accepted",
        }

    @app.get(
        "/api/v1/rule-selection-requests/{request_id}/status",
        dependencies=[Depends(_authenticate)],
    )
    def get_rule_selection_status(request_id: str) -> dict:
        store = app.state.job_store
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job status storage is unavailable",
            )
        try:
            return store.status_payload(request_id)
        except JobRecordNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rule selection request not found",
            ) from error
        except JobDatabaseError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job status storage is unavailable",
            ) from error

    return app


def create_durable_app() -> FastAPI:
    if os.environ.get("JOB_RECOVERY_ENABLED", "false").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return create_app()
    from src.jobs.submission import DurableJobSubmitter

    return create_app(DurableJobSubmitter())


app = create_durable_app()
