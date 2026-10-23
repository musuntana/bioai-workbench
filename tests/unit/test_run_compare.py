"""Run comparison contract tests using a disposable file-backed manager."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.run_compare import compare_runs
from runtime.state import RunStore


def _manager(root: Path):
    store = RunStore(root)
    return SimpleNamespace(
        store=store,
        get_artifacts=lambda run_id: (
            [{"path": "result.csv", "sha256": "a" * 64}]
            if run_id == "a" * 32 else
            [{"path": "result.csv", "sha256": "b" * 64}]
        ),
    )


def test_compares_parameters_and_checksums():
    with TemporaryDirectory() as temporary:
        manager = _manager(Path(temporary))
        manager.store.create("a" * 32, "deseq2-basic", parameters={"alpha": 0.05, "contrast": "treated"})
        manager.store.create("b" * 32, "deseq2-basic", parameters={"alpha": 0.01, "contrast": "treated"})
        payload = compare_runs(manager, "a" * 32, "b" * 32)
        assert payload["same_workflow"] is True
        assert payload["changed_parameters"] == [
            {"field": "alpha", "run_a": 0.05, "run_b": 0.01}
        ]
        assert payload["artifacts"][0]["same_checksum"] is False
        assert "not input content hashes" in payload["limitations"]


@pytest.mark.parametrize("run_a,run_b,status", [
    ("../invalid", "b" * 32, 422),
    ("a" * 32, "a" * 32, 422),
    ("a" * 32, "b" * 32, 404),
])
def test_rejects_invalid_or_missing_runs(run_a, run_b, status):
    with TemporaryDirectory() as temporary:
        manager = _manager(Path(temporary))
        manager.store.create("a" * 32, "deseq2-basic")
        with pytest.raises(HTTPException) as caught:
            compare_runs(manager, run_a, run_b)
        assert caught.value.status_code == status
