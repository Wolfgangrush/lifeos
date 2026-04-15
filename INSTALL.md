# Quick Installation Guide

This guide will get you up and running with Life OS in under 10 minutes.

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] Python 3.9 or higher installed (`python3 --version`)
- [ ] Node.js 18 or higher installed (`node --version`)
- [ ] Ollama installed ([Download here](https://ollama.ai/download))
- [ ] Telegram account
- [ ] 5-10 minutes of free time

## Step-by-Step Installation

### 1. Install Ollama (2 minutes)

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

**Windows:**
Download from [ollama.ai/download](https://ollama.ai/download)

**Download the AI model:**
```bash
ollama pull llama3.1:8b
```

This downloads an 8GB model. It may take a few minutes depending on your internet speed.

**Verify it works:**
```bash
ollama list
```

You should see `llama3.1:8b` in the list.

### 2. Create Your Telegram Bot (3 minutes)

1. **Open Telegram** (mobile or desktop)

2. **Message @BotFather:** https://t.me/botfather

3. **Create bot:**
   - Send: `/newbot`
   - Enter bot name: `My Life OS Bot` (or any name you like)
   - Enter username: `my_life_os_bot` (must end in `_bot`)

4. **Copy the token** that looks like:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   **Keep this safe!**

5. **Get your Chat ID:**
   - Message your new bot: `/start`
   - Then message @userinfobot: https://t.me/userinfobot
   - It will reply with your ID (a number like `987654321`)
   - **Copy this number!**

### 3. Set Up Life OS (5 minutes)

```bash
# Navigate to where you want Life OS
cd ~/Documents  # or wherever you prefer

# If you received this as a .skill file, extract it:
# unzip life-os.skill -d life-os

# Navigate into the folder
cd life-os

# Create Python virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows

# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
```

### 4. Configure Your Credentials

Edit the `.env` file:

```bash
# Open with your favorite editor
nano .env  # or: code .env, vim .env, etc.
```

**Add your credentials:**
```bash
TELEGRAM_BOT_TOKEN=<paste your bot token here>
TELEGRAM_CHAT_ID=<paste your chat ID here>

# Leave these as default:
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b
DATABASE_PATH=data/life_os.db
API_PORT=8000
LOG_LEVEL=INFO
```

**Save and exit** (Ctrl+X, then Y in nano)

### 5. Initialize Database

```bash
# Create database with sample data to test
python scripts/init_db.py --seed
```

You should see:
```
Initializing database at data/life_os.db...
Database schema created successfully!
Seeding database with sample data...
  • Added 4 sample tasks
  • Added 2 sample food logs
  • Added 5 sample energy logs
  • Added 1 sample health logs

✅ Database ready at data/life_os.db
```

### 6. Install Dashboard Dependencies

```bash
cd dashboard
npm install
cd ..
```

### 7. Start Life OS

**Make sure Ollama is running:**
```bash
# In a separate terminal
ollama serve
```

**Start all Life OS services:**
```bash
python scripts/start_all.py
```

You should see:
```
==================================================
🚀 Starting Life OS...
==================================================
Starting API Server...
✅ API Server started (PID: 12345)
Starting Automation Engine...
✅ Automation Engine started (PID: 12346)
Starting Telegram Bot...
✅ Telegram Bot started (PID: 12347)
==================================================
✅ All services started!
==================================================

📱 Telegram bot is running - send it a message
🌐 API server: http://localhost:8000
📊 Dashboard: http://localhost:3000 (start with: cd dashboard && npm run dev)

Press Ctrl+C to stop all services
==================================================
```

### 8. Start the Dashboard

**In a new terminal:**
```bash
cd dashboard
npm run dev
```

### 9. Test It!

1. **Open your browser** to http://localhost:3000
2. **Message your Telegram bot**: "Ate breakfast"
3. **Watch the magic happen!** 🎉

## First Steps

Try these commands to get familiar:

**In Telegram, message your bot:**

```
/start
/eatery
Had coffee and toast
Completed morning workout
Feeling energized
/summary
/stats
```

**Watch the dashboard update in real-time!**

## Common Issues

### "Telegram bot not responding"

Check your token and chat ID in `.env`:
```bash
cat .env | grep TELEGRAM
```

Test your token:
```bash
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
```

### "Database error"

Reset it:
```bash
python scripts/init_db.py --reset --seed
```

### "LLM not working"

Check Ollama is running:
```bash
ollama list
ollama serve  # Start if not running
```

### "Dashboard won't start"

Check Node.js version (need 18+):
```bash
node --version
```

Clear and reinstall:
```bash
cd dashboard
rm -rf node_modules
npm install
```

## Next Steps

1. **Read the README.md** for full documentation
2. **Customize automations** in `scripts/automation.py`
3. **Modify the LLM prompts** in `scripts/llm_parser.py`
4. **Adjust dashboard colors** in `dashboard/tailwind.config.js`

## Getting Help

1. Check logs: `tail -f logs/bot.log`
2. Review documentation in `references/`
3. Test components individually
4. Check the troubleshooting section in README.md

## Stopping Life OS

Press **Ctrl+C** in the terminal running `start_all.py`

Or kill processes individually:
```bash
pkill -f "python scripts/"
pkill -f "vite"
```

## Uninstall

```bash
# Stop all services
# Delete the folder
cd ..
rm -rf life-os
```

---

**Congratulations! You now have your own AI-powered Life Operating System!** 🎉

Start tracking your life and watch the insights flow in.
