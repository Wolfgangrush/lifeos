---
name: life-os
description: Complete AI-powered Life Operating System for frictionless personal tracking via Telegram. Use when users want to track tasks, food, health, supplements, energy levels, or build a personal productivity dashboard. Triggers on mentions of "life tracking," "personal OS," "Telegram bot," "productivity system," "food logging," "task tracking," "energy monitoring," or requests to build an integrated life management system. Also use for setting up local LLM parsing, SQLite databases, real-time dashboards, or webhook-based input systems.
---

# Life Operating System

A complete, locally-hosted AI-powered command center that uses Telegram as an ultra-low-friction input method to track tasks, reminders, health, supplements, food intake, and energy levels.

## System Architecture

```
┌─────────────────┐
│  Telegram Bot   │  ← User sends messages
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Python Ingestion Pipeline          │
│  (Webhook/Long Polling)              │
└────────┬────────────────────────────┘
         │
         ├──→ Slash Commands (/eatery, /task, etc.)
         │
         ├──→ Natural Language → Local LLM (Ollama)
         │                        │
         │                        ▼
         │              ┌──────────────────┐
         │              │  JSON Extraction  │
         │              │  & Classification │
         │              └────────┬──────────┘
         ▼                       │
┌──────────────────┐            │
│  SQLite Database │ ←──────────┘
│  (Local Vault)   │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────┐
│  FastAPI Backend             │
│  (Serves data via WebSocket) │
└────────┬─────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  React + Tailwind Dashboard  │
│  (Real-time UI)              │
└──────────────────────────────┘
```

## Components Overview

1. **Telegram Webhook Handler** - Captures all user input
2. **Local LLM Parser** - Extracts structured data from natural language
3. **SQLite Database** - Stores all logs and events
4. **FastAPI Backend** - Serves data to frontend
5. **React Dashboard** - Beautiful real-time UI
6. **Automation Engine** - Nightly summaries and contextual reminders

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+ (for dashboard)
- Ollama installed with a model (recommended: `llama3.1:8b`)
- Telegram Bot Token (from @BotFather)

### Installation

```bash
# 1. Set up Python environment
cd life-os
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Telegram token and settings

# 3. Initialize database
python scripts/init_db.py

# 4. Install dashboard dependencies
cd dashboard
npm install

# 5. Start all services
cd ..
python scripts/start_all.py
```

## File Structure

```
life-os/
├── scripts/
│   ├── bot.py              # Telegram bot handler
│   ├── llm_parser.py       # LLM parsing engine
│   ├── database.py         # Database models & operations
│   ├── api_server.py       # FastAPI backend
│   ├── automation.py       # Background tasks & reminders
│   ├── init_db.py          # Database initialization
│   └── start_all.py        # Launch all services
├── dashboard/
│   ├── src/
│   │   ├── App.jsx         # Main React component
│   │   ├── components/     # UI components
│   │   └── hooks/          # WebSocket & data hooks
│   ├── package.json
│   └── vite.config.js
├── references/
│   ├── prompts.md          # LLM system prompts
│   ├── database_schema.md  # Database design
│   └── api_docs.md         # API endpoints
├── .env.example
├── requirements.txt
└── SKILL.md (this file)
```

## Usage Guide

### Text the Bot

Simply message your Telegram bot with natural language:

- **Tasks**: "Finished drafting the affidavit"
- **Food**: "Ate dal and rice at 3 PM"
- **Health**: "Took vitamin D and magnesium"
- **Reminders**: "Need to draft this petition by Friday"
- **Energy**: "Feeling sluggish after lunch"

### Slash Commands

Quick access to common functions:

- `/eatery` - Interactive food logging menu
- `/task` - Quick task creation
- `/energy` - Log current energy level
- `/summary` - Get today's summary
- `/stats` - View weekly statistics

### View the Dashboard

Open `http://localhost:3000` in your browser to see:

- Real-time task list (Things 3 style)
- Energy level graph throughout the day
- Food intake timeline with macro predictions
- Upcoming reminders based on energy patterns
- Daily summary cards

## Implementation Details

### 1. Telegram Bot (scripts/bot.py)

The bot uses `python-telegram-bot` with long polling for reliability. It:

- Receives all messages
- Routes slash commands to handlers
- Sends natural language to LLM parser
- Provides interactive keyboards for quick input
- Sends real-time confirmations back to user

Key features:
- Handles rate limiting gracefully
- Queues messages when LLM is busy
- Supports voice messages (converted to text)
- Markdown formatting in responses

### 2. LLM Parser (scripts/llm_parser.py)

Uses Ollama's API to run a local model. Critical system prompt enforces:

- JSON-only output (no preambles)
- Strict categorization: `task_complete`, `task_pending`, `food_log`, `health_metric`, `energy_level`
- Macro estimation for food
- Energy prediction based on food composition
- Smart time parsing (relative and absolute)

Example interaction:
```
Input: "Ate dal and rice at 3 PM"
Output: {
  "type": "food_log",
  "timestamp": "15:00",
  "items": ["dal", "rice"],
  "macros": {"carbs": "high", "protein": "medium", "fat": "low"},
  "energy_prediction": {
    "status": "crash_warning",
    "time_of_crash": "15:45",
    "message": "Heavy carbs detected. Energy dip expected in 45 mins."
  }
}
```

### 3. Database (scripts/database.py)

SQLite schema with interconnected tables:

**Tasks**
- id, description, status, created_at, completed_at, priority, focus_required

**FoodLogs**
- id, timestamp, items (JSON), macros (JSON), energy_prediction (JSON)

**EnergyLevels**
- id, timestamp, level (1-10), context, predicted (boolean)

**HealthLogs**
- id, timestamp, supplements (JSON), metrics (JSON)

**SystemEvents**
- id, timestamp, event_type, data (JSON), triggered_by

All tables indexed for fast queries. Full-text search enabled on descriptions.

### 4. API Server (scripts/api_server.py)

FastAPI endpoints:

**HTTP Endpoints**
- `GET /api/tasks` - Get all tasks (with filters)
- `GET /api/food` - Get food logs (date range)
- `GET /api/energy` - Get energy timeline
- `GET /api/summary/{date}` - Get daily summary
- `GET /api/stats` - Get aggregate statistics

**WebSocket**
- `WS /ws` - Real-time updates when data changes
- Broadcasts: `task_updated`, `food_logged`, `energy_predicted`

### 5. Dashboard (dashboard/src/)

React components styled with Tailwind CSS:

**Components**
- `TaskBoard` - Kanban-style task view with drag-and-drop
- `EnergyChart` - Real-time line chart with predictions
- `FoodTimeline` - Visual food log with macro breakdowns
- `DailySummary` - AI-generated summary card
- `UpcomingReminders` - Context-aware task suggestions

**Features**
- Dark mode support
- Responsive design (mobile-friendly)
- Smooth animations
- Live updates via WebSocket
- Keyboard shortcuts

### 6. Automation Engine (scripts/automation.py)

Background scheduler that runs:

**Nightly Summary (11:59 PM)**
```python
# Queries all day's data
# Feeds to LLM: "Summarize this person's day"
# Stores in SystemEvents
# Sends to Telegram
```

**Energy Predictions (Continuous)**
```python
# When food logged:
#   - Calculate potential crash time
#   - Schedule notification
#   - Update dashboard
```

**Contextual Reminders**
```python
# Analyzes task + historical energy data
# Suggests optimal time blocks
# "You're usually energized at 9 AM - good time for 'Draft petition'"
```

**Weekly Review (Sunday 9 PM)**
```python
# Aggregate week's data
# Generate insights report
# Send to Telegram + save to dashboard
```

## Advanced Customization

### Custom LLM Prompts

Edit `references/prompts.md` to modify how the LLM categorizes input. Examples:

- Add new categories (e.g., `mood_log`, `exercise`)
- Adjust energy prediction logic
- Change macro estimation rules

### Dashboard Themes

Modify `dashboard/src/styles/theme.js` for custom colors and layouts.

### Notification Rules

Edit `scripts/automation.py` to add custom triggers:

```python
# Example: Warn if no water logged by 2 PM
if current_hour == 14 and not water_logged_today():
    send_telegram_message("Remember to drink water! 💧")
```

### Database Extensions

Add new tables in `scripts/database.py`:

```python
class MoodLog(Base):
    __tablename__ = 'mood_logs'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    mood = Column(String)  # happy, neutral, stressed, etc.
    context = Column(String)
```

## Troubleshooting

**Bot not responding**
- Check Telegram token in `.env`
- Verify bot is running: `ps aux | grep bot.py`
- Check logs: `tail -f logs/bot.log`

**LLM returning invalid JSON**
- Ensure Ollama is running: `ollama list`
- Try a different model: Edit `LLM_MODEL` in `.env`
- Check system prompt in `references/prompts.md`

**Dashboard not updating**
- Check WebSocket connection in browser console
- Verify FastAPI is running on port 8000
- Ensure SQLite database is not locked

**Database errors**
- Reset database: `python scripts/init_db.py --reset`
- Check permissions on `data/life_os.db`

## Security Notes

- All data is local - nothing sent to cloud
- Telegram messages are encrypted in transit
- Consider encrypting SQLite database for sensitive health data
- Use environment variables for all secrets
- Never commit `.env` file to version control

## Performance Optimization

- SQLite handles 100K+ entries easily
- LLM parsing typically <500ms with `llama3.1:8b`
- Dashboard updates in <50ms via WebSocket
- Weekly cleanup script removes old predictions

## Future Enhancements

Potential additions:

1. **Voice Input** - Direct voice messages to bot
2. **Image Recognition** - Photo food logging
3. **Habit Tracking** - Streak visualization
4. **Goal Setting** - Progress tracking
5. **Export** - PDF reports, CSV exports
6. **Mobile App** - Native iOS/Android
7. **Multi-user** - Family/team tracking
8. **Integrations** - Calendar, fitness trackers

## Support

For questions or issues:
1. Check `references/` folder for detailed docs
2. Review logs in `logs/` directory
3. Test individual components in isolation

## License

MIT License - Use freely for personal or commercial projects.
