# ADR 0001: Local-first registered workflows

- **Status:** Accepted for the initial product skeleton
- **Date:** 2026-10-23

## Context

The repository has one clean-room DESeq2 CLI workflow but no shared API, run state, or artifact contract. Introducing a general agent, database, queue, or distributed scheduler before proving the first workflow would increase maintenance and security risk.

## Decision

1. Keep the analysis implementation in R and reuse DESeq2.
2. Expose only registered workflow IDs through the Python runtime.
3. Keep the deterministic execution path independent of an LLM.
4. Use FastAPI for a thin local API and static UI.
5. Persist run state and artifacts on the local filesystem for the first vertical.
6. Validate input paths beneath a configured input root; launch subprocesses without a shell and with time/log limits.
7. Use `uv` and `pyproject.toml` for the Python development environment.

## Consequences

The initial system is easy to inspect and run locally but is not a multi-user or distributed execution service. If concurrent workloads, crash recovery, or isolation requirements grow, evaluate Snakemake/Nextflow and an established container/runtime boundary before implementing a custom scheduler. Any future model provider must return a validated plan over registered workflows and cannot execute arbitrary generated code.
