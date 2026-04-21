#!/bin/bash
# Setup script for Pure Telegram Life OS
# This script installs dependencies and helps configure the bot

echo "🚀 Setting up Pure Telegram Life OS..."
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $PYTHON_VERSION"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data logs

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements_telegram.txt --break-system-packages

# Check if Ollama is installed
echo ""
echo "🔍 Checking Ollama..."
if command -v ollama &> /dev/null; then
    echo "✓ Ollama is installed"
    OLLAMA_MODEL=$(ollama list 2>/dev/null | grep llama3 || echo "")
    if [ -n "$OLLAMA_MODEL" ]; then
        echo "✓ Llama3 model found"
    else
        echo "⚠️  Llama3 model not found. Pulling it now..."
        ollama pull llama3.1:8b
    fi
else
    echo "⚠️  Ollama not found!"
    echo "   Install from: https://ollama.com/download"
    echo "   Then run: ollama pull llama3.1:8b"
fi

# Check .env file
echo ""
echo "🔐 Checking configuration..."
if [ -f .env ]; then
    echo "✓ .env file exists"
else
    echo "⚠️  .env file not found!"
    echo "   Creating from template..."
    cp .env.example.telegram .env
    echo "   ❗ EDIT .env and add your TELEGRAM_BOT_TOKEN and GEMINI_API_KEY"
fi

# Check if tokens are set
if grep -q "your_telegram_bot_token_here" .env 2>/dev/null; then
    echo ""
    echo "❌ SETUP INCOMPLETE!"
    echo ""
    echo "Please edit .env and add:"
    echo "  1. TELEGRAM_BOT_TOKEN (from @BotFather)"
    echo "  2. GEMINI_API_KEY (from https://makersuite.google.com/app/apikey)"
    echo ""
    echo "Then run: ./setup_telegram_bot.sh again"
    exit 1
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the bot:"
echo "  ./start_telegram_bot.sh"
echo ""
echo "Or run directly:"
echo "  python3 pure_telegram_bot.py"
