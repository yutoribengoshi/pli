#!/bin/bash
# PLI (Private Link Interpreter) — 起動スクリプト
# Usage: ./run.sh

cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 が見つかりません"
    exit 1
fi

# Check venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "=== PLI 起動中 ==="
python3 main.py "$@"
