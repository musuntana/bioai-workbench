"""Compare significant-gene sets from two verified DESeq2 result tables."""

from __future__ import annotations

import re
from typing import Any, Callable

from fastapi import HTTPException

RUN_ID = re.compile(r"^[a-f0-9]{32}$")


def compare_gene_sets(
    run_a: str,
    run_b: str,
    load_rows: Callable[[str, float, float], tuple[list[str], list[dict[str, Any]]]],
    *,
    padj_max: float = 0.05,
    min_abs_log2fc: float = 1.0,
) -> dict[str, Any]:
    if not RUN_ID.fullmatch(run_a) or not RUN_ID.fullmatch(run_b):
        raise HTTPException(status_code=422, detail="Invalid run ID.")
    if run_a == run_b:
        raise HTTPException(status_code=422, detail="Select two different runs.")
    _, rows_a = load_rows(run_a, padj_max, min_abs_log2fc)
    _, rows_b = load_rows(run_b, padj_max, min_abs_log2fc)

    def index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for row in rows:
            identifier = row["gene_id"]
            if identifier in indexed:
                raise HTTPException(status_code=409, detail="Duplicate gene IDs prevent comparison.")
            indexed[identifier] = row
        return indexed

    a, b = index(rows_a), index(rows_b)
    shared_universe = set(a) & set(b)
    sig_a = {gene for gene in shared_universe if a[gene]["significant"]}
    sig_b = {gene for gene in shared_universe if b[gene]["significant"]}
    shared = sig_a & sig_b
    only_a = sig_a - sig_b
    only_b = sig_b - sig_a
    categories = {"both": shared, "only_a": only_a, "only_b": only_b}
    entries = [
        {
            "gene_id": gene,
            "category": category,
            "run_a_padj": a[gene].get("padj"),
            "run_b_padj": b[gene].get("padj"),
            "run_a_log2fc": a[gene].get("log2FoldChange"),
            "run_b_log2fc": b[gene].get("log2FoldChange"),
        }
        for category, identifiers in categories.items()
        for gene in sorted(identifiers)
    ]
    return {
        "run_a": run_a,
        "run_b": run_b,
        "padj_max": padj_max,
        "min_abs_log2fc": min_abs_log2fc,
        "counts": {
            "genes_in_a": len(a),
            "genes_in_b": len(b),
            "common_tested_genes": len(shared_universe),
            "a_only_tested": len(set(a) - set(b)),
            "b_only_tested": len(set(b) - set(a)),
            "both_significant": len(shared),
            "only_a_significant": len(only_a),
            "only_b_significant": len(only_b),
        },
        "genes": entries,
        "note": (
            "Significance is recalculated using the same display thresholds for both runs. "
            "Only genes present in both results are compared. Changed significance is not "
            "evidence of a statistically significant between-run difference. Check contrast "
            "direction and input provenance before interpreting fold-change comparisons."
        ),
    }
