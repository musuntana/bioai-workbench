"""Compare persisted analysis runs without executing or altering workflows."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

_RUN_ID = re.compile(r"^[0-9a-f]{32}$")


def compare_runs(manager: Any, run_a: str, run_b: str) -> dict[str, Any]:
    """Compare immutable-looking snapshots and manifested output checksums.

    A comparison is descriptive, not proof that inputs or environments matched.
    """
    if not _RUN_ID.fullmatch(run_a) or not _RUN_ID.fullmatch(run_b):
        raise HTTPException(status_code=422, detail="Run IDs must be 32 lowercase hex characters.")
    if run_a == run_b:
        raise HTTPException(status_code=422, detail="Select two different runs.")

    runs = []
    for run_id in (run_a, run_b):
        record = manager.store.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        artifacts = manager.get_artifacts(run_id) or []
        hashes = {
            item["path"]: item["sha256"]
            for item in artifacts
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        }
        runs.append({
            "run_id": run_id,
            "workflow_id": record.get("workflow_id"),
            "status": record.get("status"),
            "created_at": record.get("created_at"),
            "parameters": record.get("parameters") or {},
            "artifact_hashes": hashes,
            "input_provenance": record.get("input_provenance") or {},
            "environment_provenance": record.get("environment_provenance") or {},
        })

    first, second = runs
    parameters_a, parameters_b = first["parameters"], second["parameters"]
    changed_parameters = [
        {"field": key, "run_a": parameters_a.get(key), "run_b": parameters_b.get(key)}
        for key in sorted(set(parameters_a) | set(parameters_b))
        if parameters_a.get(key) != parameters_b.get(key)
    ]
    input_comparison = {}
    for role in ("counts", "metadata"):
        a = first["input_provenance"].get(role, {})
        b = second["input_provenance"].get(role, {})
        hash_a, hash_b = a.get("sha256"), b.get("sha256")
        valid_a = isinstance(hash_a, str) and re.fullmatch(r"[0-9a-f]{64}", hash_a)
        valid_b = isinstance(hash_b, str) and re.fullmatch(r"[0-9a-f]{64}", hash_b)
        input_comparison[role] = {
            "run_a_sha256": hash_a if valid_a else None,
            "run_b_sha256": hash_b if valid_b else None,
            "same_content": hash_a == hash_b if valid_a and valid_b else None,
        }
    hashes_a, hashes_b = first["artifact_hashes"], second["artifact_hashes"]
    changed_artifacts = [
        {
            "path": path,
            "run_a_sha256": hashes_a.get(path),
            "run_b_sha256": hashes_b.get(path),
            "same_checksum": hashes_a.get(path) == hashes_b.get(path)
            if path in hashes_a and path in hashes_b else None,
        }
        for path in sorted(set(hashes_a) | set(hashes_b))
    ]
    env_a, env_b = first["environment_provenance"], second["environment_provenance"]
    environment_comparison = [
        {
            "field": key,
            "run_a": env_a.get(key),
            "run_b": env_b.get(key),
            "same": env_a[key] == env_b[key] if key in env_a and key in env_b else None,
        }
        for key in sorted(set(env_a) | set(env_b))
    ]
    return {
        "runs": runs,
        "environment": environment_comparison,
        "same_workflow": first["workflow_id"] == second["workflow_id"],
        "changed_parameters": changed_parameters,
        "inputs": input_comparison,
        "artifacts": changed_artifacts,
        "limitations": (
            "Older runs may lack input hashes. Frozen input hashes document bytes passed to R. "
            "Matching output manifest hashes do not prove identical environments. "
            "Artifacts are not rehashed by this comparison; use verified downloads to check integrity."
        ),
    }
