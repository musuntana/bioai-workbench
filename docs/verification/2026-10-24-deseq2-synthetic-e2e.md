# Synthetic DESeq2 end-to-end verification record

**Status:** PASS  
**Verified at:** 2026-10-24 00:41:29 UTC  
**Verified commit:** `b8920dc402d80a37e9c42b931e0b54df4d758003`  
**Scope:** synthetic software acceptance only; not biological or clinical validation.

## Environment

| Component | Verified version |
|---|---|
| Runner OS | Ubuntu 24.04.5 LTS |
| Python | 3.12 |
| R | 4.4.3 (2025-02-28) |
| Bioconductor | 3.20.0 |
| DESeq2 | 1.46.0 |
| Workflow | `deseq2-basic` 0.1.0 |

The GitHub Actions job installs the pinned R/Bioconductor/DESeq2 baseline and asserts that the installed DESeq2 version is exactly 1.46.0.

## Evidence links

- [Pinned end-to-end GitHub Actions run](https://github.com/musuntana/bioai-workbench/actions/runs/40045705171)
- [Downloadable evidence artifact](https://github.com/musuntana/bioai-workbench/actions/runs/40045705171/artifacts/12541506222)
- [M1 acceptance issue, closed after verification](https://github.com/musuntana/bioai-workbench/issues/1)

The ZIP artifact SHA-256 is `f5404da8975f177dda01dd6de7723ed827dab58a469ca36e1e2355d1dc69de70`. GitHub retains this artifact until 2026-11-07; this Markdown record preserves the key evidence beyond that retention window.

## CLI acceptance

The synthetic fixture generator and DESeq2 CLI completed successfully. The smoke test verified all expected output files, a manifest without absolute input paths, and seven invalid-input cases:

- mismatched sample IDs;
- missing condition metadata;
- negative counts;
- non-integer counts;
- duplicate gene IDs;
- insufficient replicates;
- counts exceeding R's integer range.

## API end-to-end acceptance

The original API run `c9c8fed52f8241aba2d2ca13eaa51a74` and immutable-snapshot rerun `8603ed1709a04b8eabf62554c015beeb` both succeeded using the same verified input and workflow snapshots.

All eight acceptance categories passed:

- Rscript/DESeq2 execution;
- result schema and statistics;
- downloaded CSV SHA-256 checks;
- volcano/MA plot points and gene detail;
- gene and gene-set comparison;
- standalone report;
- immutable-snapshot and environment provenance;
- byte-identical result CSVs across rerun.

The fixture contains 100 genes and 6 samples. The API returned 100 volcano points and 100 MA points; 2 genes met the preview significance thresholds.

## Output fingerprints

| Artifact | Size (bytes) | SHA-256 |
|---|---:|---|
| `differential_expression_all.csv` | 11,916 | `35a89b68d9579ef7f6e07530cb86d92137d79d0a64d8460978427f1ca2223928` |
| `differential_expression_significant.csv` | 310 | `606fbc1930c18b25d40aa10f5fc6b1980a4591e9098519093aa37ea92f9447d0` |
| `run_manifest.tsv` | 597 | `6255d518540db87b6158da36cccd0682777a05fad4310e829071ad697c813f03` |
| `session_info.txt` | 2,123 | `732911a32bf15fb11d742c8ff95c3461de36b89535029228f910a3bcdac935fd` |

The full and significant results CSVs and `session_info.txt` were byte-identical across the original run and rerun. `run_manifest.tsv` intentionally differed because its timestamp is run-specific; both records had the same input hashes, workflow hash, parameters, and runtime versions.

## Limits and follow-up

This evidence demonstrates software behavior for a synthetic fixture, not the correctness of conclusions on real biological samples. It does not establish clinical suitability, production multi-user isolation, or publication rights for private/workplace scripts. The CI pins the top-level R/Bioconductor/DESeq2 baseline and captures `session_info.txt`, but does not yet lock every transitive R package.

Next engineering focus should be the M2 runtime lifecycle: failure/recovery semantics, bounded retry policy only for safe transient failures, and explicit artifact compatibility rules. Do not add Snakemake until a measured multi-step DAG justifies the dependency.
