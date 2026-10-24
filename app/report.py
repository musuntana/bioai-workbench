"""Render a portable, script-free scientific report from verified result previews.

This is an on-demand export, not an extra artifact written into the run directory.
"""

from __future__ import annotations

import math
import re
from html import escape
from pathlib import PurePosixPath
from typing import Any

_VERSION_KEYS = ("r_version", "deseq2_version", "bioconductor_version",
                 "workflow_version", "workflow_sha256")
_PARAMETER_KEYS = ("condition", "reference", "contrast", "alpha")


def _html(value: object) -> str:
    if value is None:
        return "Not recorded"
    return escape(str(value), quote=True)


def _number(value: object) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "NA"
    return f"{value:.5g}"


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    header = "".join(f"<th scope='col'>{_html(item)}</th>" for item in headers)
    if not rows:
        cells = f"<td colspan='{len(headers)}'>No entries available.</td>"
        body = f"<tr>{cells}</tr>"
    else:
        body = "".join(
            "<tr>" + "".join(f"<td>{_html(value)}</td>" for value in row) + "</tr>"
            for row in rows
        )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _plot_svg(points: list[dict[str, Any]], kind: str) -> str:
    """Plot only finite numeric values; strings go inside escaped SVG titles."""
    prepared: list[tuple[float, float, str, bool]] = []
    for point in points:
        fold = point.get("log2FoldChange")
        measure = point.get("padj" if kind == "volcano" else "baseMean")
        if not isinstance(fold, (int, float)) or not math.isfinite(fold):
            continue
        if not isinstance(measure, (int, float)) or not math.isfinite(measure):
            continue
        if measure < 0:
            continue
        if kind == "volcano":
            x, y = fold, min(50.0, -math.log10(max(measure, 1e-50)))
        else:
            x, y = math.log10(measure + 1), max(-10.0, min(10.0, fold))
        prepared.append((x, y, str(point["gene_id"]), bool(point.get("significant"))))

    if not prepared:
        return "<p>No genes have the required numeric coordinates for this plot.</p>"

    width, height = 860, 330
    left, right, top, bottom = 76, 24, 22, 48
    plot_width, plot_height = width - left - right, height - top - bottom
    x_min = min(0.0, *(p[0] for p in prepared))
    x_max = max(1.0, *(p[0] for p in prepared))
    if x_max <= x_min:
        x_max = x_min + 1
    if kind == "volcano":
        y_min, y_max = 0.0, max(2.0, *(p[1] for p in prepared))
        x_label = "log2 fold change"
        y_label = "-log10(adjusted p-value), capped at 50"
    else:
        y_min, y_max = -10.0, 10.0
        x_label = "log10(baseMean + 1)"
        y_label = "log2 fold change, capped at +/-10"

    def cx(x: float) -> float:
        return left + (x - x_min) / (x_max - x_min) * plot_width

    def cy(y: float) -> float:
        return top + (y_max - y) / (y_max - y_min) * plot_height

    circles = "".join(
        f'<circle cx="{cx(x):.2f}" cy="{cy(y):.2f}" r="2.2" '
        f'fill="{"#b33a50" if sig else "#527da2"}">'
        f"<title>{_html(gene)}</title></circle>"
        for x, y, gene, sig in prepared
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_html(kind)} plot, {len(prepared)} sampled genes" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" '
        'stroke="#666"/>'
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" '
        f'y2="{top + plot_height}" stroke="#666"/>'
        f'{circles}'
        f'<text x="{width // 2}" y="{height - 6}" text-anchor="middle">'
        f'{_html(x_label)}</text>'
        f'<text x="10" y="17">{_html(y_label)}</text></svg>'
    )


def render_html_report(
    record: dict[str, Any], results: dict[str, Any], artifacts: list[dict[str, Any]]
) -> str:
    """Make a bounded standalone report without rendering untrusted markup."""
    summary = results["summary"]
    run_id = record["run_id"]
    params = record.get("parameters") or {}
    inputs = record.get("input_provenance") or {}
    environment = record.get("environment_provenance") or {}

    parameter_rows = [(key, params.get(key)) for key in _PARAMETER_KEYS]
    input_rows = []
    for role in ("counts", "metadata"):
        item = inputs.get(role) or {}
        filename = item.get("filename")
        name = PurePosixPath(filename).name if isinstance(filename, str) else None
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            digest = None
        input_rows.append((role, name, item.get("size_bytes"), digest))
    environment_rows = [(key, environment.get(key)) for key in _VERSION_KEYS]
    artifact_rows = [
        (item.get("path"), item.get("size_bytes"), item.get("sha256"))
        for item in sorted(artifacts, key=lambda entry: str(entry.get("path", "")))
        if isinstance(item, dict)
    ]
    gene_filter = results.get("gene_filter") or {}
    is_gene_list_report = gene_filter.get("requested", 0) > 0
    gene_rows = [
        (row.get("gene_id"), _number(row.get("baseMean")),
         _number(row.get("log2FoldChange")), _number(row.get("padj")))
        for row in results["rows"]
    ]
    missing_gene_rows = [(gene_id,) for gene_id in gene_filter.get("missing", [])]
    gene_filter_section = ""
    if is_gene_list_report:
        gene_filter_section = (
            "<h2>Gene list filter</h2>"
            "<p>Matching uses case-sensitive exact gene IDs. The table and plots below "
            "contain only requested IDs found in this run; rows are included regardless "
            "of the display significance threshold.</p>"
            "<div class=\"stats\">"
            f"<span>Requested IDs: <strong>{_html(gene_filter.get('requested', 0))}</strong></span>"
            f"<span>Found in run: <strong>{_html(gene_filter.get('found', 0))}</strong></span>"
            f"<span>Missing IDs: <strong>{_html(len(missing_gene_rows))}</strong></span>"
            "</div>"
            "<h3>IDs not found</h3>"
            f"{_table(('Missing gene ID',), missing_gene_rows)}"
        )
    gene_section_title = "Selected gene list" if is_gene_list_report else "Top significant genes"
    gene_section_description = (
        f"The table includes {len(gene_rows)} exact-match gene(s) found from the requested list. "
        "All matched rows are included, including non-significant rows; missing IDs are listed above."
        if is_gene_list_report else
        f"Up to {len(gene_rows)} genes ordered by adjusted p-value; use the full verified CSV export for all results."
    )
    report_title = "DESeq2 gene-list report" if is_gene_list_report else "DESeq2 analysis report"

    style = """
      body { font-family: system-ui, sans-serif; color: #202632; margin: auto;
             max-width: 1060px; padding: 32px; line-height: 1.5; }
      h1,h2 { color: #203451; }
      h2 { border-bottom: 1px solid #d3d9e0; padding-bottom: 6px; margin-top: 35px; }
      .muted { color: #5d6674; }
      .stats { display: flex; flex-wrap: wrap; gap: 12px; }
      .stats span { background: #eef2f7; padding: 12px; border-radius: 6px; }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      th,td { text-align: left; vertical-align: top; padding: 8px;
              border-bottom: 1px solid #ddd; overflow-wrap: anywhere; }
      th { background: #eef2f7; }
      svg { width: 100%; height: auto; background: #fafbfc; }
      .figure { margin: 25px 0; }
      @media print { body { padding: 0; } h2, .figure { break-inside: avoid; } }
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html(report_title)} – {_html(run_id)}</title>
<style>{style}</style></head>
<body>
<h1>{_html(report_title)}</h1>
<p class="muted">Run {_html(run_id)} · workflow {_html(record.get("workflow_id"))}
 · completed {_html(record.get("finished_at"))}</p>
<p><strong>Interpretation boundary:</strong> This is an exploratory computational report,
not a biological or clinical conclusion. Verify the contrast and input metadata.</p>
<h2>Result summary</h2>
<div class="stats">
<span>Total genes: <strong>{summary["total_genes"]}</strong></span>
<span>Significant: <strong>{summary["significant_genes"]}</strong></span>
<span>Missing adjusted p-value: <strong>{summary["missing_padj_genes"]}</strong></span>
</div>
<p>These counts describe the full run, not just the selected gene list. Report significance rule: padj ≤ {_html(summary["padj_max"])}
 and |log2FC| ≥ {_html(summary["min_abs_log2fc"])}.
 This display rule may differ from the workflow's alpha-only significant CSV.</p>
{gene_filter_section}
<h2>Workflow parameters</h2>
{_table(("Parameter", "Value"), parameter_rows)}
<h2>Input provenance</h2>
{_table(("Role", "Input filename", "Bytes", "SHA-256"), input_rows)}
<h2>Runtime and workflow identity</h2>
{_table(("Component", "Recorded value"), environment_rows)}
<h2>Volcano plot</h2>
<div class="figure">{_plot_svg(results["plot_points"], "volcano")}
<p class="muted">Showing {summary["plot_points_returned"]} of
 {summary["plot_eligible_genes"]} eligible points.
 Sampling is bounded and may omit genes. Thresholds are reflected in point colors.</p></div>
<h2>MA plot</h2>
<div class="figure">{_plot_svg(results["ma_points"], "ma")}
<p class="muted">Showing {summary["ma_points_returned"]} of
 {summary["ma_eligible_genes"]} eligible points. Display y-axis capped at ±10.</p></div>
<h2>{_html(gene_section_title)}</h2>
<p class="muted">{_html(gene_section_description)}</p>
{_table(("Gene ID", "baseMean", "log2FC", "padj"), gene_rows)}
<h2>Output artifact inventory</h2>
{_table(("Relative filename", "Bytes", "Recorded SHA-256"), artifact_rows)}
<p class="muted">The DESeq2 result CSV was SHA-256 checked against its artifact
manifest when this report was rendered. Other hashes above are recorded manifest
values, not independently reverified by report export. Missing provenance in older
runs is shown as Not recorded. This report is generated on demand and does not
modify the run's stored artifacts.</p>
</body></html>"""
