"""Stable request/response schemas for the first local workbench API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: Literal["deseq2-basic"] = "deseq2-basic"
    counts_file: str = Field(min_length=1, max_length=240)
    metadata_file: str = Field(min_length=1, max_length=240)
    condition: str = Field(default="condition", min_length=1, max_length=80)
    reference: str = Field(default="control", min_length=1, max_length=120)
    contrast: str = Field(default="treatment", min_length=1, max_length=120)
    alpha: float = Field(default=0.05, gt=0, lt=1)

    @field_validator("counts_file", "metadata_file")
    @classmethod
    def validate_relative_csv(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or "\x00" in value
            or "\\" in value
            or value.startswith("/")
            or re.match(r"^[A-Za-z]:", value)
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Input files must be safe relative paths under BIOAI_INPUT_ROOT.")
        if not value.lower().endswith(".csv"):
            raise ValueError("Input files must use the .csv extension.")
        return value

    @field_validator("condition")
    @classmethod
    def validate_condition_column(cls, value: str) -> str:
        if value == "sample_id" or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._]*", value):
            raise ValueError("condition must name a metadata column and cannot be sample_id.")
        return value

    @field_validator("reference", "contrast")
    @classmethod
    def validate_factor_level(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Condition levels must be non-empty printable strings.")
        return value

    @model_validator(mode="after")
    def distinct_levels(self) -> RunRequest:
        if self.reference == self.contrast:
            raise ValueError("reference and contrast must be different.")
        return self


class WorkflowInfo(BaseModel):
    id: str
    name: str
    version: str
    description: str
    inputs: list[dict[str, str]]
    parameters: list[dict[str, object]]


class WorkflowList(BaseModel):
    workflows: list[WorkflowInfo]


class RunAccepted(BaseModel):
    run_id: str
    workflow_id: str
    status: str
    created_at: str
    status_url: str


RunState = Literal["queued", "running", "succeeded", "failed", "timed_out"]


class RunStatus(BaseModel):
    run_id: str
    workflow_id: str
    parameters: dict[str, object] = Field(default_factory=dict)
    status: RunState
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    artifact_count: int = 0
    log_truncated: bool = False


class RunList(BaseModel):
    runs: list[RunStatus]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ArtifactInfo(BaseModel):
    path: str
    size_bytes: int
    sha256: str


class ArtifactList(BaseModel):
    run_id: str
    artifacts: list[ArtifactInfo]


class LogResponse(BaseModel):
    run_id: str
    text: str
    truncated: bool
