#!/usr/bin/env bash
set -euo pipefail

# Opt-in local integration smoke test. Requires R and Bioconductor DESeq2.
# Every fixture generated here is synthetic; no private data is read.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/bioai-workbench-deseq2.XXXXXX")"
trap 'rm -rf "$TMP_BASE"' EXIT
INPUT_DIR="$TMP_BASE/input"
OUTPUT_DIR="$TMP_BASE/output"
mkdir -p "$INPUT_DIR"

cd "$ROOT_DIR"
Rscript examples/deseq2/generate_synthetic_data.R "$INPUT_DIR"

run_workflow() {
  local metadata_path="$1"
  local counts_path="$2"
  local output_path="$3"
  Rscript scripts/run_deseq2.R \
    --counts "$counts_path" \
    --metadata "$metadata_path" \
    --condition condition \
    --reference control \
    --contrast treatment \
    --outdir "$output_path"
}

run_workflow "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts.csv" "$OUTPUT_DIR"

for expected in \
  differential_expression_all.csv \
  differential_expression_significant.csv \
  run_manifest.tsv \
  session_info.txt
do
  test -s "$OUTPUT_DIR/$expected" || {
    echo "Missing or empty expected output: $expected" >&2
    exit 1
  }
done

if grep -F "$TMP_BASE" "$OUTPUT_DIR/run_manifest.tsv"; then
  echo "Run manifest unexpectedly contains a local absolute path." >&2
  exit 1
fi

# Negative test 1: sample IDs must match exactly between counts and metadata.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
metadata <- utils::read.csv(args[[1]], stringsAsFactors = FALSE)
metadata$sample_id[[1]] <- "intentionally_missing_sample"
utils::write.csv(metadata, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/metadata.csv" "$INPUT_DIR/metadata-mismatch.csv"

if run_workflow "$INPUT_DIR/metadata-mismatch.csv" "$INPUT_DIR/counts.csv" "$TMP_BASE/invalid-sample-output" >"$TMP_BASE/invalid-sample.log" 2>&1; then
  echo "Expected mismatched sample IDs to fail, but the workflow succeeded." >&2
  exit 1
fi
grep -q "must match exactly" "$TMP_BASE/invalid-sample.log" || {
  echo "Mismatched-sample failure did not produce the expected actionable error." >&2
  exit 1
}

# Negative test 2: negative raw counts must be rejected.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
counts <- utils::read.csv(args[[1]], check.names = FALSE)
counts[[2]][[1]] <- -1
utils::write.csv(counts, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/counts.csv" "$INPUT_DIR/counts-negative.csv"

if run_workflow "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts-negative.csv" "$TMP_BASE/invalid-count-output" >"$TMP_BASE/invalid-count.log" 2>&1; then
  echo "Expected negative counts to fail, but the workflow succeeded." >&2
  exit 1
fi
grep -q "non-negative integers" "$TMP_BASE/invalid-count.log" || {
  echo "Negative-count failure did not produce the expected actionable error." >&2
  exit 1
}

echo "DESeq2 smoke test passed: valid input, expected artifacts, path-free manifest, and two negative cases."
