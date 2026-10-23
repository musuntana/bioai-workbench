"""Explicit allowlist of workflow entrypoints exposed by the API/runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.config import PROJECT_ROOT


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    version: str
    description: str
    entrypoint: Path
    inputs: tuple[dict[str, str], ...]
    parameters: tuple[dict[str, Any], ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.workflow_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "inputs": list(self.inputs),
            "parameters": list(self.parameters),
        }


WORKFLOWS: dict[str, WorkflowDefinition] = {
    "deseq2-basic": WorkflowDefinition(
        workflow_id="deseq2-basic",
        name="Differential expression (DESeq2)",
        version="0.1.0",
        description=(
            "Run a two-condition DESeq2 analysis from a raw-count matrix and sample metadata."
        ),
        entrypoint=PROJECT_ROOT / "workflows" / "deseq2" / "run.R",
        inputs=(
            {
                "name": "counts_file",
                "format": "CSV",
                "description": "Relative path under BIOAI_INPUT_ROOT; first column gene_id.",
            },
            {
                "name": "metadata_file",
                "format": "CSV",
                "description": "Relative path under BIOAI_INPUT_ROOT; requires sample_id and condition.",
            },
        ),
        parameters=(
            {"name": "condition", "type": "string", "default": "condition"},
            {"name": "reference", "type": "string", "default": "control"},
            {"name": "contrast", "type": "string", "default": "treatment"},
            {"name": "alpha", "type": "number", "default": 0.05, "minimum": 0.000001, "maximum": 0.999999},
        ),
    )
}


def get_workflow(workflow_id: str) -> WorkflowDefinition | None:
    """Return a registered workflow, never resolve an arbitrary caller-supplied path."""
    return WORKFLOWS.get(workflow_id)


def list_workflows() -> list[dict[str, Any]]:
    return [workflow.public_dict() for workflow in WORKFLOWS.values()]
