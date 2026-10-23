# Architecture

## Goal

Provide a reliable execution workbench for established bioinformatics analyses. The first release proves one workflow end to end before adding a general-purpose agent or a broad UI.

## High-level flow

```text
User request / CLI
       |
       v
Validated workflow specification
       |
       v
Workflow engine (candidate: Snakemake)
       |
       v
Isolated R/Python task
       |
       +--> structured logs
       +--> tool/session versions
       +--> output files
       +--> run manifest and checks
```

An optional agent may later draft a workflow specification, explain errors, or suggest tools. It does not execute arbitrary generated code directly and cannot skip validation.

## Component boundaries

### 1. Workflow specification

A versioned, schema-validated description of the analysis: workflow name/version, input paths, parameter values, output location, and resource requirements. User data paths are runtime inputs, not hard-coded defaults.

### 2. Analysis tools

Use existing statistical packages and domain tools. The first candidate is DESeq2 on synthetic count data. Algorithm implementations are not being recreated.

### 3. Workflow engine

Evaluate Snakemake first because the initial product is a dependency graph of R/Python tasks with reproducible execution. Do not introduce a custom scheduler until requirements demonstrate a gap.

### 4. Execution and provenance

Every run should record:
- run ID and status;
- workflow and code version;
- input file fingerprints (not copies of sensitive inputs);
- parameters and dependency/tool versions;
- timestamps, exit code, and bounded logs;
- output manifest and validation results.

Sensitive input content should not be copied into logs or manifests.

### 5. Agent adapter (later)

Keep the agent behind an interface. Evaluate Biomni and ClawBio with a narrow proof of concept. Any generated plan must map to registered workflow/tool IDs and schema-validated parameters. No arbitrary shell commands by default.

### 6. API/UI (later)

Add an API or UI only after the CLI workflow and provenance contract are stable. The first interface should make it easy to inspect parameters, progress, logs, outputs, and validation status.

## Initial non-goals

- replacing DESeq2, Seurat, Snakemake, or other mature tools;
- autonomous clinical interpretation;
- uploading raw data to external LLMs by default;
- a multi-agent architecture before one workflow is reliable;
- migrating entire private repositories into the public project.
