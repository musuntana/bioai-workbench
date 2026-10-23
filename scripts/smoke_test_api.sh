#!/usr/bin/env bash
set -euo pipefail

# Opt-in API-to-runtime-to-R/DESeq2 end-to-end smoke test using synthetic data only.
# Run after "uv sync --extra dev" in an environment with R and DESeq2 installed.
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
KEEP_ARTIFACTS="$(printenv BIOAI_SMOKE_KEEP_ARTIFACTS || printf '0')"
MAX_WAIT_SECONDS="$(printenv BIOAI_API_SMOKE_WAIT_SECONDS || printf '300')"

for command_name in uv Rscript curl python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: $command_name" >&2
    exit 2
  fi
done

if ! uv run --no-sync python -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Python dependencies are missing; run 'uv sync --extra dev' first." >&2
  exit 2
fi
if ! Rscript -e 'if (!requireNamespace("DESeq2", quietly = TRUE)) quit(status = 1)' >/dev/null 2>&1; then
  echo 'DESeq2 is missing; install it with BiocManager::install("DESeq2").' >&2
  exit 2
fi
if ! [[ "$MAX_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "BIOAI_API_SMOKE_WAIT_SECONDS must be a positive integer." >&2
  exit 2
fi

TMP_PARENT="$(printenv TMPDIR || printf '/tmp')"
TMP_BASE="$(mktemp -d "$TMP_PARENT/bioai-workbench-api-smoke.XXXXXX")"
INPUT_ROOT="$TMP_BASE/inputs"
RUNS_ROOT="$TMP_BASE/runs"
SERVER_LOG="$TMP_BASE/server.log"
SERVER_PID=""
mkdir -p "$INPUT_ROOT/demo" "$RUNS_ROOT"

cleanup() {
  local exit_code=$?
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ "$KEEP_ARTIFACTS" == "1" ]]; then
    printf 'Evidence retained at: %s\n' "$TMP_BASE"
  else
    rm -rf "$TMP_BASE"
  fi
  return "$exit_code"
}
trap cleanup EXIT

cd "$ROOT_DIR"
Rscript examples/deseq2/generate_synthetic_data.R "$INPUT_ROOT/demo"

PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
BASE_URL="http://127.0.0.1:$PORT"
env BIOAI_INPUT_ROOT="$INPUT_ROOT" BIOAI_RUNS_DIR="$RUNS_ROOT" BIOAI_MAX_RUN_SECONDS="$MAX_WAIT_SECONDS" uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for ((attempt = 0; attempt < 60; attempt++)); do
  if curl --connect-timeout 1 --max-time 2 -fsS "$BASE_URL/healthz" -o "$TMP_BASE/health.json"; then
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "API server exited before becoming healthy. Server log:" >&2
    cat "$SERVER_LOG" >&2
    exit 1
  fi
  sleep 1
done
if [[ ! -s "$TMP_BASE/health.json" ]]; then
  echo "API server did not become healthy. Server log:" >&2
  cat "$SERVER_LOG" >&2
  exit 1
fi

curl -fsS "$BASE_URL/api/v1/workflows" -o "$TMP_BASE/workflows.json"
curl -fsS -X POST "$BASE_URL/api/v1/runs" -H 'Content-Type: application/json' -d '{"workflow_id":"deseq2-basic","counts_file":"demo/counts.csv","metadata_file":"demo/metadata.csv","condition":"condition","reference":"control","contrast":"treatment","alpha":0.05}' -o "$TMP_BASE/run-accepted.json"
RUN_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["run_id"])' "$TMP_BASE/run-accepted.json")"

STATUS="queued"
for ((attempt = 0; attempt < MAX_WAIT_SECONDS; attempt++)); do
  if ! curl --connect-timeout 2 --max-time 10 -fsS "$BASE_URL/api/v1/runs/$RUN_ID" -o "$TMP_BASE/run-status.json"; then
    echo "Could not read run status. Server log:" >&2
    cat "$SERVER_LOG" >&2
    exit 1
  fi
  STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' "$TMP_BASE/run-status.json")"
  case "$STATUS" in
    succeeded) break ;;
    failed|timed_out)
      echo "Workflow finished with status: $STATUS" >&2
      curl -fsS "$BASE_URL/api/v1/runs/$RUN_ID/logs" -o "$TMP_BASE/run-logs.json" || true
      cat "$TMP_BASE/run-status.json" >&2
      [[ ! -f "$TMP_BASE/run-logs.json" ]] || cat "$TMP_BASE/run-logs.json" >&2
      exit 1
      ;;
    queued|running) sleep 1 ;;
    *)
      echo "Unexpected run status: $STATUS" >&2
      cat "$TMP_BASE/run-status.json" >&2
      exit 1
      ;;
  esac
done
if [[ "$STATUS" != "succeeded" ]]; then
  echo "Workflow did not finish within $MAX_WAIT_SECONDS seconds (last status: $STATUS)." >&2
  cat "$TMP_BASE/run-status.json" >&2
  exit 1
fi

curl -fsS "$BASE_URL/api/v1/runs/$RUN_ID/logs" -o "$TMP_BASE/run-logs.json"
curl -fsS "$BASE_URL/api/v1/runs/$RUN_ID/artifacts" -o "$TMP_BASE/artifacts.json"
ARTIFACTS_JSON="$(cat "$TMP_BASE/artifacts.json")"

for artifact_name in differential_expression_all.csv differential_expression_significant.csv run_manifest.tsv session_info.txt; do
  expected_hash="$(printf '%s' "$ARTIFACTS_JSON" | python3 -c 'import json,sys; name=sys.argv[1]; data=json.load(sys.stdin); print(next((item["sha256"] for item in data["artifacts"] if item["path"] == name), ""))' "$artifact_name")"
  if [[ ! "$expected_hash" =~ ^[a-f0-9]{64}$ ]]; then
    echo "Expected artifact missing from API manifest: $artifact_name" >&2
    exit 1
  fi
  curl -fsS -D "$TMP_BASE/headers-$artifact_name.txt" -o "$TMP_BASE/download-$artifact_name" "$BASE_URL/api/v1/runs/$RUN_ID/artifacts/$artifact_name"
  header_hash="$(awk 'tolower($1) == "x-artifact-sha256:" { gsub(sprintf("%c", 13), "", $2); print $2 }' "$TMP_BASE/headers-$artifact_name.txt" | tail -n 1)"
  actual_hash="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$TMP_BASE/download-$artifact_name")"
  if [[ "$expected_hash" != "$header_hash" || "$expected_hash" != "$actual_hash" ]]; then
    echo "Artifact checksum mismatch for $artifact_name" >&2
    exit 1
  fi
  test -s "$TMP_BASE/download-$artifact_name"
done

if grep -Fq "$TMP_BASE" "$TMP_BASE/download-run_manifest.tsv"; then
  echo "Run manifest unexpectedly contains the temporary absolute path." >&2
  exit 1
fi

# Exercise the real result explorer, scientific report, exact-gene view and
# immutable rerun. These checks run only in an explicit opt-in R/DESeq2 smoke.
curl -fsS "$BASE_URL/api/v1/runs/$RUN_ID/results?limit=100" \
  -o "$TMP_BASE/results.json"
curl -fsS "$BASE_URL/api/v1/runs/$RUN_ID/genes/gene_001" \
  -o "$TMP_BASE/gene-detail.json"
curl -fsS -D "$TMP_BASE/report-headers.txt" \
  "$BASE_URL/api/v1/runs/$RUN_ID/report" -o "$TMP_BASE/report.html"

if ! grep -qi '^content-disposition: attachment;' "$TMP_BASE/report-headers.txt"; then
  echo "Report export was not offered as a download." >&2
  exit 1
fi

curl -fsS -X POST "$BASE_URL/api/v1/runs/$RUN_ID/rerun" \
  -o "$TMP_BASE/rerun-accepted.json"
RERUN_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["run_id"])' "$TMP_BASE/rerun-accepted.json")"
RERUN_STATUS="queued"
for ((attempt = 0; attempt < MAX_WAIT_SECONDS; attempt++)); do
  curl --connect-timeout 2 --max-time 10 -fsS \
    "$BASE_URL/api/v1/runs/$RERUN_ID" -o "$TMP_BASE/rerun-status.json"
  RERUN_STATUS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' "$TMP_BASE/rerun-status.json")"
  case "$RERUN_STATUS" in
    succeeded) break ;;
    failed|timed_out)
      echo "Snapshot rerun terminated with status $RERUN_STATUS." >&2
      curl -fsS "$BASE_URL/api/v1/runs/$RERUN_ID/logs" -o "$TMP_BASE/rerun-logs.json" || true
      cat "$TMP_BASE/rerun-status.json" >&2
      exit 1 ;;
    queued|running) sleep 1 ;;
    *) echo "Unexpected snapshot rerun state: $RERUN_STATUS" >&2; exit 1 ;;
  esac
done
if [[ "$RERUN_STATUS" != "succeeded" ]]; then
  echo "Snapshot rerun failed to complete within $MAX_WAIT_SECONDS seconds." >&2
  exit 1
fi
curl -fsS "$BASE_URL/api/v1/runs/$RERUN_ID/artifacts" \
  -o "$TMP_BASE/rerun-artifacts.json"
curl -fsS "$BASE_URL/api/v1/runs/compare?run_a=$RUN_ID&run_b=$RERUN_ID" \
  -o "$TMP_BASE/run-comparison.json"
curl -fsS "$BASE_URL/api/v1/runs/compare/gene?run_a=$RUN_ID&run_b=$RERUN_ID&gene_id=gene_001" \
  -o "$TMP_BASE/gene-comparison.json"
curl -fsS "$BASE_URL/api/v1/runs/compare/genes?run_a=$RUN_ID&run_b=$RERUN_ID" \
  -o "$TMP_BASE/gene-set-comparison.json"

# A standalone standard-library validator cross-checks downloaded DESeq2 CSVs,
# live API summaries, SVG report contents and the real rerun's artifact hashes.
python3 scripts/verify_deseq2_smoke.py "$TMP_BASE"

R_VERSION="$(Rscript -e 'cat(R.version.string)')"
DESEQ2_VERSION="$(Rscript -e 'cat(as.character(utils::packageVersion("DESeq2")))' )"
COMMIT_SHA="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
VERIFIED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
python3 - "$TMP_BASE/verification-summary.json" "$RUN_ID" "$R_VERSION" "$DESEQ2_VERSION" "$COMMIT_SHA" "$VERIFIED_AT" "$ARTIFACTS_JSON" <<'PY'
import json
import sys
from pathlib import Path

output, run_id, r_version, deseq2_version, commit, verified_at, artifacts_json = sys.argv[1:]
artifacts = json.loads(artifacts_json)["artifacts"]
summary = {
    "status": "passed",
    "run_id": run_id,
    "verified_at_utc": verified_at,
    "git_commit": commit,
    "r_version": r_version,
    "deseq2_version": deseq2_version,
    "artifacts": {
        item["path"]: {"size_bytes": item["size_bytes"], "sha256": item["sha256"]}
        for item in artifacts
    },
    "scope": "synthetic API-to-DESeq2 end-to-end smoke test; not scientific or clinical validation",
}
summary["acceptance_matrix"] = json.loads(
    (Path(output).parent / "acceptance-matrix.json").read_text(encoding="utf-8")
)
Path(output).write_text(json.dumps(summary, indent=2) + chr(10), encoding="utf-8")
PY

printf 'API end-to-end smoke test passed. Run ID: %s\n' "$RUN_ID"
printf 'Verified R: %s; DESeq2: %s\n' "$R_VERSION" "$DESEQ2_VERSION"
printf 'All four expected artifacts downloaded and matched their manifest/header SHA-256 values.\n'
