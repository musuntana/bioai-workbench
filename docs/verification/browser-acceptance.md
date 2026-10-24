# Real browser acceptance (synthetic, opt-in)

The [Browser acceptance workflow](../../.github/workflows/browser-acceptance.yml) launches **real headless Chromium** against a local FastAPI/Uvicorn server, with a fresh temporary input/run directory for every execution. It is **not** included in ordinary application-only pull request CI. It runs when the workflow or browser harness changes, or via manual `workflow_dispatch`.

## Coverage

The browser script `tests/browser/browser_smoke.py` exercises:

- Upload counts and sample-metadata CSVs via the actual page, select their roles, and validate preflight/library-size indicators.
- Submit the form and launch a local worker using a deliberately fake `Rscript`, then view a manifest-verified result table, checksum-gated artifacts, and CSV export link.
- Browse past the first 20 persisted runs and compare two runs selected on different pages.
- Observe a subprocess log **while that subprocess is still active**; confirm cancellation from the page, check its terminal state and that partial artifacts remain inaccessible.
- Filter the history to cancelled runs; fail on unhandled browser JavaScript errors.

The script saves `acceptance.json` with passed checks, plus server logs and an on-failure screenshot, in a seven-day GitHub Actions artifact. All fixtures and run data are synthetic and remain in a temporary directory.

## Run locally

Use the existing locked Python project dependencies, then install Playwright only in the test environment:

```bash
uv sync --locked --extra dev
uv pip install --python .venv/bin/python "playwright==1.56.0"
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser/browser_smoke.py
```

If Chromium reports missing system libraries, use the official OS-dependency installation procedure; the Linux CI job does `playwright install --with-deps chromium`.

## Evidence boundaries

This verifies browser UI and HTTP/runtime plumbing with a **fake Rscript**, not actual R, DESeq2 inference, real datasets, or scientific validity. Existing pinned [synthetic real-DESeq2 integration evidence](2026-10-24-expanded-report-evidence.md) supports a different boundary. Neither proves multi-user production safety. A browser smoke result is only valid when its corresponding Actions execution succeeds and emits the evidence artifact. Keep running the inexpensive Python tests for ordinary changes; trigger the browser workflow for major UI/runtime changes or release acceptance.
