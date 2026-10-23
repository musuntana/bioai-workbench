"""Gene focus regression tests for result previews and deterministic plot sampling."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import _include_focused_point, _sample_ma_points, app, run_manager
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def test_focus_sampling_is_bounded_unique_and_deterministic() -> None:
    candidates = [
        {"gene_id": f"gene_{index}", "baseMean": float(index), "log2FoldChange": 1.0}
        for index in range(101)
    ]
    sampled = _sample_ma_points(candidates, limit=10)
    focused = _include_focused_point(sampled, candidates, "gene_37", limit=10)
    assert len(focused) == 10
    assert len({point["gene_id"] for point in focused}) == 10
    assert "gene_37" in {point["gene_id"] for point in focused}
    assert focused == _include_focused_point(sampled, candidates, "gene_37", limit=10)
    assert _include_focused_point(sampled, candidates, "not_found", limit=10) == sampled
    assert _include_focused_point(sampled, candidates, "gene_37", limit=0) == sampled


def test_results_focus_returns_exact_gene_and_missing_plot_coordinates() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        run_id = "f" * 32
        store.create(run_id, "deseq2-basic")
        result_file = store.run_dir(run_id) / "outputs" / "differential_expression_all.csv"
        result_file.write_text(
            "gene_id,baseMean,log2FoldChange,pvalue,padj\n"
            "valid,20,2.4,0.01,0.02\n"
            "missing_padj,10,-1.2,,\n"
            "no_mean,,0.5,0.2,0.3\n",
            encoding="utf-8",
        )
        write_artifact_manifest(result_file.parent, run_id=run_id, workflow_id="deseq2-basic")
        store.update(run_id, status="succeeded")

        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            valid = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "valid", "q": "valid"},
            )
            no_padj = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "missing_padj"},
            )
            no_mean = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "no_mean"},
            )
            unknown = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "unknown"},
            )
            invalid = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "x" * 201},
            )
            result_file.write_text("tampered\n", encoding="utf-8")
            tampered = client.get(
                f"/api/v1/runs/{run_id}/results",
                params={"focus_gene": "valid"},
            )

    assert valid.status_code == 200
    assert valid.json()["focus"] == {
        "gene_id": "valid", "found": True,
        "volcano_plottable": True, "ma_plottable": True,
    }
    assert {p["gene_id"] for p in valid.json()["plot_points"]} == {"valid", "no_mean"}
    assert no_padj.json()["focus"]["volcano_plottable"] is False
    assert no_padj.json()["focus"]["ma_plottable"] is True
    assert no_mean.json()["focus"]["volcano_plottable"] is True
    assert no_mean.json()["focus"]["ma_plottable"] is False
    assert unknown.json()["focus"]["found"] is False
    assert invalid.status_code == 422
    assert tampered.status_code == 409


def test_gene_focus_controls_are_in_workbench() -> None:
    page = TestClient(app).get("/")
    assert page.status_code == 200
    for marker in ('id="locate-result-gene"', 'id="result-search"', "focus_gene:",
                   "selected-row", "is-selected"):
        assert marker in page.text
