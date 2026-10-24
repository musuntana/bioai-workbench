# Local API guide

Start the service on loopback:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

## Discover workflows

```bash
curl http://127.0.0.1:8000/api/v1/workflows
```

## Preview an input CSV

Preview a bounded number of rows from an input file under `BIOAI_INPUT_ROOT` before validating or submitting a run:

```bash
curl "http://127.0.0.1:8000/api/v1/inputs/preview?filename=demo/counts.csv&limit=8"
```

`filename` must be a relative CSV path inside the configured input root. `limit` is between 1 and 20 (default 8). The response returns relative path, file size, columns, sample rows, and a `has_more` flag. Files larger than 25 MiB, malformed rows, traversal paths, and files outside the input root are rejected. Preview content may contain research identifiers, so keep the unauthenticated service bound to localhost.
## Preflight count-depth indicators

`POST /api/v1/inputs/validate` returns `valid`, `errors`, `summary`, and a non-blocking `warnings` list. Alongside the existing counts/metadata schema checks, it computes the following from the validated raw counts matrix in the **same CSV scan**:

- `summary.library_sizes`: exact sum of integer counts for each sample column (in original header order).
- `summary.all_zero_genes`: genes with zero counts in every sample.
- `summary.zero_library_samples`: sample columns with no counts; this is a blocking validation error.
- `summary.library_size_ratio`: maximum/minimum positive library-size ratio; `null` when any library is zero or the matrix is invalid.
- `warnings[]`: a descriptive note when the largest raw-count library is at least 5× the smallest. This is only a screening heuristic, **not** a DESeq2 significance or quality threshold.

When counts are malformed, QC totals are withheld rather than presented as a complete profile. The UI shows per-sample raw count totals without inserting sample IDs as HTML. No new Python/R dependency or additional file scan is required. Input QC is not evidence of good biological replication or valid experimental design, and these raw totals are **not DESeq2-normalized counts**.

## Submit a DESeq2 run

Input files must already exist under `BIOAI_INPUT_ROOT` (default `data/inputs/`). Use relative paths; absolute paths, traversal segments, non-CSV extensions, and symlinks escaping the root are rejected.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "workflow_id": "deseq2-basic",
    "counts_file": "demo/counts.csv",
    "metadata_file": "demo/metadata.csv",
    "condition": "condition",
    "reference": "control",
    "contrast": "treatment",
    "alpha": 0.05
  }'
```

The response includes a `run_id` and `status_url`. Poll `GET /api/v1/runs/{run_id}`; the status response includes the validated parameter snapshot (relative input filenames and analysis parameters) used for this run. Inspect `/logs` and `/artifacts` after completion.


## List run history

The history endpoint returns newest-first records and supports bounded pagination and optional status filtering:

```bash
curl "http://127.0.0.1:8000/api/v1/runs?limit=20&offset=0"
curl "http://127.0.0.1:8000/api/v1/runs?status=succeeded&limit=10"
```

The response includes `runs`, `total` (after status filtering), `limit`, and `offset`. The maximum page size is 100. Valid status filters are `queued`, `running`, `succeeded`, `failed`, and `timed_out`. Invalid filters or pagination values return HTTP 422. Corrupt or incomplete on-disk run records are skipped rather than breaking the history response. The local UI includes the same history list and status filter, 20-row previous/next page controls, and an explicit clear-selection action. Exactly two run IDs can be selected for comparison **across history pages**, with the selection visible until cleared; switching the status filter returns to page one without silently discarding chosen runs. Selecting a record opens its current status, logs, and artifact checksums.


## Cancel a queued or active analysis

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/runs/<run_id>/cancel"
```

Cancellation is explicit and idempotent. A queued run transitions to `cancelled` immediately without starting R. An active run transitions to `cancelling` while the current local worker stops its subprocess group; poll `GET /api/v1/runs/{run_id}` for the final `cancelled` status. Repeating cancellation in either state is safe. Successful/failed/timed-out runs return HTTP 409 without altering their results; unknown IDs return HTTP 404. The UI offers **Cancel current run** only when a queued or running task is selected, and asks for confirmation.

No partially generated artifacts are downloadable from a cancelled run. If the runtime restarts while a task is cancelling, startup recovery records the incomplete task as `failed` rather than claiming cancellation completed. This feature is single-process only and is **not** a distributed task cancellation mechanism. To run again from verified snapshots, use the separate explicit rerun endpoint. An early cancellation may have no complete snapshots and cannot be rerun from that task.



To repeat a completed run, call the rerun endpoint. It creates a new run ID and output directory while reusing the source run's immutable `counts.csv`, `metadata.csv`, and `workflow.R` snapshots only after verifying each SHA-256 against the source provenance.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/runs/<run_id>/rerun"
```

Only terminal runs (`succeeded`, `failed`, or `timed_out`) with intact snapshots can be rerun. A run that predates snapshot capture, has missing snapshots, or has a checksum mismatch is rejected with HTTP 409. Unknown runs return HTTP 404. The response contains `parent_run_id` and `attempt`; the run status and history preserve lineage. A lineage is limited to five total attempts. The new run records the same input hashes and workflow hash, but captures its own runtime environment; identical inputs and code do not guarantee identical results across different R/Bioconductor environments.

Reruns use a fresh output directory and never reuse the source run's result files. This is a manual reproducibility action, not an automatic retry policy or a resumable Snakemake DAG.
## Preview differential-expression results

After the run status becomes `succeeded`, query the verified full result table. The endpoint refuses to preview results for unfinished/failed runs and rechecks the artifact SHA-256 before parsing it.

```bash
curl "http://127.0.0.1:8000/api/v1/runs/<run_id>/results?limit=25&offset=0&padj_max=0.05&min_abs_log2fc=1"
curl "http://127.0.0.1:8000/api/v1/runs/<run_id>/results?significant_only=true&sort_by=padj&sort_order=asc"
```

Query parameters:
- `limit` (1–100) and `offset` for table pagination.
- `q` for a case-insensitive gene-ID search.
- `significant_only=true` to show only genes passing both thresholds.
- `padj_max` (default `0.05`) and `min_abs_log2fc` (default `1`) define significance.
- `sort_by`: `padj`, `log2FoldChange`, `baseMean`, or `gene_id`; `sort_order`: `asc` or `desc`.

The response includes the current page, total matching rows, result summary, `plot_points` for the volcano chart, and `ma_points` for an MA plot (log10(mean expression + 1) versus log2 fold change). MA points are deterministically sampled across mean expression when more than 5,000 genes are plottable. Missing adjusted p-values are returned as `null` and are excluded from the plot. The plot is capped at 5,000 points, preserving significant points when possible; use the full CSV download for complete, unmodified results. This endpoint is a visualization aid, not a substitute for scientific review.
## Export filtered gene results

The workbench can download **all genes matching the currently applied search, significance thresholds, and sort order**, not only the visible table page. The export reuses the same run-status, manifest SHA-256, data-schema, and size/row validation as result preview.

```bash
curl -fOJ "http://127.0.0.1:8000/api/v1/runs/<run_id>/results/export?significant_only=true&padj_max=0.05&min_abs_log2fc=1&sort_by=padj&sort_order=asc"
```

Use the same filters as the result preview (`q`, `significant_only`, `padj_max`, `min_abs_log2fc`, `sort_by`, `sort_order`), without `limit` or `offset`. Original CSV columns and their string values are preserved, including NA/empty statistics. A zero-match export contains only the CSV header. Original unfiltered results remain available via the artifact download endpoint.

The export preserves gene identifiers exactly for scientific use. When opening untrusted CSV content in spreadsheet software, beware that spreadsheet applications may interpret cell values starting with formula characters as formulas; inspect imported data and disable formula evaluation when appropriate.
## Download a run-wide or selected-gene HTML report

The standalone report rechecks the successful run's result artifact against its SHA-256 manifest, records workflow parameters and provenance, and does not write into immutable run outputs. By default it summarizes the full run and lists up to 20 significant genes. To create a report for a pasted list, pass up to 100 unique exact gene IDs (case-sensitive); lines, commas, semicolons, or whitespace may separate IDs:

```bash
curl -fOJ --get "http://127.0.0.1:8000/api/v1/runs/<run_id>/report" \
  --data-urlencode "gene_ids=GeneA,GeneB,MissingGene" \
  --data-urlencode "padj_max=0.05" \
  --data-urlencode "min_abs_log2fc=1"
```

A gene-list report includes every requested ID found in the verified results, even when it does not pass the display significance threshold; it reports missing IDs explicitly and scopes both plots to the selected genes. The run-wide total/significant counts remain run-level context. If no non-empty `gene_ids` is supplied, the report retains its run-wide behavior. Search and the UI's significant-only table toggle are not applied to the report; only the explicit gene list and the report significance thresholds are relevant. Lists are bounded to 4,000 characters, 100 unique IDs, and 200 characters per ID. Unfinished runs, invalid thresholds, oversized lists, and checksum mismatches are rejected. The report is HTML for offline viewing/printing, not a clinical interpretation.

## Cross-run evidence report and full gene alignment

Select two successful DESeq2 runs for a descriptive gene-ID comparison. The existing `GET /api/v1/runs/compare/genes` and its CSV export default to **significant genes in the shared tested universe**, with a 100-row JSON preview and full significant-set CSV.

For a **full outer alignment** (all genes present in either run), use:

```bash
curl -fOJ "http://127.0.0.1:8000/api/v1/runs/compare/genes/export?run_a=<run_a>&run_b=<run_b>&scope=all&padj_max=0.05&min_abs_log2fc=1"
curl -fOJ "http://127.0.0.1:8000/api/v1/runs/compare/genes/report?run_a=<run_a>&run_b=<run_b>&padj_max=0.05&min_abs_log2fc=1"
```

Both endpoints verify each run is complete, refuse malformed/duplicate gene IDs and rehash each DESeq2 result against its recorded manifest. The full CSV provides per-run `baseMean`, `log2FC`, `padj`, significance flags, run IDs, contrast/reference labels, input fingerprints, recorded result SHA-256 hashes and the exact comparison thresholds. The category distinguishes `both`, `only_a`, `only_b`, `neither_significant`, `only_a_tested`, and `only_b_tested`. **Absent genes are not treated as non-significant**. For spreadsheet safety, potentially formula-like cells in cross-run CSV exports (including leading whitespace, control characters and BOM before formula operators) are prefixed with an apostrophe. The validated source result artifacts preserve the exact original gene IDs, so use those artifacts when byte-identical identifiers are required. The offline HTML report contains a deterministic *first 100* gene-row preview, all-gene coverage counts, run-level parameters, input hashes and runtime/workflow versions, and an interpretation warning when contrasts or other evidence differ. Use `scope=all` CSV for the complete union; HTML is intentionally bounded.

Differences in within-run significance do *not* constitute a statistical test for changes *between* runs. Changed contrast direction, input bytes, workflow alpha and runtime versions can invalidate straightforward comparisons. No HTML runs scripts; downloads use no-store/nosniff headers and the HTML report uses restrictive CSP. As with other endpoints, this is intended for localhost only and is not clinically validated.

## Local trust boundary

The API currently has no authentication and the file-backed run store is single-process. Bind to localhost only. Do not use this service as a shared or public endpoint. The runtime does not claim to be a hardened sandbox.


## Download an artifact

After a run succeeds, download an artifact by its manifest-listed relative path. Only files listed in that run's `artifact_manifest.json` are served; unlisted files and paths outside the output directory return HTTP 404.

```bash
curl -fOJ "http://127.0.0.1:8000/api/v1/runs/<run_id>/artifacts/differential_expression_all.csv"
```

The server recomputes SHA-256 immediately before sending the file and refuses the download with HTTP 409 if the file no longer matches the manifest. The response includes the verified digest in the `X-Artifact-SHA256` header. This endpoint is local-only and does not add authentication or make the service suitable for untrusted networks.


## Validation errors

Request validation failures return HTTP 422 with a stable, value-free error envelope. `error.code` is `VALIDATION_ERROR`; `error.message` is a general summary; and `error.details` is a list of `field`/`message` entries. Field paths omit transport prefixes such as `body` and `query`. The response does not echo submitted values, which may contain local paths or sensitive identifiers.

Example:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "counts_file",
        "message": "Value error, Input files must be safe relative paths under BIOAI_INPUT_ROOT."
      }
    ]
  }
}
```
