"""Build path-safe manifests for generated workflow artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_NAME = "artifact_manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactManifestError(ValueError):
    """A run's artifact manifest or its referenced files failed validation."""


def load_artifact_manifest(
    output_dir: Path,
    *,
    run_id: str,
    workflow_id: str,
    required_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Load a manifest only when its identity, paths, sizes, and file hashes verify."""
    try:
        if output_dir.is_symlink():
            raise ValueError
        output_root = output_dir.resolve(strict=True)
        manifest_path = output_root / MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArtifactManifestError("Artifact manifest is missing or unreadable.") from exc

    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("run_id") != run_id
        or manifest.get("workflow_id") != workflow_id
        or not isinstance(manifest.get("created_at"), str)
        or not manifest["created_at"]
        or not isinstance(manifest.get("artifacts"), list)
    ):
        raise ArtifactManifestError("Artifact manifest metadata is invalid.")

    seen_paths: set[str] = set()
    for entry in manifest["artifacts"]:
        if not isinstance(entry, dict):
            raise ArtifactManifestError("Artifact manifest contains an invalid entry.")
        relative_name = entry.get("path")
        size_bytes = entry.get("size_bytes")
        expected_hash = entry.get("sha256")
        if (
            not isinstance(relative_name, str)
            or not relative_name
            or "\\" in relative_name
            or any(part in {"", ".", ".."} for part in relative_name.split("/"))
            or relative_name == MANIFEST_NAME
            or isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or not isinstance(expected_hash, str)
            or not _SHA256_RE.fullmatch(expected_hash)
        ):
            raise ArtifactManifestError("Artifact manifest entry metadata is invalid.")

        relative_path = PurePosixPath(relative_name)
        if relative_path.is_absolute() or relative_path.as_posix() != relative_name:
            raise ArtifactManifestError("Artifact manifest contains an unsafe path.")
        if relative_name in seen_paths:
            raise ArtifactManifestError("Artifact manifest contains duplicate paths.")
        seen_paths.add(relative_name)

        candidate = output_root
        for part in relative_path.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ArtifactManifestError("Artifact manifest references a symlink.")
        try:
            artifact_path = candidate.resolve(strict=True)
            if (
                not artifact_path.is_relative_to(output_root)
                or not artifact_path.is_file()
                or artifact_path.stat().st_size != size_bytes
            ):
                raise ValueError
            actual_hash = _sha256(artifact_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ArtifactManifestError(
                "Artifact checksum or file metadata mismatch; refusing to expose artifacts."
            ) from exc
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise ArtifactManifestError("Artifact checksum mismatch; refusing to expose artifacts.")

    missing = set(required_paths) - seen_paths
    if missing:
        raise ArtifactManifestError("Artifact manifest is missing required workflow outputs.")
    return manifest


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
