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

The response includes `runs`, `total` (after status filtering), `limit`, and `offset`. The maximum page size is 100. Valid status filters are `queued`, `running`, `succeeded`, `failed`, and `timed_out`. Invalid filters or pagination values return HTTP 422. Corrupt or incomplete on-disk run records are skipped rather than breaking the history response. The local UI includes the same history list and status filter; selecting a record opens its current status, logs, and artifact checksums.


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

The response includes the current page, total matching rows, result summary, and `plot_points` for the volcano chart. Missing adjusted p-values are returned as `null` and are excluded from the plot. The plot is capped at 5,000 points, preserving significant points when possible; use the full CSV download for complete, unmodified results. This endpoint is a visualization aid, not a substitute for scientific review.
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
