# Reproducibility contract

## Per-run record

Each run receives an opaque random ID and a file-backed state record at \`runs/<run_id>/run.json\`. The record contains workflow ID, status transitions, timestamps, exit code, a bounded error summary, artifact count, and whether log output was truncated. It does not store the submitted absolute input paths.

## Input and output provenance

- Input files are selected by relative path beneath \`BIOAI_INPUT_ROOT\`; symlinks resolving outside that root are rejected.
- The DESeq2 workflow records input fingerprints, selected parameters, R and DESeq2 versions, and output fingerprints in \`run_manifest.tsv\`.
- The runtime emits \`outputs/artifact_manifest.json\` with relative artifact names, byte sizes, and SHA-256 checksums.
- Artifact manifests intentionally omit absolute paths and do not hash themselves.
- Raw input files are not copied into the run directory by the runtime.

## Execution evidence

A successful API run requires exit code zero and all four expected DESeq2 outputs. Missing outputs convert the run to failure even if the child process exits zero. Failure logs are bounded by \`BIOAI_MAX_LOG_BYTES\`; runtime is bounded by \`BIOAI_MAX_RUN_SECONDS\`.

## Known limits

The initial state store is local and single-process, not a distributed job queue. The R analysis is not fully hermetic: package installation and the host R library remain external prerequisites until a pinned environment is added. Reproducibility claims require a successful clean-environment integration run and a recorded R/DESeq2 version pair. Checksums prove byte identity, not scientific validity.
