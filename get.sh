#!/usr/bin/env bash
# Bootstrap script — downloads and installs the agent-linux CLI
set -euo pipefail

REPO="https://raw.githubusercontent.com/theOSCARP2/agent-linux/master"
BIN="/usr/local/bin/agent-linux"

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required but not found." >&2
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "Error: Python 3.10+ is required (found $PY_VER)." >&2
    exit 1
fi

echo "→ Python $PY_VER detected"

# Ensure pip is available (ensurepip is built into Python — no apt needed)
if ! python3 -m pip --version &>/dev/null 2>&1; then
    echo "→ Bootstrapping pip via ensurepip…"
    python3 -m ensurepip --upgrade
fi

# Download CLI
echo "→ Downloading agent-linux CLI…"
curl -fsSL "$REPO/cli/agent_linux_cli.py" -o "$BIN"
chmod +x "$BIN"

echo ""
echo "✓ agent-linux installed at $BIN"
echo ""
echo "Tapez  agent-linux install  pour commencer."
