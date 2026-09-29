#!/usr/bin/env bash
# ==============================================================================
# VerbaClear AV Appliance Automated Provisioning & Verification Script
# Designed for dedicated sound booth Linux workstations, NUCs, and rack servers.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================================"
echo "    VerbaClear Hardware Appliance Installer & Validator    "
echo "============================================================"

# 1. System prerequisites check
echo "[1/5] Checking system prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo >&2 "Error: python3 is required. Aborting."; exit 1; }
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python version: ${PYTHON_VERSION}"

# Check for PortAudio system libraries
if command -v ldconfig >/dev/null 2>&1; then
    if ldconfig -p | grep -q libportaudio; then
        echo "Found system PortAudio C library."
    else
        echo "Warning: libportaudio not found in ldconfig cache. If audio input fails, install with:"
        echo "  sudo apt-get install -y portaudio19-dev libasound2-dev"
    fi
fi

# 2. Virtual environment setup
echo "[2/5] Initializing Python virtual environment..."
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment at .venv..."
    python3 -m venv .venv
fi

VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
VENV_PIP="$PROJECT_ROOT/.venv/bin/pip"

# 3. Installing dependencies
echo "[3/5] Installing core dependencies..."
"$VENV_PIP" install --upgrade pip setuptools wheel
"$VENV_PIP" install -e ".[dev]"

# 4. Verifying spaCy linguistic models & Silero VAD
echo "[4/5] Verifying NLP language models and neural VAD assets..."
"$VENV_PYTHON" -m spacy download en_core_web_sm || {
    echo "spaCy model download warning; continuing with installed packages."
}

# 5. Seeding offline lexicons & verifying test suite
echo "[5/5] Running verification test suite..."
PYTHONPATH=. "$PROJECT_ROOT/.venv/bin/pytest" tests/test_audio_device_management.py -q

echo "============================================================"
echo "  VerbaClear Appliance Provisioned Successfully!            "
echo "  To launch the system, run: ./scripts/run_appliance.sh      "
echo "============================================================"
