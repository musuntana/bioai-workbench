from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_expensive_deseq2_integration_requires_explicit_owner_opt_in() -> None:
    workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")

    # The normal pull-request gate must remain independent of R/Bioconductor setup.
    assert "  pull_request:" in workflow
    assert "  workflow_dispatch:" in workflow
    assert "default: false" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.run_r_integration" in workflow

    # A comment can trigger the expensive job only on the dedicated M1 issue,
    # with the exact command from the repository owner (not arbitrary PR comments).
    assert "  issue_comment:\n    types: [created]" in workflow
    assert "github.event.issue.number == 1" in workflow
    assert "!github.event.issue.pull_request" in workflow
    assert "github.event.comment.body == '/run-deseq2-integration'" in workflow
    assert "github.event.comment.user.login == github.repository_owner" in workflow
    assert "github.event_name != 'issue_comment'" in workflow
