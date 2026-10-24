"""Portable report contracts: real artifact hash checks, HTML safety, and no mutation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, run_manager
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def _setup_run(root: Path, run_id: str, *, status: str = "succeeded"):
    store = RunStore(root)
    store.create(
        run_id, "deseq2-basic",
        parameters={
            "condition": "condition", "reference": "control",
            "contrast": "<script>alert(1)</script>", "alpha": 0.05,
        },
    )
    outputs = store.run_dir(run_id) / "outputs"
    result = outputs / "differential_expression_all.csv"
    result.write_text(
        "gene_id,baseMean,log2FoldChange,pvalue,padj\n"
        'gene_a,100,2.5,0.0001,0.001\n'
        '"<img src=x onerror=alert(2)>",10,-1.2,0.01,0.02\n'
        'gene_c,5,0.1,0.5,\n',
        encoding="utf-8",
    )
    for name, content in (
        ("differential_expression_significant.csv", "gene_id,baseMean,log2FoldChange,pvalue,padj\n"),
        ("run_manifest.tsv", "key\tvalue\n"),
        ("session_info.txt", "synthetic session info\n"),
    ):
        (outputs / name).write_text(content, encoding="utf-8")
    write_artifact_manifest(outputs, run_id=run_id, workflow_id="deseq2-basic")
    store.update(
        run_id, status=status, finished_at="2026-10-23T00:00:00+00:00",
        input_provenance={"counts": {
            "filename": "inputs/<counts>.csv", "size_bytes": 10, "sha256": "a" * 64,
        }},
        environment_provenance={
            "r_version": "R version 4.4.2", "deseq2_version": "1.46.0",
            "workflow_sha256": "b" * 64,
        },
    )
    return store, result


def test_download_report_contains_summary_charts_provenance_and_no_active_markup():
    with tempfile.TemporaryDirectory() as directory:
        run_id = "a" * 32
        store, source = _setup_run(Path(directory), run_id)
        before = sorted(str(path.relative_to(store.run_dir(run_id)))
                        for path in store.run_dir(run_id).rglob("*"))
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            response = client.get(f"/api/v1/runs/{run_id}/report")
            tuned = client.get(f"/api/v1/runs/{run_id}/report",
                               params={"min_abs_log2fc": 3})
        after = sorted(str(path.relative_to(store.run_dir(run_id)))
                       for path in store.run_dir(run_id).rglob("*"))

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    assert "nosniff" == response.headers["x-content-type-options"]
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "text/html" in response.headers["content-type"]
    assert "<svg" in response.text
    assert "<circle" in response.text
    assert "Total genes: <strong>3</strong>" in response.text
    assert "Significant: <strong>2</strong>" in response.text
    assert "deseq2_version" in response.text
    assert "1.46.0" in response.text
    assert "a" * 64 in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in response.text
    assert "<script>" not in response.text
    assert '<img src=x onerror=alert(2)>' not in response.text
    assert "inputs/<counts>.csv" not in response.text
    assert before == after
    assert source.is_file() is False  # TemporaryDirectory was cleaned up
    assert tuned.status_code == 200
    assert "Significant: <strong>0</strong>" in tuned.text


def test_report_rejects_unfinished_tampered_or_invalid_results():
    with tempfile.TemporaryDirectory() as directory:
        run_id = "b" * 32
        store, source = _setup_run(Path(directory), run_id, status="running")
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            unfinished = client.get(f"/api/v1/runs/{run_id}/report")
            store.update(run_id, status="succeeded")
            source.write_text("tampered", encoding="utf-8")
            tampered = client.get(f"/api/v1/runs/{run_id}/report")
            invalid_threshold = client.get(f"/api/v1/runs/{run_id}/report",
                                           params={"padj_max": 2})
            invalid_run_id = client.get("/api/v1/runs/bad-id/report")

    assert unfinished.status_code == 409
    assert tampered.status_code == 409
    assert invalid_threshold.status_code == 422
    assert invalid_run_id.status_code == 404


def test_report_supports_historical_runs_without_provenance():
    with tempfile.TemporaryDirectory() as directory:
        run_id = "c" * 32
        store, _ = _setup_run(Path(directory), run_id)
        store.update(run_id, input_provenance={}, environment_provenance={})
        with patch.object(run_manager, "store", store):
            response = TestClient(app).get(f"/api/v1/runs/{run_id}/report")
        assert response.status_code == 200
        assert "Not recorded" in response.text


def test_report_download_link_is_available_in_results_ui():
    home = TestClient(app).get("/")
    assert home.status_code == 200
    assert 'id="results-report-link"' in home.text
    assert '"/report?"' in home.text
