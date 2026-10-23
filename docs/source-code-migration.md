# Safe Migration of Existing R Scripts

This process is for deciding whether an existing script can contribute to BioAI Workbench. It is not a promise that any particular private script is safe to publish.

## Decision states

- **HOLD:** ownership, permission, data provenance, or license is unclear.
- **REJECT:** contains real research/client data, restricted business logic, credentials, or other material that must not be published.
- **REIMPLEMENT:** useful behavior is generic, but the original source cannot be published safely or its provenance is uncertain.
- **REFACTOR-ELIGIBLE:** rights are confirmed and the script passes the complete review below.
- **APPROVED:** refactored code has tests, synthetic fixtures, documented dependencies, and human approval.

## Review checklist

### A. Rights and provenance
- Who authored the script and under what employment/contract terms?
- Does it include company-owned deliverables or third-party code?
- Are copied functions and embedded assets licensed for redistribution?
- Is there written permission if ownership is uncertain?

### B. Data and identifiers
- Remove real sample, patient, client, project, order, and case identifiers.
- Remove real input/output files, screenshots, reports, and embedded metadata.
- Use synthetic fixture data that cannot be linked back to a real project.
- Do not commit reference databases or annotation assets unless redistribution is permitted.

### C. Environment and infrastructure
- Replace absolute paths and working-directory assumptions with CLI/config inputs.
- Remove internal URLs, hostnames, IPs, storage locations, database endpoints, and service names.
- Remove credentials, tokens, private keys, and personal contact details.
- Do not log raw data or sensitive command arguments.

### D. Product and code quality
- Separate reusable analysis logic from customer/report-specific formatting.
- Make parameters explicit and validate them before execution.
- Pin/document dependencies and supported versions.
- Add tests for valid input, invalid input, and expected outputs.
- Record tool versions and output manifests.

### E. Release
- Scan the diff and generated artifacts.
- Review the entire diff manually.
- Confirm license and attribution.
- Merge only after the review is complete.

## Recommended extraction pattern

1. Describe the workflow in a neutral specification: inputs, outputs, algorithm, parameters, assumptions, and failure modes.
2. Decide which parts are public, generic domain knowledge versus organization-specific implementation.
3. Where rights are clear, refactor the reusable module while preserving required notices.
4. Where rights are unclear, do not copy or mechanically transform the source; implement the generic behavior independently using documented public APIs.
5. Test the resulting implementation using synthetic data.
6. Keep the original private repository unchanged.

**Important:** replacing names, paths, or emails does not by itself establish ownership or make proprietary code safe to release.
