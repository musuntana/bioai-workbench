# BioAI Workbench

**A local-first, reproducible workbench for bioinformatics workflows, with optional AI-assisted planning.**

BioAI Workbench aims to turn established R/Python bioinformatics tools into workflows that are easier to run, inspect, reproduce, and extend. It prioritizes reliable execution and traceable artifacts over autonomous analysis claims.

> **Project status:** Early scaffold. The repository currently contains no imported company scripts, private datasets, or production credentials. The first workflow will be built against synthetic data.

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
