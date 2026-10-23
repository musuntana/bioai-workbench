"""Deterministic planner baseline; no model calls or arbitrary command execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.contracts import WorkflowPlan
from app.registry import get_workflow
from app.schemas import RunRequest


_TASK_TO_WORKFLOW = {
    "differential_expression": "deseq2-basic",
    "deseq2": "deseq2-basic",
    "deseq2-basic": "deseq2-basic",
}


def plan_task(task: str, parameters: Mapping[str, Any]) -> WorkflowPlan:
    """Map a known task to a registered workflow and validate all proposed parameters."""
    workflow_id = _TASK_TO_WORKFLOW.get(task.strip().lower())
    if workflow_id is None or get_workflow(workflow_id) is None:
        raise ValueError("Unsupported task. Available task: differential_expression.")

    validated = RunRequest.model_validate(
        {"workflow_id": workflow_id, **dict(parameters)}
    )
    return WorkflowPlan(
        workflow_id=workflow_id,
        parameters=validated.model_dump(),
        rationale=(
            "The request maps to the registered DESeq2 workflow. Inputs and parameters "
            "must pass the runtime checks before execution."
        ),
        requires_approval=True,
    )
