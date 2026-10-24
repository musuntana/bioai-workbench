# Runtime

The initial runtime is deliberately single-host and file-backed.

- Only workflow IDs present in `app/registry.py` can be executed.
- Input CSV paths are relative to `BIOAI_INPUT_ROOT`; resolved symlinks must remain under that root.
- The child process is launched without a shell and receives a small environment allowlist.
- Execution has a wall-clock timeout, a bounded log file, and a configurable concurrency limit.
- Run state is written atomically to `runs/<run_id>/run.json`.
- Output files are checksummed into `outputs/artifact_manifest.json`; absolute paths are not included in that manifest.

On startup, the local runtime marks persisted `queued`/`running` records as `failed` with an explicit interruption message; it does not automatically retry or resume them. A user can request a manual rerun only when the source run's immutable input/workflow snapshots still pass checksum verification. Corrupt state records are skipped rather than guessed at.

This is not a multi-user service or a hardened container sandbox. Bind the API to localhost, do not expose it to an untrusted network, and use OS/container isolation before running untrusted workloads. State recovery is local and single-process, not a distributed job queue.
