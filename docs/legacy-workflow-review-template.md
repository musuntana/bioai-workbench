# Legacy Workflow Candidate Review Template

Use one copy of this template per candidate workflow. Record only a neutral candidate ID and generalized technical facts. **Do not include private script contents, private repository URLs, company/client names, real file paths, sample identifiers, screenshots, reports, or data.** Keep any sensitive mapping between this ID and the original private script in the authorized private workspace, not here.

## 1. Candidate identity

- Candidate ID: `WF-____` (neutral, non-identifying)
- Review date:
- Reviewer:
- General workflow category: (e.g. differential expression, QC, annotation, reporting)
- Decision: `HOLD` / `REJECT` / `REIMPLEMENT` / `REFACTOR-ELIGIBLE` / `APPROVED`
- Decision owner / required approver:

## 2. Purpose and behavior (describe, do not copy)

- User/research problem solved:
- Inputs and formats:
- Outputs and formats:
- Main algorithm or established tools used:
- Important parameters and defaults:
- Assumptions and known failure modes:
- Reusable behavior independent of any employer/customer:

## 3. Rights and provenance gate

For each item, record `YES`, `NO`, or `UNKNOWN` and a non-sensitive evidence reference. Do not attach restricted contracts or internal correspondence.

| Check | Status | Evidence reference / next action |
|---|---|---|
| Authorship is known | UNKNOWN | |
| Employment/contract ownership terms reviewed | UNKNOWN | |
| Permission to publish is confirmed where required | UNKNOWN | |
| Third-party code and assets are identified | UNKNOWN | |
| Dependency licenses are compatible | UNKNOWN | |
| Required copyright and attribution notices are preserved | UNKNOWN | |

**Gate rule:** any material `UNKNOWN` means `HOLD` or `REIMPLEMENT`; do not copy the original implementation into this repository.

## 4. Sensitive-material review

Record categories and outcomes only. Never paste the matched value.

| Category | Present? (YES/NO/UNKNOWN) | Action / evidence |
|---|---|---|
| Real research, patient, participant, sample, or customer data | UNKNOWN | |
| Identifiers embedded in code, comments, filenames, or fixtures | UNKNOWN | |
| Absolute paths, internal hosts, endpoints, IPs, or storage locations | UNKNOWN | |
| Credentials, tokens, certificates, or personal contact details | UNKNOWN | |
| Internal report templates, logos, reference databases, or bundled assets | UNKNOWN | |
| Employer/customer-specific business rules or confidential logic | UNKNOWN | |
| Git history, generated logs, or output files containing restricted material | UNKNOWN | |

## 5. Extraction decision

- [ ] Reuse an established public package or official API instead of custom code.
- [ ] Define a neutral input/output contract before implementation.
- [ ] Separate general analysis from organization-specific reporting and integration.
- [ ] Implement independently from public documentation because source rights are unclear.
- [ ] Preserve required third-party notices if code is legally reusable.
- [ ] Use synthetic or explicitly redistributable fixtures only.

Chosen path and rationale:

## 6. Public implementation acceptance

Complete only for a new clean-room implementation or rights-cleared refactor.

- [ ] No private source or real data was copied into this repository.
- [ ] CLI/configuration replaces machine-specific assumptions.
- [ ] Input validation and actionable failure cases are covered.
- [ ] Synthetic fixture and expected-output contract are committed.
- [ ] Tool/dependency versions and reproducibility requirements are documented.
- [ ] `python scripts/audit_public_release.py` reviewed; findings investigated.
- [ ] Full diff, outputs, logs, and Git history implications reviewed by a human.
- [ ] License and attribution review completed.
- [ ] Required technical and ownership approvals recorded.

Test commands and evidence links:

Known limitations / unverified behavior:

## 7. Final sign-off

- Technical reviewer:
- Rights/ownership reviewer (if required):
- Final decision:
- Date:
- Follow-up issue or PR:
