# BioAI Workbench

**A local-first, reproducible workbench for bioinformatics workflows, with optional AI-assisted planning.**

BioAI Workbench wraps established R/Python tools in a thin API and UI with validated inputs, observable runs, bounded execution, and checksummed artifacts. The first workflow is a two-condition differential-expression analysis using DESeq2.

> **Project status:** the product skeleton and DESeq2 adapter are implemented on the current development branch. The clean-environment DESeq2 integration test remains pending. Do not treat the current skeleton as a hardened multi-user service or a clinically validated system.

## Product principles

- **Reuse mature tools:** integrate established statistical packages and workflow engines rather than reimplementing their methods.
- **Deterministic execution first:** workflows run without an LLM.
- **Agent proposes; runtime validates:** planning can select registered workflow IDs only; it cannot submit arbitrary shell commands.
- **Reproducibility by default:** record parameters, tool versions, input fingerprints, run state, and output checksums.
- **Local-first privacy:** raw research data stays in the configured local input root and is not sent to external models by default.
- **Clean public provenance:** use original, authorized, or license-compatible code and synthetic/publicly licensed examples only.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), R, and a Bioconductor-compatible installation of DESeq2.

### 1. Install the Python environment

```bash
uv sync --locked --extra dev
```

### 2. Install DESeq2

Run in R:

```r
if (!requireNamespace("BiocManager", quietly = TRUE)) {
  install.packages("BiocManager")
}
BiocManager::install("DESeq2")
```

### 3. Generate synthetic input files

```bash
mkdir -p data/inputs/demo
Rscript examples/deseq2/generate_synthetic_data.R data/inputs/demo
```

The generated fixture is synthetic. The API accepts only relative CSV paths beneath `BIOAI_INPUT_ROOT`, which defaults to `data/inputs/`. You can also upload CSVs from the web UI; uploaded files are stored locally and are not sent to an external model. Use **Preview selected CSVs** to inspect the first rows of both files, then use **Validate inputs** to catch common schema and sample-matching errors before submitting the analysis.

### 4. Start the local workbench

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Use `demo/counts.csv` and `demo/metadata.csv`, then confirm the condition column, reference, and contrast.

The API docs are available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The API is unauthenticated and intended for localhost only; do not expose it to an untrusted network. Terminal runs can be rerun from their immutable, SHA-256-verified input and workflow snapshots; reruns do not silently pick up changed files from the input directory. After a successful run, the workbench displays the gene table, volcano plot, and MA plot. Search/sort/filter controls operate on the verified result artifact; the original CSV remains downloadable.

### CLI compatibility

The original CLI entrypoint remains available:

```bash
Rscript scripts/run_deseq2.R \
  --counts data/inputs/demo/counts.csv \
  --metadata data/inputs/demo/metadata.csv \
  --condition condition \
  --reference control \
  --contrast treatment \
  --outdir /tmp/bioai-output
```

The canonical R implementation now lives in `workflows/deseq2/run.R`.

## API surface

- `GET /healthz` — process health.
- `GET /api/v1/workflows` — registered workflow metadata.
- `GET /api/v1/inputs` — list available CSV inputs using relative paths and sizes.
- `GET /api/v1/inputs/preview?filename=...` — preview up to 20 rows from a local CSV without exposing host paths.
- `PUT /api/v1/inputs/{filename}` — upload a validated UTF-8 CSV (25 MiB limit); existing files are never overwritten.
- `POST /api/v1/inputs/validate` — preflight-check DESeq2 counts/metadata schemas, sample IDs, count values, and condition replication before a run.
- `POST /api/v1/runs` — validate and queue a registered workflow request.
- `POST /api/v1/runs/{run_id}/rerun` — rerun a terminal run from its verified input/workflow snapshots, recording lineage and enforcing a five-attempt family cap.
- `GET /api/v1/runs` — browse run history with pagination and status filtering.
- `GET /api/v1/runs/{run_id}` — state and exit information.
- `GET /api/v1/runs/{run_id}/logs` — bounded execution log.
- `GET /api/v1/runs/{run_id}/artifacts` — relative artifact names, byte sizes, and SHA-256 checksums.
- `GET /api/v1/runs/{run_id}/artifacts/{artifact_path}` — download a manifest-listed artifact.
- `GET /api/v1/runs/{run_id}/results` — preview, search, sort, paginate, and filter the verified DESeq2 result table; returns capped volcano-plot points.
- `GET /api/v1/runs/{run_id}/results/export` — download all rows matching the table filters as a CSV, preserving the original result values.

See [the API guide](docs/api.md) and [reproducibility contract](docs/reproducibility.md).

## Repository map

```text
app/                         FastAPI API and static local UI
agent/                       Provider-neutral, deterministic planning contract
workflows/deseq2/             Canonical DESeq2 workflow and manifest
skills/differential-expression/ Task contract for differential expression
runtime/                     Run state, bounded process execution, resource limits
artifacts/                   Artifact manifest and checksum helpers
tests/unit/                  Pure component tests
tests/integration/           API contract tests
tests/workflow/              Workflow registration and contract tests
examples/deseq2/              Synthetic fixture generator
docs/                         Architecture, decisions, API, reproducibility
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BIOAI_INPUT_ROOT` | `data/inputs/` | Allowed root for input CSV files |
| `BIOAI_RUNS_DIR` | `runs/` | Local run records, logs, and outputs |
| `BIOAI_MAX_RUN_SECONDS` | `1800` | Per-run wall-clock limit |
| `BIOAI_MAX_LOG_BYTES` | `2097152` | Maximum bytes retained per run log |
| `BIOAI_MAX_CONCURRENT_RUNS` | `2` | Maximum concurrent workflow processes |

Relative configuration paths are resolved from the repository root. The runtime rejects absolute input paths, path traversal, and symlinks that resolve outside the input root. Generated run files are ignored by Git.

## Tests and local safety checks

Python dependencies are pinned in `uv.lock`. Use `uv lock` after changing `pyproject.toml`, commit both files together, and run `uv lock --check` before opening a pull request. The R/Bioconductor environment remains a separate reproducibility task.

```bash
uv run pytest
python3 -m unittest discover -s tests -v
python3 scripts/audit_public_release.py
bash scripts/smoke_test_deseq2.sh
bash scripts/smoke_test_api.sh
```

The two smoke-test scripts require R and DESeq2; the API smoke test also requires the Python environment installed by `uv sync --locked --extra dev` and `curl`. It starts the API on loopback, uses synthetic data, waits for a successful run, downloads all four expected outputs, and verifies each downloaded SHA-256 against both the artifact manifest and response header. It then validates the results API against the downloaded DESeq2 CSV, checks the exact-gene view and standalone report, and performs a second real DESeq2 run using verified immutable snapshots. It requires identical result CSV bytes, matching input and workflow hashes, and consistent gene-level/gene-set comparisons. A deterministic Python evidence validator records each check in `acceptance-matrix.json`. This second execution is deliberately limited to the **manual opt-in** integration gate, not ordinary PR CI. Set `BIOAI_SMOKE_KEEP_ARTIFACTS=1` to retain a local evidence bundle containing the run status/logs, downloaded outputs, and a JSON summary with the R/DESeq2 versions and artifact hashes, plus the evidence files and `acceptance-matrix.json`. A successful normal PR check does **not** count as this real-environment acceptance. The real run must produce a successful integration-job URL and a passing acceptance matrix. These commands are verification tools, not scientific or clinical validation. The clean-environment integration run remains pending until a real run completes successfully. To run it on GitHub, open Actions → Targeted quality gates → Run workflow, enable `run_r_integration`, and start the workflow; the opt-in job executes both CLI and API paths and uploads the synthetic evidence bundle.

## Architecture direction

- **Analysis:** established tools such as DESeq2 and Seurat.
- **Workflow:** registered workflow contracts first; evaluate Snakemake or Nextflow when multi-step DAGs justify them.
- **Runtime:** bounded local subprocesses, observable state, structured logs, and artifact checksums.
- **Agent:** optional planning over allowlisted workflow IDs, with explicit user approval.
- **Future deployment:** add stronger process/container isolation and multi-user authentication before offering a shared service.

Biomni, ClawBio, Snakemake, and Nextflow remain evaluation candidates rather than mandatory runtime dependencies. See [architecture](docs/architecture.md), [roadmap](docs/roadmap.md), and [source migration policy](docs/source-code-migration.md).

## Public-release rule

Do not copy scripts from a workplace or private repository into this public repository merely by renaming variables or removing company names. Confirm ownership and redistribution rights, classify sensitive dependencies, define a clean interface, and use synthetic tests. If publication rights are uncertain, implement the generic behavior independently.

This project is not a clinical diagnostic system and has not been validated for clinical decisions.
