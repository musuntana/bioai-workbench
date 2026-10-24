"""Safe local executor for registered workflows."""

from __future__ import annotations

import hashlib
import hmac
import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.registry import get_workflow
from app.schemas import RunRequest
from artifacts.manifest import load_artifact_manifest, write_artifact_manifest
from runtime.config import RuntimeConfig
from runtime.environment import read_environment_versions
from runtime.state import RunStore, utc_now

EXPECTED_DESEQ2_OUTPUTS = (
    "differential_expression_all.csv",
    "differential_expression_significant.csv",
    "run_manifest.tsv",
    "session_info.txt",
)
MAX_RUN_FAMILY_ATTEMPTS = 5
_TERMINAL_STATUSES = {"succeeded", "failed", "timed_out"}


class RunManager:
    """Run only registered workflow entrypoints with bounded runtime and log output."""

    def __init__(
        self, config: RuntimeConfig | None = None, store: RunStore | None = None
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.config.prepare()
        self.store = store or RunStore(self.config.runs_root)
        # A new local runtime has no live worker handles for persisted in-flight runs.
        # Mark them failed rather than exposing stale queued/running status forever.
        self.store.recover_interrupted_runs()
        self._slots = threading.BoundedSemaphore(self.config.max_concurrent_runs)

    def create_run(self, request: RunRequest) -> dict[str, Any]:
        if get_workflow(request.workflow_id) is None:
            raise ValueError("Workflow is not registered.")
        return self.store.create(
            uuid4().hex,
            request.workflow_id,
            parameters=request.model_dump(exclude={"workflow_id"}),
        )

    def create_rerun(self, source_run_id: str) -> dict[str, Any]:
        """Create a bounded rerun from a terminal run's hash-verified snapshots."""
        source_record, request, _ = self._validated_rerun_source(source_run_id)
        root_run_id = source_record.get("root_run_id") or source_run_id
        try:
            return self.store.create(
                uuid4().hex,
                request.workflow_id,
                parameters=request.model_dump(exclude={"workflow_id"}),
                parent_run_id=source_run_id,
                root_run_id=root_run_id,
                max_family_attempts=MAX_RUN_FAMILY_ATTEMPTS,
            )
        except ValueError as exc:
            if "maximum number of attempts" in str(exc):
                raise ValueError(
                    f"This run lineage is limited to {MAX_RUN_FAMILY_ATTEMPTS} total attempts."
                ) from exc
            raise

    def _validated_rerun_source(
        self, source_run_id: str
    ) -> tuple[dict[str, Any], RunRequest, dict[str, Path]]:
        """Check terminal state and verify every immutable snapshot against recorded hashes."""
        try:
            record = self.store.get(source_run_id)
        except ValueError as exc:
            raise FileNotFoundError("Run not found.") from exc
        if record is None:
            raise FileNotFoundError("Run not found.")
        if record.get("status") not in _TERMINAL_STATUSES:
            raise ValueError("Only completed runs can be rerun.")
        environment_provenance = record.get("environment_provenance")
        input_provenance = record.get("input_provenance")
        if not isinstance(environment_provenance, dict) or not isinstance(input_provenance, dict):
            raise ValueError("This run has no verified immutable snapshots and cannot be rerun.")
        workflow_hash = environment_provenance.get("workflow_sha256")
        if not isinstance(workflow_hash, str) or len(workflow_hash) != 64:
            raise ValueError("This run has no verified immutable snapshots and cannot be rerun.")

        expected_hashes: dict[str, str] = {"workflow.R": workflow_hash}
        for role in ("counts", "metadata"):
            details = input_provenance.get(role)
            digest = details.get("sha256") if isinstance(details, dict) else None
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError("This run has no verified immutable snapshots and cannot be rerun.")
            expected_hashes[f"{role}.csv"] = digest

        snapshots = {
            name: self._verified_snapshot_path(source_run_id, name, expected_hash)
            for name, expected_hash in expected_hashes.items()
        }
        try:
            request = RunRequest.model_validate(
                {"workflow_id": record["workflow_id"], **record["parameters"]}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Run parameters cannot be revalidated; this run cannot be rerun.") from exc
        return record, request, snapshots

    def _verified_snapshot_path(self, run_id: str, filename: str, expected_sha256: str) -> Path:
        """Resolve a fixed-name snapshot within a run and confirm its recorded digest."""
        try:
            run_dir = self.store.run_dir(run_id)
            if run_dir.is_symlink():
                raise ValueError
            resolved_run = run_dir.resolve(strict=True)
            if not resolved_run.is_relative_to(self.store.root):
                raise ValueError
            tmp_dir = resolved_run / "tmp"
            if tmp_dir.is_symlink():
                raise ValueError
            resolved_tmp = tmp_dir.resolve(strict=True)
            if not resolved_tmp.is_relative_to(resolved_run):
                raise ValueError
            candidate = resolved_tmp / filename
            if candidate.is_symlink():
                raise ValueError
            snapshot = candidate.resolve(strict=True)
            if not snapshot.is_relative_to(resolved_tmp) or not snapshot.is_file():
                raise ValueError
            digest = _sha256_file(snapshot)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(
                "This run has no valid immutable snapshots and cannot be rerun."
            ) from exc
        if not _constant_time_digest_match(digest, expected_sha256):
            raise ValueError("A recorded snapshot checksum does not match; this run cannot be rerun.")
        return snapshot

    @staticmethod
    def _copy_snapshot(source: Path, destination: Path, expected_sha256: str) -> str:
        """Copy a verified snapshot into a new run while checking the bytes being copied."""
        digest = hashlib.sha256()
        try:
            with source.open("rb") as input_stream, destination.open("xb") as output_stream:
                while chunk := input_stream.read(1024 * 1024):
                    digest.update(chunk)
                    output_stream.write(chunk)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise ValueError("A required immutable snapshot could not be copied.") from exc
        actual_sha256 = digest.hexdigest()
        if not _constant_time_digest_match(actual_sha256, expected_sha256):
            destination.unlink(missing_ok=True)
            raise ValueError("A recorded snapshot checksum does not match; this run cannot be rerun.")
        return actual_sha256

    def execute(
        self,
        run_id: str,
        request_data: dict[str, Any],
        *,
        source_run_id: str | None = None,
    ) -> None:
        """Execute a previously queued request. Safe to pass as a background task."""
        run_dir = self.store.run_dir(run_id)
        log_path = run_dir / "run.log"
        output_dir = run_dir / "outputs"
        tmp_dir = run_dir / "tmp"
        if not self.store.claim_queued_run(run_id):
            # Duplicate dispatches must never truncate the existing run log or
            # overwrite immutable artifacts. A rerun requires its own run ID.
            return

        try:
            tmp_dir.mkdir(exist_ok=True)
            request = RunRequest.model_validate(request_data)
            workflow = get_workflow(request.workflow_id)
            if workflow is None:
                raise ValueError("Workflow is not registered.")
            workflow_snapshot = tmp_dir / "workflow.R"
            snapshots: dict[str, Path] = {}
            provenance: dict[str, dict[str, Any]] = {}

            if source_run_id is not None:
                source_record, source_request, source_snapshots = self._validated_rerun_source(
                    source_run_id
                )
                if (
                    source_record.get("workflow_id") != request.workflow_id
                    or source_request.model_dump() != request.model_dump()
                ):
                    raise ValueError("Rerun parameters do not match the source run.")
                source_environment = source_record["environment_provenance"]
                workflow_hash = self._copy_snapshot(
                    source_snapshots["workflow.R"],
                    workflow_snapshot,
                    source_environment["workflow_sha256"],
                )
                for role in ("counts", "metadata"):
                    source_details = source_record["input_provenance"][role]
                    snapshot = tmp_dir / f"{role}.csv"
                    self._copy_snapshot(
                        source_snapshots[f"{role}.csv"],
                        snapshot,
                        source_details["sha256"],
                    )
                    snapshots[role] = snapshot
                    provenance[role] = dict(source_details)
            else:
                if not workflow.entrypoint.is_file():
                    raise RuntimeError("The registered workflow entrypoint is missing.")

                # Run a private script copy: the provenance hash identifies
                # exactly the script bytes submitted to Rscript.
                digest = hashlib.sha256()
                with workflow.entrypoint.open("rb") as source, workflow_snapshot.open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                workflow_hash = digest.hexdigest()
                counts_path = self._resolve_input(request.counts_file)
                metadata_path = self._resolve_input(request.metadata_file)
                # Freeze the bytes consumed by R, not merely a mutable input filename.
                for role, path in (("counts", counts_path), ("metadata", metadata_path)):
                    snapshot = tmp_dir / f"{role}.csv"
                    digest = hashlib.sha256()
                    with path.open("rb") as source, snapshot.open("xb") as target:
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                            digest.update(chunk)
                    snapshots[role] = snapshot
                    provenance[role] = {
                        "filename": request.counts_file if role == "counts" else request.metadata_file,
                        "sha256": digest.hexdigest(),
                        "size_bytes": snapshot.stat().st_size,
                    }

            self.store.update(
                run_id, environment_provenance={"workflow_sha256": workflow_hash}
            )
            self.store.update(run_id, input_provenance=provenance)
            rscript = self._find_rscript()
            command = [
                rscript,
                str(workflow_snapshot),
                "--counts",
                str(snapshots["counts"]),
                "--metadata",
                str(snapshots["metadata"]),
                "--condition",
                request.condition,
                "--reference",
                request.reference,
                "--contrast",
                request.contrast,
                "--alpha",
                str(request.alpha),
                "--outdir",
                str(output_dir),
            ]
            environment = self._child_environment(tmp_dir)

            with self._slots:
                return_code, timed_out, log_truncated = _run_bounded_process(
                    command=command,
                    cwd=self.config.project_root,
                    environment=environment,
                    log_path=log_path,
                    timeout_seconds=self.config.max_run_seconds,
                    max_log_bytes=self.config.max_log_bytes,
                )

            if timed_out:
                self.store.update(
                    run_id,
                    status="timed_out",
                    finished_at=utc_now(),
                    exit_code=return_code,
                    error_message="Workflow exceeded the configured runtime limit.",
                    log_truncated=log_truncated,
                )
                return

            if return_code != 0:
                self.store.update(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    exit_code=return_code,
                    error_message=f"Workflow exited with code {return_code}; inspect the run log.",
                    log_truncated=log_truncated,
                )
                return

            missing_outputs = [
                name for name in EXPECTED_DESEQ2_OUTPUTS if not (output_dir / name).is_file()
            ]
            if missing_outputs:
                with log_path.open("ab") as stream:
                    stream.write(
                        ("\nMissing expected workflow outputs: " + ", ".join(missing_outputs) + "\n").encode()
                    )
                self.store.update(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    exit_code=1,
                    error_message="Workflow exited successfully but required output artifacts are missing.",
                    log_truncated=log_truncated,
                )
                return

            manifest = write_artifact_manifest(
                output_dir, run_id=run_id, workflow_id=request.workflow_id
            )
            environment_versions = read_environment_versions(output_dir / "run_manifest.tsv")
            environment_versions["workflow_sha256"] = workflow_hash
            self.store.update(run_id, environment_provenance=environment_versions)
            self.store.update(
                run_id,
                status="succeeded",
                finished_at=utc_now(),
                exit_code=0,
                artifact_count=len(manifest["artifacts"]),
                log_truncated=log_truncated,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            # Keep public status messages generic; detailed paths are not copied into run metadata.
            safe_message = _public_error_message(exc)
            with log_path.open("ab") as stream:
                stream.write((safe_message + "\n").encode("utf-8", errors="replace"))
            self.store.update(
                run_id,
                status="failed",
                finished_at=utc_now(),
                exit_code=None,
                error_message=safe_message,
            )

    def get_log(self, run_id: str) -> tuple[str, bool] | None:
        if self.store.get(run_id) is None:
            return None
        log_path = self.store.run_dir(run_id) / "run.log"
        if not log_path.is_file():
            return "", False
        content = log_path.read_bytes()
        return content.decode("utf-8", errors="replace"), bool(
            self.store.get(run_id).get("log_truncated", False)
        )

    def get_artifacts(self, run_id: str) -> list[dict[str, Any]] | None:
        record = self.store.get(run_id)
        if record is None:
            return None
        # Partial outputs from queued/running/failed runs are never advertised.
        if record.get("status") != "succeeded":
            return []
        return load_artifact_manifest(
            self.store.run_dir(run_id) / "outputs",
            run_id=run_id,
            workflow_id=record["workflow_id"],
            required_paths=EXPECTED_DESEQ2_OUTPUTS,
        )["artifacts"]

    def _resolve_input(self, relative_name: str) -> Path:
        root = self.config.input_root.resolve()
        try:
            resolved = (root / relative_name).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("An input CSV was not found under BIOAI_INPUT_ROOT.") from exc
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Input CSV files must remain under BIOAI_INPUT_ROOT.")
        if resolved.suffix.lower() != ".csv":
            raise ValueError("Workflow inputs must be CSV files.")
        return resolved

    @staticmethod
    def _find_rscript() -> str:
        path = shutil.which("Rscript")
        if path is None:
            raise RuntimeError("Rscript was not found; install R and make Rscript available on PATH.")
        return path

    @staticmethod
    def _child_environment(tmp_dir: Path) -> dict[str, str]:
        # Do not forward arbitrary API-server environment variables to analysis subprocesses.
        allowed = ("PATH", "HOME", "R_HOME", "R_LIBS_USER", "R_LIBS_SITE", "LANG", "LC_ALL")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        environment["TMPDIR"] = str(tmp_dir)
        environment.setdefault("LANG", "C.UTF-8")
        environment.setdefault("LC_ALL", "C.UTF-8")
        return environment


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _constant_time_digest_match(actual: str, expected: str) -> bool:
    return hmac.compare_digest(actual, expected)


def _public_error_message(exc: Exception) -> str:
    message = str(exc)
    if message.startswith("An input CSV") or message.startswith("Input CSV"):
        return message
    if message.startswith("Workflow ") or message.startswith("Rscript "):
        return message
    if isinstance(exc, FileNotFoundError):
        return "A required runtime file was not found."
    return "Run setup failed; check local configuration and the run log."


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate the process group, including children that outlive the leader."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        elif process.poll() is None:
            process.terminate()
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass

    # The parent may have exited while a child still holds the output pipe open.
    # On POSIX, signal the group even when process.poll() is no longer None.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _run_bounded_process(
    *,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    log_path: Path,
    timeout_seconds: int,
    max_log_bytes: int,
) -> tuple[int, bool, bool]:
    """Stream child output to a bounded log while enforcing a wall-clock timeout."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        shell=False,
        start_new_session=(os.name == "posix"),
    )
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    log_truncated = False
    bytes_written = 0

    with log_path.open("wb") as log_stream:
        while process.poll() is None or selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not timed_out:
                timed_out = True
                _stop_process(process)

            if not selector.get_map():
                # A child may close stdout and keep running; timeout still applies.
                time.sleep(0.05)
                continue

            events = selector.select(timeout=0.1)
            for key, _ in events:
                chunk = os.read(key.fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                available = max_log_bytes - bytes_written
                if available > 0:
                    kept = chunk[:available]
                    log_stream.write(kept)
                    bytes_written += len(kept)
                if len(chunk) > max(available, 0):
                    log_truncated = True

    selector.close()
    try:
        return_code = process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        return_code = process.poll()
        if return_code is None:
            return_code = -1
    return return_code, timed_out, log_truncated
