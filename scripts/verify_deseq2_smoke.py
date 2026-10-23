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
