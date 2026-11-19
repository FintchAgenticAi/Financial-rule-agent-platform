import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import create_app


CALLBACK_URL = "https://dpm.example.com/api/v1/rule-selection-results"
PAYLOAD = {
    "request_id": "request-001",
    "batch_id": "batch-001",
    "dataset_id": "dataset-001",
    "r2_bucket": "financial-rule-platform-dev",
    "csv_object_key": "datasets/ds-001/input.csv",
    "callback_url": CALLBACK_URL,
}


class AcceptingSubmitter:
    def __init__(self) -> None:
        self.requests = []

    def submit(self, request) -> None:
        self.requests.append(request)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "RULE_MANAGER_API_TOKEN": "test-token",
                "RULE_MANAGER_APPROVED_CALLBACK_URL": CALLBACK_URL,
            },
            clear=False,
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def test_openapi_exposes_http_bearer_security(self) -> None:
        client = TestClient(create_app(AcceptingSubmitter()))
        openapi = client.get("/openapi.json").json()

        scheme = openapi["components"]["securitySchemes"]["HTTPBearer"]
        self.assertEqual(scheme["type"], "http")
        self.assertEqual(scheme["scheme"], "bearer")

        post_operation = openapi["paths"][
            "/api/v1/rule-selection-requests"
        ]["post"]
        status_operation = openapi["paths"][
            "/api/v1/rule-selection-requests/{request_id}/status"
        ]["get"]
        self.assertIn({"HTTPBearer": []}, post_operation["security"])
        self.assertIn({"HTTPBearer": []}, status_operation["security"])

        health_operation = openapi["paths"]["/health"]["get"]
        ready_operation = openapi["paths"]["/ready"]["get"]
        self.assertNotIn("security", health_operation)
        self.assertNotIn("security", ready_operation)

    def test_invalid_bearer_token_returns_401(self) -> None:
        client = TestClient(create_app(AcceptingSubmitter()))

        response = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer wrong-token"},
        )

        self.assertEqual(response.status_code, 401)

    def test_health_and_ready(self) -> None:
        client = TestClient(create_app())

        self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(client.get("/ready").status_code, 503)

    def test_default_submitter_returns_service_unavailable(self) -> None:
        client = TestClient(create_app())

        response = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 503)

    def test_injected_submitter_returns_accepted(self) -> None:
        submitter = AcceptingSubmitter()
        client = TestClient(create_app(submitter))

        response = client.post(
            "/api/v1/rule-selection-requests",
            json=PAYLOAD,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["request_id"], "request-001")
        self.assertEqual(len(submitter.requests), 1)

    def test_authentication_and_callback_are_enforced(self) -> None:
        client = TestClient(create_app(AcceptingSubmitter()))

        missing_auth = client.post(
            "/api/v1/rule-selection-requests", json=PAYLOAD
        )
        self.assertEqual(missing_auth.status_code, 401)

        invalid_callback = {**PAYLOAD, "callback_url": "https://evil.example"}
        response = client.post(
            "/api/v1/rule-selection-requests",
            json=invalid_callback,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_r2_fields_are_rejected(self) -> None:
        client = TestClient(create_app(AcceptingSubmitter()))
        invalid_payload = {**PAYLOAD, "r2_bucket": "bad bucket"}

        response = client.post(
            "/api/v1/rule-selection-requests",
            json=invalid_payload,
            headers={"Authorization": "Bearer test-token"},
        )

        self.assertEqual(response.status_code, 422)

    def test_dpm_results_route_is_not_owned_by_this_api(self) -> None:
        client = TestClient(create_app())

        self.assertEqual(
            client.post("/api/v1/rule-selection-results").status_code,
            404,
        )

    def test_ready_requires_api_token(self) -> None:
        with patch.dict(os.environ, {"RULE_MANAGER_API_TOKEN": ""}, clear=False):
            client = TestClient(create_app(AcceptingSubmitter()))
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "API is not configured")

    def test_ready_requires_approved_callback(self) -> None:
        with patch.dict(
            os.environ,
            {"RULE_MANAGER_APPROVED_CALLBACK_URL": ""},
            clear=False,
        ):
            client = TestClient(create_app(AcceptingSubmitter()))
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "API is not configured")

    def test_ready_rejects_unavailable_database_or_queue(self) -> None:
        class UnavailableStore:
            def ping(self) -> None:
                raise RuntimeError("database unavailable")

        class UnavailableQueue:
            def ping(self) -> None:
                raise RuntimeError("queue unavailable")

        class UnavailableInfrastructureSubmitter:
            store = UnavailableStore()
            queue = UnavailableQueue()

            def submit(self, request) -> None:
                raise RuntimeError("unavailable")

        with patch.dict(
            os.environ,
            {"JOB_RECOVERY_ENABLED": "true"},
            clear=False,
        ):
            client = TestClient(create_app(UnavailableInfrastructureSubmitter()))
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"],
            "Durable job acceptance is unavailable",
        )


if __name__ == "__main__":
    unittest.main()
