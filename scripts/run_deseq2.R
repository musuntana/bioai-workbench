#!/usr/bin/env Rscript

# Clean-room, synthetic-data-first DESeq2 workflow.
# Inputs are supplied at runtime; no workplace paths, datasets, or report templates
# are embedded in this script.

usage <- function() {
  paste(
    "Usage:",
    "Rscript scripts/run_deseq2.R",
    "--counts <counts.csv>",
    "--metadata <metadata.csv>",
    "--condition <metadata-column>",
    "--reference <reference-level>",
    "--contrast <contrast-level>",
    "--outdir <output-directory>",
    "[--alpha <0..1>]",
    "",
    "Counts CSV: first column is gene_id; remaining columns are sample IDs.",
    "Metadata CSV: required sample_id column plus the selected condition column.",
    sep = " "
  )
}

parse_args <- function(args) {
  if (length(args) == 0L || length(args) %% 2L != 0L) {
    stop(usage(), call. = FALSE)
  }

  keys <- args[seq.int(1L, length(args), by = 2L)]
  values <- args[seq.int(2L, length(args), by = 2L)]

  if (any(!grepl("^--[a-z][a-z-]*$", keys))) {
    stop("Options must use --kebab-case followed by a value.\n", usage(), call. = FALSE)
  }
  if (anyDuplicated(keys)) {
    stop("Each option may be supplied only once.", call. = FALSE)
  }

  allowed <- c("--counts", "--metadata", "--condition", "--reference",
               "--contrast", "--outdir", "--alpha")
  unknown <- setdiff(keys, allowed)
  if (length(unknown) > 0L) {
    stop("Unknown option(s): ", paste(unknown, collapse = ", "), call. = FALSE)
  }

  options <- as.list(values)
  names(options) <- sub("^--", "", keys)

  required <- c("counts", "metadata", "condition", "reference", "contrast", "outdir")
  missing <- required[!required %in% names(options)]
  if (length(missing) > 0L) {
    stop("Missing required option(s): ",
         paste(paste0("--", missing), collapse = ", "),
         "\n", usage(), call. = FALSE)
  }

  if (identical(options$condition, "sample_id") ||
      !grepl("^[A-Za-z][A-Za-z0-9._]*$", options$condition)) {
    stop("--condition must name a metadata column using letters, digits, dots, or underscores; it cannot be sample_id.",
         call. = FALSE)
  }
  if (!nzchar(options$reference) || !nzchar(options$contrast) ||
      identical(options$reference, options$contrast)) {
    stop("--reference and --contrast must be non-empty and different.", call. = FALSE)
  }

  alpha_text <- if (is.null(options$alpha)) "0.05" else options$alpha
  alpha <- suppressWarnings(as.numeric(alpha_text))
  if (length(alpha) != 1L || is.na(alpha) || !is.finite(alpha) ||
      alpha <= 0 || alpha >= 1) {
    stop("--alpha must be a number strictly between 0 and 1.", call. = FALSE)
  }
  options$alpha <- alpha
  options
}

read_and_validate_inputs <- function(counts_path, metadata_path, condition,
                                     reference, contrast) {
  counts_table <- utils::read.csv(
    counts_path, check.names = FALSE, stringsAsFactors = FALSE
  )
  if (ncol(counts_table) < 3L) {
    stop("Counts CSV must contain gene_id plus at least two sample columns.", call. = FALSE)
  }

  gene_ids <- as.character(counts_table[[1L]])
  if (anyNA(gene_ids) || any(!nzchar(trimws(gene_ids))) || anyDuplicated(gene_ids)) {
    stop("The first counts column must contain unique, non-empty gene IDs.", call. = FALSE)
  }

  count_columns <- counts_table[-1L]
  if (!all(vapply(count_columns, is.numeric, logical(1)))) {
    stop("Every sample column in counts CSV must contain numeric raw counts.", call. = FALSE)
  }

  count_matrix <- as.matrix(count_columns)
  rownames(count_matrix) <- gene_ids
  if (anyNA(count_matrix) || any(!is.finite(count_matrix)) ||
      any(count_matrix < 0) || any(count_matrix != floor(count_matrix))) {
    stop("Counts must be finite, non-negative integers with no missing values.", call. = FALSE)
  }
  if (is.null(colnames(count_matrix)) || anyDuplicated(colnames(count_matrix)) ||
      any(!nzchar(colnames(count_matrix)))) {
    stop("Counts sample column names must be unique and non-empty.", call. = FALSE)
  }
  storage.mode(count_matrix) <- "integer"

  metadata <- utils::read.csv(
    metadata_path, check.names = FALSE, stringsAsFactors = FALSE
  )
  required_columns <- c("sample_id", condition)
  if (!all(required_columns %in% names(metadata))) {
    stop("Metadata CSV must include columns: ",
         paste(required_columns, collapse = " and "), call. = FALSE)
  }

  metadata$sample_id <- as.character(metadata$sample_id)
  if (anyNA(metadata$sample_id) || any(!nzchar(trimws(metadata$sample_id))) ||
      anyDuplicated(metadata$sample_id)) {
    stop("metadata sample_id values must be unique and non-empty.", call. = FALSE)
  }
  if (!setequal(colnames(count_matrix), metadata$sample_id)) {
    stop("Counts sample columns and metadata sample_id values must match exactly.", call. = FALSE)
  }

  metadata <- metadata[match(colnames(count_matrix), metadata$sample_id), , drop = FALSE]
  condition_values <- as.character(metadata[[condition]])
  if (anyNA(condition_values) || any(!condition_values %in% c(reference, contrast))) {
    stop("The selected condition column must contain only the requested reference and contrast levels.",
         call. = FALSE)
  }
  if (sum(condition_values == reference) < 2L || sum(condition_values == contrast) < 2L) {
    stop("At least two samples per condition are required for this example workflow.",
         call. = FALSE)
  }

  metadata[[condition]] <- factor(condition_values, levels = c(reference, contrast))
  rownames(metadata) <- metadata$sample_id
  metadata$sample_id <- NULL

  list(counts = count_matrix, metadata = metadata)
}

write_manifest <- function(outdir, values) {
  manifest <- data.frame(
    key = names(values),
    value = vapply(values, function(value) paste(as.character(value), collapse = ","), character(1)),
    stringsAsFactors = FALSE
  )
  utils::write.table(
    manifest, file = file.path(outdir, "run_manifest.tsv"),
    sep = "\t", quote = FALSE, row.names = FALSE
  )
}

main <- function() {
  options <- parse_args(commandArgs(trailingOnly = TRUE))
  counts_path <- normalizePath(options$counts, mustWork = TRUE)
  metadata_path <- normalizePath(options$metadata, mustWork = TRUE)
  outdir <- path.expand(options$outdir)

  if (!dir.exists(outdir) && !dir.create(outdir, recursive = TRUE, showWarnings = FALSE)) {
    stop("Could not create output directory.", call. = FALSE)
  }
  outdir <- normalizePath(outdir, mustWork = TRUE)

  if (!requireNamespace("DESeq2", quietly = TRUE)) {
    stop("DESeq2 is required. Install it with BiocManager::install('DESeq2').",
         call. = FALSE)
  }

  inputs <- read_and_validate_inputs(
    counts_path, metadata_path, options$condition,
    options$reference, options$contrast
  )

  dds <- DESeq2::DESeqDataSetFromMatrix(
    countData = inputs$counts,
    colData = inputs$metadata,
    design = stats::reformulate(options$condition)
  )
  dds <- DESeq2::DESeq(dds, quiet = TRUE)
  result <- as.data.frame(DESeq2::results(
    dds,
    contrast = c(options$condition, options$contrast, options$reference),
    alpha = options$alpha
  ))
  result$gene_id <- rownames(result)
  result <- result[, c("gene_id", setdiff(names(result), "gene_id")), drop = FALSE]

  significant <- result[!is.na(result$padj) & result$padj < options$alpha, , drop = FALSE]
  all_results_path <- file.path(outdir, "differential_expression_all.csv")
  significant_path <- file.path(outdir, "differential_expression_significant.csv")
  session_path <- file.path(outdir, "session_info.txt")

  utils::write.csv(result, all_results_path, row.names = FALSE, na = "")
  utils::write.csv(significant, significant_path, row.names = FALSE, na = "")
  writeLines(capture.output(utils::sessionInfo()), session_path)

  input_md5 <- tools::md5sum(c(counts_path, metadata_path))
  output_md5 <- tools::md5sum(c(all_results_path, significant_path, session_path))
  manifest_values <- c(
    workflow = "deseq2-basic",
    workflow_version = "0.1.0",
    status = "success",
    timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
    r_version = R.version.string,
    deseq2_version = as.character(utils::packageVersion("DESeq2")),
    condition_column = options$condition,
    reference_level = options$reference,
    contrast_level = options$contrast,
    alpha = options$alpha,
    sample_count = ncol(inputs$counts),
    gene_count = nrow(inputs$counts),
    significant_gene_count = nrow(significant),
    counts_input_md5 = unname(input_md5[[1L]]),
    metadata_input_md5 = unname(input_md5[[2L]]),
    all_results_md5 = unname(output_md5[[1L]]),
    significant_results_md5 = unname(output_md5[[2L]]),
    session_info_md5 = unname(output_md5[[3L]])
  )
  write_manifest(outdir, manifest_values)

  message("DESeq2 workflow completed. Outputs were written to the requested output directory.")
  message("Significant genes at adjusted p-value < ", options$alpha, ": ", nrow(significant))
}

tryCatch(
  main(),
  error = function(error) {
    message("ERROR: ", conditionMessage(error))
    quit(status = 1L)
  }
)
