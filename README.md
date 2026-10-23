# BioAI Workbench

**A local-first, reproducible workbench for bioinformatics workflows, with optional AI-assisted planning.**

BioAI Workbench aims to turn established R/Python bioinformatics tools into workflows that are easier to run, inspect, reproduce, and extend. It prioritizes reliable execution and traceable artifacts over autonomous analysis claims.

> **Project status:** Initial clean-room DESeq2 CLI and synthetic-data generator are present. The local integration smoke test has not yet been executed in a clean R/Bioconductor environment. No company scripts or private datasets have been imported.

## Product principles

- **Reuse mature tools:** integrate established packages and workflow engines instead of reimplementing statistical methods.
- **Deterministic execution first:** a workflow must be runnable and testable without an LLM.
- **AI proposes; the workflow validates:** model output never bypasses input validation, resource limits, or explicit approval gates.
- **Reproducibility by default:** record parameters, tool versions, input fingerprints, logs, and output manifests.
- **Local-first privacy:** raw research data stays in the user's configured environment unless an explicit integration says otherwise.
- **Clean public provenance:** only original, authorized, or license-compatible code and synthetic/publicly licensed examples may enter this repository.

## Initial scope

The first vertical is a small, reproducible differential-expression workflow using **DESeq2** and synthetic count data. The initial milestone is intentionally narrow:

1. validate count-matrix and sample-metadata contracts;
2. run a deterministic R analysis;
3. save result tables, session information, and a machine-readable run manifest;
4. test success and failure paths;
5. make the workflow callable by a future workflow runner or agent adapter.

This is not a clinical diagnostic system and does not claim clinical validity.

## Quick start

Requirements: R plus a Bioconductor-compatible installation of DESeq2.

Install DESeq2 in R if needed:

```r
if (!requireNamespace("BiocManager", quietly = TRUE)) {
  install.packages("BiocManager")
}
BiocManager::install("DESeq2")
```

Generate synthetic input data and run the workflow:

```bash
Rscript examples/deseq2/generate_synthetic_data.R /tmp/bioai-input
Rscript scripts/run_deseq2.R \
  --counts /tmp/bioai-input/counts.csv \
  --metadata /tmp/bioai-input/metadata.csv \
  --condition condition \
  --reference control \
  --contrast treatment \
  --outdir /tmp/bioai-output
```

Optional integration smoke test (requires the same dependencies):

```bash
bash scripts/smoke_test_deseq2.sh
```

The example uses generated synthetic counts only. It has not yet been runtime-verified in this repository; please treat the smoke-test result as pending until it is run successfully.

## Architecture direction

- **Analysis layer:** R/Python tools such as DESeq2, Seurat, and other established packages.
- **Workflow layer:** adopt a mature engine such as Snakemake after validating the first vertical.
- **Execution layer:** isolated jobs, structured logs, resource controls, explicit run states, and artifact manifests.
- **Agent layer (later):** optional planning and tool selection through adapters; all proposed actions are validated before execution.
- **Workbench API/UI (later):** project setup, run history, logs, artifacts, and review/approval steps.

Biomni and ClawBio are candidates for evaluation, not mandatory runtime dependencies. Integration decisions will follow a small proof of concept rather than a wholesale fork.

## Repository map

- `docs/architecture.md` — system boundaries and data flow
- `docs/roadmap.md` — milestones and acceptance criteria
- `docs/source-code-migration.md` — safe migration process for existing scripts
- `SECURITY.md` — reporting and data-handling expectations
- `examples/` — synthetic or explicitly authorized examples only

## Public-release rule

Do not copy scripts from a workplace or private repository into this public repository merely by renaming variables or removing company names. First confirm reuse rights, classify sensitive dependencies, write a clean interface specification, then either refactor code you are authorized to release or implement the generic workflow independently. Never upload real client/patient data, internal endpoints, credentials, private reference databases, or report templates.

## Development status

The repository foundation is being established. A workflow is not considered complete until its inputs, outputs, runtime dependencies, validation behavior, and reproducibility evidence are documented and tested.
