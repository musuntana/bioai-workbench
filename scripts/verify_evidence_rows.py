"""Cross-check every DESeq2 results API row/plot point against the downloaded CSV.

The CSV has already been authenticated by the enclosing smoke validator. This
module checks semantic fidelity of the API and plotted data.
"""

from __future__ import annotations

import math
from typing import Any

MAX_POINTS_FOR_FULL_COVERAGE = 5000
_REQUIRED_FIELDS = (
    "gene_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj",
)


class EvidenceRowsError(ValueError):
    """The API's numeric or plot response disagrees with the DESeq2 source CSV."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceRowsError(message)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise EvidenceRowsError("Boolean encountered where a numeric statistic was expected")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceRowsError("Non-numeric DESeq2 statistic") from exc
    if not math.isfinite(number):
        raise EvidenceRowsError("Non-finite DESeq2 statistic")
    return number


def _same(left: Any, right: Any) -> bool:
    a, b = _num(left), _num(right)
    return (a is None and b is None) or (
        a is not None and b is not None
        and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    )


def verify_result_rows(csv_rows: list[dict[str, str]], api: dict[str, Any]) -> None:
    """Fail closed on source/API disagreement, including silently omitted plot points.

    The caller is responsible for checking the downloaded CSV's SHA-256 against
    the run artifact manifest before passing these parsed rows.
    """
    for index, row in enumerate(csv_rows, start=1):
        _require(isinstance(row, dict), f"CSV row {index} is not an object")
        for field in _REQUIRED_FIELDS:
            _require(field in row, f"CSV row {index} missing required CSV field: {field}")
        _require(
            isinstance(row["gene_id"], str) and bool(row["gene_id"]),
            f"CSV row {index} has an empty gene identifier",
        )

    source = {row["gene_id"]: row for row in csv_rows}
    _require(len(source) == len(csv_rows), "Duplicate gene identifiers in DESeq2 CSV")
    api_rows = api.get("rows")
    _require(isinstance(api_rows, list), "Results API returned no row list")
    _require(len(api_rows) == len(csv_rows), "Results API row count does not match CSV")
    seen: set[str] = set()
    summary = api.get("summary")
    _require(isinstance(summary, dict), "Results API summary is missing")
    try:
        padj_limit = _num(summary["padj_max"])
        lfc_limit = _num(summary["min_abs_log2fc"])
    except KeyError as exc:
        raise EvidenceRowsError("Results API threshold metadata is missing") from exc
    _require(padj_limit is not None and 0 < padj_limit <= 1, "Invalid padj threshold")
    _require(lfc_limit is not None and lfc_limit >= 0, "Invalid log2FC threshold")

    def significant(gene: dict[str, Any]) -> bool:
        padj = _num(gene.get("padj"))
        fold = _num(gene.get("log2FoldChange"))
        return (
            padj is not None and fold is not None
            and padj <= padj_limit and abs(fold) >= lfc_limit
        )

    for row in api_rows:
        _require(isinstance(row, dict), "Result API contains a non-object row")
        name = row.get("gene_id")
        _require(isinstance(name, str) and name in source, "Result API returned an unknown gene")
        _require(name not in seen, f"Result API returned duplicate gene {name}")
        seen.add(name)
        original = source[name]
        for field in _REQUIRED_FIELDS[1:]:
            _require(field in row, f"API row {name}: missing {field}")
            _require(_same(original[field], row[field]), f"API row {name}: changed {field}")
        _require(isinstance(row.get("significant"), bool), f"API row {name}: significance not Boolean")
        _require(row["significant"] == significant(original), f"API row {name}: wrong significance")
    _require(seen == set(source), "Results API omitted genes despite matching row count")

    expected_significant = sum(significant(row) for row in csv_rows)
    expected_missing = sum(_num(row["padj"]) is None for row in csv_rows)
    expected_volcano = sum(
        _num(row["log2FoldChange"]) is not None
        and (padj := _num(row["padj"])) is not None and padj >= 0
        for row in csv_rows
    )
    expected_ma = sum(
        (mean := _num(row["baseMean"])) is not None and mean >= 0
        and _num(row["log2FoldChange"]) is not None
        for row in csv_rows
    )
    for key, expected in (
        ("total_genes", len(csv_rows)),
        ("significant_genes", expected_significant),
        ("missing_padj_genes", expected_missing),
        ("plot_eligible_genes", expected_volcano),
        ("ma_eligible_genes", expected_ma),
    ):
        _require(summary.get(key) == expected, f"Results API summary {key} mismatch")

    for kind, fields in (
        ("plot_points", ("log2FoldChange", "padj")),
        ("ma_points", ("baseMean", "log2FoldChange")),
    ):
        points = api.get(kind)
        _require(isinstance(points, list), f"Results API {kind} is missing")
        point_ids: set[str] = set()
        for point in points:
            _require(isinstance(point, dict), f"Results API {kind} contains malformed point")
            name = point.get("gene_id")
            _require(isinstance(name, str) and name in source, f"{kind} contains unknown gene")
            _require(name not in point_ids, f"{kind} contains duplicate gene {name}")
            point_ids.add(name)
            original = source[name]
            for field in fields:
                _require(field in point, f"{kind} {name}: missing {field}")
                _require(_same(original[field], point[field]), f"{kind} {name}: changed {field}")
                _require(_num(point[field]) is not None, f"{kind} {name}: missing/nonfinite {field}")
            _require(
                isinstance(point.get("significant"), bool),
                f"{kind} {name}: significance is not Boolean",
            )
            _require(point["significant"] == significant(original), f"{kind} {name}: wrong significance")
            if kind == "plot_points":
                _require(_num(point["padj"]) >= 0, f"{kind} {name}: negative padj")
            else:
                _require(_num(point["baseMean"]) >= 0, f"{kind} {name}: negative mean")

        count_key = "plot_points_returned" if kind == "plot_points" else "ma_points_returned"
        _require(summary.get(count_key) == len(points), f"Results API {count_key} mismatch")
        eligible_key = "plot_eligible_genes" if kind == "plot_points" else "ma_eligible_genes"
        truncated_key = "plot_points_truncated" if kind == "plot_points" else "ma_points_truncated"
        _require(
            summary.get(truncated_key) == (len(points) < summary[eligible_key]),
            f"Results API {truncated_key} mismatch",
        )

        # The smoke fixture has 100 genes, well below the backend's 5,000-point
        # cap. Require full coverage so a truncation flag cannot hide omissions.
        if summary[eligible_key] <= MAX_POINTS_FOR_FULL_COVERAGE:
            if kind == "plot_points":
                eligible_ids = {
                    row["gene_id"] for row in csv_rows
                    if _num(row["log2FoldChange"]) is not None
                    and (padj := _num(row["padj"])) is not None and padj >= 0
                }
            else:
                eligible_ids = {
                    row["gene_id"] for row in csv_rows
                    if (mean := _num(row["baseMean"])) is not None and mean >= 0
                    and _num(row["log2FoldChange"]) is not None
                }
            _require(point_ids == eligible_ids, f"{kind} missing eligible genes")
