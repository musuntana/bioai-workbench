"""Local HTTP API and minimal web UI for BioAI Workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.registry import list_workflows
from app.schemas import (
    ArtifactList,
    LogResponse,
    RunAccepted,
    RunRequest,
    RunStatus,
    WorkflowList,
)
from runtime.config import RuntimeConfig
from runtime.manager import RunManager
from runtime.state import RunStore


config = RuntimeConfig.from_env()
config.prepare()
store = RunStore(config.runs_root)
run_manager = RunManager(config=config, store=store)

app = FastAPI(
    title="BioAI Workbench",
    version="0.2.0",
    description="Local-first API for registered reproducible bioinformatics workflows.",
)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "templates" / "index.html")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bioai-workbench"}


@app.get("/api/v1/workflows", response_model=WorkflowList)
def workflows() -> dict[str, list[dict[str, Any]]]:
    return {"workflows": list_workflows()}


@app.post("/api/v1/runs", response_model=RunAccepted, status_code=202)
def submit_run(request: RunRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    try:
        record = run_manager.create_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Workflow is not registered.") from exc

    background_tasks.add_task(run_manager.execute, record["run_id"], request.model_dump())
    run_id = record["run_id"]
    return {
        "run_id": run_id,
        "workflow_id": request.workflow_id,
        "status": record["status"],
        "created_at": record["created_at"],
        "status_url": f"/api/v1/runs/{run_id}",
    }


@app.get("/api/v1/runs/{run_id}", response_model=RunStatus)
def get_run(run_id: str) -> dict[str, Any]:
    try:
        record = store.get(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return record


@app.get("/api/v1/runs/{run_id}/logs", response_model=LogResponse)
def get_run_logs(run_id: str) -> dict[str, Any]:
    try:
        result = run_manager.get_log(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    text, truncated = result
    return {"run_id": run_id, "text": text, "truncated": truncated}


@app.get("/api/v1/runs/{run_id}/artifacts", response_model=ArtifactList)
def get_run_artifacts(run_id: str) -> dict[str, Any]:
    try:
        artifacts = run_manager.get_artifacts(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run_id": run_id, "artifacts": artifacts}
