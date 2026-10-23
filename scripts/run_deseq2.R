#!/usr/bin/env Rscript

# Backwards-compatible CLI entrypoint.
# Canonical implementation lives in workflows/deseq2/run.R.
args <- commandArgs(trailingOnly = FALSE)
script_argument <- grep("^--file=", args, value = TRUE)
if (length(script_argument) != 1L) {
  stop("Could not resolve the compatibility entrypoint path.", call. = FALSE)
}
script_path <- normalizePath(sub("^--file=", "", script_argument[[1L]]), mustWork = TRUE)
project_root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
canonical_script <- file.path(project_root, "workflows", "deseq2", "run.R")
if (!file.exists(canonical_script)) {
  stop("Canonical DESeq2 workflow entrypoint is missing.", call. = FALSE)
}
source(canonical_script, local = globalenv())
