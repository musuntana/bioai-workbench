"""Opt-in, real-Chromium UI acceptance on synthetic data and a fake Rscript.

This checks the browser -> FastAPI -> local runtime path, not DESeq2 science.
Run only through the isolated browser-smoke workflow (Playwright is optional).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from runtime.state import RunStore

COUNTS = (
    "gene_id,s1,s2,s3,s4\n"
    "gene_alpha,12,15,28,33\n"
    "gene_beta,42,39,23,18\n"
    "gene_gamma,8,7,8,9\n"
)
METADATA = (
    "sample_id,condition\n"
    "s1,control\ns2,control\ns3,treatment\ns4,treatment\n"
)
RESULT_HEADER = "gene_id,baseMean,log2FoldChange,lfcSE,stat,pvalue,padj\n"

# The local executable is intentionally NOT R/DESeq2; it produces deterministic
# well-formed synthetic artifacts to exercise runtime and UI contracts.
FAKE_RSCRIPT = """#!/usr/bin/env python3
import pathlib
import sys
import time

args = sys.argv[1:]
outdir = pathlib.Path(args[args.index('--outdir') + 1])
counts = pathlib.Path(args[args.index('--counts') + 1]).read_text()
print('synthetic-browser-live-output', flush=True)
if 'slow_gene' in counts:
    time.sleep(20)
outdir.joinpath('differential_expression_all.csv').write_text(
    'gene_id,baseMean,log2FoldChange,lfcSE,stat,pvalue,padj\\n'
    'gene_alpha,100,2.5,0.5,5,0.0001,0.001\\n'
    'gene_beta,60,-1.2,0.4,-3,0.002,0.02\\n'
    'gene_gamma,40,0.1,0.2,0.5,0.6,0.7\\n'
)
outdir.joinpath('differential_expression_significant.csv').write_text(
    'gene_id,baseMean,log2FoldChange,lfcSE,stat,pvalue,padj\\n'
    'gene_alpha,100,2.5,0.5,5,0.0001,0.001\\n'
    'gene_beta,60,-1.2,0.4,-3,0.002,0.02\\n'
)
outdir.joinpath('run_manifest.tsv').write_text(
    'key\\tvalue\\n' 'r_version\\t4.4.3\\n' 'deseq2_version\\t1.46.0\\n'
)
outdir.joinpath('session_info.txt').write_text('synthetic fake Rscript; not a DESeq2 run\\n')
print('synthetic-browser-finished', flush=True)
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _await_server(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Synthetic workbench server exited before becoming healthy.")
        try:
            with urlopen(url + "/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.1)
    raise TimeoutError("Synthetic workbench server was not ready within 20 seconds.")


def _upload(page, filename: str, csv_text: str) -> None:
    page.locator("#input-upload-file").set_input_files({
        "name": filename,
        "mimeType": "text/csv",
        "buffer": csv_text.encode("utf-8"),
    })
    page.locator("#upload-input-button").click()
    expect(page.locator("#input-summary")).to_contain_text(
        "Uploaded " + filename, timeout=10_000
    )


def _select_inputs(page, counts_name: str) -> None:
    page.locator("#counts-file").select_option(counts_name)
    page.locator("#metadata-file").select_option("browser_metadata.csv")
    page.locator("#validate-inputs").click()
    expect(page.locator("#input-validation-summary")).to_contain_text(
        "Inputs valid", timeout=10_000
    )
    expect(page.locator("#input-library-qc")).to_be_visible()


def _seed_history(runs_dir: Path) -> str:
    store = RunStore(runs_dir)
    for i in range(1, 23):
        run_id = f"{i:032x}"
        store.create(run_id, "deseq2-basic")
        store.update(run_id, status="failed", finished_at="2026-10-24T00:00:00+00:00")
    return f"{1:032x}"


def run_browser_smoke(page, old_run_id: str) -> list[str]:
    checks: list[str] = []
    page.goto(page.context.browser_base_url, wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="BioAI Workbench")).to_be_visible()
    expect(page.locator("#history-summary")).to_contain_text("22 runs")
    checks.append("browser_home_and_paginated_history")

    _upload(page, "browser_counts.csv", COUNTS)
    _upload(page, "browser_metadata.csv", METADATA)
    _select_inputs(page, "browser_counts.csv")
    checks.append("browser_upload_select_and_preflight")

    page.locator("#run-form button[type=submit]").click()
    expect(page.locator("#run-summary")).to_contain_text("succeeded", timeout=20_000)
    match = re.search(r"Run ([0-9a-f]{32})", page.locator("#run-summary").inner_text())
    assert match, "No completed run ID in browser"
    success_id = match.group(1)
    expect(page.locator("#results-table-body")).to_contain_text(
        "gene_alpha", timeout=10_000
    )
    expect(page.locator("#results-export-link")).to_be_visible()
    expect(page.locator("#artifact-list")).to_contain_text("Download")
    checks.append("browser_submit_real_worker_and_verified_result_view")

    # Select runs that appear on different history pages. Selection must survive.
    page.locator("#refresh-history").click()
    selector = f'#history-list input[aria-label="Select run {success_id} for comparison"]'
    page.locator(selector).check()
    page.locator("#history-next").click()
    expect(page.locator("#history-summary")).to_contain_text("Showing 21")
    page.locator(
        f'#history-list input[aria-label="Select run {old_run_id} for comparison"]'
    ).check()
    expect(page.locator("#history-selection-summary")).to_contain_text("Selected (2/2)")
    page.locator("#compare-history").click()
    expect(page.locator("#comparison-summary")).to_contain_text(
        "Same workflow: true", timeout=10_000
    )
    checks.append("browser_cross_page_history_comparison")

    _upload(page, "browser_slow_counts.csv", COUNTS.replace("gene_alpha", "slow_gene"))
    _select_inputs(page, "browser_slow_counts.csv")
    page.locator("#run-form button[type=submit]").click()
    expect(page.locator("#run-log")).to_contain_text(
        "synthetic-browser-live-output", timeout=12_000
    )
    expect(page.locator("#cancel-run")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#cancel-run").click()
    expect(page.locator("#run-summary")).to_contain_text("cancelled", timeout=12_000)
    expect(page.locator("#artifact-list")).to_be_empty()
    expect(page.locator("#results-panel")).to_be_hidden()
    checks.append("browser_live_logs_and_running_job_cancellation")

    page.locator("#history-status").select_option("cancelled")
    expect(page.locator("#history-list")).to_contain_text("cancelled", timeout=10_000)
    checks.append("browser_cancelled_history_filter")
    return checks


def main() -> None:
    evidence_dir = Path(os.environ.get("BIOAI_BROWSER_EVIDENCE_DIR", "browser-evidence"))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bioai-browser-synthetic-") as temp_dir:
        root = Path(temp_dir)
        runs_dir = root / "runs"
        inputs_dir = root / "inputs"
        inputs_dir.mkdir()
        old_run_id = _seed_history(runs_dir)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        rscript = bin_dir / "Rscript"
        rscript.write_text(FAKE_RSCRIPT, encoding="utf-8")
        rscript.chmod(0o755)

        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        env = dict(os.environ)
        env.update({
            "BIOAI_INPUT_ROOT": str(inputs_dir),
            "BIOAI_RUNS_DIR": str(runs_dir),
            "BIOAI_MAX_RUN_SECONDS": "30",
            "BIOAI_MAX_CONCURRENT_RUNS": "1",
            "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
        })
        with (evidence_dir / "server.log").open("wb") as output:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app",
                 "--host", "127.0.0.1", "--port", str(port)],
                env=env, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                _await_server(url, server)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 960})
                        # Keep a base URL in the browser-scoped test context.
                        page.context.browser_base_url = url
                        page_errors: list[str] = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        try:
                            checks = run_browser_smoke(page, old_run_id)
                            assert not page_errors, "Browser JS errors: " + repr(page_errors)
                        except Exception:
                            page.screenshot(
                                path=str(evidence_dir / "browser-failure.png"), full_page=True
                            )
                            raise
                        (evidence_dir / "acceptance.json").write_text(
                            json.dumps({
                                "status": "passed",
                                "checks": checks,
                                "scope": "real Chromium + FastAPI + synthetic fake Rscript",
                                "scientific_validation": "not_assessed",
                            }, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        print("Browser synthetic acceptance passed:", ", ".join(checks))
                    finally:
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    main()
