---
id: differential-expression
name: Differential expression
version: 0.1.0
workflow_id: deseq2-basic
---

# Differential-expression skill

## Purpose

Prepare a validated request for the registered DESeq2 two-condition workflow. This skill describes the task contract; it does not execute code and does not authorize an LLM to choose arbitrary shell commands.

## Required inputs

- A raw integer count matrix CSV with a unique \`gene_id\` column followed by sample columns.
- A metadata CSV with unique \`sample_id\` values and a selected condition column.
- The exact condition column name, reference level, and contrast level.
- At least two samples per condition for this starter workflow.

Input file names must be relative to \`BIOAI_INPUT_ROOT\`. Never request or transmit raw research data to an external model.

## Planning rules

1. Confirm the user intends a two-condition differential-expression analysis.
2. Validate that counts and metadata files are available within the configured input root.
3. Confirm reference and contrast labels match the metadata values exactly.
4. Do not guess missing sample annotations, infer experimental design from filenames, or silently drop samples.
5. Propose only workflow ID \`deseq2-basic\` and the documented parameters.
6. Require an explicit user action before starting the workflow.
7. If inputs are invalid or the design is not supported, stop and ask for correction rather than improvising.

## Outputs

The workflow produces all-gene and significant-result CSVs, a run manifest, session information, and a SHA-256 artifact manifest. Results are research outputs, not clinical interpretations.
