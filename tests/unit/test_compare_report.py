"""Cross-run gene alignment exports must preserve evidence and interpretation boundaries."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, run_manager
from artifacts.manifest import write_artifact_manifest
from runtime.state import RunStore


def _make_run(store: RunStore, run_id: str, genes: str, *, reverse: bool = False) -> Path:
    store.create(
        run_id, "deseq2-basic",
        parameters={
            "condition": "condition",
            "reference": "treated" if reverse else "control",
            "contrast": "control" if reverse else "treated",
            "alpha": 0.05,
        },
    )
    output = store.run_dir(run_id) / "outputs"
    result_file = output / "differential_expression_all.csv"
    result_file.write_text(
        "gene_id,baseMean,log2FoldChange,pvalue,padj\n" + genes, encoding="utf-8"
    )
    for name, contents in (
        ("differential_expression_significant.csv", "gene_id,baseMean,log2FoldChange,pvalue,padj\n"),
        ("run_manifest.tsv", "key\tvalue\n"),
        ("session_info.txt", "synthetic session info\n"),
    ):
        (output / name).write_text(contents, encoding="utf-8")
    write_artifact_manifest(output, run_id=run_id, workflow_id="deseq2-basic")
    store.update(
        run_id, status="succeeded",
        input_provenance={"counts": {"sha256": "a" * 64},
                          "metadata": {"sha256": "b" * 64}},
        environment_provenance={"r_version": "R 4.4.3", "deseq2_version": "1.46.0",
                                "workflow_sha256": "c" * 64},
    )
    return result_file


def test_all_gene_export_aligns_union_and_records_provenance_without_formulas():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "a" * 32, "b" * 32
        _make_run(
            store, a,
            "common,10,2,0.01,0.01\n"
            "switch,8,2,0.001,0.01\n"
            "neutral,7,0.1,0.8,0.8\n"
            "only_a,5,1.8,0.03,0.04\n"
            "=RISK,2,1.1,0.04,0.04\n",
        )
        _make_run(
            store, b,
            "common,10,2,0.01,0.01\n"
            "switch,8,0.2,0.6,0.6\n"
            "neutral,7,0.2,0.7,0.7\n"
            "only_b,5,-2,0.03,0.04\n",
            reverse=True,
        )
        params = {"run_a": a, "run_b": b, "scope": "all"}
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            all_csv = client.get("/api/v1/runs/compare/genes/export", params=params)
            old_csv = client.get(
                "/api/v1/runs/compare/genes/export",
                params={"run_a": a, "run_b": b},
            )
            report = client.get(
                "/api/v1/runs/compare/genes/report", params={"run_a": a, "run_b": b},
            )

        assert all_csv.status_code == 200
        assert old_csv.status_code == 200
        entries = list(csv.DictReader(io.StringIO(all_csv.text)))
        assert len(entries) == 6
        by_gene = {entry["gene_id"]: entry for entry in entries}
        assert "'=RISK" in by_gene
        assert by_gene["only_a"]["category"] == "only_a_tested"
        assert by_gene["only_a"]["run_b_padj"] == ""
        assert by_gene["only_b"]["category"] == "only_b_tested"
        assert by_gene["neutral"]["category"] == "neither_significant"
        assert by_gene["common"]["category"] == "both"
        assert by_gene["switch"]["category"] == "only_a"
        assert by_gene["switch"]["run_a_base_mean"] == "8.0"
        assert by_gene["switch"]["run_b_base_mean"] == "8.0"
        assert by_gene["common"]["run_a_id"] == a
        assert by_gene["common"]["run_b_id"] == b
        assert by_gene["common"]["run_a_counts_sha256"] == "a" * 64
        assert by_gene["common"]["run_b_metadata_sha256"] == "b" * 64
        assert by_gene["common"]["padj_max"] == "0.05"
        assert by_gene["common"]["min_abs_log2fc"] == "1.0"
        assert by_gene["common"]["run_a_contrast"] == "treated"
        assert by_gene["common"]["run_b_contrast"] == "control"
        legacy_entries = list(csv.DictReader(io.StringIO(old_csv.text)))
        assert {row["gene_id"] for row in legacy_entries} == {"common", "switch"}
        assert all(row["gene_id"] not in {"only_a", "only_b"} for row in legacy_entries)

        assert report.status_code == 200
        assert report.headers["cache-control"] == "no-store"
        assert "default-src 'none'" in report.headers["content-security-policy"]
        assert "text/html" in report.headers["content-type"]
        assert "Both runs tested" in report.text
        assert "6" in report.text
        assert "only_a" in report.text
        assert "only_b" in report.text
        assert "Reference/contrast" in report.text
        assert "treated" in report.text
        assert a in report.text and b in report.text
        assert "a" * 64 in report.text
        assert "b" * 64 in report.text
        assert "deseq2_version" in report.text
        assert "&quot;" not in report.text  # no unsafe HTML attribute injection in these fixtures
        assert "<script>" not in report.text


def test_aligned_report_rejects_tampering_duplicates_and_invalid_ids():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "c" * 32, "d" * 32
        target = _make_run(store, a, "ok,10,2,0.01,0.01\n")
        _make_run(store, b, "ok,10,2,0.01,0.01\n")
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            route = "/api/v1/runs/compare/genes/report"
            assert client.get(route, params={"run_a": a, "run_b": a}).status_code == 422
            assert client.get(route, params={"run_a": "bad", "run_b": b}).status_code == 422
            target.write_text("tampered", encoding="utf-8")
            assert client.get(route, params={"run_a": a, "run_b": b}).status_code == 409
            assert client.get(
                "/api/v1/runs/compare/genes/export",
                params={"run_a": a, "run_b": b, "scope": "all"},
            ).status_code == 409
            assert client.get(
                "/api/v1/runs/compare/genes/export",
                params={"run_a": a, "run_b": b, "scope": "invalid"},
            ).status_code == 422


def test_all_gene_comparison_requires_unique_gene_ids():
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "e" * 32, "f" * 32
        _make_run(store, a, "dup,1,1,0.02,0.03\ndup,2,2,0.01,0.01\n")
        _make_run(store, b, "dup,1,1,0.02,0.03\n")
        with patch.object(run_manager, "store", store):
            res = TestClient(app).get(
                "/api/v1/runs/compare/genes/report", params={"run_a": a, "run_b": b}
            )
            assert res.status_code == 409


def test_comparison_report_ui_offers_html_and_full_union_export():
    home = TestClient(app).get("/")
    assert home.status_code == 200
    assert 'id="gene-comparison-report"' in home.text
    assert 'id="gene-comparison-all-export"' in home.text
    assert '/compare/genes/report?' in home.text
    assert 'allQuery.set("scope", "all")' in home.text


def test_comparison_exports_escape_spreadsheet_formula_prefixes_and_html_injection():
    """Excel-style consumers must not evaluate formula IDs hidden behind whitespace/BOM."""
    hostile = [
        "\t=2+2", "  @SUM(1)", "\ufeff+3", "\r\n-4", "'=already_text",
        "<script>alert(1)</script>",
    ]
    source = io.StringIO()
    writer = csv.writer(source)
    for gene in hostile:
        writer.writerow((gene, 10, 2, 0.01, 0.01))
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "1" * 32, "2" * 32
        _make_run(store, a, source.getvalue())
        _make_run(store, b, source.getvalue())
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            route = "/api/v1/runs/compare/genes/export"
            exports = [
                client.get(route, params={"run_a": a, "run_b": b, "scope": scope})
                for scope in ("all", "significant")
            ]
            report = client.get(
                "/api/v1/runs/compare/genes/report", params={"run_a": a, "run_b": b}
            )
        for response in exports:
            assert response.status_code == 200
            exported_ids = {
                entry["gene_id"]
                for entry in csv.DictReader(io.StringIO(response.text))
            }
            assert exported_ids == {
                "'\t=2+2", "'  @SUM(1)", "'\ufeff+3", "'\r\n-4",
                "'=already_text", "<script>alert(1)</script>",
            }
        assert report.status_code == 200
        assert "<script>alert(1)</script>" not in report.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in report.text


def test_report_preview_has_exact_100_row_boundary_but_csv_is_complete():
    """The HTML preview must not silently truncate the separately exported union."""
    with TemporaryDirectory() as directory:
        store = RunStore(Path(directory))
        a, b = "3" * 32, "4" * 32
        genes = "".join(f"g{i:03d},10,2,0.01,0.01\n" for i in range(125))
        _make_run(store, a, genes)
        _make_run(store, b, "g000,10,2,0.01,0.01\n")
        with patch.object(run_manager, "store", store):
            client = TestClient(app)
            params = {"run_a": a, "run_b": b}
            report = client.get("/api/v1/runs/compare/genes/report", params=params)
            export = client.get(
                "/api/v1/runs/compare/genes/export",
                params={**params, "scope": "all"},
            )
        assert report.status_code == 200
        assert "first 100 of\n 125 union genes" in report.text
        assert "<td>g099</td>" in report.text
        assert "<td>g100</td>" not in report.text
        assert export.status_code == 200
        rows = list(csv.DictReader(io.StringIO(export.text)))
        assert len(rows) == 125
        assert {row["gene_id"] for row in rows} == {f"g{i:03d}" for i in range(125)}
