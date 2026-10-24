"""M2 cancellation must preserve terminal artifacts and terminate owned processes."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import RunRequest
from runtime.config import PROJECT_ROOT, RuntimeConfig
from runtime.manager import RunManager
from runtime.state import RunStore


def _new_manager(root: Path, *, slow_script: bool = False) -> tuple[RunManager, RunRequest, Path]:
    inputs = root / "inputs"
    inputs.mkdir()
    (inputs / "counts.csv").write_text(
        "gene_id,s1,s2,s3,s4\ng1,10,20,30,40\n", encoding="utf-8"
    )
    (inputs / "metadata.csv").write_text(
        "sample_id,condition\ns1,control\ns2,control\ns3,treatment\ns4,treatment\n",
        encoding="utf-8",
    )
    executable = root / "Rscript"
    if slow_script:
        executable.write_text(
            "#!/usr/bin/env python3\nimport time\n"
            "print('started', flush=True)\ntime.sleep(15)\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    manager = RunManager(config=RuntimeConfig(
        project_root=PROJECT_ROOT,
        input_root=inputs,
        runs_root=root / "runs",
        max_run_seconds=20,
    ))
    return manager, RunRequest(counts_file="counts.csv", metadata_file="metadata.csv"), executable


def test_cancel_queued_is_idempotent_and_never_creates_snapshots(tmp_path: Path) -> None:
    manager, request, _ = _new_manager(tmp_path)
    run = manager.create_run(request)
    run_id = run["run_id"]
    first = manager.cancel_run(run_id)
    assert first["status"] == "cancelled"
    assert first["started_at"] is None
    assert first["finished_at"] is not None
    assert manager.cancel_run(run_id) == first
    manager.execute(run_id, request.model_dump())
    assert manager.store.get(run_id) == first
    assert not (manager.store.run_dir(run_id) / "tmp").exists()
    assert manager.get_artifacts(run_id) == []


def test_cancel_running_stops_child_and_does_not_publish_partial_artifacts(tmp_path: Path) -> None:
    manager, request, executable = _new_manager(tmp_path, slow_script=True)
    run_id = manager.create_run(request)["run_id"]
    # This test exercises a real child process, not just an Event mock.
    with patch.object(manager, "_find_rscript", return_value=str(executable)):
        with ThreadPoolExecutor(max_workers=2) as pool:
            worker = pool.submit(manager.execute, run_id, request.model_dump())
            deadline = time.monotonic() + 10
            log_path = manager.store.run_dir(run_id) / "run.log"
            while time.monotonic() < deadline:
                if log_path.exists() and b"started" in log_path.read_bytes():
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Slow workflow never reached subprocess execution")
            accepted = manager.cancel_run(run_id)
            assert accepted["status"] == "cancelling"
            assert manager.cancel_run(run_id)["status"] == "cancelling"
            worker.result(timeout=8)
    finished = manager.store.get(run_id)
    assert finished["status"] == "cancelled"
    assert finished["finished_at"] is not None
    assert finished["artifact_count"] == 0
    assert manager.get_artifacts(run_id) == []
    assert manager.cancel_run(run_id) == finished
    assert not (manager.store.run_dir(run_id) / "outputs" / "artifacts.json").exists()


def test_cancel_terminal_run_refuses_without_modifying_record(tmp_path: Path) -> None:
    manager, request, _ = _new_manager(tmp_path)
    run_id = manager.create_run(request)["run_id"]
    manager.store.update(run_id, status="succeeded", finished_at="2026-10-24T00:00:00+00:00")
    prior = manager.store.get(run_id)
    with pytest.raises(ValueError, match="completed"):
        manager.cancel_run(run_id)
    assert manager.store.get(run_id) == prior


def test_cancel_recovery_marks_interrupted_cancelling_as_failed(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    run_id = "f" * 32
    store.create(run_id, "deseq2-basic")
    store.update(run_id, status="cancelling")
    assert store.recover_interrupted_runs() == [run_id]
    assert store.get(run_id)["status"] == "failed"


def test_cancel_http_contract_queued_terminal_unknown(tmp_path: Path) -> None:
    manager, request, _ = _new_manager(tmp_path)
    queued_id = manager.create_run(request)["run_id"]
    completed_id = manager.create_run(request)["run_id"]
    manager.store.update(completed_id, status="succeeded")
    with patch("app.main.run_manager", manager), patch("app.main.store", manager.store):
        client = TestClient(app)
        queued = client.post(f"/api/v1/runs/{queued_id}/cancel")
        assert queued.status_code == 200
        assert queued.json()["status"] == "cancelled"
        assert client.get(f"/api/v1/runs/{queued_id}").json()["status"] == "cancelled"
        assert client.get("/api/v1/runs", params={"status": "cancelled"}).json()["total"] == 1
        assert client.post(f"/api/v1/runs/{completed_id}/cancel").status_code == 409
        assert client.post(f"/api/v1/runs/{'a' * 32}/cancel").status_code == 404
        assert client.post("/api/v1/runs/not-valid/cancel").status_code == 404


def test_ui_has_explicit_cancel_control_and_terminal_state():
    page = TestClient(app).get("/").text
    assert 'id="cancel-run"' in page
    assert '"/cancel"' in page
    assert '"cancelled"' in page
