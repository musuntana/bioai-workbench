# Security and Data Handling

## Scope

BioAI Workbench is an early-stage research workflow project. It is not a clinical diagnostic device and has not been validated for clinical decisions.

## Do not commit

- credentials, API keys, access tokens, private keys, or session cookies;
- real patient, participant, client, or customer data;
- internal hostnames, private URLs, server addresses, database connection strings, or storage paths;
- company-owned scripts, report templates, datasets, reference databases, or business logic unless the right to publish them has been explicitly confirmed;
- logs, screenshots, or generated reports that can reveal any of the above.

Synthetic data should be used for tests and demos. Public datasets may be used only when their license and redistribution terms permit the intended use.

## Before publishing a script

1. Confirm ownership and permission to publish.
2. Review code, comments, string literals, paths, URLs, emails, identifiers, and embedded metadata.
3. Replace machine-specific paths with explicit CLI/config inputs.
4. Remove real sample identifiers and use synthetic fixtures.
5. Check dependency and copied-code licenses.
6. Run secret and sensitive-data scans.
7. Review generated outputs and test logs, not only source files.
8. Require a human review before merging.

Removing a company name alone is not sufficient to make code safe to publish.

## Reporting

Do not open a public issue containing a suspected secret or private dataset. If sensitive material is found in the repository, stop further publication, restrict access where possible, rotate exposed credentials, and follow the relevant provider's secret-removal guidance. Rewriting the latest file does not erase data from Git history.

## AI integrations

External model calls must be opt-in and clearly documented. Raw research data must not be sent to an external model by default. Any future agent execution must use allowlisted tools, validated parameters, bounded resources, explicit approval for destructive or external actions, and auditable logs.
