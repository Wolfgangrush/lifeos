# Enhanced Life OS - Smart Features Installation Guide

## Overview

This upgrade adds **10 major enhancements** to your Life OS Telegram bot:

1. ✅ **Conversation Memory** - Bot remembers past conversations
2. ✅ **Temporal Pattern Recognition** - Time-aware context (morning/afternoon/evening)
3. ✅ **Proactive Insights Engine** - Automated pattern analysis and suggestions
4. ✅ **Entity Extraction** - Remembers people, projects, locations
5. ✅ **Sentiment/Mood Tracking** - Tracks emotional trends over time
6. ✅ **Function Calling with JSON Schema** - More reliable structured output
7. ✅ **Adaptive Response Styles** - Brief, Friendly, or Analytical modes
8. ✅ **Ambiguity Resolution** - Smart clarification with actual options
9. ✅ **Scheduled Reminders** - Proactive notifications based on patterns
10. ✅ **Model Selection Optimization** - Fast vs smart model routing

## Installation

### Step 1: Backup Your Current Setup

```bash
cd /Users/wolfgang_rush/Desktop/los
cp bot.py bot.backup.py
cp llm_parser.py llm_parser.backup.py
cp database.py database.backup.py
```

### Step 2: Update Python Dependencies

Add these to your `requirements.txt` if not present:

```text
python-telegram-bot==20.7
sqlalchemy==2.0.23
httpx==0.25.2
python-dotenv==1.0.0
```

Install:

```bash
source .venv/bin/activate  # or source .venv312/bin/activate
pip install -r requirements.txt
```

### Step 3: Update Environment Variables

Add to your `.env` file:

```bash
# LLM Settings
OLLAMA_URL=http://localhost:11434
LLM_MODEL=llama3.1:8b

# Telegram (already set)
TELEGRAM_BOT_TOKEN=your_token_here

# Optional: For insights scheduler
ENABLE_INSIGHTS_SCHEDULER=true
```

### Step 4: Run Database Migration

The new features require additional database tables. Run:

```bash
python -c "
from conversation_memory import ConversationMemory
from database import Database
db = Database()
memory = ConversationMemory(db)
print('Database tables created successfully!')
"
```

### Step 5: Start the Enhanced Bot

```bash
# Option A: Run enhanced bot directly
python enhanced_bot.py

# Option B: Or use your existing start_all.py (after updating)
python start_all.py
```

## New Commands

| Command | Description |
|---------|-------------|
| `/style` | Change how the bot responds (Brief/Friendly/Analytical) |
| `/insights` | View recent proactive insights |
| `/mood` | See your mood trends over time |
| `/entities` | View remembered people, projects, locations |

## Response Styles

### Brief Mode
```
You: "Finished the report"
Bot: "Logged: Report complete."
```

### Friendly Mode (default)
```
You: "Finished the report"
Bot: "Awesome work! 🎉 I've logged that. How are you feeling about it?"
```

### Analytical Mode
```
You: "Finished the report"
Bot: "Task logged: Report (completed). Duration: ~3 hours. Productivity: +1 task today."
```

## How Smart Features Work

### Conversation Memory
The bot now remembers context from previous messages:

```
You: "I'm so tired"
Bot: "That sounds tough. When did you start feeling this way?"
You: "Since lunch"
Bot: "Got it. Since around 1 PM then. Did you have a heavy meal?"
```

### Temporal Awareness
Responses adapt to time of day:

```
[8 AM] You: "Hey"
Bot: "Good morning! ☀️ Ready to start the day?"

[2 PM] You: "Hey"
Bot: "Hey! Afternoon energy check-in - how's it going?"

[9 PM] You: "Hey"
Bot: "Good evening! 🌙 Winding down or still working?"
```

### Entity Extraction
The bot remembers people, projects, and places:

```
You: "Working on the Peterson report"
Bot: "Got it! I'll track the Peterson report."
...
[Later]
You: "Done with Peterson"
Bot: "Marked Peterson report as complete!"
```

### Mood Tracking
The bot detects and tracks emotional sentiment:

```
You: "Ugh, I'm so overwhelmed"
Bot: "I hear you. 😔 That sounds stressful. Want to talk about what's overwhelming?"
[Bot logs: sentiment=-0.7, emotion=stressed]
```

### Proactive Insights
The bot analyzes patterns and sends insights:

```
[Daily insight at 9 AM]
Bot: "🔥 Productive Day!
You completed 6 tasks yesterday! That's your best day this week.
Keep the momentum going - start with your hardest task."
```

### Smart Clarification
When unclear, shows actual options:

```
You: "Done"
Bot: "Done with what? I see you have these active tasks:
[1] Draft quarterly report
[2] Call dentist
[3] Review budget
[Reply with choice or type your own]"
```

## Architecture Overview

```
enhanced_bot.py          # Main bot with all smart features
├── enhanced_llm_parser.py    # LLM with memory, entities, sentiment
├── conversation_memory.py    # Database tables for memory, entities, mood
├── insights_engine.py        # Proactive insights and reminders
└── bot.py (original)         # Fallback for command handlers
```

## Database Schema Additions

### New Tables

| Table | Purpose |
|-------|---------|
| `conversation_messages` | Stores chat history per user |
| `conversation_entities` | Remembers people, projects, places |
| `conversation_mood` | Tracks sentiment over time |
| `user_preferences` | Stores user settings |
| `scheduled_insights` | Queues insights to send |
| `proactive_reminders` | Queues proactive reminders |

## Testing the Features

### Test Conversation Memory
```
1. "I'm working on project X"
2. "How's it going with project X?"  (Bot should remember)
```

### Test Temporal Awareness
```
Send: "Good morning" at different times
Bot should respond appropriately
```

### Test Entity Extraction
```
"I need to call Sarah about the Acme account"
"Did you call Sarah?"  (Bot should remember)
```

### Test Mood Tracking
```
"I'm so frustrated today"
Then run: /mood  (Should show negative sentiment)
```

### Test Response Styles
```
/style → Select "Brief"
"Finished task" → Should get brief response
```

## Troubleshooting

### Bot not responding
- Check logs: `tail -f logs/bot.log`
- Verify Ollama is running: `ollama list`
- Check token is valid

### Conversation memory not working
- Verify tables were created
- Check database permissions

### Insights not sending
- Check `ENABLE_INSIGHTS_SCHEDULER=true` in .env
- Verify bot token has permission to send messages
- Check `scheduled_insights` table for pending items

### Model errors
- Verify Ollama models: `ollama list`
- Pull larger model if using SMART_MODEL: `ollama pull llama3.1:70b`

## Reverting to Original

If needed, revert to the original bot:

```bash
cp bot.backup.py bot.py
python bot.py
```

## Future Enhancements

Potential additions:
- Multi-user support with isolated contexts
- Voice message transcription and analysis
- Image recognition for food logging
- Calendar integration for task scheduling
- Export conversation history
- Custom entity types and attributes

---

**Your Life OS is now smarter!** 🧠✨
