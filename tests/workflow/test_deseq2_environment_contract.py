from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_manual_deseq2_job_pins_the_verified_runtime_versions() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    # The first successful clean-environment run established this exact baseline.
    # Prevent future CI drift from silently changing the tested runtime.
    assert 'r-version: "4.4.3"' in workflow
    assert 'BiocManager::install(version = "3.20", ask = FALSE, update = FALSE)' in workflow
    assert 'BiocManager::install("DESeq2", version = "3.20", ask = FALSE, update = FALSE)' in workflow
    assert 'as.character(packageVersion("DESeq2")) == "1.46.0"' in workflow
