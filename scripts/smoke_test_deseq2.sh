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

expect_failure() {
  local label="$1"
  local expected_message="$2"
  local metadata_path="$3"
  local counts_path="$4"
  local log_path="$TMP_BASE/$label.log"

  if run_workflow "$metadata_path" "$counts_path" "$TMP_BASE/$label-output" >"$log_path" 2>&1; then
    echo "Expected invalid case '$label' to fail, but the workflow succeeded." >&2
    exit 1
  fi
  grep -Fq "$expected_message" "$log_path" || {
    echo "Invalid case '$label' did not produce the expected actionable error." >&2
    exit 1
  }
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

if grep -Fq "$TMP_BASE" "$OUTPUT_DIR/run_manifest.tsv"; then
  echo "Run manifest unexpectedly contains a local absolute path." >&2
  exit 1
fi

# Invalid metadata: sample IDs do not match the count matrix.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
metadata <- utils::read.csv(args[[1]], stringsAsFactors = FALSE)
metadata$sample_id[[1]] <- "intentionally_missing_sample"
utils::write.csv(metadata, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/metadata.csv" "$INPUT_DIR/metadata-mismatch.csv"
expect_failure "mismatched-samples" "must match exactly" \
  "$INPUT_DIR/metadata-mismatch.csv" "$INPUT_DIR/counts.csv"

# Invalid metadata: the selected condition column is missing.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
metadata <- utils::read.csv(args[[1]], stringsAsFactors = FALSE)
metadata$condition <- NULL
utils::write.csv(metadata, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/metadata.csv" "$INPUT_DIR/metadata-missing-condition.csv"
expect_failure "missing-condition" "Metadata CSV must include columns" \
  "$INPUT_DIR/metadata-missing-condition.csv" "$INPUT_DIR/counts.csv"

# Invalid counts: negative values.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
counts <- utils::read.csv(args[[1]], check.names = FALSE)
counts[[2]][[1]] <- -1
utils::write.csv(counts, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/counts.csv" "$INPUT_DIR/counts-negative.csv"
expect_failure "negative-counts" "non-negative integers" \
  "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts-negative.csv"

# Invalid counts: non-integer values.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
counts <- utils::read.csv(args[[1]], check.names = FALSE)
counts[[2]][[1]] <- 1.5
utils::write.csv(counts, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/counts.csv" "$INPUT_DIR/counts-noninteger.csv"
expect_failure "noninteger-counts" "non-negative integers" \
  "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts-noninteger.csv"

# Invalid counts: duplicate gene IDs.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
counts <- utils::read.csv(args[[1]], check.names = FALSE)
counts$gene_id[[2]] <- counts$gene_id[[1]]
utils::write.csv(counts, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/counts.csv" "$INPUT_DIR/counts-duplicate-gene.csv"
expect_failure "duplicate-gene-ids" "unique, non-empty gene IDs" \
  "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts-duplicate-gene.csv"

# Invalid metadata: one group has fewer than two replicates.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
metadata <- utils::read.csv(args[[1]], stringsAsFactors = FALSE)
metadata$condition <- c("control", rep("treatment", nrow(metadata) - 1L))
utils::write.csv(metadata, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/metadata.csv" "$INPUT_DIR/metadata-low-replicate.csv"
expect_failure "low-replicate-count" "At least two samples per condition" \
  "$INPUT_DIR/metadata-low-replicate.csv" "$INPUT_DIR/counts.csv"

# Invalid counts: values outside R's integer storage range.
Rscript -e '
args <- commandArgs(trailingOnly = TRUE)
counts <- utils::read.csv(args[[1]], check.names = FALSE)
counts[[2]][[1]] <- .Machine$integer.max + 1000
utils::write.csv(counts, args[[2]], row.names = FALSE, quote = FALSE)
' "$INPUT_DIR/counts.csv" "$INPUT_DIR/counts-overflow.csv"
expect_failure "integer-overflow" "supported integer range" \
  "$INPUT_DIR/metadata.csv" "$INPUT_DIR/counts-overflow.csv"

echo "DESeq2 smoke test passed: valid input, expected artifacts, path-free manifest, and seven invalid-input cases."
