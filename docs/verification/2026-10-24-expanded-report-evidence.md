# Expanded synthetic DESeq2 report acceptance, 2026-10-24

**Result:** PASS for the **synthetic software integration scope only**. This record does not represent biological or clinical validity.

- Verified `main` commit: `ea60cd2574a3cb347e68a5bb48650ea5bd94bf1a` (PR #43)
- [GitHub Actions run #40060567106](https://github.com/musuntana/bioai-workbench/actions/runs/40060567106)
- [Evidence archive #12546964500](https://github.com/musuntana/bioai-workbench/actions/runs/40060567106/artifacts/12546964500), expiring 2026-11-07
- GitHub-reported evidence archive digest: `sha256:5c9d2232924130863069e6eb3a00badd25b5652ff6ecd6f50e482c1e76f8cc01`
- Environment: R 4.4.3, DESeq2 1.46.0; pinned Bioconductor 3.20.
- Source-safety/Python job: succeeded. Manual synthetic R/DESeq2 integration job: succeeded.
- Log records: `Real synthetic R/DESeq2 acceptance passed` and `API end-to-end smoke test passed`, with generated evidence at `acceptance-matrix.json`.

The expanded ninth check, `selected_gene_and_cross_run_evidence`, joins the eight prior acceptance categories. It fetches a multi-gene filtered preview, CSV export and selected-gene HTML report; executes a real immutable-snapshot rerun; and fetches full-union aligned CSV plus a cross-run HTML report. The standard-library evidence validator checks returned identifiers, numeric statistics, per-run significance, SHA-256 source provenance and report contents against the downloaded result CSVs. The historical eight-category verification record predates these features and should not be used as their evidence.

**Evidence scope:** real R/DESeq2 on generated data, genuine HTTP/API artifact download, and an actual rerun. Unit tests of the evidence validator alone are not this proof. Browser interaction, real study samples, interpretation of biological effects, multi-user isolation, and every transitive R dependency remain outside this verification.

**Later changes:** PR #44 added Python-only library-size preflight indicators after this verified commit. The present runtime ownership change likewise requires its own Python contract regression tests and does not inherit new R acceptance. Do not label those newer behaviors as tested in this earlier integration run.
