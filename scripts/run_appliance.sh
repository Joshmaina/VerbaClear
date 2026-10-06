#!/usr/bin/env bash
# ==============================================================================
# VerbaClear AV Sound Booth Runtime Appliance Launcher
# Starts the ASGI WebSocket Hub, Real-Time Audio Pipeline, and Static Surfaces.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Detect local LAN IP address for QR code & mobile companion distribution
LOCAL_IP="localhost"
if command -v hostname >/dev/null 2>&1; then
    DETECTED_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    if [ -n "$DETECTED_IP" ]; then
        LOCAL_IP="$DETECTED_IP"
    fi
fi

PORT="${VERBACLEAR_PORT:-}"
if [ -z "$PORT" ]; then
    if command -v ss >/dev/null 2>&1 && ss -tulpn 2>/dev/null | grep -q ":8000 "; then
        PORT="8888"
        echo "[INFO] Port 8000 is occupied by another local service; automatically binding to port 8888."
    else
        PORT="8000"
    fi
fi
HOST="${VERBACLEAR_HOST:-0.0.0.0}"

echo "============================================================"
echo "    __     __        _          ____  _                     "
echo "    \ \   / /__ _ __| |__   __ / ___|| | ___  __ _ _ __     "
echo "     \ \ / / _ \ '__| '_ \ / _\ |    | |/ _ \/ _\` | '__|    "
echo "      \ V /  __/ |  | |_) | (_| | ___| |  __/ (_| | |       "
echo "       \_/ \___|_|  |_.__/ \__,_|\____|_|\___|\__,_|_|       "
echo "                                                            "
echo "  VerbaClear Ambient Real-Time Speech Intelligence Platform "
echo "============================================================"
echo "  [AV Operator Control Room] : http://${LOCAL_IP}:${PORT}/admin"
echo "  [Stage Display Screen]     : http://${LOCAL_IP}:${PORT}/stage"
echo "  [Attendee Mobile Companion]: http://${LOCAL_IP}:${PORT}/companion"
echo "  [Audience QR Code API]     : http://${LOCAL_IP}:${PORT}/api/session/qr"
echo "============================================================"
echo "Starting VerbaClear ASGI runtime on ${HOST}:${PORT}..."

exec "$PROJECT_ROOT/.venv/bin/python" -m uvicorn src.api.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info
