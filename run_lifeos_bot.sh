#!/usr/bin/env zsh
set -euo pipefail

# Resolve project directory (where this script lives)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Ensure Ollama is up (local LLM is required for classification)
if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  ollama serve >/dev/null 2>&1 &
  sleep 3
fi

exec python3 "$PROJECT_DIR/pure_telegram_bot_v4.py"
