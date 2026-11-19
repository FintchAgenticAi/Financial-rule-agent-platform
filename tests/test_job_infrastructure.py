import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import create_app
from src.jobs.database import JobDatabaseError, JobIdConflict, JobStore
from src.jobs.queue import QueueUnavailable
from src.jobs.submission import DurableJobSubmitter


CALLBACK_URL = "https://dpm.example.com/api/v1/rule-selection-results"
PAYLOAD = {
    "request_id": "req-001",
    "batch_id": "batch-001",
    "dataset_id": "dataset-001",
    "r2_bucket": "financial-rule-platform-dev",
    "csv_object_key": "datasets/dataset-001/input.csv",
    "callback_url": CALLBACK_URL,
}


class FakeQueue:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued = []

    def ping(self) -> None:
        if self.fail:
            raise QueueUnavailable("Redis unavailable")

    def enqueue(self, request_id: str) -> bool:
        if self.fail:
            raise QueueUnavailable("Redis unavailable")
        self.enqueued.append(request_id)
        return True


class JobInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = JobStore(str(Path(self.directory.name) / "jobs.db"))
        self.environment = patch.dict(
            os.environ,
            {
                "RULE_MANAGER_API_TOKEN": "test-token",
                "RULE_MANAGER_APPROVED_CALLBACK_URL": CALLBACK_URL,
                "JOB_RECOVERY_ENABLED": "true",
                "JOB_DATABASE_PATH": str(Path(self.directory.name) / "jobs.db"),
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.store.close()
        self.directory.cleanup()

    def request_model(self):
        from src.api import RuleSelectionRequest

        return RuleSelectionRequest(**PAYLOAD)

    def test_durable_202_and_identical_duplicate(self) -> None:
        queue = FakeQueue()
        submitter = DurableJobSubmitter(self.store, queue)
        client = TestClient(create_app(submitter))

        first = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer test-token"},
        )
        second = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(queue.enqueued, ["req-001"])
        self.assertEqual(self.store.get("req-001")["status"], "queued")
        self.assertEqual(first.json()["status"], "queued")

    def test_conflicting_duplicate_returns_409(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())

        conflicting = {**PAYLOAD, "dataset_id": "other-dataset"}
        client = TestClient(create_app(submitter))
        response = client.post(
            "/api/v1/rule-selection-requests",
            json=conflicting,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 409)

    def test_redis_outage_is_pending_but_202_when_recovery_enabled(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue(fail=True))
        client = TestClient(create_app(submitter))

        response = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            self.store.get("req-001")["status"],
            "pending_enqueue",
        )

    def test_pending_recovery_enqueues_and_marks_queued(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())

        self.store.mark_pending_enqueue("req-001")
        queue = FakeQueue()
        from src.jobs.recovery import dispatch_pending_jobs_once

        count = dispatch_pending_jobs_once(self.store, queue)

        self.assertEqual(queue.enqueued, ["req-001"])
        self.assertEqual(self.store.get("req-001")["status"], "queued")
        self.assertEqual(count, 1)

    def test_status_endpoint_is_authenticated_and_safe(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())
        client = TestClient(create_app(submitter))

        unauthenticated = client.get(
            "/api/v1/rule-selection-requests/req-001/status"
        )
        authenticated = client.get(
            "/api/v1/rule-selection-requests/req-001/status",
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(authenticated.json()["status"], "queued")
        self.assertNotIn("callback_url", authenticated.json())

    def test_recovery_setting_wires_durable_submitter(self) -> None:
        with patch.dict(
            os.environ,
            {"JOB_RECOVERY_ENABLED": "true"},
            clear=False,
        ):
            from src.api import create_durable_app

            durable_app = create_durable_app()
            submitter = durable_app.state.job_submitter
            self.assertNotEqual(
                submitter.__class__.__name__,
                "UnavailableJobSubmitter",
            )

    def test_compose_passes_phase5_environment_and_host_ollama(self) -> None:
        compose_path = Path(__file__).resolve().parents[1] / "compose.yaml"
        compose = compose_path.read_text(encoding="utf-8")

        self.assertIn("env_file:", compose)
        self.assertIn("- .env", compose)
        self.assertIn("JOB_DATABASE_PATH: /app/job-state/jobs.db", compose)
        self.assertIn("REDIS_URL: redis://redis:6379/0", compose)
        self.assertIn("OLLAMA_BASE_URL: http://host.docker.internal:11434", compose)

    def test_execution_ownership_prevents_concurrency(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())
        self.store.mark_pending_enqueue("req-001")

        self.assertTrue(
            self.store.acquire_processing("req-001", "worker-a", 60)
        )
        self.assertFalse(
            self.store.acquire_processing("req-001", "worker-b", 60)
        )

    def test_missing_database_parent_directory_is_created(self) -> None:
        nested_path = Path(self.directory.name) / "new-state" / "jobs.db"
        store = JobStore(str(nested_path))
        try:
            store.ping()
            self.assertTrue(nested_path.parent.is_dir())
            self.assertTrue(nested_path.is_file())
        finally:
            store.close()

    def test_database_path_under_file_raises_database_error(self) -> None:
        blocking_file = Path(self.directory.name) / "not-a-directory"
        blocking_file.write_text("occupied", encoding="utf-8")

        with self.assertRaises(JobDatabaseError):
            JobStore(str(blocking_file / "jobs.db"))

    def test_worker_success_persists_three_output_keys(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())
        self.store.mark_pending_enqueue("req-001")

        async def fake_process(**kwargs):
            return {
                "transformation_json_key": "rule-results/dataset-001/req-001/transformation.json",
                "validation_json_key": "rule-results/dataset-001/req-001/validation.json",
                "deduplication_json_key": "rule-results/dataset-001/req-001/deduplication.json",
            }

        with patch(
            "src.jobs.rq_worker.process_r2_dataset",
            new=fake_process,
        ):
            from src.jobs.rq_worker import process_request

            result = process_request("req-001")

        self.assertEqual(result["status"], "completed")
        record = self.store.get("req-001")
        self.assertEqual(
            record["transformation_json_key"],
            "rule-results/dataset-001/req-001/transformation.json",
        )

    def test_worker_failure_is_sanitized_and_bounded(self) -> None:
        submitter = DurableJobSubmitter(self.store, FakeQueue())
        submitter.submit(self.request_model())
        self.store.mark_pending_enqueue("req-001")

        async def fake_process(**kwargs):
            raise RuntimeError("secret=DO-NOT-STORE")

        with patch.dict(os.environ, {"RQ_MAX_RETRIES": "1"}), patch(
            "src.jobs.rq_worker.process_r2_dataset",
            new=fake_process,
        ):
            from src.jobs.rq_worker import process_request

            with self.assertRaises(RuntimeError):
                process_request("req-001")

        record = self.store.get("req-001")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error_message"], "Processing failed with RuntimeError")
        self.assertNotIn("DO-NOT-STORE", record["error_message"])


if __name__ == "__main__":
    unittest.main()
