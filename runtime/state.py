"""Small file-backed run store for a single-process local workbench."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_ALLOWED_STATUSES = {"queued", "running", "cancelling", "cancelled", "succeeded", "failed", "timed_out"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    """Persist run state as atomic JSON files beneath the configured runs directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _run_dir(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run ID.")
        return self.root / run_id

    def create(
        self,
        run_id: str,
        workflow_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        parent_run_id: str | None = None,
        root_run_id: str | None = None,
        attempt: int | None = None,
        max_family_attempts: int | None = None,
    ) -> dict[str, Any]:
        if parent_run_id is not None and not _RUN_ID.fullmatch(parent_run_id):
            raise ValueError("Invalid parent run ID.")
        if root_run_id is not None and not _RUN_ID.fullmatch(root_run_id):
            raise ValueError("Invalid root run ID.")
        if attempt is not None and (
            isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1
        ):
            raise ValueError("Run attempt must be a positive integer.")
        if max_family_attempts is not None and (
            isinstance(max_family_attempts, bool)
            or not isinstance(max_family_attempts, int)
            or max_family_attempts < 1
        ):
            raise ValueError("Maximum family attempts must be a positive integer.")
        root_id = root_run_id or run_id
        now = utc_now()
        record: dict[str, Any] = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "parameters": dict(parameters or {}),
            "parent_run_id": parent_run_id,
            "root_run_id": root_id,
            "attempt": attempt or 1,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "error_message": None,
            "artifact_count": 0,
            "log_truncated": False,
            "input_provenance": {},
            "environment_provenance": {},
        }
        with self._lock:
            if parent_run_id is not None:
                family_count = self._count_runs_in_family_unlocked(root_id)
                if max_family_attempts is not None and family_count >= max_family_attempts:
                    raise ValueError("Run lineage reached the maximum number of attempts.")
                record["attempt"] = attempt or (family_count + 1)
            run_dir = self._run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=False)
            (run_dir / "outputs").mkdir()
            self._write(run_id, record)
        return record

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(run_id) / "run.json"
        with self._lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

    def claim_queued_run(self, run_id: str) -> bool:
        """Claim one queued run for this process; never reopen an active/terminal run.

        The file store is deliberately single-process. The lock makes a duplicate
        background-task dispatch harmless within the same runtime instance, not
        a distributed lease or cross-process fencing mechanism.
        """
        with self._lock:
            record = self.get(run_id)
            if record is None:
                raise FileNotFoundError("Run not found.")
            if record["status"] != "queued":
                return False
            now = utc_now()
            record.update(status="running", started_at=now, updated_at=now)
            self._write(run_id, record)
            return True

    def request_cancel(self, run_id: str) -> dict[str, Any]:
        """Move queued/active runs toward cancellation without changing terminal history."""
        with self._lock:
            record = self.get(run_id)
            if record is None:
                raise FileNotFoundError("Run not found.")
            status = record["status"]
            if status in {"cancelled", "cancelling"}:
                return record
            if status not in {"queued", "running"}:
                raise ValueError("A completed run cannot be cancelled.")
            now = utc_now()
            if status == "queued":
                record.update(
                    status="cancelled", finished_at=now,
                    error_message="Run cancelled before execution.",
                )
            else:
                record["status"] = "cancelling"
            record["updated_at"] = now
            self._write(run_id, record)
            return record

    def list_runs(
        self, *, limit: int = 20, offset: int = 0, status: str | None = None
    ) -> dict[str, Any]:
        """Return a newest-first page of valid run records."""
        if not 1 <= limit <= 100:
            raise ValueError("Run history limit must be between 1 and 100.")
        if offset < 0:
            raise ValueError("Run history offset must be non-negative.")
        if status is not None and status not in _ALLOWED_STATUSES:
            raise ValueError("Unsupported run status filter.")

        records: list[dict[str, Any]] = []
        with self._lock:
            for run_dir in self.root.iterdir():
                if (
                    not run_dir.is_dir()
                    or run_dir.is_symlink()
                    or not _RUN_ID.fullmatch(run_dir.name)
                ):
                    continue
                record_path = run_dir / "run.json"
                if not record_path.is_file():
                    continue
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("run_id") != run_dir.name:
                    continue
                if record.get("status") not in _ALLOWED_STATUSES:
                    continue
                if not isinstance(record.get("created_at"), str):
                    continue
                if status is not None and record["status"] != status:
                    continue
                records.append(record)

        records.sort(
            key=lambda item: (item["created_at"], item["run_id"]),
            reverse=True,
        )
        return {
            "runs": records[offset : offset + limit],
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }

    def recover_interrupted_runs(self) -> list[str]:
        """Mark queued/running records failed after a local runtime restart.

        This store is deliberately single-process. A newly created runtime has no
        worker handles for records left queued/running by a previous process, so
        it must not present those records as active or silently resume them.
        """
        recovered: list[str] = []
        now = utc_now()
        with self._lock:
            for run_dir in self.root.iterdir():
                if (
                    not run_dir.is_dir()
                    or run_dir.is_symlink()
                    or not _RUN_ID.fullmatch(run_dir.name)
                ):
                    continue
                record_path = run_dir / "run.json"
                if not record_path.is_file():
                    continue
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict) or record.get("run_id") != run_dir.name:
                    continue
                if record.get("status") not in {"queued", "running", "cancelling"}:
                    continue

                record.update(
                    {
                        "status": "failed",
                        "updated_at": now,
                        "finished_at": now,
                        "exit_code": None,
                        "error_message": (
                            "Run was interrupted by a runtime restart before completion. "
                            "Inspect the run log and rerun only if verified snapshots are available."
                        ),
                    }
                )
                self._write(run_dir.name, record)
                recovered.append(run_dir.name)
        return recovered

    def count_runs_in_family(self, root_run_id: str) -> int:
        """Count valid records in one rerun lineage, including legacy root records."""
        if not _RUN_ID.fullmatch(root_run_id):
            raise ValueError("Invalid root run ID.")
        with self._lock:
            return self._count_runs_in_family_unlocked(root_run_id)

    def _count_runs_in_family_unlocked(self, root_run_id: str) -> int:
        count = 0
        for run_dir in self.root.iterdir():
            if (
                not run_dir.is_dir()
                or run_dir.is_symlink()
                or not _RUN_ID.fullmatch(run_dir.name)
            ):
                continue
            record_path = run_dir / "run.json"
            if not record_path.is_file():
                continue
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict) or record.get("run_id") != run_dir.name:
                continue
            if record.get("status") not in _ALLOWED_STATUSES:
                continue
            family_id = record.get("root_run_id") or record.get("run_id")
            if family_id == root_run_id:
                count += 1
        return count

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "exit_code",
            "error_message",
            "artifact_count",
            "log_truncated",
            "input_provenance",
            "environment_provenance",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported run state field(s): {', '.join(sorted(unknown))}")
        if "status" in changes and changes["status"] not in _ALLOWED_STATUSES:
            raise ValueError("Unsupported run status.")

        with self._lock:
            current = self.get(run_id)
            if current is None:
                raise FileNotFoundError("Run not found.")
            current.update(changes)
            current["updated_at"] = utc_now()
            self._write(run_id, current)
            return current

    def run_dir(self, run_id: str) -> Path:
        return self._run_dir(run_id)

    def _write(self, run_id: str, record: dict[str, Any]) -> None:
        run_dir = self._run_dir(run_id)
        temporary = run_dir / ".run.json.tmp"
        temporary.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(run_dir / "run.json")
