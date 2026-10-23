#!/usr/bin/env Rscript

# Generates synthetic counts only. No external or real research data is used.
args <- commandArgs(trailingOnly = TRUE)
outdir <- if (length(args) >= 1L) args[[1L]] else "examples/deseq2/generated"

if (!dir.exists(outdir) && !dir.create(outdir, recursive = TRUE, showWarnings = FALSE)) {
  stop("Could not create output directory: ", outdir, call. = FALSE)
}

set.seed(20261023)
gene_ids <- sprintf("gene_%03d", seq_len(100L))
sample_ids <- c(paste0("control_", seq_len(3L)), paste0("treatment_", seq_len(3L)))
base_means <- exp(stats::runif(length(gene_ids), min = log(60), max = log(900)))

counts <- vapply(seq_along(sample_ids), function(index) {
  means <- base_means
  if (index > 3L) {
    means[seq_len(10L)] <- means[seq_len(10L)] * 2.5
  }
  stats::rnbinom(length(gene_ids), mu = means, size = 10)
}, numeric(length(gene_ids)))

rownames(counts) <- gene_ids
colnames(counts) <- sample_ids
counts_table <- data.frame(gene_id = gene_ids, counts, check.names = FALSE)
metadata <- data.frame(
  sample_id = sample_ids,
  condition = c(rep("control", 3L), rep("treatment", 3L)),
  stringsAsFactors = FALSE
)

utils::write.csv(counts_table, file.path(outdir, "counts.csv"), row.names = FALSE, quote = FALSE)
utils::write.csv(metadata, file.path(outdir, "metadata.csv"), row.names = FALSE, quote = FALSE)
message("Synthetic count matrix and metadata written to: ", normalizePath(outdir))
