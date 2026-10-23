"""Environment-backed configuration for the local execution runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _configured_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    candidate = Path(raw).expanduser() if raw else default
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


@dataclass(frozen=True)
class RuntimeConfig:
    """Limits and directories for one local workbench instance."""

    project_root: Path = PROJECT_ROOT
    input_root: Path = PROJECT_ROOT / "data" / "inputs"
    runs_root: Path = PROJECT_ROOT / "runs"
    max_run_seconds: int = 1800
    max_log_bytes: int = 2 * 1024 * 1024
    max_concurrent_runs: int = 2

    @classmethod
    def from_env(cls) -> RuntimeConfig:
        return cls(
            project_root=PROJECT_ROOT,
            input_root=_configured_path("BIOAI_INPUT_ROOT", PROJECT_ROOT / "data" / "inputs"),
            runs_root=_configured_path("BIOAI_RUNS_DIR", PROJECT_ROOT / "runs"),
            max_run_seconds=_positive_int("BIOAI_MAX_RUN_SECONDS", 1800),
            max_log_bytes=_positive_int("BIOAI_MAX_LOG_BYTES", 2 * 1024 * 1024),
            max_concurrent_runs=_positive_int("BIOAI_MAX_CONCURRENT_RUNS", 2),
        )

    def prepare(self) -> None:
        self.input_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
