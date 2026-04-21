#!/bin/bash
# Start script for Pure Telegram Life OS v4

echo "🤖 Starting Pure Telegram Life OS v4..."

# Kill any existing bot
pkill -f "pure_telegram_bot" 2>/dev/null

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama is not running!"
    echo "   Start it with: ollama serve &"
    echo "   Starting Ollama in background..."
    ollama serve > /dev/null 2>&1 &
    sleep 3
fi

# Check .env
if [ ! -f .env ]; then
    echo "❌ .env file not found! Run ./setup_telegram_bot.sh first"
    exit 1
fi

# Start the v4 bot with Python 3.12
/opt/homebrew/bin/python3.12 pure_telegram_bot_v4.py
