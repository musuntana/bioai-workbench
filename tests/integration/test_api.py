from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from runtime.state import RunStore


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

    def test_run_history_supports_pagination_and_status_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_store = RunStore(Path(temp_dir))
            history_store.create("a" * 32, "deseq2-basic")
            history_store.update(
                "a" * 32, status="failed", finished_at="2026-10-23T00:00:00+00:00"
            )
            history_store.create("b" * 32, "deseq2-basic")
            history_store.update(
                "b" * 32, status="succeeded", finished_at="2026-10-23T00:01:00+00:00"
            )

            with patch("app.main.store", history_store):
                page = self.client.get("/api/v1/runs", params={"limit": 1, "offset": 0})
                next_page = self.client.get(
                    "/api/v1/runs", params={"limit": 1, "offset": 1}
                )
                succeeded = self.client.get(
                    "/api/v1/runs", params={"status": "succeeded"}
                )
                invalid_status = self.client.get(
                    "/api/v1/runs", params={"status": "private"}
                )

            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.json()["total"], 2)
            self.assertEqual(len(page.json()["runs"]), 1)
            self.assertEqual(next_page.status_code, 200)
            self.assertEqual(len(next_page.json()["runs"]), 1)
            self.assertNotEqual(
                page.json()["runs"][0]["run_id"], next_page.json()["runs"][0]["run_id"]
            )
            self.assertEqual(succeeded.status_code, 200)
            self.assertEqual(succeeded.json()["runs"][0]["status"], "succeeded")
            self.assertEqual(invalid_status.status_code, 422)

    def test_unknown_run_is_not_found(self) -> None:
        response = self.client.get("/api/v1/runs/" + "f" * 32)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
