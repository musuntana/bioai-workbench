"""Gene detail API tests; source rows require successful SHA-256 verification."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, run_manager
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def _run(store, run_id, csv):
    store.create(run_id, "deseq2-basic")
    output = store.run_dir(run_id) / "outputs"
    file = output / "differential_expression_all.csv"
    file.write_text("gene_id,baseMean,log2FoldChange,pvalue,padj\n" + csv, encoding="utf-8")
    for name, content in (
        ("differential_expression_significant.csv", "gene_id,baseMean,log2FoldChange,pvalue,padj\n"),
        ("run_manifest.tsv", "key\tvalue\n"),
        ("session_info.txt", "synthetic session info\n"),
    ):
        (output / name).write_text(content, encoding="utf-8")
    write_artifact_manifest(output, run_id=run_id, workflow_id="deseq2-basic")
    store.update(run_id, status="succeeded")
    return file


def test_gene_detail_and_two_run_comparison_enforce_artifact_hashes():
    with tempfile.TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "a" * 32, "b" * 32
        _run(store, a, "gene_x,10,2.5,0.001,0.01\n")
        other = _run(store, b, "gene_x,15,0.3,0.5,0.6\n")
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            detail = client.get(f"/api/v1/runs/{a}/genes/gene_x")
            assert detail.status_code == 200
            assert detail.json()["gene"]["significant"] is True
            assert detail.json()["gene"]["log2FoldChange"] == 2.5
            assert client.get(f"/api/v1/runs/{a}/genes/missing").status_code == 404
            compared = client.get("/api/v1/runs/compare/gene", params={
                "run_a": a, "run_b": b, "gene_id": "gene_x",
            })
            assert compared.status_code == 200
            assert compared.json()["a"]["significant"] is True
            assert compared.json()["b"]["significant"] is False
            other.write_text("tampered", encoding="utf-8")
            assert client.get("/api/v1/runs/compare/gene", params={
                "run_a": a, "run_b": b, "gene_id": "gene_x",
            }).status_code == 409


def test_duplicate_genes_refused():
    with tempfile.TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        run_id = "c" * 32
        _run(store, run_id, "gene_x,1,2,0.01,0.01\ngene_x,2,3,0.01,0.01\n")
        with patch.object(run_manager, "store", store):
            assert TestClient(app).get(f"/api/v1/runs/{run_id}/genes/gene_x").status_code == 409
