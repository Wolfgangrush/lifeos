#!/bin/bash
# LifeOS Configuration Script
# Run this once after cloning to set up LifeOS on your machine.

set -e

LIFEOS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  LifeOS Configuration"
echo "============================================"
echo ""
echo "Project directory: $LIFEOS_DIR"
echo ""

# -----------------------------------------------
# 1. Create required directories
# -----------------------------------------------
echo "[1/6] Creating directories..."
mkdir -p "$LIFEOS_DIR/data"
mkdir -p "$LIFEOS_DIR/logs"
mkdir -p "$HOME/.lifeos"

# -----------------------------------------------
# 2. Set up .env from template if missing
# -----------------------------------------------
echo "[2/6] Checking .env..."
if [ ! -f "$LIFEOS_DIR/.env" ]; then
    cp "$LIFEOS_DIR/.env.example" "$LIFEOS_DIR/.env"
    echo "  Created .env from template."
    echo "  >>> IMPORTANT: Edit .env and add your TELEGRAM_BOT_TOKEN and other keys <<<"
else
    echo "  .env already exists — skipping."
fi

# -----------------------------------------------
# 3. Install Python dependencies
# -----------------------------------------------
echo "[3/6] Installing Python dependencies..."
if [ -d "$LIFEOS_DIR/.venv" ]; then
    echo "  Using existing virtualenv at .venv"
else
    python3 -m venv "$LIFEOS_DIR/.venv"
    echo "  Created virtualenv at .venv"
fi
"$LIFEOS_DIR/.venv/bin/pip" install -q -r "$LIFEOS_DIR/requirements.txt"
if [ -f "$LIFEOS_DIR/requirements_telegram.txt" ]; then
    "$LIFEOS_DIR/.venv/bin/pip" install -q -r "$LIFEOS_DIR/requirements_telegram.txt"
fi
echo "  Python dependencies installed."

# -----------------------------------------------
# 4. Install Node dependencies
# -----------------------------------------------
echo "[4/6] Installing Node dependencies..."
if command -v npm &>/dev/null; then
    (cd "$LIFEOS_DIR" && npm install --silent)
    echo "  Node dependencies installed."
else
    echo "  npm not found — skipping dashboard dependencies."
    echo "  Install Node.js 18+ to use the dashboard."
fi

# -----------------------------------------------
# 5. Generate macOS LaunchAgent (optional)
# -----------------------------------------------
echo "[5/6] Setting up macOS LaunchAgent..."
if [[ "$(uname)" == "Darwin" ]]; then
    PLIST_SRC="$LIFEOS_DIR/com.lifeos.bot.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.lifeos.bot.plist"

    # Generate personalised plist from template
    sed \
        -e "s|__LIFEOS_DIR__|${LIFEOS_DIR}|g" \
        -e "s|__HOME__|${HOME}|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    echo "  Installed LaunchAgent at $PLIST_DST"

    # Symlink operator command
    mkdir -p "$HOME/.local/bin"
    ln -sf "$LIFEOS_DIR/Operator" "$HOME/.local/bin/operator"
    echo "  Symlinked operator -> $HOME/.local/bin/operator"

    # Remind about PATH
    if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
        echo ""
        echo "  NOTE: Add ~/.local/bin to your PATH if not already done:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo "  Add this line to your ~/.zshrc or ~/.bashrc."
    fi
else
    echo "  Not macOS — skipping LaunchAgent setup."
    echo "  Use ./start_telegram_bot.sh to run the bot manually."
fi

# -----------------------------------------------
# 6. Check Ollama
# -----------------------------------------------
echo "[6/6] Checking Ollama..."
if command -v ollama &>/dev/null; then
    echo "  Ollama is installed."
    if ollama list 2>/dev/null | grep -q "llama3"; then
        echo "  Llama3 model found."
    else
        echo "  Llama3 model not found. Pull it with:"
        echo "    ollama pull llama3.2:latest"
    fi
else
    echo "  Ollama not found. Install from: https://ollama.com/download"
    echo "  Then run: ollama pull llama3.2:latest"
fi

# -----------------------------------------------
# Done
# -----------------------------------------------
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys:"
echo "     nano $LIFEOS_DIR/.env"
echo ""
echo "  2. Start LifeOS:"
if [[ "$(uname)" == "Darwin" ]]; then
echo "     operator on          # macOS background service"
echo "     operator status      # check if running"
fi
echo "     ./start_telegram_bot.sh   # manual foreground mode"
echo ""
echo "  3. Open the dashboard:"
echo "     npm run dev"
echo "     # then visit http://127.0.0.1:3000"
echo ""
