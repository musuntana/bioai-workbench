"""Regression tests: summary-only checks must not certify corrupted gene statistics."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.verify_evidence_rows import EvidenceRowsError, verify_result_rows


def _fixture():
    source = [
        {"gene_id": "gene_001", "baseMean": "100", "log2FoldChange": "2.4", "lfcSE": "0.6",
         "stat": "4", "pvalue": "0.0001", "padj": "0.001"},
        {"gene_id": "gene_002", "baseMean": "20", "log2FoldChange": "-0.4", "lfcSE": "0.2",
         "stat": "-2", "pvalue": "0.05", "padj": "0.12"},
        {"gene_id": "gene_003", "baseMean": "0", "log2FoldChange": "", "lfcSE": "",
         "stat": "", "pvalue": "", "padj": ""},
    ]
    rows = [
        {**{k: (float(v) if k != "gene_id" and v else (None if k != "gene_id" else v))
            for k, v in gene.items()}, "significant": gene["gene_id"] == "gene_001"}
        for gene in source
    ]
    api = {
        "rows": rows,
        "summary": {
            "total_genes": 3, "significant_genes": 1, "missing_padj_genes": 1,
            "padj_max": 0.05, "min_abs_log2fc": 1,
            "plot_eligible_genes": 2, "ma_eligible_genes": 2,
            "plot_points_returned": 2, "ma_points_returned": 2,
            "plot_points_truncated": False, "ma_points_truncated": False,
        },
        "plot_points": [
            {"gene_id": row["gene_id"], "log2FoldChange": row["log2FoldChange"],
             "padj": row["padj"], "significant": row["significant"]}
            for row in rows[:2]
        ],
        "ma_points": [
            {"gene_id": row["gene_id"], "baseMean": row["baseMean"],
             "log2FoldChange": row["log2FoldChange"], "significant": row["significant"]}
            for row in rows[:2]
        ],
    }
    return source, api


def test_correct_per_gene_numeric_and_plot_values() -> None:
    verify_result_rows(*_fixture())


@pytest.mark.parametrize("mutation,expected", [
    (lambda r: r["rows"][1].update(padj=0.4), "API row gene_002: changed padj"),
    (lambda r: r["rows"][1].update(log2FoldChange=1.4), "API row gene_002: changed log2FoldChange"),
    (lambda r: r["rows"][1].update(significant=True), "API row gene_002: wrong significance"),
    (lambda r: r["rows"][1].update(gene_id="gene_001"), "duplicate gene"),
    (lambda r: r["plot_points"][1].update(padj=0.01), "plot_points gene_002: changed padj"),
    (lambda r: r["ma_points"][1].update(baseMean=5), "ma_points gene_002: changed baseMean"),
    (lambda r: r["summary"].update(ma_eligible_genes=1), "summary ma_eligible_genes mismatch"),
    (lambda r: r["summary"].update(plot_points_truncated=True), "plot_points_truncated mismatch"),
    (lambda r: r["rows"].pop(), "row count does not match CSV"),
])
def test_rejects_corrupted_evidence_not_detectable_from_summary_only(mutation, expected) -> None:
    source, api = _fixture()
    changed = deepcopy(api)
    mutation(changed)
    with pytest.raises(EvidenceRowsError, match=expected):
        verify_result_rows(source, changed)


@pytest.mark.parametrize("kind,count_key,truncated_key", [
    ("plot_points", "plot_points_returned", "plot_points_truncated"),
    ("ma_points", "ma_points_returned", "ma_points_truncated"),
])
def test_rejects_silent_point_omission_when_every_eligible_gene_fits(
    kind, count_key, truncated_key
) -> None:
    """A plot must not claim truncation to hide missing points in a tiny cohort."""
    source, api = _fixture()
    api[kind].pop()
    api["summary"][count_key] = 1
    api["summary"][truncated_key] = True
    with pytest.raises(EvidenceRowsError, match="missing eligible genes"):
        verify_result_rows(source, api)


def test_rejects_missing_required_csv_column() -> None:
    source, api = _fixture()
    source[0].pop("padj")
    with pytest.raises(EvidenceRowsError, match="missing required CSV field: padj"):
        verify_result_rows(source, api)


def test_rejects_non_finite_csv_statistic_instead_of_treating_it_as_missing() -> None:
    source, api = _fixture()
    source[1]["padj"] = "NaN"
    with pytest.raises(EvidenceRowsError, match="non-finite DESeq2 statistic"):
        verify_result_rows(source, api)
