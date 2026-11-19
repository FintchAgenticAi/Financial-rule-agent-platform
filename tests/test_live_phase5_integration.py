import os
import time
import unittest

from fastapi.testclient import TestClient


@unittest.skipUnless(
    os.environ.get("RUN_PHASE5_LIVE_INTEGRATION") == "true",
    "Opt-in live Phase 5 integration test",
)
class LivePhase5IntegrationTests(unittest.TestCase):
    def test_api_queue_worker_r2_langgraph_r2(self) -> None:
        from src.api import app

        client = TestClient(app)
        health = client.get("/health")
        ready = client.get("/ready")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(ready.status_code, 200)

        payload = {
            "request_id": os.environ["LIVE_REQUEST_ID"],
            "batch_id": os.environ["LIVE_BATCH_ID"],
            "dataset_id": os.environ["LIVE_DATASET_ID"],
            "r2_bucket": os.environ["R2_BUCKET"],
            "csv_object_key": os.environ["LIVE_CSV_OBJECT_KEY"],
            "callback_url": os.environ["RULE_MANAGER_APPROVED_CALLBACK_URL"],
        }
        token = os.environ["RULE_MANAGER_API_TOKEN"]
        response = client.post(
            "/api/v1/rule-selection-requests",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 202)

        timeout = time.time() + int(
            os.environ.get("LIVE_PHASE5_TIMEOUT_SECONDS", "1800")
        )
        while time.time() < timeout:
            status_response = client.get(
                f"/api/v1/rule-selection-requests/{payload['request_id']}/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(status_response.status_code, 200)
            state = status_response.json()["status"]
            if state in {"completed", "failed"}:
                self.assertEqual(state, "completed")
                return
            time.sleep(5)
        self.fail("Live Phase 5 integration timed out")
