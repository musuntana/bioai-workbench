# Runtime

The initial runtime is deliberately single-host and file-backed.

- Only workflow IDs present in `app/registry.py` can be executed.
- Input CSV paths are relative to `BIOAI_INPUT_ROOT`; resolved symlinks must remain under that root.
- The child process is launched without a shell and receives a small environment allowlist.
- Execution has a wall-clock timeout, a bounded log file, and a configurable concurrency limit.
- Run state is written atomically to `runs/<run_id>/run.json`.
- Output files are checksummed into `outputs/artifact_manifest.json`; absolute paths are not included in that manifest.

This is not a multi-user service or a hardened container sandbox. Bind the API to localhost, do not expose it to an untrusted network, and use OS/container isolation before running untrusted workloads. Process state is not distributed and may need manual recovery after a host crash.
