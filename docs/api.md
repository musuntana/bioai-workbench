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


## Local trust boundary

The API currently has no authentication and the file-backed run store is single-process. Bind to localhost only. Do not use this service as a shared or public endpoint. The runtime does not claim to be a hardened sandbox.


## Download an artifact

After a run succeeds, download an artifact by its manifest-listed relative path. Only files listed in that run's `artifact_manifest.json` are served; unlisted files and paths outside the output directory return HTTP 404.

```bash
curl -fOJ "http://127.0.0.1:8000/api/v1/runs/<run_id>/artifacts/differential_expression_all.csv"
```

The endpoint recomputes the file's SHA-256 before serving it and compares it with the manifest. A missing or mismatched checksum returns HTTP 409 instead of serving altered content. Successful downloads include the verified digest in `X-Artifact-SHA256`. This endpoint is local-only and does not add authentication or make the service suitable for untrusted networks.
