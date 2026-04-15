# Life OS - Your AI-Powered Life Operating System

A complete, locally-hosted AI command center that uses Telegram as an ultra-low-friction input method to track your tasks, reminders, health, supplements, food intake, and energy levels.

![Life OS Architecture](https://via.placeholder.com/800x400?text=Life+OS+Dashboard)

## ✨ Features

- 🤖 **Natural Language Input** - Just text your Telegram bot like talking to a friend
- 🧠 **Local LLM Processing** - Runs entirely on your machine using Ollama
- 📊 **Beautiful Dashboard** - Real-time React UI inspired by Things 3
- ⚡ **Energy Predictions** - AI predicts energy crashes from food intake
- 🎯 **Smart Reminders** - Contextual task suggestions based on your energy patterns
- 📈 **Automatic Summaries** - Daily and weekly AI-generated summaries
- 🔒 **100% Private** - All data stays on your machine
- 🚀 **Real-time Updates** - WebSocket-powered instant synchronization

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Telegram Bot                             │
│              (Ultra-Low Friction Input)                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Python Ingestion Pipeline                       │
│         (Webhook/Long Polling Handler)                       │
└────────────┬──────────────────────┬─────────────────────────┘
             │                      │
             ▼                      ▼
    ┌──────────────┐      ┌──────────────────┐
    │ Slash        │      │ Natural Language │
    │ Commands     │      │ → Local LLM      │
    │ (/eatery)    │      │ (Ollama)         │
    └──────┬───────┘      └────────┬─────────┘
           │                       │
           │                       ▼
           │              ┌──────────────────┐
           │              │ JSON Extraction  │
           │              │ & Classification │
           │              └────────┬─────────┘
           │                       │
           └───────────┬───────────┘
                       │
                       ▼
            ┌────────────────────┐
            │  SQLite Database   │
            │  (Local Vault)     │
            └──────────┬─────────┘
                       │
                       ▼
            ┌────────────────────┐
            │  FastAPI Backend   │
            │  (REST + WebSocket)│
            └──────────┬─────────┘
                       │
                       ▼
            ┌────────────────────┐
            │  React Dashboard   │
            │  (Real-time UI)    │
            └────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **Node.js 18+**
- **Ollama** ([Download](https://ollama.ai/download))
- **Telegram Account** (to create a bot)

### 1. Install Ollama and Download a Model

```bash
# Install Ollama
# Visit https://ollama.ai/download for your OS

# Download recommended model
ollama pull llama3.1:8b

# Verify it's running
ollama list
```

### 2. Create Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/botfather)
2. Send `/newbot`
3. Follow prompts to name your bot
4. **Save the token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
5. Message your new bot and send `/start`
6. Get your chat ID: Message [@userinfobot](https://t.me/userinfobot)
7. **Save your chat ID** (a number like `987654321`)

### 3. Clone and Setup

```bash
# Navigate to where you want Life OS
cd ~/projects

# Copy the life-os-skill folder to your desired location
cp -r /path/to/life-os-skill ./life-os

cd life-os

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env  # or vim, code, etc.
```

### 4. Configure Environment

Edit `.env`:

```bash
# Your Telegram bot token from BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Your Telegram chat ID from @userinfobot
TELEGRAM_CHAT_ID=987654321

# Ollama configuration (default should work)
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b

# Database location
DATABASE_PATH=data/life_os.db

# API server port
API_PORT=8000

# Logging level
LOG_LEVEL=INFO
```

### 5. Initialize Database

```bash
# Create database with sample data
python scripts/init_db.py --seed

# Or start fresh without sample data
python scripts/init_db.py
```

### 6. Install Dashboard Dependencies

```bash
cd dashboard
npm install
cd ..
```

### 7. Start All Services

**Option A: Start All Together**
```bash
# Ensure Ollama is running first
ollama serve  # In a separate terminal if not running

# Start all Life OS services
python scripts/start_all.py
```

**Option B: Start Separately** (for debugging)
```bash
# Terminal 1: API Server
python scripts/api_server.py

# Terminal 2: Telegram Bot
python scripts/bot.py

# Terminal 3: Automation Engine
python scripts/automation.py

# Terminal 4: Dashboard
cd dashboard && npm run dev
```

### 8. Access the Dashboard

Open your browser to: **http://localhost:3000**

## 📱 Using Life OS

### Telegram Commands

#### Slash Commands (Quick Actions)

- `/start` - Welcome message and help
- `/eatery` - Interactive food logging menu
- `/task` - Quick task creation/completion
- `/energy` - Log current energy level (1-10)
- `/summary` - Get today's summary
- `/stats` - View weekly statistics
- `/help` - Show help message

#### Natural Language Examples

Just text your bot naturally:

**Tasks:**
```
✅ "Finished drafting the affidavit"
📝 "Need to file petition by Friday"
🎯 "Draft quarterly report - high priority"
```

**Food:**
```
🍽️ "Ate dal and rice at 3 PM"
☕ "Had coffee and toast for breakfast"
🥗 "Chicken salad for lunch"
💧 "Drank water"
```

**Energy:**
```
⚡ "Feeling energized"
😴 "Tired after lunch"
🚀 "Peak focus right now"
```

**Health:**
```
💊 "Took vitamin D and magnesium"
😴 "Slept 7.5 hours last night"
🏃 "Went for a 30-minute run"
```

The bot will:
1. Parse your message using local LLM
2. Extract structured data
3. Store in SQLite database
4. Update dashboard in real-time
5. Send confirmation message

### Dashboard Features

**Main Dashboard View:**
- Daily summary card with key metrics
- Task board (Things 3 style)
- Energy level chart with predictions
- Food timeline with macro breakdown

**Tasks View:**
- Kanban-style board
- Pending vs Completed columns
- Priority indicators
- Focus-required tags
- Deadline alerts

**Energy View:**
- Current energy level
- Today's timeline
- Hourly breakdown
- Predicted crashes

**Food View:**
- Meal timeline
- Macro composition (carbs, protein, fat)
- Energy impact predictions
- Common foods tracker

**Stats View:**
- Weekly overview
- Productivity metrics
- Energy patterns (peak/low times)
- Nutrition insights
- Current streak counter

## 🤖 Automation Features

Life OS automatically:

### Nightly Summary (11:59 PM)
```
🌙 Daily Summary - January 15, 2024

You crushed it today! Completed 5 tasks including that 
important quarterly report. Your energy peaked around 
9 AM—that's when you're usually at your best. Consider 
scheduling tomorrow's focus work for that time window.

Stats:
• Tasks: 5 completed, 3 pending
• Meals: 3 logged
• Energy: 7.2/10

Rest well! 😴
```

### Morning Briefing (8:00 AM)
```
☀️ Good Morning!

Yesterday:
• 5 tasks completed
• Energy avg: 7.2/10

Today's Top Tasks:
1. 🔴 File petition
2. 🟡 Review proposals
3. 🟢 Call dentist

💡 Tip: You're usually most energized at 09:00

Have a productive day! 🚀
```

### Energy Crash Warnings
```
⚠️ Energy Alert

Heavy carbs detected. Energy dip expected in 45 mins.

Consider:
• Taking a short walk
• Having a healthy snack
• Taking a brief break

Stay energized! ⚡
```

### Contextual Reminders
```
🎯 Perfect Timing!

You're usually at peak energy right now. Great time 
to tackle:

Draft quarterly report

Make it count! 💪
```

### Weekly Review (Sunday 9 PM)
```
📊 Weekly Review

Productivity:
• 20 tasks completed
• 80.0% completion rate
• 7 day streak 🔥

Energy Patterns:
• Average: 7.1/10
• Peak time: 09:00
• Low time: 15:00

Nutrition:
• 21 meals logged
• Top food: rice

Keep up the great work! 💪
```

## 🎨 Customization

### Modify LLM Behavior

Edit `scripts/llm_parser.py`:

```python
def _get_system_prompt(self):
    # Add new categories
    # Adjust energy prediction rules
    # Change time parsing logic
    # Modify priority detection
```

### Add New Automation

Edit `scripts/automation.py`:

```python
async def custom_reminder(self):
    """Your custom automation"""
    # Check conditions
    # Send Telegram message
    # Log to database

# Schedule it
self.scheduler.add_job(
    self.custom_reminder,
    CronTrigger(hour=14, minute=0),  # 2 PM daily
    id='custom_reminder'
)
```

### Customize Dashboard Theme

Edit `dashboard/tailwind.config.js`:

```javascript
theme: {
  extend: {
    colors: {
      // Your custom colors
      primary: '#your-color',
    },
  },
}
```

### Add Database Tables

Edit `scripts/database.py`:

```python
class CustomLog(Base):
    __tablename__ = 'custom_logs'
    id = Column(Integer, primary_key=True)
    # Your fields
```

## 📊 Data Management

### Backup Database

```bash
# Manual backup
cp data/life_os.db backups/life_os_$(date +%Y%m%d).db

# Automated daily backup (add to cron)
0 0 * * * cp /path/to/life_os.db /path/to/backups/life_os_$(date +\%Y\%m\%d).db
```

### Export Data

```bash
# Export to JSON
python -c "
from scripts.database import Database
import json

db = Database()
tasks = db.get_tasks(limit=1000)

with open('export.json', 'w') as f:
    json.dump([t.to_dict() for t in tasks], f, indent=2)
"
```

### Reset Database

```bash
python scripts/init_db.py --reset --seed
```

## 🔧 Troubleshooting

### Bot Not Responding

```bash
# Check if bot is running
ps aux | grep bot.py

# Check logs
tail -f logs/bot.log

# Verify Telegram token
echo $TELEGRAM_BOT_TOKEN

# Test bot manually
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
```

### LLM Not Parsing

```bash
# Check Ollama
ollama list
ollama serve  # Start if not running

# Test LLM directly
ollama run llama3.1:8b "Parse: Ate rice at 3 PM"

# Check model is correct
cat .env | grep LLM_MODEL
```

### Dashboard Not Updating

```bash
# Check WebSocket connection (browser console)
# Should show: "WebSocket connected"

# Check API server
curl http://localhost:8000/api/health

# Restart services
pkill -f "python scripts/"
python scripts/start_all.py
```

### Database Errors

```bash
# Check file permissions
ls -la data/life_os.db

# Fix permissions
chmod 644 data/life_os.db

# Check for corruption
sqlite3 data/life_os.db "PRAGMA integrity_check;"

# Reset if needed
python scripts/init_db.py --reset
```

## 📚 Documentation

- [SKILL.md](SKILL.md) - Complete skill documentation
- [references/prompts.md](references/prompts.md) - LLM prompt guide
- [references/database_schema.md](references/database_schema.md) - Database schema
- [references/api_docs.md](references/api_docs.md) - API reference

## 🛠️ Development

### Project Structure

```
life-os/
├── scripts/              # Python backend
│   ├── bot.py           # Telegram bot
│   ├── llm_parser.py    # LLM integration
│   ├── database.py      # Database models
│   ├── api_server.py    # FastAPI backend
│   ├── automation.py    # Background tasks
│   ├── init_db.py       # DB initialization
│   └── start_all.py     # Service launcher
├── dashboard/           # React frontend
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   └── hooks/
│   └── package.json
├── references/          # Documentation
├── data/                # SQLite database
├── logs/                # Log files
├── .env                 # Configuration
└── requirements.txt
```

### Running Tests

```bash
# Test database operations
python -c "from scripts.database import Database; db = Database(); print(db.get_tasks())"

# Test LLM parsing
python -c "from scripts.llm_parser import LLMParser; import asyncio; p = LLMParser(); print(asyncio.run(p.parse_message('Ate rice')))"

# Test API endpoints
curl http://localhost:8000/api/tasks
curl http://localhost:8000/api/summary/today
```

## 🚀 Deployment

### Local Network Access

To access from other devices on your network:

1. Find your local IP:
```bash
ifconfig | grep "inet "  # macOS/Linux
ipconfig  # Windows
```

2. Update dashboard API URL in `dashboard/src/hooks/useData.js`:
```javascript
const API_URL = 'http://192.168.1.100:8000/api';
```

3. Start with network binding:
```bash
uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000
```

### Production Deployment (Advanced)

Not recommended for beginners. Life OS is designed for local use.

If you must deploy:
- Use HTTPS (Let's Encrypt + nginx)
- Add authentication (OAuth2, API keys)
- Use gunicorn for API
- Deploy dashboard as static build
- Set up monitoring (Sentry, DataDog)
- Regular backups
- Rate limiting
- CORS configuration

## 🤝 Contributing

This is a skill/template. Fork and customize for your needs!

Ideas for contributions:
- Voice input support
- Image recognition for food
- More automation recipes
- Mobile app (React Native)
- Integrations (Notion, Obsidian, etc.)
- Multi-user support
- Advanced analytics

## 📄 License

MIT License - Feel free to use and modify!

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Powered by [Ollama](https://ollama.ai/)
- UI inspired by [Things 3](https://culturedcode.com/things/)
- React + [Tailwind CSS](https://tailwindcss.com/)

## 📬 Support

Questions? Issues? Ideas?

1. Check documentation in `references/`
2. Review troubleshooting section above
3. Test individual components
4. Check logs in `logs/` directory

---

**Built with ❤️ for personal productivity and privacy**

*Your data, your machine, your life OS.*
