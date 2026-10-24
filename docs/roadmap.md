# Roadmap

## M0 — Safe foundation

- [x] Establish project boundaries and public-release rules.
- [x] Document architecture and source-code migration process.
- [x] Add a synthetic-data DESeq2 example generator and CLI runner.
- [x] Add a local source/config/documentation scanner and unit tests for common accidental-disclosure patterns.
- [x] Add path-filtered pull-request checks and a manual workflow dispatch; no push-triggered CI.

**Exit gate:** public repository contains only reviewed documentation and original/authorized code; no workplace scripts or real research data have been imported.

## M1 — First reproducible workflow

- [x] Define counts/metadata schemas and validation behavior.
- [x] Implement a clean-room DESeq2 CLI workflow using synthetic input data.
- [x] Save full/significant result tables, session information, parameters, and a run manifest with input/output fingerprints.
- [x] Add an opt-in local integration smoke-test script covering valid input, expected artifacts, path-free manifest, mismatched samples, missing condition metadata, negative/non-integer counts, duplicate gene IDs, insufficient replicates, and integer overflow.
- [x] Run the smoke test in a clean R/Bioconductor environment and confirm all positive/negative cases.
- [x] Document and pin a tested R/DESeq2 dependency combination: R 4.4.3, Bioconductor 3.20.0, DESeq2 1.46.0.

**Status:** runtime verification passed on 2026-10-24 using the pinned R 4.4.3 / Bioconductor 3.20 / DESeq2 1.46.0 baseline. The [successful pinned GitHub Actions run](https://github.com/musuntana/bioai-workbench/actions/runs/40045705171) confirms the CLI's valid run and seven invalid-input cases; the API run verified four downloaded artifacts against manifest/response-header SHA-256 values, all eight acceptance categories, and byte-identical result CSVs across a rerun with matching input/workflow fingerprints. See the [durable verification record](verification/2026-10-24-deseq2-synthetic-e2e.md) and [evidence artifact](https://github.com/musuntana/bioai-workbench/actions/runs/40045705171/artifacts/12541506222), retained until 2026-11-07. This exit gate establishes software behavior on synthetic data only, not scientific or clinical validity.

## M1.5 — Open-source product skeleton

- [x] Add a `uv`-managed Python project and FastAPI API/UI.
- [x] Commit `uv.lock` and enforce locked Python dependency resolution in CI.
- [x] Add a registered DESeq2 workflow contract and preserve the legacy CLI entrypoint.
- [x] Add deterministic, approval-gated planning over registered workflow IDs only.
- [x] Add file-backed run state, bounded subprocess execution, timeout/log limits, and relative input-root checks.
- [x] Add artifact manifests with relative paths and SHA-256 checksums.
- [x] Add unit, API integration, and workflow contract tests.
- [x] Add an opt-in API-to-DESeq2 smoke test and manual CI evidence capture using synthetic data.
- [x] Complete clean-environment end-to-end execution through the API using synthetic inputs and real R/DESeq2.

**Exit gate:** met for the synthetic DESeq2 CLI/API path in [run #40044312203](https://github.com/musuntana/bioai-workbench/actions/runs/40044312203); four artifacts were verified and an immutable-snapshot rerun reproduced both result CSVs byte-for-byte. This is not evidence of production multi-user isolation or scientific validity.

## M1.6 — Input experience

- [x] Upload local CSV inputs through the UI/API without requiring manual filesystem placement.
- [x] List available CSVs using relative paths and sizes; select counts and metadata inputs from the UI.
- [x] Enforce upload size, safe filename, UTF-8/CSV structure, and no-overwrite rules.
- [x] Validate counts/metadata headers, sample IDs, count values, selected condition levels, and replicate counts before a run is submitted.

**Exit gate:** users can upload, select, validate, and submit synthetic inputs through the UI; malformed and oversized uploads are rejected, and existing files are not silently replaced.

## M2 — Workflow orchestration

- [ ] Wrap the workflow in Snakemake after M1 is stable.
- [ ] Record task state, exit status, logs, and artifact checksums.
- [x] Add manual reruns from hash-verified immutable input/workflow snapshots, with parent lineage and a five-attempt family limit.
- [ ] Add bounded automatic retries and safe resume behavior where supported.
- [ ] Verify that reruns do not silently reuse incompatible artifacts.

**Exit gate:** successful and failed runs are observable and reproducible from documented inputs.

## M3 — Safe agent integration

- [ ] Compare a narrow Biomni and ClawBio proof of concept.
- [ ] Add a provider-neutral interface for plan generation/tool selection.
- [ ] Restrict execution to registered workflows and validated parameters.
- [ ] Require confirmation for expensive, destructive, or external actions.
- [ ] Evaluate against fixed tasks; keep a deterministic fallback.

**Exit gate:** the agent cannot bypass workflow validation, and evaluation evidence is recorded.

## M4 — Workbench experience

- [x] Add a paginated run-history API with status filtering; the existing detail endpoint exposes current run status.
- [x] Expose logs and checksummed artifact metadata through dedicated endpoints.
- [x] Add manifest-gated artifact download with path containment checks.
- [x] Persist and expose validated parameter snapshots with each run record.
- [x] Expose structured validation results and validation errors in a stable response contract.
- [x] Add a run-history UI with status filtering and links into run details after the history API stabilized.
- [x] Add local CSV upload/discovery endpoints and UI selection for counts/metadata inputs, with size, filename, CSV-shape, and no-overwrite checks.
- [x] Add bounded CSV preview for selected Counts/Metadata inputs, with path containment and malformed-row checks.
- [x] Add manifest-verified DESeq2 result preview API with search, significance filtering, sorting, pagination, and capped volcano-plot points.
- [x] Add result table, volcano plot, and MA plot to the run detail UI; retain the original checksummed CSV download.
- [x] Export all filtered DESeq2 results to CSV using the same verified artifact and selection criteria as the results table.
- [ ] Add optional local model support only if it improves a measured use case.

## Public release gate for migrated scripts

No script from a private or workplace context is eligible merely because it runs. Require ownership/permission review, data and identifier review, path/endpoint review, license review, tests using synthetic fixtures, and human approval. If publication rights are uncertain, implement the generic behavior independently instead of copying the source.
