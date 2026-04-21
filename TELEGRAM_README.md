# Pure Telegram Life OS

Your entire life tracking system, now in a simple Telegram chat. No web dashboard, no localhost - just natural conversation.

## What It Does

Talk naturally and the bot understands:

| You say | Bot does |
|---------|----------|
| "Drafted APL application for quashing" | Logs as completed task (legal work) |
| "At High Court" | Starts timer, logs check-in |
| "Transit" | Ends timer, calculates duration |
| "Had paneer butter masala" | Logs food with nutrition info |
| "Spent 2500 on groceries" | Logs expense |
| "Note: Judge mentioned 2019 precedent" | Saves note |
| "Remind me to call Sharma ji next week" | Sets reminder |
| "How's my day going?" | Analyzes data, gives insights |

## Setup (5 minutes)

### 1. Get Telegram Bot Token

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Name your bot (e.g., "My Life OS")
4. Copy the token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Gemini API Key (for smart insights)

1. Go to https://makersuite.google.com/app/apikey
2. Create a new API key
3. Copy it

### 3. Install Ollama (for local AI)

```bash
# Mac
brew install ollama

# Or download from: https://ollama.com/download

# Start Ollama and pull the model
ollama serve
ollama pull llama3.1:8b
```

### 4. Configure the Bot

```bash
# Run setup
./setup_telegram_bot.sh

# Edit .env file with your tokens
nano .env  # or use your preferred editor
```

Add to `.env`:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
GEMINI_API_KEY=AIzaSyC-abcdefghijklmnopqrstuvwxyz123456
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b
DATABASE_PATH=data/life_os.db
```

### 5. Start the Bot

```bash
./start_telegram_bot.sh
```

Or:
```bash
python3 pure_telegram_bot.py
```

## Using the Bot

### Tasks (Work & Personal)

**Completed tasks:**
- "Drafted APL application for quashing"
- "Filed motion in Civil Suit 456/2024"
- "Meeting with Sharma ji concluded"
- "Cleaned the bathroom"

**Pending tasks:**
- "Need to file appeal by Friday"
- "Review client documents tomorrow"
- "Call insurance company"

### Food

- "Had paneer butter masala for lunch"
- "Coffee and sandwich"
- "Ate dal rice and curd"

### Expenses

- "Spent 2500 on groceries"
- "Paid 500 for parking"
- "Petrol 2000 rupees"

### Location Tracking

- "At High Court" → Starts timer ⏱️
- "Transit" or "Leaving" → Stops timer, shows duration

### Notes

- "Note: Judge mentioned 2019 precedent in similar case"
- "Remember to check case file Cavity 123"
- "Save this: Client wants settlement by next week"

### Reminders

- "Remind me to call Sharma ji next week"
- "Remind me to file appeal on Friday 10am"

### Insights (Ask anything)

- "How's my day going?"
- "What did I do today?"
- "Show my productivity"
- "Analyze my spending"
- "Weekly summary"
- "Show court board"

## Architecture

```
┌─────────────────┐
│  Telegram Chat  │ ← You talk here naturally
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   pure_telegram_bot.py          │
│   - Message handler             │
│   - Intent detection            │
└──────────────┬──────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌──────────────┐  ┌──────────────┐
│   Ollama     │  │   Gemini     │
│  (Local LLM) │  │ (Internet)   │
│  Understands │  │  Provides    │
│  your input  │  │  insights    │
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
       ┌────────────────┐
       │  SQLite DB     │
       │  (All your     │
       │   life data)   │
       └────────────────┘
```

## Stopping the Web Dashboard

To run only Telegram mode, stop the web services:

```bash
# Stop if running
pkill -f api_server.py
pkill -f uvicorn

# Run only Telegram bot
./start_telegram_bot.sh
```

## Troubleshooting

**Ollama connection failed:**
```bash
# Make sure Ollama is running
ollama serve
```

**Database locked:**
```bash
# Stop any running instances
pkill -f pure_telegram_bot.py
pkill -f api_server.py
```

**Bot not responding:**
- Check bot token in `.env`
- Make sure you've started a chat with your bot in Telegram
- Check logs: `tail -f logs/telegram_bot.log`

## Features Summary

| Feature | Command |
|---------|---------|
| Log completed task | Just say what you did |
| Add pending task | "Need to..." or "Have to..." |
| Log food | "Had/ate..." |
| Log expense | "Spent/paid..." |
| Check in | "At [place]" |
| Check out | "Transit", "Leaving" |
| Save note | "Note: ..." |
| Set reminder | "Remind me to..." |
| Get insights | "How's my day/week?" |
| Court board | "Show board" or "Add to board..." |

---

Everything stored locally on your Mac. Telegram messages are encrypted. Gemini API calls are only made when you ask for insights.
