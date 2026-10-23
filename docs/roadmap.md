# Roadmap

## M0 — Safe foundation

- [x] Establish project boundaries and public-release rules.
- [x] Document architecture and source-code migration process.
- [x] Add a synthetic-data DESeq2 example generator and CLI runner.
- [ ] Add repository checks for accidental secrets and private data patterns.

**Exit gate:** public repository contains only reviewed documentation and original/authorized code; no workplace scripts or real research data have been imported.

## M1 — First reproducible workflow

- [x] Define counts/metadata schemas and validation behavior.
- [x] Implement a clean-room DESeq2 CLI workflow using synthetic input data.
- [x] Save full/significant result tables, session information, parameters, and a run manifest with input/output fingerprints.
- [x] Add an opt-in local integration smoke-test script.
- [ ] Run the smoke test in a clean R/Bioconductor environment and exercise failure cases.
- [ ] Document and pin a tested R/DESeq2 dependency combination.

**Status:** implementation is present; runtime verification is pending. **Exit gate:** a clean environment can run the synthetic example and produce inspectable artifacts, and failure cases are tested. Statistical output should be validated against the documented fixture; do not claim clinical validity.

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

- [ ] Add run history and status API.
- [ ] Expose logs, parameters, validation results, and artifacts.
- [ ] Add UI only after API contracts are stable.
- [ ] Add optional local model support only if it improves a measured use case.

## Public release gate for migrated scripts

No script from a private or workplace context is eligible merely because it runs. Require ownership/permission review, data and identifier review, path/endpoint review, license review, tests using synthetic fixtures, and human approval. If publication rights are uncertain, implement the generic behavior independently instead of copying the source.
