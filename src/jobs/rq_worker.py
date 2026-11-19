import asyncio
import os
import uuid

from rq import Retry

from src.jobs.database import JobStore
from src.services.rule_processing_service import process_r2_dataset


def _safe_error(error: BaseException) -> str:
    return f"Processing failed with {type(error).__name__}"


def process_request(request_id: str) -> dict:
    store = JobStore()
    lease_seconds = int(os.environ.get("RQ_JOB_LEASE_SECONDS", "1800"))
    owner_id = str(uuid.uuid4())

    if not store.acquire_processing(request_id, owner_id, lease_seconds):
        store.close()
        return {
            "request_id": request_id,
            "status": "not_owned",
            "message": "Execution ownership belongs to another worker",
        }

    record = store.get(request_id)
    try:
        result = asyncio.run(
            process_r2_dataset(
                request_id=request_id,
                dataset_id=record["dataset_id"],
                r2_bucket=record["r2_bucket"],
                csv_object_key=record["csv_object_key"],
            )
        )
        store.mark_completed(request_id, owner_id, result)
        status = store.status_payload(request_id)
        store.close()
        return status
    except Exception as error:
        safe_message = _safe_error(error)
        record = store.get(request_id)
        max_retries = int(os.environ.get("RQ_MAX_RETRIES", "3"))
        if int(record["processing_attempts"]) >= max_retries:
            store.mark_failed(request_id, owner_id, safe_message)
            store.close()
            raise

        store.mark_pending_for_owner(request_id, owner_id)
        store.close()
        raise Retry(
            max=max_retries,
            interval=[30, 60, 120],
        ) from error
