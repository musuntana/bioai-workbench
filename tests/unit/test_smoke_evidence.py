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
             "lfcSE": 0.6 if i == 1 else 0.1, "stat": 4.0 if i == 1 else 0.1,
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
    # New report/export fixtures independently mirror the original R CSV values.
    _write_json(tmp_path / "batch-results.json", {
        "run_id": original,
        "gene_filter": {
            "requested": 3, "found": 2, "missing": ["missing_gene_xyz"],
        },
        "filtered_genes": 2,
        "rows": [
            {"gene_id": "gene_001", "baseMean": 100.0, "log2FoldChange": 2.0, "padj": 0.01},
            {"gene_id": "gene_050", "baseMean": 100.0, "log2FoldChange": 0.1, "padj": 0.8},
        ],
    })
    with (tmp_path / "batch-export.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["gene_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"])
        writer.writerow(["gene_001", 100, 2, 0.6, 4, 0.001, 0.01])
        writer.writerow(["gene_050", 100, 0.1, 0.1, 0.1, 0.5, 0.8])
    (tmp_path / "batch-report.html").write_text(
        f'<html><h1>DESeq2 gene-list report</h1>{original}{digest}'
        '<p>Requested IDs: <strong>3</strong></p>'
        '<p>Found in run: <strong>2</strong></p>'
        '<td>gene_001</td><td>gene_050</td><td>missing_gene_xyz</td></html>',
        encoding="utf-8",
    )
    with (tmp_path / "aligned-gene-comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "gene_id", "category", "run_a_base_mean", "run_b_base_mean",
            "run_a_log2fc", "run_b_log2fc", "run_a_padj", "run_b_padj",
            "run_a_significant", "run_b_significant",
            "run_a_id", "run_b_id", "run_a_counts_sha256", "run_b_counts_sha256",
            "run_a_metadata_sha256", "run_b_metadata_sha256",
            "run_a_result_sha256", "run_b_result_sha256",
            "padj_max", "min_abs_log2fc",
        ])
        writer.writeheader()
        for index in range(1, 101):
            significant = index == 1
            writer.writerow({
                "gene_id": f"gene_{index:03}", "category": "both" if significant else "neither_significant",
                "run_a_base_mean": 100, "run_b_base_mean": 100,
                "run_a_log2fc": 2 if significant else 0.1,
                "run_b_log2fc": 2 if significant else 0.1,
                "run_a_padj": 0.01 if significant else 0.8,
                "run_b_padj": 0.01 if significant else 0.8,
                "run_a_significant": significant, "run_b_significant": significant,
                "run_a_id": original, "run_b_id": rerun,
                "run_a_counts_sha256": "e" * 64, "run_b_counts_sha256": "e" * 64,
                "run_a_metadata_sha256": "f" * 64, "run_b_metadata_sha256": "f" * 64,
                "run_a_result_sha256": digest, "run_b_result_sha256": digest,
                "padj_max": 0.05, "min_abs_log2fc": 1,
            })
    (tmp_path / "cross-run-report.html").write_text(
        f'<html><h1>DESeq2 cross-run evidence report</h1>{original}{rerun}{digest}'
        f'<p>Counts: {"e" * 64} {"f" * 64}</p>'
        '<p>Both runs tested: 100</p>'
        '<p>Changes in significance categories do not establish a statistically '
        'significant between-run difference.</p></html>',
        encoding="utf-8",
    )
    return tmp_path


def test_valid_synthetic_evidence_bundle(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    report = verify_bundle(bundle)
    assert report["status"] == "passed"
    assert report["checks"]["rerun_result_byte_equality"] == "passed"
    assert report["checks"]["selected_gene_and_cross_run_evidence"] == "passed"
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


@pytest.mark.parametrize("target,change,expected", [
    ("batch-results.json", lambda d: d["gene_filter"].update(found=3), "batch filter found"),
    ("batch-results.json", lambda d: d["rows"][0].update(padj=0.5), "batch preview padj"),
])
def test_new_report_evidence_rejects_forged_api_results(tmp_path: Path, target, change, expected) -> None:
    bundle = _make_bundle(tmp_path)
    p = bundle / target
    payload = json.loads(p.read_text(encoding="utf-8"))
    change(payload)
    _write_json(p, payload)
    with pytest.raises(AcceptanceError, match=expected):
        verify_bundle(bundle)


def test_new_report_evidence_rejects_tampered_full_union_csv(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    p = bundle / "aligned-gene-comparison.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("gene_050", "gene_forged"))
    with pytest.raises(AcceptanceError, match="aligned gene IDs"):
        verify_bundle(bundle)


def test_new_report_evidence_rejects_missing_provenance_in_html(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    p = bundle / "cross-run-report.html"
    p.write_text(p.read_text(encoding="utf-8").replace("e" * 64, "0" * 64))
    with pytest.raises(AcceptanceError, match="cross-run report counts input hash"):
        verify_bundle(bundle)
