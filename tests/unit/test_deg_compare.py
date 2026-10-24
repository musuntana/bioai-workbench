"""DEG set comparison regression tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.deg_compare import compare_gene_sets
from app.main import app
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def _row(gene, padj, lfc):
    return {"gene_id": gene, "padj": padj, "log2FoldChange": lfc,
            "significant": padj is not None and padj <= 0.05 and abs(lfc) >= 1}


def test_overlap_excludes_genes_missing_in_one_run():
    data = {
        "a" * 32: [_row("both", 0.001, 2), _row("only_a", 0.02, 2),
                   _row("missing_from_b", 0.001, 3), _row("only_b", 0.8, 1)],
        "b" * 32: [_row("both", 0.001, 2), _row("only_a", 0.5, 2),
                   _row("only_b", 0.001, 3)],
    }
    result = compare_gene_sets("a" * 32, "b" * 32, lambda run_id, *_: ([], data[run_id]))
    assert result["counts"] == {
        "genes_in_a": 4, "genes_in_b": 3, "common_tested_genes": 3,
        "a_only_tested": 1, "b_only_tested": 0, "both_significant": 1,
        "only_a_significant": 1, "only_b_significant": 1,
    }
    assert {g["category"]: g["gene_id"] for g in result["genes"]} == {
        "both": "both", "only_a": "only_a", "only_b": "only_b",
    }


def test_duplicate_gene_rejected():
    with pytest.raises(HTTPException) as caught:
        compare_gene_sets("a" * 32, "b" * 32,
                          lambda *_: ([], [_row("dup", 0.01, 2), _row("dup", 0.01, 2)]))
    assert caught.value.status_code == 409


def test_endpoint_only_reads_verified_successful_results_and_exports():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        for run_id, genes in (
            ("a" * 32, "both,10,2,0.01,0.01\nonly_a,10,2,0.01,0.01\n"),
            ("b" * 32, "both,10,2,0.01,0.01\nonly_a,10,0.1,0.9,0.9\n"),
        ):
            store.create(run_id, "deseq2-basic")
            output = store.run_dir(run_id) / "outputs"
            (output / "differential_expression_all.csv").write_text(
                "gene_id,baseMean,log2FoldChange,pvalue,padj\n" + genes,
                encoding="utf-8",
            )
            for name, content in (
                ("differential_expression_significant.csv", "gene_id,baseMean,log2FoldChange,pvalue,padj\n"),
                ("run_manifest.tsv", "key\tvalue\n"),
                ("session_info.txt", "synthetic session info\n"),
            ):
                (output / name).write_text(content, encoding="utf-8")
            write_artifact_manifest(output, run_id=run_id, workflow_id="deseq2-basic")
            store.update(run_id, status="succeeded")
        from app.main import run_manager
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            params = {"run_a": "a" * 32, "run_b": "b" * 32}
            response = client.get("/api/v1/runs/compare/genes", params=params)
            assert response.status_code == 200
            assert response.json()["counts"]["only_a_significant"] == 1
            export = client.get("/api/v1/runs/compare/genes/export", params=params)
            assert export.status_code == 200
            assert "only_a,only_a" in export.text
            (store.run_dir("b" * 32) / "outputs" /
             "differential_expression_all.csv").write_text("tamper", encoding="utf-8")
            invalid = client.get("/api/v1/runs/compare/genes", params=params)
            assert invalid.status_code == 409
