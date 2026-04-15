# LLM System Prompts for Life OS

This document contains the system prompts used to extract structured data from natural language input.

## Main Parsing Prompt

The core system prompt is defined in `scripts/llm_parser.py` in the `_get_system_prompt()` method.

### Categories

The LLM categorizes user input into these types:

1. **task_complete** - User finished a task
2. **task_pending** - User needs to do something
3. **food_log** - User ate/drank something
4. **health_metric** - User logged supplements or health data
5. **energy_level** - User described their energy state

### Schema Examples

#### Task Complete
```json
{
  "type": "task_complete",
  "description": "clear task description",
  "timestamp": "ISO datetime or null"
}
```

#### Task Pending
```json
{
  "type": "task_pending",
  "description": "clear task description",
  "deadline": "ISO datetime or null",
  "priority": "low/medium/high",
  "focus_required": true/false
}
```

#### Food Log
```json
{
  "type": "food_log",
  "timestamp": "ISO datetime",
  "items": ["item1", "item2"],
  "macros": {
    "carbs": "low/medium/high",
    "protein": "low/medium/high",
    "fat": "low/medium/high"
  },
  "energy_prediction": {
    "status": "stable/crash_warning/boost_expected",
    "time_of_crash": "ISO datetime or null",
    "message": "explanation"
  }
}
```

#### Energy Level
```json
{
  "type": "energy_level",
  "level": 1-10,
  "context": "why this energy level",
  "timestamp": "ISO datetime"
}
```

## Energy Prediction Rules

The LLM uses these heuristics for energy predictions:

- **High carbs** (rice, bread, pasta) → crash_warning in 30-60 mins
- **High sugar** (sweets, soda) → crash_warning in 20-45 mins  
- **Balanced protein+fat+carbs** → stable
- **High protein+fat** → boost_expected
- **Coffee/tea** → boost_expected for 2-3 hours

## Time Parsing

Natural language time expressions are parsed as follows:

- "at 3 PM" → 15:00 today
- "yesterday" → yesterday's date
- "lunch" → 12:00-14:00
- "breakfast" → 07:00-09:00
- "dinner" → 18:00-21:00
- No time specified → current time
- "tomorrow" → tomorrow at same time
- "Friday" → next Friday at 17:00

## Priority Detection

Task priority is inferred from keywords:

**High Priority:**
- "urgent", "ASAP", "critical", "important", "emergency"
- Deadline within 48 hours

**Low Priority:**
- "when you get a chance", "eventually", "sometime", "maybe"
- No deadline specified

**Medium Priority:**
- Default for everything else

## Focus Required Detection

Tasks that require deep focus are identified by these keywords:

**Requires Focus:**
- "draft", "write", "design", "analyze", "research", "study", "plan", "review", "code", "develop"

**Does Not Require Focus:**
- "call", "email", "buy", "schedule", "pay", "send", "remind"

## Customizing Prompts

To modify the LLM behavior:

1. Edit `scripts/llm_parser.py`
2. Find the `_get_system_prompt()` method
3. Adjust the rules or add new categories
4. Restart the bot

### Example: Adding a New Category

```python
# In the system prompt, add a new schema:

mood_log:
{
  "type": "mood_log",
  "timestamp": "ISO datetime",
  "mood": "happy/neutral/sad/stressed/anxious",
  "trigger": "what caused this mood",
  "intensity": 1-10
}
```

Then update `bot.py` to handle the new category in `process_parsed_data()`.

## Daily Summary Prompt

The prompt for generating daily summaries:

```
Generate a brief, encouraging daily summary based on this data:

Tasks Completed: {count}
Tasks Pending: {count}
Meals Logged: {count}
Average Energy: {avg}/10

Write a 2-3 sentence summary that:
1. Celebrates accomplishments
2. Notes energy patterns
3. Gives a supportive tip for tomorrow

Keep it personal, warm, and actionable. No bullet points.
```

## Contextual Reminder Prompts

When suggesting optimal times for tasks, the system uses:

```
Based on your energy patterns:
- You're usually at {energy_level}/10 around {hour}:00
- This is a {good/great/perfect} time for: {task_description}
```

## Tips for Better Parsing

1. **Be specific with times**: "at 3 PM" is better than "afternoon"
2. **Use action verbs**: "Draft the report" vs "The report"
3. **Include deadlines**: "by Friday" helps prioritization
4. **Describe food clearly**: "chicken salad" vs just "salad"
5. **Mention quantities**: "2 cups of coffee" vs "coffee"

## Troubleshooting

If the LLM is not parsing correctly:

1. Check Ollama is running: `ollama list`
2. Try a different model: Set `LLM_MODEL` in `.env`
3. Increase timeout in `llm_parser.py` if responses are slow
4. Check logs: `tail -f logs/bot.log`
5. Test the LLM directly: `ollama run llama3.1:8b`

## Advanced: JSON Mode

The parser uses Ollama's JSON mode (`"format": "json"`). This forces the LLM to return only valid JSON.

If you need to disable this (for debugging):
```python
# In llm_parser.py, remove:
"format": "json"
```

Then the LLM will return regular text, which the `_extract_json()` method will parse.
