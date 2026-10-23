"""Build path-safe manifests for generated workflow artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MANIFEST_NAME = "artifact_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(
    output_dir: Path, *, run_id: str, workflow_id: str
) -> dict[str, Any]:
    """Describe files beneath output_dir without embedding absolute filesystem paths."""
    output_dir = output_dir.resolve(strict=True)
    artifacts: list[dict[str, Any]] = []

    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == MANIFEST_NAME:
            continue
        relative_path = path.relative_to(output_dir).as_posix()
        artifacts.append(
            {
                "path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "created_at": datetime.now(UTC).isoformat(),
        "artifacts": artifacts,
    }


def write_artifact_manifest(
    output_dir: Path, *, run_id: str, workflow_id: str
) -> dict[str, Any]:
    """Write and return the artifact manifest; the manifest does not hash itself."""
    manifest = build_artifact_manifest(output_dir, run_id=run_id, workflow_id=workflow_id)
    destination = output_dir / MANIFEST_NAME
    temporary = output_dir / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return manifest
