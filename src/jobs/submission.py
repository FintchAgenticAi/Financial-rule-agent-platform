import os
from typing import Any

from src.jobs.database import JobDatabaseError, JobStore
from src.jobs.queue import QueueUnavailable, RedisQueue


class DurableAcceptanceUnavailable(RuntimeError):
    pass


class DurableJobSubmitter:
    def __init__(self, store: JobStore | None = None, queue: RedisQueue | None = None) -> None:
        self.store = store or JobStore()
        self.queue = queue or RedisQueue()

    def submit(self, request: Any) -> dict[str, Any]:
        try:
            self.store.ping()
        except (JobDatabaseError, QueueUnavailable) as error:
            raise DurableAcceptanceUnavailable(str(error)) from error

        if os.environ.get("JOB_RECOVERY_ENABLED", "false").lower() not in {
            "1",
            "true",
            "yes",
        }:
            raise DurableAcceptanceUnavailable(
                "Reliable pending-job recovery is not configured."
            )

        payload = {
            "request_id": request.request_id,
            "batch_id": request.batch_id,
            "dataset_id": request.dataset_id,
            "r2_bucket": request.r2_bucket,
            "csv_object_key": request.csv_object_key,
            "callback_url": str(request.callback_url),
        }
        record, created = self.store.submit(payload)

        if record["status"] in {"completed", "failed", "processing", "queued"}:
            return record

        try:
            self.queue.ping()
            self.queue.enqueue(request.request_id)
            self.store.mark_queued(request.request_id)
        except (QueueUnavailable, JobDatabaseError):
            self.store.mark_pending_enqueue(request.request_id)

        return self.store.get(request.request_id)
