# Reproducibility contract

## Per-run record

Each run receives an opaque random ID and a file-backed state record at `runs/<run_id>/run.json`. The record contains workflow ID, the validated parameter snapshot, status transitions, timestamps, exit code, a bounded error summary, artifact count, and whether log output was truncated. The snapshot records relative input filenames and analysis parameters, never submitted absolute input paths. Existing records created before this field was added are returned with an empty parameter object.

## Environment dependencies

Python runtime and development dependencies are resolved in the committed `uv.lock`. CI checks that the lock remains consistent with `pyproject.toml` and installs with `uv sync --locked --extra dev`; dependency changes must update both files. The manual end-to-end gate pins R 4.4.3, Bioconductor 3.20, and DESeq2 1.46.0, and fails if the installed DESeq2 version differs. The first clean-environment run using this pinned configuration passed on 2026-10-24; see the [durable verification record](verification/2026-10-24-deseq2-synthetic-e2e.md).

## Input and output provenance

- Input files are selected by relative path beneath `BIOAI_INPUT_ROOT`; symlinks resolving outside that root are rejected.
- The DESeq2 workflow records input fingerprints, selected parameters, R and DESeq2 versions, and output fingerprints in `run_manifest.tsv`.
- The runtime emits `outputs/artifact_manifest.json` with relative artifact names, byte sizes, and SHA-256 checksums.
- Artifact manifests intentionally omit absolute paths and do not hash themselves.
- Raw input files are not copied into the run directory by the runtime.

## Execution evidence

A successful API run requires exit code zero and all four expected DESeq2 outputs. Missing outputs convert the run to failure even if the child process exits zero. Failure logs are bounded by `BIOAI_MAX_LOG_BYTES`; runtime is bounded by `BIOAI_MAX_RUN_SECONDS`.

The verified synthetic acceptance run checks the CLI's valid and invalid input paths, API result statistics and plots, gene details/comparisons, standalone report, artifact downloads and SHA-256 values, plus a rerun from immutable input/workflow snapshots. Its run URL, versions, checksums, and limitations are preserved in the [verification record](verification/2026-10-24-deseq2-synthetic-e2e.md); GitHub's downloadable evidence artifact has a 14-day retention window.

## Known limits

The initial state store is local and single-process, not a distributed job queue. The R analysis is not fully hermetic: CI pins the R version, Bioconductor release, and DESeq2 version, and captures `session_info.txt`, but does not yet commit a lockfile for every transitive R package. The clean-environment synthetic integration gate has passed; any change to the pinned baseline or workflow should rerun it. Checksums prove byte identity, not scientific validity.
