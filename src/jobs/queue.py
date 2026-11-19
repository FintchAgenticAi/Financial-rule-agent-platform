import os
from typing import Any

import redis
from rq import Queue, Retry
from rq.job import Job


class QueueUnavailable(RuntimeError):
    pass


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def queue_name() -> str:
    return os.environ.get("RQ_QUEUE_NAME", "rule-selection")


class RedisQueue:
    def __init__(self) -> None:
        self.redis = redis.Redis.from_url(redis_url(), decode_responses=False)
        self.queue = Queue(queue_name(), connection=self.redis)

    def ping(self) -> None:
        try:
            self.redis.ping()
        except redis.RedisError as error:
            raise QueueUnavailable("Redis is unavailable.") from error

    def enqueue(self, request_id: str) -> bool:
        try:
            existing = Job.fetch(request_id, connection=self.redis)
            if existing.get_status(refresh=True) in {
                "queued",
                "started",
                "deferred",
                "scheduled",
                "running",
            }:
                return False
            existing.delete()
        except Exception:
            pass

        timeout = int(os.environ.get("RQ_JOB_TIMEOUT_SECONDS", "1800"))
        max_retries = int(os.environ.get("RQ_MAX_RETRIES", "3"))
        try:
            self.queue.enqueue(
                "src.jobs.rq_worker.process_request",
                request_id,
                job_id=request_id,
                job_timeout=timeout,
                retry=Retry(max=max_retries, interval=[30, 60, 120]),
            )
            return True
        except Exception as error:
            raise QueueUnavailable("Could not enqueue the durable job.") from error
