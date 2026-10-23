"""Typed contracts shared by optional planning adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowPlan:
    """A proposed registered workflow call; it is not executable code."""

    workflow_id: str
    parameters: dict[str, Any]
    rationale: str
    requires_approval: bool = True
    status: str = "proposed"
