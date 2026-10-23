# Contributing

BioAI Workbench prioritizes small, testable integrations with mature bioinformatics tools.

## Contribution requirements

- Keep deterministic workflows usable without an LLM.
- Add tests for input validation, expected outputs, and failure behavior.
- Document runtime requirements and commands needed to reproduce results.
- Use synthetic or explicitly licensed public data in examples and tests.
- Record important architecture choices in `docs/decisions/` when that directory is introduced.
- Keep changes narrow; do not add infrastructure before a demonstrated requirement exists.

## Source-code provenance

Only contribute code that you wrote, are authorized to publish, or can redistribute under a compatible license. For third-party code, retain required notices and attribution. Do not submit workplace code or report templates until ownership and publication rights have been checked.

Before submitting a change, review the full diff for secrets, private paths, internal URLs, identifying sample names, and generated data. A clean scanner result is useful but does not replace human review.

## Pull requests

Describe:
1. the user problem;
2. the smallest change that solves it;
3. commands/tests run and their results;
4. data used (synthetic, public, or authorized);
5. known limitations and unverified behavior.
