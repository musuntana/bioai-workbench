"""Only one in-process worker can claim a queued run for execution."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runtime.state import RunStore


def test_claim_is_atomic_under_concurrent_workers(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "a" * 32
    store.create(run_id, "deseq2-basic")

    with ThreadPoolExecutor(max_workers=12) as pool:
        claimed = list(pool.map(store.claim_queued_run, [run_id] * 24))

    assert claimed.count(True) == 1
    assert claimed.count(False) == 23
    record = store.get(run_id)
    assert record["status"] == "running"
    assert record["started_at"] is not None
    assert record["finished_at"] is None


@pytest.mark.parametrize("terminal_status", ["succeeded", "failed", "timed_out"])
def test_claim_does_not_reopen_terminal_runs(tmp_path: Path, terminal_status: str) -> None:
    store = RunStore(tmp_path)
    run_id = "b" * 32
    store.create(run_id, "deseq2-basic")
    store.update(run_id, status=terminal_status, finished_at="2026-10-24T00:00:00+00:00")
    previous = store.get(run_id)

    assert store.claim_queued_run(run_id) is False
    assert store.get(run_id) == previous


def test_claim_refuses_recovered_run_and_unknown_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "c" * 32
    store.create(run_id, "deseq2-basic")
    assert store.recover_interrupted_runs() == [run_id]
    assert store.claim_queued_run(run_id) is False
    assert "runtime restart" in store.get(run_id)["error_message"]
    with pytest.raises(FileNotFoundError):
        store.claim_queued_run("d" * 32)


def test_claim_is_idempotent_for_running_record(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "e" * 32
    store.create(run_id, "deseq2-basic")
    assert store.claim_queued_run(run_id)
    first = store.get(run_id)
    assert not store.claim_queued_run(run_id)
    assert store.get(run_id) == first
