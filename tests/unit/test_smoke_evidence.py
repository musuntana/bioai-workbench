"""Synthetic offline fixtures for the real-R smoke evidence validator.

These tests validate *checking logic*, not the R/DESeq2 computation itself.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_deseq2_smoke import AcceptanceError, verify_bundle


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_bundle(tmp_path: Path) -> Path:
    original, rerun = "a" * 32, "b" * 32
    source = tmp_path / "download-differential_expression_all.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["gene_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"])
        for index in range(1, 101):
            writer.writerow([
                f"gene_{index:03}", "100", "2" if index == 1 else "0.1",
                "0.6" if index == 1 else "0.1", "4" if index == 1 else "0.1",
                "0.001" if index == 1 else "0.5",
                "0.01" if index == 1 else "0.8",
            ])
    (tmp_path / "rerun-differential_expression_all.csv").write_bytes(source.read_bytes())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifacts = {"artifacts": [
        {"path": "differential_expression_all.csv", "sha256": digest},
        {"path": "differential_expression_significant.csv", "sha256": "c" * 64},
    ]}
    _write_json(tmp_path / "artifacts.json", artifacts)
    _write_json(tmp_path / "rerun-artifacts.json", artifacts)
    versions = {
        "workflow_sha256": "d" * 64,
        "r_version": "R version 4.4",
        "deseq2_version": "1.46.0",
    }
    inputs = {role: {"sha256": letter * 64} for role, letter in
              (("counts", "e"), ("metadata", "f"))}
    _write_json(tmp_path / "run-status.json", {
        "status": "succeeded", "run_id": original,
        "input_provenance": inputs, "environment_provenance": versions,
    })
    _write_json(tmp_path / "rerun-status.json", {
        "status": "succeeded", "run_id": rerun, "parent_run_id": original,
        "input_provenance": inputs, "environment_provenance": versions,
    })
    _write_json(tmp_path / "results.json", {
        "run_id": original,
        "rows": [
            {"gene_id": f"gene_{i:03}", "baseMean": 100.0,
             "log2FoldChange": 2.0 if i == 1 else 0.1,
             "pvalue": 0.001 if i == 1 else 0.5,
             "padj": 0.01 if i == 1 else 0.8,
             "lfcSE": 0.6, "stat": 4.0 if i == 1 else 0.1,
             "significant": i == 1}
            for i in range(1, 101)
        ],
        "summary": {
            "total_genes": 100, "significant_genes": 1,
            "missing_padj_genes": 0, "padj_max": 0.05,
            "min_abs_log2fc": 1,
            "plot_eligible_genes": 100, "ma_eligible_genes": 100,
            "plot_points_returned": 100, "ma_points_returned": 100,
            "plot_points_truncated": False, "ma_points_truncated": False,
        },
        "plot_points": [
            {"gene_id": f"gene_{i:03}", "log2FoldChange": 2.0 if i == 1 else 0.1,
             "padj": 0.01 if i == 1 else 0.8, "significant": i == 1}
            for i in range(1, 101)
        ],
        "ma_points": [
            {"gene_id": f"gene_{i:03}", "baseMean": 100.0,
             "log2FoldChange": 2.0 if i == 1 else 0.1, "significant": i == 1}
            for i in range(1, 101)
        ],
    })
    gene = {
        "gene_id": "gene_001", "baseMean": 100,
        "log2FoldChange": 2, "pvalue": 0.001, "padj": 0.01,
    }
    _write_json(tmp_path / "gene-detail.json", {"run_id": original, "gene": gene})
    _write_json(tmp_path / "run-comparison.json", {
        "same_workflow": True, "inputs": {
            "counts": {"same_content": True},
            "metadata": {"same_content": True},
        },
    })
    _write_json(tmp_path / "gene-comparison.json", {
        "gene_id": "gene_001", "a": gene, "b": gene,
    })
    _write_json(tmp_path / "gene-set-comparison.json", {
        "counts": {"only_a_significant": 0, "only_b_significant": 0},
    })
    (tmp_path / "report.html").write_text(
        f"<html><h1>DESeq2 analysis report</h1>{original}"
        "<p>Total genes: <strong>100</strong></p>"
        "<p>Significant: <strong>1</strong></p>"
        "<svg><circle/></svg><svg><circle/></svg></html>",
        encoding="utf-8",
    )
    return tmp_path


def test_valid_synthetic_evidence_bundle(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    report = verify_bundle(bundle)
    assert report["status"] == "passed"
    assert report["checks"]["rerun_result_byte_equality"] == "passed"
    assert report["metrics"]["total_genes"] == 100
    assert report["metrics"]["significant_genes_at_preview_threshold"] == 1


@pytest.mark.parametrize("target,edit,expected", [
    ("results.json", lambda p: p["summary"].update(significant_genes=2),
     "significance mismatch"),
    ("rerun-status.json", lambda p: p["input_provenance"]["counts"].update(sha256="0" * 64),
     "changed counts input bytes"),
    ("gene-comparison.json", lambda p: p["b"].update(log2FoldChange=1),
     "changed gene_001 log2FoldChange"),
    ("gene-set-comparison.json", lambda p: p["counts"].update(only_a_significant=1),
     "significant-gene membership"),
])
def test_detects_acceptance_regressions(tmp_path: Path, target, edit, expected) -> None:
    bundle = _make_bundle(tmp_path)
    file = bundle / target
    payload = json.loads(file.read_text(encoding="utf-8"))
    edit(payload)
    _write_json(file, payload)
    with pytest.raises(AcceptanceError, match=expected):
        verify_bundle(bundle)


def test_detects_rerun_result_tampering(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    (bundle / "rerun-differential_expression_all.csv").write_text(
        "gene_id,baseMean\nforged,1\n", encoding="utf-8",
    )
    with pytest.raises(AcceptanceError, match="rerun DESeq2 CSV"):
        verify_bundle(bundle)
