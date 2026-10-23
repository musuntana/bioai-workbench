#!/usr/bin/env bash
set -euo pipefail

# Opt-in local integration smoke test. Requires R and Bioconductor DESeq2.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

Rscript examples/deseq2/generate_synthetic_data.R "${TMPDIR:-/tmp}/bioai-workbench-deseq2-input"
Rscript scripts/run_deseq2.R \
  --counts "${TMPDIR:-/tmp}/bioai-workbench-deseq2-input/counts.csv" \
  --metadata "${TMPDIR:-/tmp}/bioai-workbench-deseq2-input/metadata.csv" \
  --condition condition \
  --reference control \
  --contrast treatment \
  --outdir "${TMPDIR:-/tmp}/bioai-workbench-deseq2-output"

test -s "${TMPDIR:-/tmp}/bioai-workbench-deseq2-output/differential_expression_all.csv"
test -s "${TMPDIR:-/tmp}/bioai-workbench-deseq2-output/differential_expression_significant.csv"
test -s "${TMPDIR:-/tmp}/bioai-workbench-deseq2-output/run_manifest.tsv"
test -s "${TMPDIR:-/tmp}/bioai-workbench-deseq2-output/session_info.txt"

echo "Smoke test passed."
