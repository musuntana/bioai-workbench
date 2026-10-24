# Runtime

The initial runtime is deliberately single-host and file-backed.

- Only workflow IDs present in `app/registry.py` can be executed.
- Input CSV paths are relative to `BIOAI_INPUT_ROOT`; resolved symlinks must remain under that root.
- The child process is launched without a shell and receives a small environment allowlist.
- Execution has a wall-clock timeout, a bounded log file, and a configurable concurrency limit.
- Run state is written atomically to `runs/<run_id>/run.json`.
- Output files are checksummed into `outputs/artifact_manifest.json`; absolute paths are not included in that manifest.

## Run lifecycle contract

| Event | State transition | Required behavior |
|---|---|---|
| Run accepted | `queued` | Persist request parameters before returning the accepted response. |
| Worker begins | `queued` → `running` | Record `started_at`; freeze workflow and input bytes and record their hashes. |
| Workflow exits zero | `running` → `succeeded` | Require all four DESeq2 outputs, write the artifact manifest, and record environment provenance and artifact count. |
| Workflow exits nonzero or setup/output validation fails | `running` → `failed` | Record a generic error and exit status; never label partial output as successful. |
| Runtime timeout | `running` → `timed_out` | Terminate the child process group and record the timeout. |
| Runtime process restarts | persisted `queued`/`running` → `failed` | Mark the stale record failed with an explicit interruption message and finish timestamp. Do not automatically retry or resume it. |
| User requests rerun | terminal source → new `queued` child run | Revalidate and copy the original immutable workflow/input snapshots; reject missing or mismatched hashes. |

The terminal states are `succeeded`, `failed`, and `timed_out`. Startup recovery only changes stale `queued`/`running` records and is idempotent; it preserves terminal records and logs. A manual rerun creates a new run ID and lineage entry rather than mutating the source run.

Before artifacts are listed, the manifest loader validates schema version, run/workflow identity, unique safe relative paths, SHA-256 syntax, file existence and size, content hashes, and the complete required DESeq2 output set. Non-succeeded runs expose no artifacts. Corrupt or inconsistent manifests return HTTP 409; downloads and result reads also verify the referenced artifact checksum.

On startup, the local runtime marks persisted `queued`/`running` records as `failed` with an explicit interruption message; it does not automatically retry or resume them. A user can request a manual rerun only when the source run's immutable input/workflow snapshots still pass checksum verification. Corrupt state records are skipped rather than guessed at.

This is not a multi-user service or a hardened container sandbox. Bind the API to localhost, do not expose it to an untrusted network, and use OS/container isolation before running untrusted workloads. State recovery is local and single-process, not a distributed job queue.
