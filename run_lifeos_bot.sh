#!/usr/bin/env zsh
set -euo pipefail

PROJECT_DIR="/Users/USERNAME/Desktop/Mac/los"
cd "$PROJECT_DIR"

exec "$PROJECT_DIR/.venv312/bin/python" "$PROJECT_DIR/start_all.py"
