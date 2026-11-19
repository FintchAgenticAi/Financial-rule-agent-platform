import os
import time

from src.jobs.database import JobStore
from src.jobs.queue import QueueUnavailable, RedisQueue


def dispatch_pending_jobs_once(
    store: JobStore | None = None,
    queue: RedisQueue | None = None,
) -> int:
    store = store or JobStore()
    queue = queue or RedisQueue()
    recovered = store.recover_expired_processing()

    queue.ping()
    dispatched = 0
    for request_id in store.pending_enqueue_ids():
        try:
            if queue.enqueue(request_id):
                store.mark_queued(request_id)
                dispatched += 1
        except QueueUnavailable:
            continue
    return dispatched + recovered


def run_recovery_loop() -> None:
    interval = int(os.environ.get("JOB_RECOVERY_INTERVAL_SECONDS", "15"))
    store = JobStore()
    queue = RedisQueue()
    while True:
        try:
            dispatch_pending_jobs_once(store, queue)
        except Exception:
            pass
        time.sleep(interval)


if __name__ == "__main__":
    run_recovery_loop()
