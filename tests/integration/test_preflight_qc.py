"""Contract tests for inexpensive pre-DESeq2 count-depth quality indicators."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from runtime.config import PROJECT_ROOT, RuntimeConfig


def _preflight(tmp_path: Path, counts: str) -> dict:
    config = RuntimeConfig(
        project_root=PROJECT_ROOT,
        input_root=tmp_path / "inputs",
        runs_root=tmp_path / "runs",
    )
    config.prepare()
    (config.input_root / "counts.csv").write_text(counts, encoding="utf-8")
    (config.input_root / "metadata.csv").write_text(
        "sample_id,condition\ns1,control\ns2,control\ns3,treated\ns4,treated\n",
        encoding="utf-8",
    )
    with patch("app.main.config", config):
        response = TestClient(app).post(
            "/api/v1/inputs/validate",
            json={
                "counts_file": "counts.csv",
                "metadata_file": "metadata.csv",
                "condition": "condition",
                "reference": "control",
                "contrast": "treated",
                "alpha": 0.05,
            },
        )
    assert response.status_code == 200
    assert str(tmp_path) not in response.text
    return response.json()


def test_qc_summarizes_library_sizes_and_all_zero_genes_without_blocking(tmp_path: Path):
    data = _preflight(
        tmp_path,
        "gene_id,s1,s2,s3,s4\ngA,5,0,10,1\ngB,0,0,0,0\ngC,5,2,0,5\n",
    )
    assert data["valid"] is True
    assert data["errors"] == []
    assert data["summary"]["gene_count"] == 3
    assert data["summary"]["library_sizes"] == {"s1": 10, "s2": 2, "s3": 10, "s4": 6}
    assert data["summary"]["all_zero_genes"] == 1
    assert data["summary"]["zero_library_samples"] == []
    assert data["summary"]["library_size_ratio"] == 5.0
    assert len(data["warnings"]) == 1
    assert "5x" in data["warnings"][0]["message"]


def test_zero_count_sample_is_invalid_but_describes_which_column_to_fix(tmp_path: Path):
    data = _preflight(
        tmp_path,
        "gene_id,s1,s2,s3,s4\ngA,5,0,10,1\ngB,3,0,4,5\n",
    )
    assert data["valid"] is False
    assert data["summary"]["zero_library_samples"] == ["s2"]
    assert data["summary"]["library_size_ratio"] is None
    assert any(e["field"] == "counts_file" and "zero" in e["message"] for e in data["errors"])
    assert data["summary"]["library_sizes"]["s2"] == 0


def test_malformed_counts_do_not_publish_partial_qc_as_complete(tmp_path: Path):
    data = _preflight(
        tmp_path,
        "gene_id,s1,s2,s3,s4\ngA,2,3,4,5\ngB,3,-1,1,1\n",
    )
    assert data["valid"] is False
    assert data["summary"]["library_sizes"] == {}
    assert data["summary"]["all_zero_genes"] is None
    assert data["summary"]["library_size_ratio"] is None
    assert data["warnings"] == []


def test_preflight_qc_ui_is_rendered_as_text_not_injected_markup():
    body = TestClient(app).get("/").text
    assert 'id="input-library-qc"' in body
    assert 'id="input-validation-warnings"' in body
    assert "sampleLabel.textContent" in body
    assert "sampleTotal.textContent" in body
