# DESeq2 workflow

This is the first registered, reproducible workflow in BioAI Workbench.

- `run.R` is the canonical clean-room R entrypoint.
- `workflow.yaml` documents the workflow ID, input/parameter contract, output contract, and runtime limits.
- `scripts/run_deseq2.R` remains as a backwards-compatible CLI entrypoint for existing commands and smoke tests.
- The API runtime invokes only the registered `deseq2-basic` workflow; it does not accept arbitrary scripts or shell commands.

## Input contract

Place CSV files under the directory configured by `BIOAI_INPUT_ROOT` (default: `data/inputs/`), then pass relative file names. The count matrix must have a unique `gene_id` first column and at least two sample columns. Metadata must contain unique `sample_id` values and the chosen condition column. The selected reference and contrast each require at least two samples.

## Outputs

The workflow writes the full result table, significant result table, `run_manifest.tsv`, and `session_info.txt`. The runtime adds `artifact_manifest.json` with relative artifact names, byte sizes, and SHA-256 checksums.

Use synthetic data first. This workflow is not a clinical diagnostic system and its results require domain-appropriate review.
