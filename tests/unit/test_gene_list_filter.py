"""Regression tests for exact batch gene filtering in verified DESeq2 results."""

import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.gene_lists import parse_gene_ids
from app.main import app, run_manager
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def _completed_run(store: RunStore, run_id: str) -> Path:
    store.create(run_id, "deseq2-basic")
    output = store.run_dir(run_id) / "outputs"
    source = output / "differential_expression_all.csv"
    source.write_text(
        "gene_id,baseMean,log2FoldChange,pvalue,padj\n"
        "GeneA,1.2500,2,0.01,0.02\n"
        "geneA,2,-2,0.001,0.005\n"
        "GeneB,3,-3,0.03,0.04\n"
        "GeneC,4,0.3,0.5,0.5\n",
        encoding="utf-8",
    )
    for name, text in (
        ("differential_expression_significant.csv", "gene_id,baseMean,log2FoldChange,pvalue,padj\n"),
        ("run_manifest.tsv", "key\tvalue\n"),
        ("session_info.txt", "synthetic session info\n"),
    ):
        (output / name).write_text(text, encoding="utf-8")
    write_artifact_manifest(output, run_id=run_id, workflow_id="deseq2-basic")
    store.update(run_id, status="succeeded")
    return source


def test_gene_id_parser_is_ordered_deduplicated_and_case_sensitive():
    assert parse_gene_ids("GeneA, GeneB\ngeneA;GeneA\tMissing") == (
        "GeneA", "GeneB", "geneA", "Missing"
    )
    assert parse_gene_ids(" \n \t ") == ()


@pytest.mark.parametrize("value", [
    " ".join(f"g{i}" for i in range(101)),
    "X" * 201,
])
def test_gene_id_parser_rejects_unbounded_lists_and_ids(value):
    with pytest.raises(ValueError):
        parse_gene_ids(value)


def test_batch_filter_preview_export_and_pagination_have_identical_gene_membership():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        run_id = "f" * 32
        _completed_run(store, run_id)
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            params = {
                "gene_ids": "GeneA, GeneB\nMissing GeneA",
                "sort_by": "gene_id",
                "sort_order": "asc",
            }
            first = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={**params, "limit": 1, "offset": 0},
            )
            second = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={**params, "limit": 1, "offset": 1},
            )
            assert first.status_code == 200
            assert second.status_code == 200
            data = first.json()
            assert data["filtered_genes"] == 2
            assert data["gene_filter"] == {
                "requested": 3, "found": 2, "missing": ["Missing"],
            }
            selected_ids = [
                data["rows"][0]["gene_id"],
                second.json()["rows"][0]["gene_id"],
            ]
            assert selected_ids == ["GeneA", "GeneB"]

            exported = client.get(f"/api/v1/runs/{run_id}/results/export", params=params)
            assert exported.status_code == 200
            csv_rows = list(csv.DictReader(io.StringIO(exported.text)))
            assert [row["gene_id"] for row in csv_rows] == selected_ids
            assert csv_rows[0]["baseMean"] == "1.2500"
            assert "GeneC" not in exported.text

            unfiltered = client.get(f"/api/v1/runs/{run_id}/results")
            assert unfiltered.status_code == 200
            assert unfiltered.json()["filtered_genes"] == 4
            assert unfiltered.json()["gene_filter"]["requested"] == 0


def test_gene_id_filter_invalid_input_or_tampered_csv_never_exports():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        run_id = "a" * 32
        artifact = _completed_run(store, run_id)
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            url = f"/api/v1/runs/{run_id}/results/export"
            assert client.get(url, params={
                "gene_ids": " ".join(f"g{i}" for i in range(101)),
            }).status_code == 422
            artifact.write_text("tampered", encoding="utf-8")
            assert client.get(url, params={"gene_ids": "GeneA"}).status_code == 409
