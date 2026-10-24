"""Safe, bounded HTML report for two verified differential-expression runs."""

from __future__ import annotations

from html import escape
from typing import Any

_PREVIEW_LIMIT = 100
_PARAMETERS = ("condition", "reference", "contrast", "alpha")
_ENVIRONMENT_FIELDS = (
    "r_version", "deseq2_version", "bioconductor_version",
    "workflow_version", "workflow_sha256",
)


def _html(value: Any) -> str:
    if value is None:
        return "Not recorded"
    return escape(str(value), quote=True)


def _table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    head = "".join(f"<th scope='col'>{_html(column)}</th>" for column in headers)
    cells = (
        "".join(
            "<tr>" + "".join(f"<td>{_html(value)}</td>" for value in row) + "</tr>"
            for row in rows
        )
        if rows else f"<tr><td colspan='{len(headers)}'>No matching rows.</td></tr>"
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{cells}</tbody></table>"


def render_gene_comparison_report(
    aligned: dict[str, Any], snapshot: dict[str, Any]
) -> str:
    """Render a script-free report; no untrusted value becomes active markup."""
    left, right = snapshot["runs"]
    counts = aligned["counts"]
    genes = aligned["genes"]
    params_a, params_b = left["parameters"], right["parameters"]
    warnings = [
        "Changes in significance categories do not establish a statistically "
        "significant between-run difference. No between-run hypothesis test was performed."
    ]
    if not snapshot["same_workflow"]:
        warnings.append("Workflow IDs differ; numerical results may not be comparable.")
    if any(params_a.get(key) != params_b.get(key) for key in ("reference", "contrast")):
        warnings.append(
            "Reference/contrast definitions differ between runs. Fold-change "
            "sign and direction must be interpreted separately before comparison."
        )
    if params_a.get("condition") != params_b.get("condition"):
        warnings.append("Condition columns differ between runs.")
    if params_a.get("alpha") != params_b.get("alpha"):
        warnings.append("Recorded workflow alpha values differ between runs.")
    if any(item["same_content"] is None for item in snapshot["inputs"].values()):
        warnings.append("At least one input checksum is unavailable in a historical run.")
    if any(item["same_content"] is False for item in snapshot["inputs"].values()):
        warnings.append("Input bytes differ between runs; descriptive changes may reflect inputs.")
    if any(item["same"] is False for item in snapshot["environment"]):
        warnings.append("Runtime or workflow version metadata differs between runs.")

    param_rows = [
        (key, params_a.get(key), params_b.get(key)) for key in _PARAMETERS
    ]
    input_rows = [
        (
            role,
            item["run_a_sha256"],
            item["run_b_sha256"],
            item["same_content"],
        )
        for role, item in snapshot["inputs"].items()
    ]
    environment_rows = [
        (
            key,
            (left["environment_provenance"] or {}).get(key),
            (right["environment_provenance"] or {}).get(key),
        )
        for key in _ENVIRONMENT_FIELDS
    ]
    artifact_rows = [
        (
            "differential_expression_all.csv",
            left["artifact_hashes"].get("differential_expression_all.csv"),
            right["artifact_hashes"].get("differential_expression_all.csv"),
        )
    ]
    gene_rows = [
        (
            gene["gene_id"], gene["category"],
            gene.get("run_a_base_mean"), gene.get("run_b_base_mean"),
            gene.get("run_a_log2fc"), gene.get("run_b_log2fc"),
            gene.get("run_a_padj"), gene.get("run_b_padj"),
            gene.get("run_a_significant"), gene.get("run_b_significant"),
        )
        for gene in genes[:_PREVIEW_LIMIT]
    ]
    warning_markup = "".join(f"<li>{_html(item)}</li>" for item in warnings)
    style = """
      body { font: 15px/1.5 system-ui, sans-serif; max-width: 1150px; margin: auto;
             padding: 28px; color: #202632; }
      h1, h2 { color: #203451; }
      h2 { border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-top: 28px; }
      .muted { color: #535e6f; }
      table { border-collapse: collapse; width: 100%; font-size: 12px; }
      th,td { padding: 7px; border-bottom: 1px solid #ccc; text-align: left;
              overflow-wrap: anywhere; }
      th { background: #eef2f7; }
      .scroll { overflow-x: auto; }
      @media print { body { padding: 0; } }
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DESeq2 cross-run evidence report</title>
<style>{style}</style></head><body>
<h1>DESeq2 cross-run evidence report</h1>
<p>Run A: <strong>{_html(aligned["run_a"])}</strong><br>
Run B: <strong>{_html(aligned["run_b"])}</strong></p>
<p class="muted">This report is descriptive and offline. Every gene was read from a
successful, SHA-256-verified DESeq2 result artifact. Other manifest values below
are recorded provenance, not separately rehashed by this report.</p>
<h2>Comparison rules and coverage</h2>
<p>Significant means padj ≤ {_html(aligned["padj_max"])} and
|log2FC| ≥ {_html(aligned["min_abs_log2fc"])} within each run.
Gene identifiers are matched exactly and case-sensitively.
A gene missing from one run is not assigned a non-significant result there.</p>
<ul>
<li>Run A genes: {_html(counts["genes_in_a"])}</li>
<li>Run B genes: {_html(counts["genes_in_b"])}</li>
<li>Both runs tested: {_html(counts["common_tested_genes"])}</li>
<li>Only A tested: {_html(counts["a_only_tested"])}</li>
<li>Only B tested: {_html(counts["b_only_tested"])}</li>
<li>Significant in both: {_html(counts["both_significant"])}</li>
<li>Significant only in A (shared genes): {_html(counts["only_a_significant"])}</li>
<li>Significant only in B (shared genes): {_html(counts["only_b_significant"])}</li>
</ul>
<h2>Interpretation warnings</h2><ul>{warning_markup}</ul>
<h2>Recorded run parameters</h2>
{_table(("Parameter", "Run A", "Run B"), param_rows)}
<h2>Input provenance</h2>
{_table(("Input role", "Run A SHA-256", "Run B SHA-256", "Identical bytes?"), input_rows)}
<h2>Workflow and runtime identity</h2>
<p>Run A workflow: {_html(left.get("workflow_id"))};
Run B workflow: {_html(right.get("workflow_id"))}.</p>
{_table(("Component", "Run A", "Run B"), environment_rows)}
<h2>Result artifact provenance</h2>
{_table(("Artifact", "Run A SHA-256", "Run B SHA-256"), artifact_rows)}
<h2>Aligned gene details</h2>
<p class="muted">Showing the first {_html(len(gene_rows))} of
 {_html(len(genes))} union genes sorted by exact gene ID. This is a bounded
 preview, not a random or representative sample. Download the full-union CSV
 from the workbench for all aligned genes and source metadata.</p>
<div class="scroll">
{_table((
    "Gene ID", "Category", "A baseMean", "B baseMean",
    "A log2FC", "B log2FC", "A padj", "B padj",
    "A significant?", "B significant?"
), gene_rows)}
</div>
<p class="muted">Missing cells mean the gene was absent from a run or the statistic was
not available. Missing/NA data must not be interpreted as evidence of no effect.
Recorded inputs and environment identity should be reviewed before
interpreting differences. This is not a clinical or biological validation.</p>
</body></html>"""
