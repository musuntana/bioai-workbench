"""Local HTTP API and minimal web UI for BioAI Workbench."""

from __future__ import annotations

import csv
import hashlib
import hmac
import math
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

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


@app.exception_handler(RequestValidationError)
async def request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a stable, value-free validation error contract for API clients."""
    del request
    details = []
    for error in exc.errors():
        location = error.get("loc", ())
        field = ".".join(str(part) for part in location if part not in {"body", "query", "path", "header"})
        details.append(
            {
                "field": field or "$",
                "message": str(error.get("msg", "Invalid value.")),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": details,
            }
        },
    )


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "templates" / "index.html")



INPUT_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.csv$")
MAX_INPUT_FILE_BYTES = 25 * 1024 * 1024


def _validate_csv_file(path: Path) -> None:
    """Validate a bounded UTF-8 CSV's basic table shape without loading it all into memory."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if (
                header is None
                or len(header) < 2
                or any(not item.strip() for item in header)
                or len({item.strip().casefold() for item in header}) != len(header)
            ):
                raise ValueError("CSV must have at least two unique, non-empty column names.")
            row_count = 0
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    raise ValueError("CSV rows must have the same number of columns as the header.")
                if all(not item.strip() for item in row):
                    continue
                row_count += 1
            if row_count == 0:
                raise ValueError("CSV must contain at least one data row.")
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("File must be a valid UTF-8 CSV.") from exc


@app.get("/api/v1/inputs")
def list_input_files() -> dict[str, list[dict[str, Any]]]:
    """List CSV inputs under the configured root without revealing absolute paths."""
    root = config.input_root.resolve()
    files: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if path.suffix.lower() != ".csv" or path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        current = root
        unsafe = False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                unsafe = True
                break
        if unsafe:
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_relative_to(root) or not resolved.is_file():
            continue
        files.append(
            {
                "path": relative.as_posix(),
                "size_bytes": resolved.stat().st_size,
            }
        )
    files.sort(key=lambda item: item["path"].casefold())
    return {"files": files}


@app.put("/api/v1/inputs/{filename}", status_code=201)
async def upload_input_file(filename: str, request: Request) -> dict[str, Any]:
    """Upload one CSV to the input root; never overwrite an existing file."""
    if not INPUT_FILENAME_PATTERN.fullmatch(filename) or ".." in filename:
        raise HTTPException(
            status_code=400,
            detail="Filename must be a simple CSV filename using letters, numbers, dot, dash, or underscore.",
        )

    root = config.input_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    if target.exists() or target.is_symlink():
        raise HTTPException(status_code=409, detail="A file with this name already exists.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bioai-upload-", suffix=".tmp", dir=root
    )
    temporary_path = Path(temporary_name)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_INPUT_FILE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"CSV exceeds the {MAX_INPUT_FILE_BYTES // (1024 * 1024)} MiB upload limit.",
                    )
                stream.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded CSV is empty.")

        try:
            _validate_csv_file(temporary_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            # A same-filesystem hard link publishes the complete file atomically and
            # fails if another request created the target in the meantime.
            os.link(temporary_path, target)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="A file with this name already exists.") from exc

        return {"path": filename, "size_bytes": size}
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bioai-workbench"}


@app.get("/api/v1/workflows", response_model=WorkflowList)
def workflows() -> dict[str, list[dict[str, Any]]]:
    return {"workflows": list_workflows()}



def _resolve_validation_input(relative_name: str, field: str, errors: list[dict[str, str]]) -> Path | None:
    """Resolve a request input under the configured root without leaking host paths."""
    root = config.input_root.resolve()
    try:
        resolved = (root / relative_name).resolve(strict=True)
    except (OSError, RuntimeError):
        errors.append({"field": field, "message": "Select an existing CSV file from the input list."})
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.suffix.lower() != ".csv":
        errors.append({"field": field, "message": "Input must be a CSV file inside BIOAI_INPUT_ROOT."})
        return None
    return resolved


@app.post("/api/v1/inputs/validate")
def validate_deseq2_inputs(request: RunRequest) -> dict[str, Any]:
    """Preflight counts and metadata contracts before spending time on a workflow run."""
    errors: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "gene_count": 0,
        "sample_count": 0,
        "metadata_sample_count": 0,
        "condition_counts": {},
    }
    counts_path = _resolve_validation_input(request.counts_file, "counts_file", errors)
    metadata_path = _resolve_validation_input(request.metadata_file, "metadata_file", errors)
    counts_samples: list[str] = []
    gene_count = 0
    counts_valid = False

    if counts_path is not None:
        try:
            with counts_path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                header = next(reader, None)
                if header is None or len(header) < 3:
                    errors.append({
                        "field": "counts_file",
                        "message": "Counts CSV must contain gene_id plus at least two sample columns.",
                    })
                elif header[0] != "gene_id":
                    errors.append({
                        "field": "counts_file",
                        "message": "The first counts column must be named gene_id.",
                    })
                elif (
                    any(not name.strip() for name in header)
                    or len({name.casefold() for name in header}) != len(header)
                ):
                    errors.append({
                        "field": "counts_file",
                        "message": "Counts column names must be unique and non-empty.",
                    })
                else:
                    counts_samples = header[1:]
                    summary["sample_count"] = len(counts_samples)
                    seen_genes: set[str] = set()
                    counts_valid = True
                    for row_number, row in enumerate(reader, start=2):
                        if not row:
                            continue
                        if len(row) != len(header):
                            errors.append({
                                "field": "counts_file",
                                "message": f"Counts row {row_number} has a different number of columns than the header.",
                            })
                            counts_valid = False
                            break
                        gene_id = row[0]
                        if not gene_id.strip() or gene_id in seen_genes:
                            errors.append({
                                "field": "counts_file",
                                "message": f"Counts row {row_number} has a missing or duplicate gene ID.",
                            })
                            counts_valid = False
                            break
                        seen_genes.add(gene_id)
                        for value in row[1:]:
                            try:
                                count = float(value)
                            except (TypeError, ValueError):
                                count = math.nan
                            if (
                                not math.isfinite(count)
                                or count < 0
                                or count != math.floor(count)
                                or count > 2147483647
                            ):
                                errors.append({
                                    "field": "counts_file",
                                    "message": f"Counts row {row_number} contains a non-integer, negative, missing, or out-of-range count.",
                                })
                                counts_valid = False
                                break
                        if not counts_valid:
                            break
                        gene_count += 1
                    if counts_valid and gene_count == 0:
                        errors.append({
                            "field": "counts_file",
                            "message": "Counts CSV must contain at least one gene row.",
                        })
                        counts_valid = False
                    summary["gene_count"] = gene_count
        except (UnicodeDecodeError, csv.Error, OSError):
            errors.append({
                "field": "counts_file",
                "message": "Counts CSV could not be parsed as a UTF-8 table.",
            })

    metadata_valid = False
    metadata_samples: list[str] = []
    condition_counts: dict[str, int] = {}
    if metadata_path is not None:
        try:
            with metadata_path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                header = next(reader, None)
                if header is None or len(header) < 2:
                    errors.append({
                        "field": "metadata_file",
                        "message": "Metadata CSV must contain column names and at least one data column.",
                    })
                elif (
                    any(not name.strip() for name in header)
                    or len({name.casefold() for name in header}) != len(header)
                ):
                    errors.append({
                        "field": "metadata_file",
                        "message": "Metadata column names must be unique and non-empty.",
                    })
                elif "sample_id" not in header or request.condition not in header:
                    errors.append({
                        "field": "metadata_file",
                        "message": f"Metadata CSV must include sample_id and {request.condition}.",
                    })
                else:
                    sample_index = header.index("sample_id")
                    condition_index = header.index(request.condition)
                    seen_samples: set[str] = set()
                    metadata_valid = True
                    for row_number, row in enumerate(reader, start=2):
                        if not row:
                            continue
                        if len(row) != len(header):
                            errors.append({
                                "field": "metadata_file",
                                "message": f"Metadata row {row_number} has a different number of columns than the header.",
                            })
                            metadata_valid = False
                            break
                        sample_id = row[sample_index]
                        condition_value = row[condition_index]
                        if not sample_id.strip() or sample_id in seen_samples:
                            errors.append({
                                "field": "metadata_file",
                                "message": f"Metadata row {row_number} has a missing or duplicate sample_id.",
                            })
                            metadata_valid = False
                            break
                        seen_samples.add(sample_id)
                        metadata_samples.append(sample_id)
                        if condition_value not in {request.reference, request.contrast}:
                            errors.append({
                                "field": "condition",
                                "message": "The selected condition column must contain only the chosen reference and contrast levels.",
                            })
                            metadata_valid = False
                            break
                        condition_counts[condition_value] = condition_counts.get(condition_value, 0) + 1
                    summary["metadata_sample_count"] = len(metadata_samples)
                    summary["condition_counts"] = condition_counts
                    if metadata_valid and not metadata_samples:
                        errors.append({
                            "field": "metadata_file",
                            "message": "Metadata CSV must contain at least one sample row.",
                        })
                        metadata_valid = False
        except (UnicodeDecodeError, csv.Error, OSError):
            errors.append({
                "field": "metadata_file",
                "message": "Metadata CSV could not be parsed as a UTF-8 table.",
            })

    if counts_path is not None and metadata_path is not None and counts_samples and metadata_samples and metadata_valid:
        if set(counts_samples) != set(metadata_samples) or len(counts_samples) != len(metadata_samples):
            errors.append({
                "field": "metadata_file",
                "message": "Counts sample columns and metadata sample_id values must match exactly.",
            })
        if (
            condition_counts.get(request.reference, 0) < 2
            or condition_counts.get(request.contrast, 0) < 2
        ):
            errors.append({
                "field": "condition",
                "message": "At least two samples per condition are required.",
            })

    return {"valid": not errors, "errors": errors, "summary": summary}


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

    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise HTTPException(status_code=409, detail="Artifact checksum metadata is invalid.")

    digest = hashlib.sha256()
    with artifact_file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise HTTPException(status_code=409, detail="Artifact checksum mismatch; refusing download.")

    return FileResponse(
        artifact_file,
        filename=artifact_file.name,
        media_type="application/octet-stream",
        headers={"X-Artifact-SHA256": actual_hash},
    )
