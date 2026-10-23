from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from artifacts.manifest import write_artifact_manifest
from runtime.config import PROJECT_ROOT, RuntimeConfig
from runtime.manager import RunManager
from runtime.state import RunStore


class WorkbenchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def _create_result_run(
        self, root: Path, run_id: str, status: str = "succeeded"
    ) -> tuple[RunManager, Path]:
        manager = RunManager(
            config=RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
        )
        manager.store.create(run_id, "deseq2-basic")
        output_dir = manager.store.run_dir(run_id) / "outputs"
        result_file = output_dir / "differential_expression_all.csv"
        result_file.write_text(
            "gene_id,baseMean,log2FoldChange,lfcSE,stat,pvalue,padj\n"
            "gene_a,100,2.5,0.5,5,0.0001,0.001\n"
            "gene_b,50,-1.5,0.6,-2.5,0.01,0.04\n"
            "gene_c,20,0.2,0.2,1,0.3,0.4\n"
            "gene_d,30,-0.5,0.3,-1.6,0.1,0.2\n"
            "gene_e,10,1.2,0.8,1.5,0.12,0.3\n"
            "gene_f,5,-2.2,1.0,-2.2,,\n",
            encoding="utf-8",
        )
        manifest = write_artifact_manifest(
            output_dir, run_id=run_id, workflow_id="deseq2-basic"
        )
        manager.store.update(
            run_id,
            status=status,
            finished_at="2026-10-23T00:00:00+00:00" if status in {"succeeded", "failed"} else None,
            exit_code=0 if status == "succeeded" else (1 if status == "failed" else None),
            artifact_count=len(manifest["artifacts"]),
        )
        return manager, result_file

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
        absolute_error = absolute.json()["error"]
        self.assertEqual(absolute_error["code"], "VALIDATION_ERROR")
        self.assertEqual(absolute_error["message"], "Request validation failed.")
        self.assertIn("counts_file", {item["field"] for item in absolute_error["details"]})
        self.assertNotIn("/private/counts.csv", absolute.text)

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
        unknown_error = unknown.json()["error"]
        self.assertEqual(unknown_error["code"], "VALIDATION_ERROR")
        self.assertIn(
            "shell_command", {item["field"] for item in unknown_error["details"]}
        )

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
            self.assertEqual(
                invalid_status.json()["error"]["code"], "VALIDATION_ERROR"
            )
            self.assertIn(
                "status",
                {item["field"] for item in invalid_status.json()["error"]["details"]},
            )

    def test_home_page_exposes_run_history_controls(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Run history", response.text)
        self.assertIn('id="history-status"', response.text)
        self.assertIn('id="refresh-history"', response.text)

    def test_artifact_download_serves_only_manifested_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = RunManager(
                config=RuntimeConfig(
                    project_root=PROJECT_ROOT,
                    input_root=root / "inputs",
                    runs_root=root / "runs",
                )
            )
            run_id = "e" * 32
            manager.store.create(run_id, "deseq2-basic")
            output_dir = manager.store.run_dir(run_id) / "outputs"
            artifact = output_dir / "differential_expression_all.csv"
            artifact.write_text("gene_id,log2FoldChange\nsynthetic_gene,1.2\n", encoding="utf-8")
            manifest = write_artifact_manifest(
                output_dir, run_id=run_id, workflow_id="deseq2-basic"
            )
            expected_hash = manifest["artifacts"][0]["sha256"]

            with patch("app.main.run_manager", manager):
                response = self.client.get(
                    f"/api/v1/runs/{run_id}/artifacts/differential_expression_all.csv"
                )
                unknown = self.client.get(f"/api/v1/runs/{run_id}/artifacts/run.json")
                traversal = self.client.get(
                    f"/api/v1/runs/{run_id}/artifacts/%2E%2E%2Frun.json"
                )
                artifact.write_text("tampered\\n", encoding="utf-8")
                tampered = self.client.get(
                    f"/api/v1/runs/{run_id}/artifacts/differential_expression_all.csv"
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("synthetic_gene,1.2", response.text)
            self.assertEqual(response.headers["x-artifact-sha256"], expected_hash)
            self.assertEqual(unknown.status_code, 404)
            self.assertEqual(traversal.status_code, 404)
            self.assertEqual(tampered.status_code, 409)


    def test_input_upload_list_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            valid_csv = b"gene_id,sample_a,sample_b\ngene_1,4,7\ngene_2,8,9\n"

            with patch("app.main.config", config):
                uploaded = self.client.put(
                    "/api/v1/inputs/counts.csv",
                    content=valid_csv,
                    headers={"content-type": "text/csv"},
                )
                listing = self.client.get("/api/v1/inputs")
                duplicate = self.client.put(
                    "/api/v1/inputs/counts.csv",
                    content=b"gene_id,sample_a\ngene_1,99\n",
                    headers={"content-type": "text/csv"},
                )

            self.assertEqual(uploaded.status_code, 201)
            self.assertEqual(uploaded.json()["path"], "counts.csv")
            self.assertEqual(uploaded.json()["size_bytes"], len(valid_csv))
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["files"], [{"path": "counts.csv", "size_bytes": len(valid_csv)}])
            self.assertNotIn(str(root), listing.text)
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual((root / "inputs" / "counts.csv").read_bytes(), valid_csv)

    def test_input_upload_rejects_bad_names_and_malformed_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            with patch("app.main.config", config):
                bad_name = self.client.put(
                    "/api/v1/inputs/bad%20name.csv",
                    content=b"a,b\n1,2\n",
                    headers={"content-type": "text/csv"},
                )
                malformed = self.client.put(
                    "/api/v1/inputs/malformed.csv",
                    content=b"a,b\n1,2,3\n",
                    headers={"content-type": "text/csv"},
                )
                empty = self.client.put(
                    "/api/v1/inputs/empty.csv",
                    content=b"",
                    headers={"content-type": "text/csv"},
                )

            self.assertEqual(bad_name.status_code, 400)
            self.assertEqual(malformed.status_code, 400)
            self.assertEqual(empty.status_code, 400)
            self.assertFalse((root / "inputs" / "malformed.csv").exists())
            self.assertFalse((root / "inputs" / "empty.csv").exists())

    def test_input_upload_enforces_size_limit_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            with (
                patch("app.main.config", config),
                patch("app.main.MAX_INPUT_FILE_BYTES", 8),
            ):
                response = self.client.put(
                    "/api/v1/inputs/large.csv",
                    content=b"column1,column2\n1,2\n",
                    headers={"content-type": "text/csv"},
                )

            self.assertEqual(response.status_code, 413)
            self.assertFalse((root / "inputs" / "large.csv").exists())
            self.assertEqual(list((root / "inputs").glob(".bioai-upload-*")), [])


    def test_results_endpoint_filters_paginates_and_returns_volcano_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "d" * 32
            manager, _ = self._create_result_run(root, run_id)
            with patch("app.main.run_manager", manager):
                page = self.client.get(
                    f"/api/v1/runs/{run_id}/results",
                    params={"limit": 2, "offset": 0},
                )
                significant = self.client.get(
                    f"/api/v1/runs/{run_id}/results",
                    params={
                        "significant_only": "true",
                        "padj_max": 0.05,
                        "min_abs_log2fc": 1,
                        "limit": 100,
                    },
                )
                sorted_rows = self.client.get(
                    f"/api/v1/runs/{run_id}/results",
                    params={"sort_by": "log2FoldChange", "sort_order": "desc", "limit": 2},
                )

            self.assertEqual(page.status_code, 200)
            payload = page.json()
            self.assertEqual(payload["filtered_genes"], 6)
            self.assertEqual([row["gene_id"] for row in payload["rows"]], ["gene_a", "gene_b"])
            self.assertEqual(payload["summary"]["total_genes"], 6)
            self.assertEqual(payload["summary"]["significant_genes"], 2)
            self.assertEqual(payload["summary"]["missing_padj_genes"], 1)
            self.assertEqual(payload["summary"]["plot_eligible_genes"], 5)
            self.assertEqual(len(payload["plot_points"]), 5)
            self.assertFalse(payload["summary"]["plot_points_truncated"])
            self.assertEqual(
                {point["gene_id"] for point in payload["plot_points"] if point["significant"]},
                {"gene_a", "gene_b"},
            )

            self.assertEqual(significant.status_code, 200)
            self.assertEqual(significant.json()["filtered_genes"], 2)
            self.assertEqual(
                [row["gene_id"] for row in significant.json()["rows"]],
                ["gene_a", "gene_b"],
            )
            self.assertEqual(sorted_rows.status_code, 200)
            self.assertEqual(
                [row["gene_id"] for row in sorted_rows.json()["rows"]],
                ["gene_a", "gene_e"],
            )

    def test_results_endpoint_requires_success_and_verified_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_id = "c" * 32
            manager, result_file = self._create_result_run(root, run_id, status="running")
            with patch("app.main.run_manager", manager):
                running = self.client.get(f"/api/v1/runs/{run_id}/results")
                manager.store.update(run_id, status="succeeded")
                result_file.write_text(result_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                tampered = self.client.get(f"/api/v1/runs/{run_id}/results")

            self.assertEqual(running.status_code, 409)
            self.assertEqual(tampered.status_code, 409)
            self.assertIn("checksum", tampered.json()["detail"].lower())

    def test_results_endpoint_rejects_invalid_filters(self) -> None:
        response = self.client.get(
            "/api/v1/runs/" + "a" * 32 + "/results",
            params={"sort_by": "arbitrary-column", "padj_max": 2},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")


    def test_input_preview_returns_bounded_rows_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            nested = config.input_root / "demo"
            nested.mkdir()
            (nested / "counts.csv").write_text(
                "gene_id,s1,s2\ngene_a,1,2\ngene_b,3,4\ngene_c,5,6\n",
                encoding="utf-8",
            )
            (config.input_root / "malformed.csv").write_text(
                "gene_id,s1,s2\ngene_a,1\n",
                encoding="utf-8",
            )
            with patch("app.main.config", config):
                response = self.client.get(
                    "/api/v1/inputs/preview",
                    params={"filename": "demo/counts.csv", "limit": 2},
                )
                traversal = self.client.get(
                    "/api/v1/inputs/preview",
                    params={"filename": "../secret.csv"},
                )
                dot_segment = self.client.get(
                    "/api/v1/inputs/preview",
                    params={"filename": "demo/../malformed.csv"},
                )
                nul_path = self.client.get(
                    "/api/v1/inputs/preview",
                    params={"filename": "bad\x00.csv"},
                )
                malformed = self.client.get(
                    "/api/v1/inputs/preview",
                    params={"filename": "malformed.csv"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["path"], "demo/counts.csv")
            self.assertEqual(payload["columns"], ["gene_id", "s1", "s2"])
            self.assertEqual(payload["rows"], [["gene_a", "1", "2"], ["gene_b", "3", "4"]])
            self.assertTrue(payload["has_more"])
            self.assertNotIn(str(root), response.text)
            self.assertEqual(traversal.status_code, 404)
            self.assertEqual(dot_segment.status_code, 404)
            self.assertEqual(nul_path.status_code, 404)
            self.assertEqual(malformed.status_code, 422)

    def test_home_page_exposes_input_upload_controls(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="input-upload-file"', response.text)
        self.assertIn('id="counts-file"', response.text)
        self.assertIn('id="metadata-file"', response.text)
        self.assertIn('id="preview-inputs"', response.text)
        self.assertIn('id="input-preview-content"', response.text)
        self.assertIn('/api/v1/inputs/preview?', response.text)
        self.assertIn('id="validate-inputs"', response.text)
        self.assertIn('/api/v1/inputs/validate', response.text)
        self.assertIn('id="results-panel"', response.text)
        self.assertIn('id="volcano-plot"', response.text)
        self.assertIn('/results?', response.text)


    def test_preflight_validation_accepts_matching_deseq2_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            (config.input_root / "counts.csv").write_text(
                "gene_id,s1,s2,s3,s4\ngene_1,1,2,3,4\ngene_2,5,6,7,8\n",
                encoding="utf-8",
            )
            (config.input_root / "metadata.csv").write_text(
                "sample_id,condition\ns1,control\ns2,control\ns3,treatment\ns4,treatment\n",
                encoding="utf-8",
            )
            payload = {
                "counts_file": "counts.csv",
                "metadata_file": "metadata.csv",
                "condition": "condition",
                "reference": "control",
                "contrast": "treatment",
                "alpha": 0.05,
            }
            with patch("app.main.config", config):
                response = self.client.post("/api/v1/inputs/validate", json=payload)

            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertTrue(result["valid"])
            self.assertEqual(result["summary"]["gene_count"], 2)
            self.assertEqual(result["summary"]["sample_count"], 4)
            self.assertEqual(result["summary"]["condition_counts"], {"control": 2, "treatment": 2})

    def test_preflight_validation_rejects_sample_mismatch_and_invalid_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            (config.input_root / "counts.csv").write_text(
                "gene_id,s1,s2,s3,s4\ngene_1,1,-2,3,4\ngene_2,5,6,7,8\n",
                encoding="utf-8",
            )
            (config.input_root / "metadata.csv").write_text(
                "sample_id,condition\ns1,control\ns2,control\ns3,treatment\nsX,treatment\n",
                encoding="utf-8",
            )
            payload = {
                "counts_file": "counts.csv",
                "metadata_file": "metadata.csv",
                "condition": "condition",
                "reference": "control",
                "contrast": "treatment",
                "alpha": 0.05,
            }
            with patch("app.main.config", config):
                response = self.client.post("/api/v1/inputs/validate", json=payload)

            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertFalse(result["valid"])
            self.assertIn("counts_file", {error["field"] for error in result["errors"]})
            self.assertIn("metadata_file", {error["field"] for error in result["errors"]})

    def test_preflight_validation_rejects_missing_files_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = RuntimeConfig(
                project_root=PROJECT_ROOT,
                input_root=root / "inputs",
                runs_root=root / "runs",
            )
            config.prepare()
            payload = {
                "counts_file": "missing-counts.csv",
                "metadata_file": "missing-metadata.csv",
                "condition": "condition",
                "reference": "control",
                "contrast": "treatment",
                "alpha": 0.05,
            }
            with patch("app.main.config", config):
                response = self.client.post("/api/v1/inputs/validate", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["valid"])
            self.assertNotIn(str(root), response.text)

    def test_unknown_run_is_not_found(self) -> None:
        response = self.client.get("/api/v1/runs/" + "f" * 32)
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
