# Synthetic DESeq2 Example

This directory will contain a small, fully synthetic example for the first workflow. No real research or client data should be added.

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

The example is a software integration fixture, not evidence of biological or clinical performance. The implementation and tests will be added in M1.
