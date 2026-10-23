"""Local HTTP API and minimal web UI for BioAI Workbench."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from app.registry import list_workflows
from app.schemas import (
    ArtifactList,
    LogResponse,
    RunAccepted,
    RunList,
    RunRequest,
    RunState,
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


@app.get("/api/v1/runs", response_model=RunList)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: RunState | None = None,
) -> dict[str, Any]:
    return store.list_runs(limit=limit, offset=offset, status=status)


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


@app.get("/api/v1/runs/{run_id}/artifacts/{artifact_path:path}", include_in_schema=True)
def download_run_artifact(run_id: str, artifact_path: str) -> FileResponse:
    """Download a file only when it is listed in the run's artifact manifest."""
    try:
        artifacts = run_manager.get_artifacts(run_id)
        run_dir = run_manager.store.run_dir(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found.") from exc
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    relative_path = PurePosixPath(artifact_path)
    if (
        not artifact_path
        or "\\" in artifact_path
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in artifact_path.split("/"))
    ):
        raise HTTPException(status_code=404, detail="Artifact not found.")

    entry = next(
        (item for item in artifacts if item.get("path") == relative_path.as_posix()),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    output_root = (run_dir / "outputs").resolve()
    candidate = output_root / Path(*relative_path.parts)
    if candidate.is_symlink():
        raise HTTPException(status_code=404, detail="Artifact not found.")
    try:
        artifact_file = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="Artifact not found.") from exc
    if not artifact_file.is_relative_to(output_root) or not artifact_file.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    return FileResponse(
        artifact_file,
        filename=artifact_file.name,
        media_type="application/octet-stream",
        headers={"X-Artifact-SHA256": str(entry.get("sha256", ""))},
    )
