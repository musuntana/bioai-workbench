"""Safe local executor for registered workflows."""

from __future__ import annotations

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
from artifacts.manifest import write_artifact_manifest
from runtime.config import RuntimeConfig
from runtime.state import RunStore, utc_now

EXPECTED_DESEQ2_OUTPUTS = (
    "differential_expression_all.csv",
    "differential_expression_significant.csv",
    "run_manifest.tsv",
    "session_info.txt",
)


class RunManager:
    """Run only registered workflow entrypoints with bounded runtime and log output."""

    def __init__(
        self, config: RuntimeConfig | None = None, store: RunStore | None = None
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.config.prepare()
        self.store = store or RunStore(self.config.runs_root)
        self._slots = threading.BoundedSemaphore(self.config.max_concurrent_runs)

    def create_run(self, request: RunRequest) -> dict[str, Any]:
        if get_workflow(request.workflow_id) is None:
            raise ValueError("Workflow is not registered.")
        return self.store.create(
            uuid4().hex,
            request.workflow_id,
            parameters=request.model_dump(exclude={"workflow_id"}),
        )

    def execute(self, run_id: str, request_data: dict[str, Any]) -> None:
        """Execute a previously queued request. Safe to pass as a background task."""
        run_dir = self.store.run_dir(run_id)
        log_path = run_dir / "run.log"
        output_dir = run_dir / "outputs"
        tmp_dir = run_dir / "tmp"
        tmp_dir.mkdir(exist_ok=True)

        self.store.update(run_id, status="running", started_at=utc_now())
        try:
            request = RunRequest.model_validate(request_data)
            workflow = get_workflow(request.workflow_id)
            if workflow is None:
                raise ValueError("Workflow is not registered.")
            if not workflow.entrypoint.is_file():
                raise RuntimeError("The registered workflow entrypoint is missing.")

            counts_path = self._resolve_input(request.counts_file)
            metadata_path = self._resolve_input(request.metadata_file)
            rscript = self._find_rscript()
            command = [
                rscript,
                str(workflow.entrypoint),
                "--counts",
                str(counts_path),
                "--metadata",
                str(metadata_path),
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
        if self.store.get(run_id) is None:
            return None
        manifest_path = self.store.run_dir(run_id) / "outputs" / "artifact_manifest.json"
        if not manifest_path.is_file():
            return []
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest.get("artifacts", [])

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
