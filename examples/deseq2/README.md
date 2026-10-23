# Synthetic DESeq2 Example

This directory contains the input contract and a generator for a small, fully synthetic example. No real research or client data should be added.

## Input contract

### Counts CSV

- One row per gene/feature.
- First column: unique `gene_id`.
- Remaining columns: sample IDs.
- Values: non-negative integer raw counts.
- Column names must match sample IDs in metadata exactly.

### Metadata CSV

- One row per sample.
- Required column: `sample_id`, unique and non-empty.
- One explicit condition column (for example, `condition`).
- The reference level and contrast level are explicit CLI parameters.
- Every count-matrix sample must have exactly one metadata row.

## Expected outputs

- complete differential-expression result table;
- filtered result table based on a documented threshold;
- input/parameter manifest that records fingerprints rather than raw data;
- R session information and tool versions;
- validation summary and exit status.

The example is a software integration fixture, not evidence of biological or clinical performance. The runner is `scripts/run_deseq2.R`; generate the input fixture with `Rscript examples/deseq2/generate_synthetic_data.R /tmp/bioai-input`. Run the workflow using the command in the root README. Runtime execution and failure-case verification remain pending.
