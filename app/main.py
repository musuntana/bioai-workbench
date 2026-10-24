"""Local HTTP API and minimal web UI for BioAI Workbench."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import math
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.gene_lists import parse_gene_ids
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
from artifacts.manifest import ArtifactManifestError
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
MAX_RESULTS_FILE_BYTES = 100 * 1024 * 1024
MAX_RESULTS_ROWS = 500_000
MAX_VOLCANO_POINTS = 5_000


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
    if (
        not relative_name
        or "\x00" in relative_name
        or "\\" in relative_name
        or relative_name.startswith("/")
        or re.match(r"^[A-Za-z]:", relative_name)
        or any(part in {"", ".", ".."} for part in relative_name.split("/"))
    ):
        errors.append({"field": field, "message": "Input must be a safe relative CSV path."})
        return None
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



@app.get("/api/v1/inputs/preview")
def preview_input_file(
    filename: str = Query(min_length=1, max_length=240),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, Any]:
    """Preview a bounded number of CSV rows without exposing absolute paths."""
    errors: list[dict[str, str]] = []
    input_path = _resolve_validation_input(filename, "filename", errors)
    if input_path is None:
        raise HTTPException(status_code=404, detail="Input CSV not found.")
    try:
        size_bytes = input_path.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Input CSV not found.") from exc
    if size_bytes > MAX_INPUT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Input CSV exceeds the preview size limit.")

    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            columns = next(reader, None)
            if (
                columns is None
                or len(columns) < 2
                or any(not column.strip() for column in columns)
                or len({column.strip().casefold() for column in columns}) != len(columns)
            ):
                raise HTTPException(status_code=422, detail="Input CSV has an invalid header.")
            rows: list[list[str]] = []
            has_more = False
            for row in reader:
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != len(columns):
                    raise HTTPException(
                        status_code=422,
                        detail="Input CSV rows must have the same number of columns as the header.",
                    )
                if len(rows) >= limit:
                    has_more = True
                    break
                rows.append(row)
    except HTTPException:
        raise
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        raise HTTPException(status_code=422, detail="Input file is not a readable UTF-8 CSV.") from exc

    return {
        "path": filename,
        "size_bytes": size_bytes,
        "columns": columns,
        "rows": rows,
        "preview_limit": limit,
        "has_more": has_more,
    }


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
        "parent_run_id": record.get("parent_run_id"),
        "attempt": record.get("attempt", 1),
    }


@app.post("/api/v1/runs/{run_id}/rerun", response_model=RunAccepted, status_code=202)
def rerun_run(run_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Queue a new run using the source run's hash-verified immutable snapshots."""
    try:
        record = run_manager.create_rerun(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    request_data = {"workflow_id": record["workflow_id"], **record["parameters"]}
    background_tasks.add_task(
        run_manager.execute,
        record["run_id"],
        request_data,
        source_run_id=run_id,
    )
    return {
        "run_id": record["run_id"],
        "workflow_id": record["workflow_id"],
        "status": record["status"],
        "created_at": record["created_at"],
        "status_url": f"/api/v1/runs/{record['run_id']}",
        "parent_run_id": record["parent_run_id"],
        "attempt": record["attempt"],
    }


@app.get("/api/v1/runs", response_model=RunList)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: RunState | None = None,
) -> dict[str, Any]:
    return store.list_runs(limit=limit, offset=offset, status=status)


def _compare_gene_sets(
    run_a: str, run_b: str, padj_max: float, min_abs_log2fc: float,
    *, include_all: bool = False,
) -> dict[str, Any]:
    from app.deg_compare import compare_gene_sets

    return compare_gene_sets(
        run_a, run_b, _load_verified_result_rows,
        padj_max=padj_max, min_abs_log2fc=min_abs_log2fc, include_all=include_all,
    )


@app.get("/api/v1/runs/compare/genes")
def compare_run_genes(
    run_a: str = Query(..., min_length=32, max_length=32),
    run_b: str = Query(..., min_length=32, max_length=32),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
) -> dict[str, Any]:
    result = _compare_gene_sets(run_a, run_b, padj_max, min_abs_log2fc)
    result["genes"] = result["genes"][:100]
    result["preview_truncated"] = sum(
        result["counts"][key] for key in
        ("both_significant", "only_a_significant", "only_b_significant")
    ) > 100
    return result


@app.get("/api/v1/runs/compare/genes/report")
def download_gene_comparison_report(
    run_a: str = Query(..., min_length=32, max_length=32),
    run_b: str = Query(..., min_length=32, max_length=32),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
) -> Response:
    """Create an offline descriptive comparison from two verified successful runs."""
    from app.compare_report import render_gene_comparison_report

    aligned = _compare_gene_sets(
        run_a, run_b, padj_max, min_abs_log2fc, include_all=True
    )
    snapshots = compare_run_snapshots(run_a=run_a, run_b=run_b)
    html = render_gene_comparison_report(aligned, snapshots)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="deg_cross_run_report.html"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        },
    )


@app.get("/api/v1/runs/compare/genes/export")
def export_compared_genes(
    run_a: str = Query(..., min_length=32, max_length=32),
    run_b: str = Query(..., min_length=32, max_length=32),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
    scope: Literal["significant", "all"] = "significant",
) -> StreamingResponse:
    """Keep the legacy significant-set CSV, or export full-union aligned evidence."""
    include_all = scope == "all"
    result = _compare_gene_sets(
        run_a, run_b, padj_max, min_abs_log2fc, include_all=include_all
    )
    columns = (
        "gene_id", "category", "run_a_padj", "run_b_padj",
        "run_a_log2fc", "run_b_log2fc",
    )
    metadata: dict[str, Any] = {}
    if include_all:
        snapshot = compare_run_snapshots(run_a=run_a, run_b=run_b)
        left, right = snapshot["runs"]
        metadata = {
            "run_a_id": run_a, "run_b_id": run_b,
            "padj_max": padj_max, "min_abs_log2fc": min_abs_log2fc,
            "run_a_reference": left["parameters"].get("reference"),
            "run_b_reference": right["parameters"].get("reference"),
            "run_a_contrast": left["parameters"].get("contrast"),
            "run_b_contrast": right["parameters"].get("contrast"),
            "run_a_counts_sha256": snapshot["inputs"]["counts"]["run_a_sha256"],
            "run_b_counts_sha256": snapshot["inputs"]["counts"]["run_b_sha256"],
            "run_a_metadata_sha256": snapshot["inputs"]["metadata"]["run_a_sha256"],
            "run_b_metadata_sha256": snapshot["inputs"]["metadata"]["run_b_sha256"],
            "run_a_result_sha256": left["artifact_hashes"].get("differential_expression_all.csv"),
            "run_b_result_sha256": right["artifact_hashes"].get("differential_expression_all.csv"),
        }
        columns = (
            *columns,
            "run_a_base_mean", "run_b_base_mean",
            "run_a_significant", "run_b_significant",
            *metadata.keys(),
        )

    def safe_csv_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def csv_lines() -> Iterator[str]:
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(columns)
        yield stream.getvalue()
        for gene in result["genes"]:
            stream.seek(0)
            stream.truncate(0)
            values = [safe_csv_value({**gene, **metadata}.get(key)) for key in columns]
            writer.writerow(values)
            yield stream.getvalue()

    filename = "deg_all_gene_comparison.csv" if include_all else "deg_set_comparison.csv"
    return StreamingResponse(
        csv_lines(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/runs/compare")
def compare_run_snapshots(
    run_a: str = Query(..., min_length=32, max_length=32),
    run_b: str = Query(..., min_length=32, max_length=32),
) -> dict[str, Any]:
    """Compare saved run parameters and manifested artifact hashes."""
    from app.run_compare import compare_runs

    return compare_runs(run_manager, run_a, run_b)


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
    except ArtifactManifestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run_id": run_id, "artifacts": artifacts}



def _parse_result_number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_significant(row: dict[str, Any], padj_max: float, min_abs_log2fc: float) -> bool:
    padj = row.get("padj")
    log2_fold_change = row.get("log2FoldChange")
    return (
        isinstance(padj, (int, float))
        and isinstance(log2_fold_change, (int, float))
        and padj <= padj_max
        and abs(log2_fold_change) >= min_abs_log2fc
    )


def _sample_plot_points(
    significant: list[dict[str, Any]],
    other: list[dict[str, Any]],
    limit: int = MAX_VOLCANO_POINTS,
) -> list[dict[str, Any]]:
    """Keep all significant points when possible and evenly sample the rest."""
    def sample(points: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        if count <= 0 or not points:
            return []
        if len(points) <= count:
            return points
        return [points[(index * len(points)) // count] for index in range(count)]

    significant = sorted(significant, key=lambda point: point["log2FoldChange"])
    other = sorted(other, key=lambda point: point["log2FoldChange"])
    if len(significant) >= limit:
        return sample(significant, limit)
    return significant + sample(other, limit - len(significant))



def _sample_ma_points(
    points: list[dict[str, Any]],
    limit: int = MAX_VOLCANO_POINTS,
) -> list[dict[str, Any]]:
    """Sample across mean expression rather than significance to preserve MA-plot coverage."""
    points = sorted(points, key=lambda point: (point["baseMean"], point["gene_id"].casefold()))
    if len(points) <= limit:
        return points
    if limit == 1:
        return [points[len(points) // 2]]
    return [points[(index * (len(points) - 1)) // (limit - 1)] for index in range(limit)]


def _include_focused_point(
    sampled: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    focus_gene: str,
    limit: int = MAX_VOLCANO_POINTS,
) -> list[dict[str, Any]]:
    """Keep a requested gene visible without exceeding the plot sampling cap."""
    if not focus_gene or limit <= 0:
        return sampled
    focused = next((point for point in candidates if point["gene_id"] == focus_gene), None)
    if focused is None or any(point["gene_id"] == focus_gene for point in sampled):
        return sampled
    if len(sampled) >= limit:
        return [*sampled[: limit - 1], focused]
    return [*sampled, focused]


def _load_verified_result_rows(
    run_id: str, padj_max: float, min_abs_log2fc: float, *, preserve_raw: bool = False
) -> tuple[list[str], list[dict[str, Any]]]:
    """Read only the manifest-verified output; optionally preserve exact source CSV values."""
    try:
        record = run_manager.store.get(run_id)
        artifacts = run_manager.get_artifacts(run_id)
        run_dir = run_manager.store.run_dir(run_id)
    except ArtifactManifestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run not found.") from exc

    if record is None or artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if record.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="Results are available only after a run succeeds.")

    entry = next(
        (item for item in artifacts if item.get("path") == "differential_expression_all.csv"),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Differential-expression results are unavailable.")

    output_root = (run_dir / "outputs").resolve()
    candidate = output_root / "differential_expression_all.csv"
    if candidate.is_symlink():
        raise HTTPException(status_code=404, detail="Differential-expression results are unavailable.")
    try:
        result_file = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="Differential-expression results are unavailable.") from exc
    if not result_file.is_relative_to(output_root) or not result_file.is_file():
        raise HTTPException(status_code=404, detail="Differential-expression results are unavailable.")
    if result_file.stat().st_size > MAX_RESULTS_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Result artifact exceeds the preview size limit.")

    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise HTTPException(status_code=409, detail="Result checksum metadata is invalid.")
    digest = hashlib.sha256()
    with result_file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_hash):
        raise HTTPException(status_code=409, detail="Result checksum mismatch; refusing preview.")

    try:
        with result_file.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            columns = reader.fieldnames or []
            required_columns = {"gene_id", "baseMean", "log2FoldChange", "pvalue", "padj"}
            if not required_columns.issubset(columns):
                raise HTTPException(status_code=409, detail="Result artifact does not match the DESeq2 result schema.")

            all_rows: list[dict[str, Any]] = []
            for row_number, raw_row in enumerate(reader, start=2):
                if row_number > MAX_RESULTS_ROWS + 1:
                    raise HTTPException(status_code=413, detail="Result artifact exceeds the preview row limit.")
                if None in raw_row or any(value is None for value in raw_row.values()):
                    raise HTTPException(status_code=409, detail="Result artifact contains a malformed row.")
                gene_id = raw_row.get("gene_id", "")
                if not gene_id.strip():
                    raise HTTPException(status_code=409, detail="Result artifact contains an empty gene ID.")
                row: dict[str, Any] = {"gene_id": gene_id}
                if preserve_raw:
                    row["_raw_csv"] = [raw_row.get(column, "") for column in columns]
                numeric_columns = {"baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"}
                for column in columns:
                    if column == "gene_id":
                        continue
                    raw_value = raw_row.get(column)
                    if column in numeric_columns:
                        row[column] = _parse_result_number(raw_value)
                    else:
                        row[column] = raw_value
                row["significant"] = _is_significant(row, padj_max, min_abs_log2fc)
                all_rows.append(row)
    except HTTPException:
        raise
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        raise HTTPException(status_code=409, detail="Result artifact is not a readable CSV.") from exc

    if not all_rows:
        raise HTTPException(status_code=409, detail="Result artifact contains no gene rows.")

    return columns, all_rows


def _filter_sort_result_rows(
    rows: list[dict[str, Any]],
    *,
    q: str,
    significant_only: bool,
    sort_by: Literal["padj", "log2FoldChange", "baseMean", "gene_id"],
    sort_order: Literal["asc", "desc"],
    gene_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Apply identical filtering and ordering to previews and CSV exports."""
    search_term = q.casefold().strip()
    exact_gene_ids = set(gene_ids)
    filtered_rows = [
        row for row in rows
        if (not search_term or search_term in row["gene_id"].casefold())
        and (not exact_gene_ids or row["gene_id"] in exact_gene_ids)
        and (not significant_only or row["significant"])
    ]
    if sort_by == "gene_id":
        filtered_rows.sort(
            key=lambda row: row["gene_id"].casefold(),
            reverse=sort_order == "desc",
        )
    else:
        def sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
            value = row.get(sort_by)
            if not isinstance(value, (int, float)):
                return (1, 0.0, row["gene_id"].casefold())
            return (
                0,
                value if sort_order == "asc" else -value,
                row["gene_id"].casefold(),
            )
        filtered_rows.sort(key=sort_key)
    return filtered_rows


@app.get("/api/v1/runs/{run_id}/genes/{gene_id}")
def get_gene_detail(
    run_id: str,
    gene_id: str,
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1, ge=0, le=1000),
) -> dict[str, Any]:
    """Return exact gene statistics from the verified run artifact."""
    if not gene_id or len(gene_id) > 200:
        raise HTTPException(status_code=422, detail="Gene ID must contain 1–200 characters.")
    _, rows = _load_verified_result_rows(run_id, padj_max, min_abs_log2fc)
    matches = [row for row in rows if row["gene_id"] == gene_id]
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Duplicate gene IDs prevent detail lookup.")
    if not matches:
        raise HTTPException(status_code=404, detail="Gene not found in this run.")
    return {"run_id": run_id, "gene": matches[0], "padj_max": padj_max,
            "min_abs_log2fc": min_abs_log2fc}


@app.get("/api/v1/runs/compare/gene")
def compare_single_gene(
    run_a: str = Query(..., min_length=32, max_length=32),
    run_b: str = Query(..., min_length=32, max_length=32),
    gene_id: str = Query(..., min_length=1, max_length=200),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1, ge=0, le=1000),
) -> dict[str, Any]:
    """Compare one gene in two independently verified DESeq2 runs."""
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", run_a) or not re.fullmatch(r"[a-f0-9]{32}", run_b):
        raise HTTPException(status_code=422, detail="Invalid run ID.")
    if run_a == run_b:
        raise HTTPException(status_code=422, detail="Select two different runs.")
    results = {}
    for label, run_id in (("run_a", run_a), ("run_b", run_b)):
        _, rows = _load_verified_result_rows(run_id, padj_max, min_abs_log2fc)
        matches = [row for row in rows if row["gene_id"] == gene_id]
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail="Duplicate gene IDs prevent comparison.")
        results[label] = matches[0] if matches else None
    return {"gene_id": gene_id, "run_a": run_a, "run_b": run_b,
            "a": results["run_a"], "b": results["run_b"],
            "note": "Different significance classifications do not establish a statistical difference between runs. Confirm contrast direction before comparing log2FC."}


@app.get("/api/v1/runs/{run_id}/results")
def get_run_results(
    run_id: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=200),
    significant_only: bool = False,
    focus_gene: str = Query(default="", max_length=200),
    gene_ids: str = Query(default="", max_length=4000),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
    sort_by: Literal["padj", "log2FoldChange", "baseMean", "gene_id"] = "padj",
    sort_order: Literal["asc", "desc"] = "asc",
) -> dict[str, Any]:
    """Return a paginated, filterable view of the verified DESeq2 result artifact."""
    try:
        requested_ids = parse_gene_ids(gene_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    columns, all_rows = _load_verified_result_rows(run_id, padj_max, min_abs_log2fc)

    focus_matches = [row for row in all_rows if focus_gene and row["gene_id"] == focus_gene]
    if len(focus_matches) > 1:
        raise HTTPException(status_code=409, detail="Duplicate gene IDs prevent focus lookup.")
    focused_row = focus_matches[0] if focus_matches else None

    significant_rows = [
        row for row in all_rows if _is_significant(row, padj_max, min_abs_log2fc)
    ]
    missing_padj_count = sum(row.get("padj") is None for row in all_rows)
    plot_candidates: list[dict[str, Any]] = []
    for row in all_rows:
        log2_fold_change = row.get("log2FoldChange")
        padj = row.get("padj")
        if not isinstance(log2_fold_change, (int, float)) or not isinstance(padj, (int, float)):
            continue
        plot_candidates.append({
            "gene_id": row["gene_id"],
            "log2FoldChange": log2_fold_change,
            "padj": padj,
            "significant": _is_significant(row, padj_max, min_abs_log2fc),
        })

    significant_points = [point for point in plot_candidates if point["significant"]]
    other_points = [point for point in plot_candidates if not point["significant"]]
    plot_points = _include_focused_point(
        _sample_plot_points(significant_points, other_points), plot_candidates, focus_gene
    )

    ma_candidates: list[dict[str, Any]] = []
    for row in all_rows:
        base_mean = row.get("baseMean")
        log2_fold_change = row.get("log2FoldChange")
        if (
            not isinstance(base_mean, (int, float))
            or base_mean < 0
            or not isinstance(log2_fold_change, (int, float))
        ):
            continue
        ma_candidates.append({
            "gene_id": row["gene_id"],
            "baseMean": base_mean,
            "log2FoldChange": log2_fold_change,
            "significant": _is_significant(row, padj_max, min_abs_log2fc),
        })
    ma_points = _include_focused_point(
        _sample_ma_points(ma_candidates), ma_candidates, focus_gene
    )

    filtered_rows = _filter_sort_result_rows(
        all_rows, q=q, significant_only=significant_only, sort_by=sort_by,
        sort_order=sort_order, gene_ids=requested_ids,
    )
    present_ids = {row["gene_id"] for row in all_rows}
    missing_ids = [identifier for identifier in requested_ids if identifier not in present_ids]

    return {
        "run_id": run_id,
        "columns": columns,
        "rows": filtered_rows[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "filtered_genes": len(filtered_rows),
        "gene_filter": {
            "requested": len(requested_ids),
            "found": len(requested_ids) - len(missing_ids),
            "missing": missing_ids,
        },
        "summary": {
            "total_genes": len(all_rows),
            "significant_genes": len(significant_rows),
            "missing_padj_genes": missing_padj_count,
            "plot_eligible_genes": len(plot_candidates),
            "plot_points_returned": len(plot_points),
            "plot_points_truncated": len(plot_candidates) > len(plot_points),
            "ma_eligible_genes": len(ma_candidates),
            "ma_points_returned": len(ma_points),
            "ma_points_truncated": len(ma_candidates) > len(ma_points),
            "padj_max": padj_max,
            "min_abs_log2fc": min_abs_log2fc,
        },
        "plot_points": plot_points,
        "ma_points": ma_points,
        "focus": {
            "gene_id": focus_gene or None,
            "found": focused_row is not None,
            "volcano_plottable": any(point["gene_id"] == focus_gene for point in plot_candidates),
            "ma_plottable": any(point["gene_id"] == focus_gene for point in ma_candidates),
        },
    }


@app.get("/api/v1/runs/{run_id}/report")
def download_run_report(
    run_id: str,
    gene_ids: str = Query(default="", max_length=4000),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
) -> Response:
    """Download a run-wide report or an exact, bounded gene-list report."""
    from app.report import render_html_report

    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise HTTPException(status_code=404, detail="Run not found.")
    try:
        requested_ids = parse_gene_ids(gene_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    has_gene_list = bool(requested_ids)
    preview = get_run_results(
        run_id=run_id,
        limit=100 if has_gene_list else 20,
        offset=0,
        q="",
        significant_only=not has_gene_list,
        focus_gene="",
        gene_ids="\n".join(requested_ids),
        padj_max=padj_max,
        min_abs_log2fc=min_abs_log2fc,
        sort_by="padj",
        sort_order="asc",
    )
    if has_gene_list:
        # Report plots should describe the same selected genes as its table,
        # not the full-run point sample returned by the interactive explorer.
        rows = preview["rows"]
        volcano_points = [
            {
                "gene_id": row["gene_id"],
                "log2FoldChange": row.get("log2FoldChange"),
                "padj": row.get("padj"),
                "significant": row.get("significant", False),
            }
            for row in rows
            if isinstance(row.get("log2FoldChange"), (int, float))
            and isinstance(row.get("padj"), (int, float))
        ]
        ma_points = [
            {
                "gene_id": row["gene_id"],
                "baseMean": row.get("baseMean"),
                "log2FoldChange": row.get("log2FoldChange"),
                "significant": row.get("significant", False),
            }
            for row in rows
            if isinstance(row.get("baseMean"), (int, float))
            and row["baseMean"] >= 0
            and isinstance(row.get("log2FoldChange"), (int, float))
        ]
        preview["plot_points"] = volcano_points
        preview["ma_points"] = ma_points
        summary = preview["summary"]
        summary["plot_eligible_genes"] = len(volcano_points)
        summary["plot_points_returned"] = len(volcano_points)
        summary["plot_points_truncated"] = False
        summary["ma_eligible_genes"] = len(ma_points)
        summary["ma_points_returned"] = len(ma_points)
        summary["ma_points_truncated"] = False

    record = run_manager.store.get(run_id)
    artifacts = run_manager.get_artifacts(run_id)
    if record is None or artifacts is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    report = render_html_report(record, preview, artifacts)
    report_kind = "gene_list_report" if has_gene_list else "report"
    return Response(
        content=report,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="deseq2_{report_kind}_{run_id}.html"'
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            ),
        },
    )


@app.get("/api/v1/runs/{run_id}/results/export")
def export_run_results(
    run_id: str,
    q: str = Query(default="", max_length=200),
    significant_only: bool = False,
    gene_ids: str = Query(default="", max_length=4000),
    padj_max: float = Query(default=0.05, gt=0, le=1),
    min_abs_log2fc: float = Query(default=1.0, ge=0, le=1000),
    sort_by: Literal["padj", "log2FoldChange", "baseMean", "gene_id"] = "padj",
    sort_order: Literal["asc", "desc"] = "asc",
) -> StreamingResponse:
    """Export all matching genes, preserving the exact values of the verified source artifact."""
    try:
        requested_ids = parse_gene_ids(gene_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    columns, rows = _load_verified_result_rows(
        run_id, padj_max, min_abs_log2fc, preserve_raw=True
    )
    filtered = _filter_sort_result_rows(
        rows, q=q, significant_only=significant_only, sort_by=sort_by,
        sort_order=sort_order, gene_ids=requested_ids,
    )

    def iter_csv() -> Iterator[str]:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for index, row in enumerate(filtered, start=1):
            writer.writerow(row["_raw_csv"])
            if index % 250 == 0:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
        if buffer.tell():
            yield buffer.getvalue()

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="deseq2_filtered_{run_id}.csv"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/runs/{run_id}/artifacts/{artifact_path:path}", include_in_schema=True)
def download_run_artifact(run_id: str, artifact_path: str) -> FileResponse:
    """Download a file only when it is listed in the run's artifact manifest."""
    try:
        artifacts = run_manager.get_artifacts(run_id)
        run_dir = run_manager.store.run_dir(run_id)
    except ArtifactManifestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
