# Architecture

## Goal

Provide a local-first workbench for running established bioinformatics analyses through a validated API and inspectable run records. The first vertical is a reproducible two-condition DESeq2 workflow. The architecture deliberately keeps execution independent from an LLM.

## End-to-end flow

```text
Browser / API client
        |
        v
FastAPI request schema
        |
        v
Registered workflow ID + validated parameters
        |
        v
RunStore creates a queued run record
        |
        v
RunStore atomically claims queued -> running (one in-process worker)
        |
        v
RunManager checks input root and runtime limits
        |
        v
Rscript -> DESeq2 workflow
        |
        +--> bounded run.log
        +--> run state and exit status
        +--> result CSVs + session information
        +--> input/output fingerprints
        +--> SHA-256 artifact manifest
```

An optional agent adapter may propose a workflow plan, but it does not execute generated code. The user submits a validated plan through the same API used by deterministic callers.

## Component boundaries

### 1. API and UI — `app/`

FastAPI exposes health, workflow discovery, run submission, run status, logs, and artifact metadata. The static UI is intentionally small and calls the same HTTP contracts as other clients. API schemas reject unknown fields and absolute/traversal input paths.

### 2. Workflow registry — `app/registry.py`

Only registered workflow IDs are accepted. A request cannot provide an executable path or arbitrary shell command. The initial registry contains `deseq2-basic`; the human-readable contract is in `workflows/deseq2/workflow.yaml`.

### 3. Analysis workflow — `workflows/deseq2/`

The canonical R entrypoint uses DESeq2. It validates raw counts and sample metadata, runs the statistical package, and writes full/significant result tables, session information, and a run manifest. `scripts/run_deseq2.R` remains a compatibility wrapper.

### 4. Agent and skill contract — `agent/`, `skills/`

The deterministic planner maps a small set of task names to the registered DESeq2 workflow and validates proposed parameters. Every plan requires explicit approval. No model provider is required. The skill file documents the task, required inputs, and stop conditions.

### 5. Runtime — `runtime/`

The first runtime is local and file-backed. It creates opaque run IDs, atomically persists state, resolves relative input files under `BIOAI_INPUT_ROOT`, launches subprocesses without a shell, passes a restricted environment, enforces wall-clock and log-size limits, and checks expected output files.

Before touching run logs, snapshots or outputs, an executor claims the queued record under the RunStore process lock. A second dispatch for an already running or terminal run exits without side effects. Exact-snapshot reruns create a new run ID, so this guard does not prevent intentional reruns. This is an **in-process safety boundary only**: it is not a filesystem lease, distributed queue, or fence for multiple Uvicorn workers. Do not share a runs directory between worker processes; add coordinated persistence/ownership before allowing multi-process execution.

This is **not** a hardened sandbox. It is designed for a single trusted local user. Do not expose the unauthenticated API to untrusted networks. Use OS/container isolation before running untrusted workflows.

### 6. Artifacts and provenance — `artifacts/`

The runtime records relative artifact paths, byte sizes, and SHA-256 checksums. The DESeq2 manifest also records tool versions, parameters, and input/output fingerprints. Raw input bytes and the registered R entrypoint are frozen under each run's private `tmp/` snapshot directory for reproducible reruns; these snapshots are not published as output artifacts. Public run-state and artifact metadata omit absolute paths. The run directory itself still contains sensitive local input bytes and should be kept private.

### 7. Tests and quality gates

- `tests/unit/`: state, path-validation, planner, and manifest tests.
- `tests/integration/`: API contract tests without invoking R.
- `tests/workflow/`: registered workflow and compatibility-entrypoint checks.
- `scripts/smoke_test_deseq2.sh`: optional real R/DESeq2 integration test with synthetic fixtures.
- GitHub Actions runs lightweight Python checks for relevant pull requests; the dependency-heavy R integration job remains opt-in.

## Reproducibility and failure behavior

A run is successful only when the child exits zero and all expected artifacts exist. Failure and timeout states include a bounded log and a non-sensitive status summary. Each artifact manifest is generated after the workflow completes and intentionally does not hash itself.

See [the reproducibility contract](reproducibility.md) for details and limits.

## Next architecture decisions

- Evaluate Snakemake/Nextflow when the workflow graph grows beyond one process.
- Add a pinned R/Bioconductor environment and record its tested version pair.
- Introduce a container or OS-level sandbox before accepting untrusted code.
- Add a persistent queue/database only when multi-process deployment or recovery requirements justify it.
- Add a model provider only after measuring a task where planning materially helps; external calls must remain opt-in.
