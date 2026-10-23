"""Small file-backed run store for a single-process local workbench."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_ALLOWED_STATUSES = {"queued", "running", "succeeded", "failed", "timed_out"}


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

    def create(self, run_id: str, workflow_id: str) -> dict[str, Any]:
        now = utc_now()
        record: dict[str, Any] = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "error_message": None,
            "artifact_count": 0,
            "log_truncated": False,
        }
        with self._lock:
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

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "exit_code",
            "error_message",
            "artifact_count",
            "log_truncated",
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
