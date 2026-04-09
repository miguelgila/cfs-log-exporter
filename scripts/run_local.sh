#!/usr/bin/env bash
# Run the full CFS Log Exporter stack locally.
# Usage: ./scripts/run_local.sh
#
# Prerequisites: Python 3.10+, Node 18+, kubeconfig with CSM cluster access
# The receiver + UI runs on localhost:8000
# The exporter connects to the CSM cluster using your local kubeconfig

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

# --- Config (override via env) ---
export API_KEY="${API_KEY:-changeme}"
export RECEIVER_URL="${RECEIVER_URL:-http://localhost:8000}"
export NAMESPACE="${NAMESPACE:-services}"
export POD_PREFIX="${POD_PREFIX:-cfs-}"
export IN_CLUSTER="${IN_CLUSTER:-false}"
export DB_PATH="${DB_PATH:-$ROOT/cfs_logs.db}"

# --- Virtualenv ---
if [ ! -d ".venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python dependencies..."
pip install -q -r receiver/requirements.txt -r exporter/requirements.txt

# --- Frontend build ---
if [ ! -d "frontend/dist" ]; then
    echo "Building frontend..."
    cd frontend
    npm install --silent
    npm run build
    cd "$ROOT"
fi

# --- Cleanup on exit ---
cleanup() {
    trap '' EXIT INT TERM   # prevent re-entry on repeated Ctrl+C
    echo ""
    echo "Shutting down..."
    [ -n "${EXPORTER_PID:-}" ] && kill "$EXPORTER_PID" 2>/dev/null || true
    [ -n "${RECEIVER_PID:-}" ] && kill "$RECEIVER_PID" 2>/dev/null || true
    # Grace period, then force-kill stragglers
    sleep 2
    [ -n "${EXPORTER_PID:-}" ] && kill -9 "$EXPORTER_PID" 2>/dev/null || true
    [ -n "${RECEIVER_PID:-}" ] && kill -9 "$RECEIVER_PID" 2>/dev/null || true
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT INT TERM

# --- Start receiver ---
echo "Starting receiver on http://localhost:8000 ..."
python -m uvicorn receiver.app:app --host 127.0.0.1 --port 8000 \
    --log-config "$ROOT/scripts/uvicorn_log_config.json" &
RECEIVER_PID=$!
sleep 2

# --- Start exporter ---
echo "Starting exporter (namespace=$NAMESPACE, prefix=$POD_PREFIX)..."
python exporter/exporter.py &
EXPORTER_PID=$!

echo ""
echo "========================================"
echo "  CFS Log Viewer: http://localhost:8000"
echo "  Watching namespace: $NAMESPACE"
echo "  Pod prefix: $POD_PREFIX"
echo "  Ctrl+C to stop"
echo "========================================"
echo ""

wait
