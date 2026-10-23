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
- [ ] Run the smoke test in a clean R/Bioconductor environment and confirm all positive/negative cases.
- [ ] Document and pin a tested R/DESeq2 dependency combination.

**Status:** implementation is present; runtime verification is pending. **Exit gate:** a clean environment can run the synthetic example and produce inspectable artifacts, and failure cases are tested. Statistical output should be validated against the documented fixture; do not claim clinical validity.

## M1.5 — Open-source product skeleton

- [x] Add a `uv`-managed Python project and FastAPI API/UI.
- [x] Commit `uv.lock` and enforce locked Python dependency resolution in CI.
- [x] Add a registered DESeq2 workflow contract and preserve the legacy CLI entrypoint.
- [x] Add deterministic, approval-gated planning over registered workflow IDs only.
- [x] Add file-backed run state, bounded subprocess execution, timeout/log limits, and relative input-root checks.
- [x] Add artifact manifests with relative paths and SHA-256 checksums.
- [x] Add unit, API integration, and workflow contract tests.
- [x] Add an opt-in API-to-DESeq2 smoke test and manual CI evidence capture using synthetic data.
- [ ] Complete local end-to-end execution through the API in a clean R/DESeq2 environment.

**Exit gate:** Python/API checks pass, the synthetic DESeq2 workflow succeeds through the UI/API, and timeout/failure/output-manifest evidence is recorded. This milestone does not mark M1's R verification as complete.

## M1.6 — Input experience

- [x] Upload local CSV inputs through the UI/API without requiring manual filesystem placement.
- [x] List available CSVs using relative paths and sizes; select counts and metadata inputs from the UI.
- [x] Enforce upload size, safe filename, UTF-8/CSV structure, and no-overwrite rules.
- [x] Validate counts/metadata headers, sample IDs, count values, selected condition levels, and replicate counts before a run is submitted.

**Exit gate:** users can upload, select, validate, and submit synthetic inputs through the UI; malformed and oversized uploads are rejected, and existing files are not silently replaced.

## M2 — Workflow orchestration

- [ ] Wrap the workflow in Snakemake after M1 is stable.
- [ ] Record task state, exit status, logs, and artifact checksums.
- [ ] Add bounded retries and safe resume behavior where supported.
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
- [x] Add manifest-verified DESeq2 result preview API with search, significance filtering, sorting, pagination, and capped volcano-plot points.
- [x] Add a result table and responsive volcano plot to the run detail UI; retain the original checksummed CSV download.
- [ ] Add optional local model support only if it improves a measured use case.

## Public release gate for migrated scripts

No script from a private or workplace context is eligible merely because it runs. Require ownership/permission review, data and identifier review, path/endpoint review, license review, tests using synthetic fixtures, and human approval. If publication rights are uncertain, implement the generic behavior independently instead of copying the source.
