#!/usr/bin/env bash
# Phase 0 orchestrator: observe -> profile -> diff.
# Usage: ./run.sh [server-command...]   (defaults to the bundled leaky target)
set -euo pipefail
export OUT_DIR="${OUT_DIR:-/tmp/probe_out}"
export HOME="${SANDBOX_HOME:-$(pwd)/sandbox_home}"   # so ~/.ssh, ~/.env resolve to planted canaries
SERVER_CMD=("${@:-python targets/leaky_server.py}")
[ $# -eq 0 ] && SERVER_CMD=(python targets/leaky_server.py)

echo "=== STEP 1: observe (strace) ==="
python probe/probe.py "${SERVER_CMD[@]}"
echo; echo "=== STEP 2: behavioral profile (ground truth) ==="
python probe/analyze.py "$OUT_DIR/trace.log"
echo "=== STEP 3: declared-vs-observed diff ==="
python probe/report.py "$OUT_DIR"
