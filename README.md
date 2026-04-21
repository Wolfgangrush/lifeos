# Life OS

A locally-hosted, AI-powered personal command center. Talk to a Telegram bot in natural language to track tasks, food, supplements, energy, expenses, reminders, and more. Everything is stored on your machine in SQLite and displayed in a real-time React dashboard.

```
You  ──►  Telegram  ──►  Ollama (local LLM)  ──►  SQLite  ──►  React Dashboard
                              + Gemini (optional, for insights)
```

## What It Does

| You say in Telegram | What happens |
|---|---|
| "Finished the quarterly report" | Logs a completed task |
| "Need to file appeal by Friday" | Creates a pending task with deadline |
| "Had paneer butter masala for lunch" | Logs food with estimated nutrition |
| "Spent 2500 on groceries" | Logs an expense |
| "At the office" | Starts a location timer |
| "Leaving" | Stops the timer, shows duration |
| "Remind me to call the bank tomorrow 10am" | Sets a reminder |
| "How's my day going?" | Returns an AI-generated summary |
| "Energy 7" | Logs current energy level (1-10) |
| "Took vitamin D and magnesium" | Logs supplement intake |

The dashboard updates in real time via WebSocket.

---

## Prerequisites

| Dependency | Version | What it does |
|---|---|---|
| **Python** | 3.10+ | Runs the bot, API server, and automation engine |
| **Node.js** | 18+ | Runs the React dashboard (Vite dev server) |
| **Ollama** | latest | Hosts the local LLM for natural language parsing |
| **Telegram account** | -- | Used to create a bot via @BotFather |

Optional: a **Google Gemini API key** for internet-powered insights and analysis.

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/Wolfgangrush/lifeos.git
cd lifeos
```

### 2. Install Ollama and pull a model

macOS:
```bash
brew install ollama
```

Linux:
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

Windows: download from [ollama.com/download](https://ollama.com/download).

Then pull the model:
```bash
ollama serve          # start the Ollama server (keep this running)
ollama pull llama3.2:latest
```

### 3. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/botfather).
2. Send `/newbot` and follow the prompts.
3. Copy the **bot token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`).
4. Message your new bot `/start` to activate it.
5. Message [@userinfobot](https://t.me/userinfobot) to get your **user/chat ID** (a number like `987654321`).

### 4. Run the configure script

```bash
./configure.sh
```

This will:
- Create a Python virtualenv and install dependencies
- Install Node.js dependencies
- Copy `.env.example` to `.env` (if it doesn't exist)
- On macOS: install a LaunchAgent so LifeOS runs in the background and the `operator` command works

### 5. Add your credentials to `.env`

Open `.env` in any editor and fill in your values:

```bash
nano .env
```

```env
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321
TELEGRAM_USER_ID=987654321

# Local LLM (defaults work if Ollama is running)
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.2:latest

# Optional: Gemini for internet-powered insights
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# Database
DATABASE_PATH=data/life_os.db

# API Server
API_PORT=8000
LOG_LEVEL=INFO
NUTRITION_PROVIDER=local
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173
```

### 6. Initialize the database

```bash
python3 init_db.py --seed    # with sample data
# or
python3 init_db.py           # empty database
```

### 7. Start LifeOS

**Option A -- All-in-one (recommended):**

```bash
python3 start_all.py
```

This starts the Telegram bot, API server, and automation engine together.

**Option B -- Services separately (for debugging):**

```bash
# Terminal 1: API server
python3 api_server.py

# Terminal 2: Telegram bot
python3 bot.py

# Terminal 3: Automation engine
python3 automation.py

# Terminal 4: Dashboard
npm run dev
```

**Option C -- macOS background service:**

If you ran `./configure.sh` on macOS, you can use the `operator` command:

```bash
operator on        # start as background service
operator status    # check if running
operator restart   # restart all services
operator off       # stop
operator logs      # view recent logs
operator tail      # follow the log live
```

### 8. Open the dashboard

```
http://127.0.0.1:3000
```

Start the Vite dev server if it isn't already running:

```bash
npm run dev
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Telegram Chat                     │
│           (your natural-language input)           │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│            Python Ingestion Pipeline             │
│         bot.py  /  pure_telegram_bot_v4.py       │
└────────┬───────────────────────┬────────────────┘
         │                       │
         ▼                       ▼
┌────────────────┐      ┌────────────────┐
│  Ollama        │      │  Gemini        │
│  (local LLM)   │      │  (cloud, opt.) │
│  classification │      │  insights      │
└───────┬────────┘      └───────┬────────┘
        │                       │
        └───────────┬───────────┘
                    ▼
         ┌────────────────────┐
         │   SQLite Database  │
         │   data/life_os.db  │
         └─────────┬──────────┘
                   │
                   ▼
         ┌────────────────────┐
         │  FastAPI + WS      │
         │  api_server.py     │
         │  :8000             │
         └─────────┬──────────┘
                   │
                   ▼
         ┌────────────────────┐
         │  React Dashboard   │
         │  Vite + Tailwind   │
         │  :3000             │
         └────────────────────┘
```

### Key files

| File | Purpose |
|---|---|
| `bot.py` | Main Telegram bot with all command handlers |
| `api_server.py` | FastAPI backend serving REST + WebSocket |
| `database.py` | SQLAlchemy models and all DB operations |
| `llm_parser.py` | Sends messages to Ollama, extracts structured JSON |
| `automation.py` | Scheduled jobs: summaries, reminders, energy alerts |
| `insights_engine.py` | Proactive pattern analysis engine |
| `conversation_memory.py` | Conversation history, entity extraction, mood tracking |
| `nutrition_estimator.py` | Estimates macros from food descriptions |
| `gemini_web_agent.py` | Gemini-powered web browsing for research |
| `start_all.py` | Launches all services together |
| `App.jsx` | Main React dashboard component |
| `useData.js` | React hook for API data fetching |
| `useWebSocket.js` | React hook for real-time WebSocket updates |
| `configure.sh` | One-command setup script |
| `Operator` | macOS service manager (start/stop/restart) |

---

## Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Welcome message |
| `/help` | Show all commands |
| `/task` | Create or manage tasks |
| `/newtask` | Quick task creation |
| `/delete_task` | Remove a task |
| `/eatery` | Interactive food logging |
| `/food` | Log food |
| `/foodtoday` | View today's food with delete option |
| `/delete_food` | Remove a food entry |
| `/energy` | Log energy level (1-10) |
| `/supplements` | Log supplement intake |
| `/addsupplement` | Add a supplement to your stack |
| `/removesupplement` | Remove a supplement |
| `/remind` | Set a reminder |
| `/reminders` | View pending reminders |
| `/summary` | Today's AI summary |
| `/stats` | Weekly statistics |
| `/analyze` | Deep AI analysis of your data |
| `/mood` | View mood/sentiment trends |
| `/style` | Change bot response style (brief/friendly/analytical) |
| `/rollover` | Move yesterday's pending tasks to today |
| `/operator` | Check service status |

You can also just type naturally -- the LLM figures out what you mean.

---

## Dashboard

The React dashboard at `http://127.0.0.1:3000` shows:

- **Daily summary** with key metrics
- **Task board** (Things 3-style, pending vs completed)
- **Energy chart** with hourly timeline
- **Food timeline** with macro breakdown and edit/delete
- **Court board** panel for case/project tracking
- **Coach analysis** with AI-generated insights
- **History strip** to browse previous days

All panels update in real time via WebSocket.

---

## Automation

The automation engine runs in the background and sends you Telegram messages:

| Automation | When | What |
|---|---|---|
| Morning briefing | 8:00 AM | Yesterday's recap + today's priorities |
| Energy crash warning | After heavy meals | "Energy dip expected in 45 min" |
| Peak energy nudge | During your peak hours | Suggests tackling hard tasks |
| Nightly summary | 11:59 PM | Full day recap with stats |
| Weekly review | Sunday 9 PM | Week-level patterns and streaks |
| Smart reminders | Context-dependent | Proactive suggestions from patterns |

---

## Customization

### Change the LLM model

Edit `.env`:
```env
LLM_MODEL=llama3.1:70b    # larger model, slower but smarter
LLM_MODEL=mistral:7b      # alternative model
LLM_MODEL=phi3:mini        # smaller, faster
```

Make sure you've pulled the model first: `ollama pull <model-name>`

### Add supplements to your stack

Use `/addsupplement` in Telegram, or edit the `DEFAULT_SUPPLEMENTS` list in `bot.py`.

### Customize the dashboard theme

Edit `tailwind.config.js` and `index.css`.

### Add new automation rules

Edit `automation.py` and add scheduled jobs:

```python
self.scheduler.add_job(
    self.your_custom_job,
    CronTrigger(hour=14, minute=0),  # runs at 2 PM daily
    id='your_custom_job'
)
```

### Modify LLM prompts

Edit `llm_parser.py` to change how natural language is parsed, add new categories, or adjust classification rules.

### Change response style

Use `/style` in Telegram to switch between:
- **Brief** -- terse confirmations
- **Friendly** -- conversational with encouragement (default)
- **Analytical** -- data-heavy responses with metrics

---

## Data & Privacy

- All data is stored locally in `data/life_os.db` (SQLite).
- The Telegram bot token is the only external credential required.
- Ollama runs entirely on your machine -- no data leaves your network.
- Gemini API calls (if configured) are only made when you explicitly request insights or analysis. This is optional.
- The `.env` file containing your credentials is gitignored and never committed.

### Backup your data

```bash
cp data/life_os.db data/life_os_backup_$(date +%Y%m%d).db
```

### Reset the database

```bash
python3 init_db.py --reset --seed
```

---

## Troubleshooting

**Bot not responding:**
```bash
# Check if Ollama is running
ollama list

# Check your bot token
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe

# Check logs
tail -f logs/bot.log
```

**Dashboard not loading:**
```bash
# Check if API server is up
curl http://127.0.0.1:8000/api/health

# Check if ports are in use
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN

# Restart
npm run dev           # dashboard
python3 api_server.py # API
```

**Database locked:**
```bash
# Stop all running instances
pkill -f bot.py
pkill -f api_server.py
pkill -f pure_telegram_bot

# Then restart
python3 start_all.py
```

**LLM parsing errors:**
```bash
# Make sure model is downloaded
ollama pull llama3.2:latest

# Test it manually
ollama run llama3.2:latest "Parse: Ate rice at 3 PM"
```

---

## Project Structure

```
los/
├── bot.py                    # Telegram bot (main)
├── api_server.py             # FastAPI backend
├── database.py               # SQLAlchemy models + queries
├── llm_parser.py             # Ollama LLM integration
├── automation.py             # Scheduled automations
├── insights_engine.py        # Proactive insights engine
├── conversation_memory.py    # Conversation context + entities
├── nutrition_estimator.py    # Food macro estimation
├── gemini_web_agent.py       # Gemini web browsing agent
├── health_image_analyzer.py  # Image-based health analysis
├── daily_export.py           # Daily data export
├── start_all.py              # Service launcher
├── init_db.py                # Database initialization
├── configure.sh              # One-command setup
├── Operator                  # macOS service manager
├── run_lifeos_bot.sh         # Launchd wrapper script
├── com.lifeos.bot.plist      # macOS LaunchAgent template
├── App.jsx                   # React dashboard (main)
├── TaskBoard.jsx             # Task board component
├── EnergyChart.jsx           # Energy chart component
├── FoodTimeline.jsx          # Food timeline component
├── DailySummary.jsx          # Summary component
├── CoachPanel.jsx            # AI coach component
├── CourtBoardPanel.jsx       # Court/project board component
├── ErrorBoundary.jsx         # React error boundary
├── useData.js                # Data fetching hook
├── useWebSocket.js           # WebSocket hook
├── main.jsx                  # React entry point
├── index.html                # HTML entry point
├── index.css                 # Styles (Tailwind)
├── tailwind.config.js        # Tailwind configuration
├── postcss.config.js         # PostCSS configuration
├── vite.config.js            # Vite configuration
├── package.json              # Node dependencies
├── requirements.txt          # Python dependencies
├── requirements_telegram.txt # Telegram-specific Python deps
├── .env.example              # Environment variable template
├── .gitignore                # Git ignore rules
└── data/                     # SQLite database (gitignored)
```

---

## License

Apache 2.0. See [LICENSE](LICENSE).
