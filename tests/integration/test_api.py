from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class WorkbenchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_workflow_registry_is_exposed_without_local_paths(self) -> None:
        response = self.client.get("/api/v1/workflows")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["workflows"]], ["deseq2-basic"])
        self.assertNotIn("entrypoint", payload["workflows"][0])

    def test_run_request_rejects_absolute_paths_and_unknown_fields(self) -> None:
        absolute = self.client.post(
            "/api/v1/runs",
            json={
                "workflow_id": "deseq2-basic",
                "counts_file": "/private/counts.csv",
                "metadata_file": "metadata.csv",
            },
        )
        self.assertEqual(absolute.status_code, 422)

        unknown = self.client.post(
            "/api/v1/runs",
            json={
                "workflow_id": "deseq2-basic",
                "counts_file": "counts.csv",
                "metadata_file": "metadata.csv",
                "shell_command": "echo unsafe",
            },
        )
        self.assertEqual(unknown.status_code, 422)

    def test_unknown_run_is_not_found(self) -> None:
        response = self.client.get("/api/v1/runs/" + "f" * 32)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
