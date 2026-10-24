"""Validate a captured *real* R/DESeq2 API smoke-test evidence bundle.

Standard-library only. This validator reads artifacts produced by a real local
or manual GitHub Actions R/DESeq2 run; it never creates proof by itself.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

# Support both `python scripts/verify_deseq2_smoke.py` and pytest imports.
if __package__:
    from .verify_evidence_rows import EvidenceRowsError, verify_result_rows
else:
    from verify_evidence_rows import EvidenceRowsError, verify_result_rows


class AcceptanceError(ValueError):
    """An observable scientific workflow acceptance condition failed."""


def _require(condition: bool, explanation: str) -> None:
    if not condition:
        raise AcceptanceError(explanation)


def _json(bundle: Path, name: str) -> dict[str, Any]:
    data = json.loads((bundle / name).read_text(encoding="utf-8"))
    _require(isinstance(data, dict), f"{name} is not a JSON object")
    return data


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _match_number(left: Any, right: Any) -> bool:
    a, b = _number(left), _number(right)
    return (a is None and b is None) or (
        a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    )


def _verify_report_evidence(
    bundle: Path,
    original: dict[str, Any],
    rerun: dict[str, Any],
    source: dict[str, dict[str, str]],
    original_sha256: str,
) -> None:
    """Cross-check new user-facing report/export paths against actual DESeq2 CSV bytes."""
    wanted = ("gene_001", "gene_050")
    preview = _json(bundle, "batch-results.json")
    _require(preview.get("run_id") == original["run_id"], "batch preview run mismatch")
    gf = preview.get("gene_filter") or {}
    _require(gf.get("requested") == 3, "batch filter requested count mismatch")
    _require(gf.get("found") == 2, "batch filter found count mismatch")
    _require(gf.get("missing") == ["missing_gene_xyz"], "batch filter missing IDs mismatch")
    _require(preview.get("filtered_genes") == 2, "batch filter result count mismatch")
    preview_rows = preview.get("rows") or []
    _require(
        sorted(row.get("gene_id") for row in preview_rows) == list(wanted),
        "batch preview gene IDs mismatch",
    )
    for row in preview_rows:
        ref = source[row["gene_id"]]
        for column in ("baseMean", "log2FoldChange", "padj"):
            _require(
                _match_number(row.get(column), ref[column]),
                f"batch preview {column} differs from verified DESeq2 CSV",
            )

    with (bundle / "batch-export.csv").open(encoding="utf-8-sig", newline="") as stream:
        exported = list(csv.DictReader(stream))
    _require(
        sorted(row["gene_id"] for row in exported) == list(wanted),
        "batch CSV exported different gene IDs than preview",
    )
    for row in exported:
        for column in ("baseMean", "log2FoldChange", "padj"):
            _require(
                _match_number(row[column], source[row["gene_id"]][column]),
                f"batch CSV {column} differs from verified DESeq2 CSV",
            )

    selected_report = (bundle / "batch-report.html").read_text(encoding="utf-8")
    for evidence, explanation in (
        ("DESeq2 gene-list report", "Selected-gene HTML report title missing"),
        (original["run_id"], "Selected-gene report run ID mismatch"),
        (original_sha256, "Selected-gene report result checksum missing"),
        ("Requested IDs: <strong>3</strong>", "Selected-gene report requested count mismatch"),
        ("Found in run: <strong>2</strong>", "Selected-gene report found count mismatch"),
        ("<td>gene_001</td>", "Selected-gene report gene_001 missing"),
        ("<td>gene_050</td>", "Selected-gene report gene_050 missing"),
        ("<td>missing_gene_xyz</td>", "Selected-gene report missing-gene evidence missing"),
    ):
        _require(evidence in selected_report, explanation)
    _require("<script" not in selected_report.lower(), "Selected-gene report contains executable script")

    with (bundle / "aligned-gene-comparison.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        aligned_rows = list(csv.DictReader(stream))
    _require(
        sorted(row["gene_id"] for row in aligned_rows) == sorted(source),
        "Full-union CSV aligned gene IDs differ from verified source",
    )
    for row in aligned_rows:
        identifier = row["gene_id"]
        expected = source[identifier]
        for stem, expected_id, expected_status in (
            ("a", original["run_id"], original),
            ("b", rerun["run_id"], rerun),
        ):
            _require(row[f"run_{stem}_id"] == expected_id, "Full-union CSV run IDs mismatch")
            for role in ("counts", "metadata"):
                _require(
                    row[f"run_{stem}_{role}_sha256"]
                    == expected_status["input_provenance"][role]["sha256"],
                    f"Full-union CSV {role} hash mismatch",
                )
            _require(
                row[f"run_{stem}_result_sha256"] == original_sha256,
                "Full-union CSV result checksum mismatch",
            )
            for column, source_col in (
                ("base_mean", "baseMean"),
                ("log2fc", "log2FoldChange"),
                ("padj", "padj"),
            ):
                _require(
                    _match_number(row[f"run_{stem}_{column}"], expected[source_col]),
                    f"Full-union CSV {source_col} mismatch",
                )
        padj, lfc = _number(expected["padj"]), _number(expected["log2FoldChange"])
        significant = padj is not None and lfc is not None and padj <= 0.05 and abs(lfc) >= 1
        _require(
            row["category"] == ("both" if significant else "neither_significant"),
            "Full-union CSV significance membership mismatch",
        )
        _require(
            row["run_a_significant"] == str(significant)
            and row["run_b_significant"] == str(significant),
            "Full-union CSV per-run significance mismatch",
        )
        _require(
            _match_number(row["padj_max"], 0.05) and _match_number(row["min_abs_log2fc"], 1),
            "Full-union CSV comparison thresholds mismatch",
        )

    comparison_report = (bundle / "cross-run-report.html").read_text(encoding="utf-8")
    for evidence, explanation in (
        ("DESeq2 cross-run evidence report", "Cross-run report title missing"),
        (original["run_id"], "Cross-run report original ID missing"),
        (rerun["run_id"], "Cross-run report rerun ID missing"),
        (original_sha256, "Cross-run report result checksum missing"),
        (f"Both runs tested: {len(source)}", "Cross-run report tested universe mismatch"),
        ("Changes in significance categories", "Cross-run report interpretation warning missing"),
    ):
        _require(evidence in comparison_report, explanation)
    for role in ("counts", "metadata"):
        _require(
            original["input_provenance"][role]["sha256"] in comparison_report,
            f"cross-run report {role} input hash missing",
        )
    _require("<script" not in comparison_report.lower(), "Cross-run report contains executable script")


def verify_bundle(bundle: Path) -> dict[str, Any]:
    """Check full data → API → report → immutable rerun → comparisons."""
    original = _json(bundle, "run-status.json")
    rerun = _json(bundle, "rerun-status.json")
    results = _json(bundle, "results.json")
    gene = _json(bundle, "gene-detail.json")
    comparison = _json(bundle, "run-comparison.json")
    single_gene = _json(bundle, "gene-comparison.json")
    gene_sets = _json(bundle, "gene-set-comparison.json")
    originals = _json(bundle, "artifacts.json")
    repeats = _json(bundle, "rerun-artifacts.json")

    _require(original.get("status") == "succeeded", "Original real R/DESeq2 run did not succeed")
    _require(rerun.get("status") == "succeeded", "Snapshot rerun did not succeed")
    _require(rerun.get("parent_run_id") == original.get("run_id"), "Rerun lineage mismatch")
    _require(rerun.get("run_id") != original.get("run_id"), "Rerun must have a new run ID")

    source_path = bundle / "download-differential_expression_all.csv"
    with source_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    _require(len(rows) == 100, "Synthetic source fixture should have exactly 100 genes")
    source = {row["gene_id"]: row for row in rows}
    _require(len(source) == len(rows), "Duplicate gene IDs in real DESeq2 results")

    all_artifacts = {item["path"]: item for item in originals["artifacts"]}
    rerun_artifacts = {item["path"]: item for item in repeats["artifacts"]}
    for name in ("differential_expression_all.csv", "differential_expression_significant.csv"):
        _require(name in all_artifacts and name in rerun_artifacts, f"Missing {name} artifact")
        _require(
            all_artifacts[name]["sha256"] == rerun_artifacts[name]["sha256"],
            f"Real snapshot rerun produced different {name} bytes",
        )
    _require(
        all_artifacts["differential_expression_all.csv"]["sha256"]
        == hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "Verified DESeq2 result CSV no longer matches its artifact manifest",
    )
    rerun_result = bundle / "rerun-differential_expression_all.csv"
    _require(
        rerun_artifacts["differential_expression_all.csv"]["sha256"]
        == hashlib.sha256(rerun_result.read_bytes()).hexdigest(),
        "Downloaded rerun DESeq2 CSV does not match its manifest SHA-256",
    )
    _require(
        rerun_result.read_bytes() == source_path.read_bytes(),
        "Downloaded rerun CSV differs from the original DESeq2 output",
    )

    threshold = results["summary"]["padj_max"]
    minimum_fc = results["summary"]["min_abs_log2fc"]
    significant = sum(
        (_number(row["padj"]) is not None and _number(row["log2FoldChange"]) is not None)
        and _number(row["padj"]) <= threshold
        and abs(_number(row["log2FoldChange"])) >= minimum_fc
        for row in rows
    )
    summary = results["summary"]
    _require(results["run_id"] == original["run_id"], "Results API returned wrong run")
    _require(summary["total_genes"] == len(rows), "Results API total gene count mismatch")
    _require(summary["significant_genes"] == significant, "Results API significance mismatch")
    _require(summary["missing_padj_genes"] == sum(
        _number(row["padj"]) is None for row in rows
    ), "Results API missing adjusted-p count mismatch")
    _require(len(results["rows"]) == len(rows), "Results API did not return all fixture genes")
    # Validate each numeric row and each sampled plot point against the verified CSV.
    try:
        verify_result_rows(rows, results)
    except EvidenceRowsError as exc:
        raise AcceptanceError(str(exc)) from exc
    _require(len(results["plot_points"]) > 0 and len(results["ma_points"]) > 0,
             "Volcano or MA plot returned no real points")
    _require(all(item["gene_id"] in source for item in results["plot_points"]),
             "Volcano plot contains an unknown gene")
    _require(all(item["gene_id"] in source for item in results["ma_points"]),
             "MA plot contains an unknown gene")

    _require(gene["run_id"] == original["run_id"], "Gene detail belongs to wrong run")
    _require(gene["gene"]["gene_id"] == "gene_001", "Gene lookup returned wrong gene")
    for column in ("baseMean", "log2FoldChange", "pvalue", "padj"):
        _require(_match_number(gene["gene"].get(column), source["gene_001"][column]),
                 f"Gene detail {column} differs from verified DESeq2 CSV")

    report = (bundle / "report.html").read_text(encoding="utf-8")
    _require(original["run_id"] in report, "HTML report has wrong run ID")
    _require("DESeq2 analysis report" in report, "Report title missing")
    _require(report.count("<svg") >= 2 and report.count("<circle") > 0,
             "Report lacks real volcano/MA SVG plots")
    _require(f'Total genes: <strong>{len(rows)}</strong>' in report,
             "Report total gene count differs from the real result CSV")
    _require(f'Significant: <strong>{significant}</strong>' in report,
             "Report significant gene count differs from DESeq2-derived preview")
    _require("<script" not in report.lower(), "Report contains an executable script")

    for role in ("counts", "metadata"):
        first = original.get("input_provenance", {}).get(role, {})
        second = rerun.get("input_provenance", {}).get(role, {})
        fingerprint = first.get("sha256")
        _require(isinstance(fingerprint, str) and len(fingerprint) == 64,
                 f"Missing original {role} input SHA-256")
        _require(second.get("sha256") == fingerprint, f"Rerun changed {role} input bytes")
        _require(comparison["inputs"][role]["same_content"] is True,
                 f"Comparison API did not confirm identical {role} bytes")

    for key in ("workflow_sha256", "r_version", "deseq2_version"):
        first = original.get("environment_provenance", {}).get(key)
        second = rerun.get("environment_provenance", {}).get(key)
        _require(bool(first) and first == second, f"Environment identity mismatch: {key}")

    _require(comparison["same_workflow"] is True, "Workflow comparison mismatch")
    _require(single_gene["gene_id"] == "gene_001", "Gene comparison resolved wrong gene")
    for key in ("baseMean", "log2FoldChange", "pvalue", "padj"):
        _require(_match_number(single_gene["a"].get(key), single_gene["b"].get(key)),
                 f"Snapshot rerun changed gene_001 {key}")
    _require(gene_sets["counts"]["only_a_significant"] == 0
             and gene_sets["counts"]["only_b_significant"] == 0,
             "Snapshot rerun changed significant-gene membership")

    _verify_report_evidence(
        bundle, original, rerun, source,
        all_artifacts["differential_expression_all.csv"]["sha256"],
    )

    return {
        "status": "passed",
        "scope": "Real R/DESeq2 synthetic fixture API smoke; not biological or clinical validation",
        "original_run_id": original["run_id"],
        "rerun_id": rerun["run_id"],
        "checks": {
            "rscript_deseq2_execution": "passed",
            "result_schema_and_statistics": "passed",
            "api_volcano_ma_and_gene_detail": "passed",
            "downloaded_csv_sha256": "passed",
            "standalone_report": "passed",
            "rerun_snapshots_and_environment": "passed",
            "rerun_result_byte_equality": "passed",
            "gene_and_gene_set_comparison": "passed",
            "selected_gene_and_cross_run_evidence": "passed",
        },
        "metrics": {
            "total_genes": len(rows),
            "significant_genes_at_preview_threshold": significant,
            "plot_points": len(results["plot_points"]),
            "ma_points": len(results["ma_points"]),
        },
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_directory", type=Path)
    args = parser.parse_args()
    evidence = verify_bundle(args.evidence_directory)
    destination = args.evidence_directory / "acceptance-matrix.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("Real synthetic R/DESeq2 acceptance passed; evidence:", destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
