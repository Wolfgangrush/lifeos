#!/usr/bin/env python3
"""
Telegram Bot Handler for Life OS
Handles incoming messages and routes them appropriately.
"""

import os
import asyncio
import fcntl
from difflib import SequenceMatcher
import logging
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from gemini_web_agent import GeminiWebBrowsingAgent
from llm_parser import LLMParser
from database import (
    Database, Task, TaskStatus,
    ConversationMessage, ConversationEntity, ConversationMood,
    UserPreference, ScheduledInsight, ProactiveReminder
)
from daily_export import export_completed_task, rebuild_completed_tasks_export
from nutrition_estimator import NUMBER_WORDS, estimate_food, estimate_food_smart, merge_macros
from sqlalchemy import desc, func
import json
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

DEFAULT_SUPPLEMENTS = [
    ("Vitamin D3", "cholecalciferol", "May support mood and energy when vitamin D is low."),
    ("Vitamin B12", "cobalamin", "Supports red blood cell and nervous system function."),
    ("Magnesium", "magnesium", "May support sleep quality and muscle relaxation."),
    ("Omega 3", "EPA DHA fish oil", "May support inflammation balance and focus."),
]

load_dotenv()
Path('logs').mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_INSTANCE_LOCK_FILE = None


def acquire_instance_lock():
    """Prevent two polling bot processes from using the same Telegram token."""
    global _INSTANCE_LOCK_FILE

    lock_path = Path("logs/lifeos_bot.lock")
    _INSTANCE_LOCK_FILE = lock_path.open("a+")
    try:
        fcntl.flock(_INSTANCE_LOCK_FILE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("Another Life OS bot instance is already running. Exiting.")
        sys.exit(1)

    _INSTANCE_LOCK_FILE.seek(0)
    _INSTANCE_LOCK_FILE.truncate()
    _INSTANCE_LOCK_FILE.write(str(os.getpid()))
    _INSTANCE_LOCK_FILE.flush()


class LifeOSBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment")

        self.db = Database()
        self.llm_parser = LLMParser()
        self.web_agent = GeminiWebBrowsingAgent()
        self.app = None
        self._ensure_default_supplements()
        self._init_enhanced_tables()  # NEW: Initialize smart features tables
        self.__init_analysis_coach()  # NEW: Initialize Analysis Coach
        self._check_ollama_connectivity()  # Check Ollama is available

    def _ensure_default_supplements(self):
        if self.db.get_supplements(active_only=False):
            return
        for name, ingredients, notes in DEFAULT_SUPPLEMENTS:
            self.db.create_supplement(name=name, ingredients=ingredients, notes=notes)

    # ===== NEW: Smart Features Methods =====

    def _init_enhanced_tables(self):
        """Initialize enhanced database tables if needed"""
        from sqlalchemy import inspect
        inspector = inspect(self.db.engine)
        existing_tables = inspector.get_table_names()

        tables_to_create = [
            ('conversation_messages', ConversationMessage),
            ('conversation_entities', ConversationEntity),
            ('conversation_mood', ConversationMood),
            ('user_preferences', UserPreference),
            ('scheduled_insights', ScheduledInsight),
            ('proactive_reminders', ProactiveReminder),
        ]

        for table_name, table_class in tables_to_create:
            if table_name not in existing_tables:
                table_class.__table__.create(self.db.engine, checkfirst=True)
                logger.info(f"Created table: {table_name}")

    def get_temporal_context(self) -> dict:
        """Get time-based context for smarter responses"""
        now = datetime.now()
        hour = now.hour

        return {
            'hour': hour,
            'hour_12': now.strftime('%-I:%M %p'),
            'day_of_week': now.strftime('%A'),
            'date': now.strftime('%B %d, %Y'),
            'is_weekend': now.weekday() >= 5,
            'is_morning': 6 <= hour < 12,
            'is_afternoon': 12 <= hour < 17,
            'is_evening': 17 <= hour < 21,
            'is_night': hour >= 21 or hour < 6,
            'part_of_day': self._get_part_of_day(hour),
        }

    def _get_part_of_day(self, hour: int) -> str:
        """Get friendly part of day description"""
        if 5 <= hour < 8:
            return "early morning"
        elif 8 <= hour < 12:
            return "morning"
        elif 12 <= hour < 14:
            return "midday"
        elif 14 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 20:
            return "evening"
        elif 20 <= hour < 23:
            return "night"
        else:
            return "late night"

    def add_conversation_message(self, user_id: int, role: str, content: str, metadata: dict = None):
        """Add message to conversation history"""
        session = self.db.get_session()
        try:
            # Clean old messages (7 days)
            cutoff = datetime.now() - timedelta(days=7)
            session.query(ConversationMessage).filter(
                ConversationMessage.user_id == user_id,
                ConversationMessage.timestamp < cutoff
            ).delete()

            # Add new message
            msg = ConversationMessage(
                user_id=user_id,
                role=role,
                content=content,
                meta_data=metadata or {}
            )
            session.add(msg)

            # Prune to 20 messages
            recent = session.query(ConversationMessage).filter(
                ConversationMessage.user_id == user_id
            ).order_by(desc(ConversationMessage.timestamp)).offset(20).all()
            for msg in recent:
                session.delete(msg)

            session.commit()
        finally:
            session.close()

    def get_conversation_history(self, user_id: int, limit: int = 10) -> list:
        """Get recent conversation history"""
        session = self.db.get_session()
        try:
            messages = session.query(ConversationMessage).filter(
                ConversationMessage.user_id == user_id
            ).order_by(desc(ConversationMessage.timestamp)).limit(limit).all()

            return [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp.isoformat() if msg.timestamp else None,
                    'metadata': msg.meta_data or {}
                }
                for msg in reversed(messages)
            ]
        finally:
            session.close()

    def get_conversation_context(self, user_id: int) -> str:
        """Get formatted conversation history for LLM"""
        history = self.get_conversation_history(user_id, limit=6)
        if not history:
            return ""

        lines = ["RECENT CONVERSATION:"]
        for msg in history:
            role_name = "User" if msg['role'] == 'user' else "Assistant"
            timestamp = msg.get('timestamp', '')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    timestamp = f" [{dt.strftime('%H:%M')}]"
                except:
                    timestamp = ""
            lines.append(f"{role_name}{timestamp}: {msg['content']}")

        return "\n".join(lines)

    def store_entity(self, user_id: int, entity_type: str, name: str, attributes: dict = None, source_message: str = None):
        """Store an entity for future reference"""
        session = self.db.get_session()
        try:
            existing = session.query(ConversationEntity).filter(
                ConversationEntity.user_id == user_id,
                func.lower(ConversationEntity.name) == name.lower(),
                ConversationEntity.entity_type == entity_type
            ).first()

            if existing:
                if attributes:
                    existing.attributes = {**(existing.attributes or {}), **attributes}
                existing.last_seen = datetime.now()
                existing.mention_count = (existing.mention_count or 0) + 1
            else:
                entity = ConversationEntity(
                    user_id=user_id,
                    entity_type=entity_type,
                    name=name,
                    attributes=attributes or {},
                    source_message=source_message
                )
                session.add(entity)

            session.commit()
        finally:
            session.close()

    def get_entities(self, user_id: int, entity_type: str = None) -> list:
        """Get stored entities"""
        session = self.db.get_session()
        try:
            query = session.query(ConversationEntity).filter(
                ConversationEntity.user_id == user_id
            )
            if entity_type:
                query = query.filter(ConversationEntity.entity_type == entity_type)

            entities = query.order_by(desc(ConversationEntity.last_seen)).limit(50).all()

            return [
                {
                    'id': e.id,
                    'type': e.entity_type,
                    'name': e.name,
                    'attributes': e.attributes or {},
                    'mention_count': e.mention_count or 0
                }
                for e in entities
            ]
        finally:
            session.close()

    def get_entities_context(self, user_id: int) -> str:
        """Get formatted entities for LLM"""
        entities = self.get_entities(user_id)
        if not entities:
            return ""

        by_type = {}
        for e in entities:
            t = e['type']
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e['name'])

        lines = ["KNOWN ENTITIES:"]
        for entity_type, names in by_type.items():
            lines.append(f"{entity_type.title()}: {', '.join(names[:10])}")

        return "\n".join(lines)

    def log_mood(self, user_id: int, sentiment: float, emotion: str = None, context: str = None, message: str = None):
        """Log user mood/sentiment"""
        session = self.db.get_session()
        try:
            mood = ConversationMood(
                user_id=user_id,
                sentiment=sentiment,
                emotion=emotion,
                context=context,
                message=message
            )
            session.add(mood)
            session.commit()
        finally:
            session.close()

    def get_mood_summary(self, user_id: int, hours: int = 24) -> dict:
        """Get mood summary"""
        session = self.db.get_session()
        try:
            since = datetime.now() - timedelta(hours=hours)
            moods = session.query(ConversationMood).filter(
                ConversationMood.user_id == user_id,
                ConversationMood.timestamp >= since
            ).all()

            if not moods:
                return {'avg': 0, 'count': 0, 'trend': 'neutral'}

            avg_sentiment = sum(m.sentiment for m in moods) / len(moods)

            if len(moods) >= 3:
                recent_avg = sum(m.sentiment for m in moods[-3:]) / min(3, len(moods))
                older_avg = sum(m.sentiment for m in moods[:-3]) / max(1, len(moods) - 3)
                if recent_avg > older_avg + 0.2:
                    trend = 'improving'
                elif recent_avg < older_avg - 0.2:
                    trend = 'declining'
                else:
                    trend = 'stable'
            else:
                trend = 'neutral'

            return {
                'avg': round(avg_sentiment, 2),
                'count': len(moods),
                'trend': trend,
                'emotions': [m.emotion for m in moods if m.emotion]
            }
        finally:
            session.close()

    def set_preference(self, user_id: int, key: str, value):
        """Set a user preference"""
        session = self.db.get_session()
        try:
            pref = session.query(UserPreference).filter(
                UserPreference.user_id == user_id,
                UserPreference.key == key
            ).first()

            if pref:
                pref.value = value
            else:
                pref = UserPreference(user_id=user_id, key=key, value=value)
                session.add(pref)

            session.commit()
        finally:
            session.close()

    def get_preference(self, user_id: int, key: str, default=None):
        """Get a user preference"""
        session = self.db.get_session()
        try:
            pref = session.query(UserPreference).filter(
                UserPreference.user_id == user_id,
                UserPreference.key == key
            ).first()
            return pref.value if pref else default
        finally:
            session.close()

    async def parse_message_with_context(self, message: str, user_id: int) -> dict:
        """Enhanced LLM parsing with conversation memory and temporal context"""
        # Initialize enhanced tables if needed
        self._init_enhanced_tables()

        # Get temporal context
        temporal = self.get_temporal_context()

        # Get conversation history
        conversation_context = self.get_conversation_context(user_id)

        # Get entities context
        entities_context = self.get_entities_context(user_id)

        # Get mood summary
        mood_summary = self.get_mood_summary(user_id, hours=24)

        # Get user preference for response style
        response_style = self.get_preference(user_id, 'response_style', 'friendly')

        style_instructions = {
            'brief': "Be BRIEF and CONCISE. Short responses, no small talk.",
            'friendly': "Be FRIENDLY and WARM. Use emojis, conversational tone.",
            'analytical': "Be ANALYTICAL. Focus on data, patterns, and insights."
        }.get(response_style, "Be FRIENDLY and WARM.")

        # Get recent tasks context
        recent_tasks = []
        try:
            tasks = self.db.get_tasks(limit=5)
            recent_tasks = [f"[ID:{t.id}] {t.description}" for t in tasks]
        except:
            pass

        context_prompt = f"""
CURRENT CONTEXT:
- Time: {temporal['hour_12']} on {temporal['day_of_week']}, {temporal['date']}
- Part of day: {temporal['part_of_day']}
- Is weekend: {temporal['is_weekend']}
- Recent tasks: {recent_tasks[:3]}
- Mood trend: {mood_summary.get('trend', 'neutral')} (avg: {mood_summary.get('avg', 0)})
{f'{conversation_context}' if conversation_context else ''}
{f'{entities_context}' if entities_context else ''}

RESPONSE STYLE: {response_style}
{style_instructions}
"""

        system_prompt = """You are an intelligent personal life assistant with memory.

CORE RULES:
1. Remember conversation context - reference what was said before
2. Understand time context - respond appropriately for time of day
3. Extract entities (people, projects, places) for future reference
4. Detect sentiment from emotional language
5. Ask smart questions with actual options when unclear
6. Be helpful but concise

INTENT TYPES:
- log_task: User mentions doing or needing to do something
- log_food: User mentions eating/drinking
- log_energy: User describes their energy level
- log_health: User mentions supplements/exercise/health
- question: User asks about their data
- chat: Casual conversation
- unclear: Needs clarification

SENTIMENT SCALE:
- -1.0 to -0.5: Very negative (angry, hopeless)
- -0.5 to -0.2: Negative (sad, frustrated, tired)
- -0.2 to 0.2: Neutral
- 0.2 to 0.5: Positive (happy, content)
- 0.5 to 1.0: Very positive (excited, accomplished)

Return ONLY valid JSON:
{
  "intent": "log_task|log_food|log_energy|log_health|question|chat|unclear",
  "understanding": "what you understood",
  "needs_clarification": true/false,
  "clarification_question": "specific question if unclear",
  "action": {"type": "store|retrieve|respond_only", "data": {}},
  "entities": {"people": [], "projects": [], "locations": []},
  "sentiment": -1.0 to 1.0,
  "emotion": "happy|sad|tired|stressed|excited|neutral",
  "response": "natural conversational response",
  "suggestions": ["optional proactive suggestions"]
}
"""

        prompt = f"""
{context_prompt}

USER MESSAGE: "{message}"

Analyze and respond with JSON only.
Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        try:
            ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
            model = os.getenv('LLM_MODEL', 'llama3.1:8b')

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.7, "num_ctx": 4096}
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    response_text = result.get('response', '')
                    parsed = self._extract_json(response_text)

                    if parsed:
                        # Store entities
                        entities = parsed.get('entities', {})
                        for entity_type, names in entities.items():
                            if entity_type == 'people':
                                for name in names:
                                    self.store_entity(user_id, 'person', name, message)
                            elif entity_type == 'projects':
                                for name in names:
                                    self.store_entity(user_id, 'project', name, message)
                            elif entity_type == 'locations':
                                for name in names:
                                    self.store_entity(user_id, 'location', name, message)

                        # Log mood
                        if 'sentiment' in parsed:
                            self.log_mood(user_id, parsed.get('sentiment', 0),
                                        parsed.get('emotion'), parsed.get('understanding'), message)

                        # Store conversation
                        self.add_conversation_message(user_id, 'user', message, {
                            'intent': parsed.get('intent'),
                            'sentiment': parsed.get('sentiment')
                        })
                        self.add_conversation_message(user_id, 'assistant', parsed.get('response', ''), {
                            'intent': parsed.get('intent')
                        })

                        return parsed

        except Exception as e:
            logger.error(f"Enhanced parsing error: {e}")

        return None

    def _extract_json(self, text: str):
        """Extract JSON from messy LLM output"""
        import json
        # Try direct parse
        try:
            return json.loads(text)
        except:
            pass

        # Try markdown code block
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass

        # Try any JSON object
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        # Try fixing trailing commas
        try:
            cleaned = re.sub(r',\s*([}\]])', r'\1', text)
            return json.loads(cleaned)
        except:
            pass

        return None

    def _extract_urls(self, text: str) -> list[str]:
        """Extract HTTP URLs from a message."""
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        return [url.rstrip(").,]") for url in urls]

    def _task_category_from_text(self, text: str) -> str:
        lowered = (text or "").lower()
        office_terms = (
            "court", "high court", "hcba", "apl", "wp/", "aba/", "revn/",
            "cra/", "draft", "drafting", "affidavit", "petition", "application",
            "case", "matter", "sir", "office", "client",
        )
        home_terms = ("home", "house", "laundry", "clean", "groceries", "kitchen", "family")
        if any(term in lowered for term in office_terms):
            return "office"
        if any(term in lowered for term in home_terms):
            return "home"
        return "misc"

    def _parse_hours(self, text: str) -> float | None:
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", text, re.IGNORECASE)
        return float(match.group(1)) if match else None

    def _parse_milestone_text(self, text: str) -> dict | None:
        raw = text.strip()
        if not raw:
            return None
        hours = self._parse_hours(raw)
        title = re.sub(r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours)\b", "", raw, flags=re.IGNORECASE)
        title = re.sub(r"^\s*(?:milestone|completed milestone|add milestone)\s*:?", "", title, flags=re.IGNORECASE).strip(" -|")
        if not title:
            return None
        return {"title": title, "hours": hours, "category": self._task_category_from_text(title)}

    def _parse_expense_from_message(self, text: str) -> dict | None:
        patterns = [
            r"\b(?:rs\.?|inr|₹)\s*(\d+(?:\.\d+)?)\s*(?:for|on)?\s*(.+)",
            r"\b(\d+(?:\.\d+)?)\s*(?:rs\.?|inr|₹)\s*(?:for|on)?\s*(.+)",
            r"\bspent\s+(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(?:for|on)?\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip(), re.IGNORECASE)
            if match:
                description = match.group(2).strip(" .") or "expense"
                lowered = description.lower()
                category = "food" if any(x in lowered for x in ("lunch", "dinner", "breakfast", "tea", "coffee", "snack", "food")) else "misc"
                return {"amount": float(match.group(1)), "description": description, "category": category}
        return None

    def _is_save_for_later(self, text: str) -> bool:
        return bool(re.search(r"\b(save|archive|keep)\b.*\b(later|future|reference|archive)\b|\bstuff for later\b", text, re.IGNORECASE))

    def _clean_saved_text(self, text: str) -> str:
        cleaned = re.sub(
            r"^\s*(?:save|archive|keep)(?:\s+this)?(?:\s+for)?(?:\s+later|\s+future reference|\s+reference)?\s*:?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return cleaned.strip() or text.strip()

    def _today_board_date(self) -> str:
        return datetime.now().date().isoformat()

    def _parse_board_date(self, text: str) -> str:
        date_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b", text)
        if not date_match:
            return self._today_board_date()
        try:
            day = int(date_match.group(1))
            month = datetime.strptime(date_match.group(2)[:3], "%b").month
            year = int(date_match.group(3))
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return self._today_board_date()

    def _parse_court_board_entries(self, text: str) -> tuple[str, list[dict]]:
        board_date = self._parse_board_date(text)
        entries = []
        current = None
        start_pattern = re.compile(
            r"Court\s+No\.\s*([^:]+)\s*:\s*(\d+)\s+([A-Z]+/[0-9]+/[0-9]+)\s*(\[[^\]]+\])?\s*(.*)",
            re.IGNORECASE,
        )
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or re.match(r"^Dt\s*:", line, re.IGNORECASE):
                continue
            match = start_pattern.search(line)
            if match:
                if current:
                    entries.append(current)
                current = {
                    "court_no": match.group(1).strip(),
                    "serial_no": int(match.group(2)),
                    "case_no": match.group(3).strip(),
                    "side": (match.group(4) or "").strip("[]") or None,
                    "title": match.group(5).strip(),
                    "remarks": None,
                }
            elif current:
                current["title"] = f"{current['title']} {line}".strip()
        if current:
            entries.append(current)
        for entry in entries:
            title = entry.get("title") or ""
            remark_match = re.search(r"(\([^()]*\)\s*)+$", title)
            if remark_match:
                entry["remarks"] = remark_match.group(0).strip()
        return board_date, entries

    def _format_board(self, entries) -> str:
        if not entries:
            return "No board saved for today. Use /board add and paste the board."
        board_date = entries[0].board_date
        lines = [f"*Today's Board - {board_date}*"]
        for entry in entries:
            serial = entry.serial_no if entry.serial_no is not None else entry.id
            title = (entry.title or "").strip()
            if len(title) > 220:
                title = title[:217] + "..."
            line = f"No. {serial} | Court {entry.court_no or '-'} | {entry.case_no or '-'}"
            if entry.is_over:
                line = f"~{line} | Over~"
                title = f"~{title}~"
            lines.append(f"{line}\n{title}")
        return "\n\n".join(lines)

    def _parse_board_over_message(self, text: str) -> int | None:
        match = re.search(r"\b(?:no\.?|number|sr\.?)\s*(\d+)\s+(?:is\s+)?(?:over|done|completed)\b", text, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(\d+)\s+(?:is\s+)?(?:over|done|completed)\b", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    async def _reply_long_text(self, update: Update, text: str, **kwargs):
        """Telegram has a 4096-character message limit."""
        max_len = 3800
        if len(text) <= max_len:
            await update.message.reply_text(text, **kwargs)
            return

        start = 0
        while start < len(text):
            chunk = text[start:start + max_len]
            split_at = chunk.rfind("\n")
            if split_at > 1200:
                chunk = chunk[:split_at]
            await update.message.reply_text(chunk, **kwargs)
            start += len(chunk)

    async def _handle_url_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message_text: str,
        urls: list[str],
    ) -> bool:
        """Analyze URL messages with Gemini without logging them as life events."""
        if not urls:
            return False

        url = urls[0]
        message_without_urls = message_text
        for found_url in urls:
            message_without_urls = message_without_urls.replace(found_url, "").strip()
        user_question = message_without_urls or None

        if not self.web_agent.configured:
            if re.match(r'^\s*https?://\S+\s*$', message_text) and ("amazon" in url.lower() or "amzn." in url.lower()):
                context.user_data["pending_url"] = url
                keyboard = [
                    [InlineKeyboardButton("💊 Add to my supplements", callback_data="url_add_supplement")],
                    [InlineKeyboardButton("🛒 Create purchase reminder", callback_data="url_add_reminder")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="url_cancel")],
                ]
                await update.message.reply_text(
                    "Amazon link detected. Gemini analysis is not enabled yet, but I can still save this link.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return True
            await update.message.reply_text(
                "I see the link, but Gemini web analysis is not enabled. Set GEMINI_API_KEY in .env, then restart the bot."
            )
            return True

        processing_msg = await update.message.reply_text("🔍 Checking that link with Gemini...")
        result = await self.web_agent.browse_url(url, user_question)

        if not result.get("success"):
            await processing_msg.edit_text(
                f"I tried to check that link but had trouble: {result.get('error', 'Unknown error')}"
            )
            return True

        try:
            await processing_msg.delete()
        except Exception:
            logger.debug("Could not delete URL processing message", exc_info=True)
        await self._reply_long_text(update, result["analysis"])

        if "amazon" in url.lower() or "amzn." in url.lower():
            context.user_data["pending_url"] = url
            keyboard = [
                [InlineKeyboardButton("💊 Add to my supplements", callback_data="url_add_supplement")],
                [InlineKeyboardButton("🛒 Create purchase reminder", callback_data="url_add_reminder")],
                [InlineKeyboardButton("❌ Cancel", callback_data="url_cancel")],
            ]
            await update.message.reply_text(
                "Want me to save this link?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        return True

    def _clean_operator_text(self, text: str) -> str:
        """Normalize the short operator syntax used from Telegram."""
        cleaned = text.strip()
        cleaned = cleaned.strip("()[]{}")
        cleaned = cleaned.replace("+", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(
            r"^(completed|complete|finished|finish|done)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" -:.,")

    def _parse_operator_task(self, text: str) -> dict | None:
        """Parse direct operator task messages without using the LLM."""
        raw = text.strip()
        if not raw:
            return None

        lower = raw.lower().strip()
        completion_markers = (
            lower.endswith("+")
            or lower.endswith("+)")
            or lower.startswith("completed ")
            or lower.startswith("(completed ")
            or lower.startswith("finished ")
            or lower.startswith("done ")
        )

        if not completion_markers:
            return None

        description = self._clean_operator_text(raw)
        if not description:
            return None

        return {
            "type": "task_complete",
            "description": description,
            "priority": "medium",
            "focus_required": True,
            "source": "operator",
        }

    def _clean_task_description(self, description: str | None) -> str:
        if not description:
            return ""
        cleaned = re.sub(r"\s+", " ", str(description)).strip()
        return cleaned.strip(" -:.")

    def _parse_numbered_items(self, block: str) -> list[str]:
        items = []
        for line in block.splitlines():
            match = re.match(r"^\s*(?:\d+[\).]|[-*])\s*(.+?)\s*$", line)
            if not match:
                continue
            item = self._clean_task_description(match.group(1))
            if item:
                items.append(item)
        return items

    def _completion_timestamp_from_text(self, text: str) -> str:
        lowered = text.lower()
        base = datetime.now()
        if "yesterday" in lowered:
            base -= timedelta(days=1)

        time_matches = list(re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE))
        if time_matches:
            match = time_matches[-1]
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            meridiem = match.group(3).lower()
            if meridiem == "pm" and hour != 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
            return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

        return base.replace(hour=18, minute=0, second=0, microsecond=0).isoformat()

    def _parse_batch_tasks(self, text: str) -> list[dict]:
        """Parse Telegram list sections before the LLM can flatten them."""
        normalized = text.replace("\r\n", "\n").strip()
        if not re.search(r"\b(tasks?\s+completed|completed\s+tasks?|tasks?\s+pending|pending\s+tasks?)\b", normalized, re.IGNORECASE):
            return []

        completed_match = re.search(
            r"(?:today'?s?\s+tasks?\s+completed|tasks?\s+completed|completed\s+tasks?)\s*[-:\n]+(.+?)(?=\n\s*(?:tasks?\s+pending|pending\s+tasks?)\s*[-:\n]+|$)",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        pending_match = re.search(
            r"(?:tasks?\s+pending|pending\s+tasks?)\s*[-:\n]+(.+)$",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )

        completed_items = self._parse_numbered_items(completed_match.group(1)) if completed_match else []
        pending_items = self._parse_numbered_items(pending_match.group(1)) if pending_match else []
        if not completed_items and not pending_items:
            return []

        completed_at = self._completion_timestamp_from_text(normalized)
        pending_block = pending_match.group(1) if pending_match else ""
        deadline = self._deadline_from_text(pending_block)
        entries = [
            {
                "type": "task_complete",
                "description": item,
                "priority": "medium",
                "focus_required": True,
                "timestamp": completed_at,
                "source": "telegram_batch",
            }
            for item in completed_items
        ]
        entries.extend(
            {
                "type": "task_pending",
                "description": item,
                "deadline": deadline,
                "priority": "high" if deadline else "medium",
                "focus_required": bool(re.search(r"\b(file|draft|verify|write|prepare|research|circulation|case|apl|affidavit|pursis)\b", item, re.IGNORECASE)),
                "source": "telegram_batch",
            }
            for item in pending_items
        )
        return entries

    def _parse_completion_time_correction(self, text: str) -> dict | None:
        lowered = text.lower()
        if "correction" not in lowered and "completed those tasks" not in lowered:
            return None
        if "completed those tasks" not in lowered:
            return None

        timestamp = self._completion_timestamp_from_text(text)
        return {
            "type": "completion_time_correction",
            "timestamp": timestamp,
        }

    def _apply_recent_completion_time_correction(self, timestamp: str) -> tuple[int, str | None]:
        corrected_at = datetime.fromisoformat(timestamp)
        session = self.db.get_session()
        try:
            since = datetime.now() - timedelta(hours=2)
            day_start = corrected_at.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = corrected_at.replace(hour=23, minute=59, second=59, microsecond=999999)
            tasks = (
                session.query(Task)
                .filter(
                    Task.status == TaskStatus.COMPLETED,
                    Task.created_at >= since,
                    Task.completed_at >= day_start,
                    Task.completed_at <= day_end,
                    Task.description != "",
                    ~Task.description.ilike("Completed tasks from%"),
                )
                .all()
            )
            for task in tasks:
                task.completed_at = corrected_at
            session.commit()

            export_path = None
            if tasks:
                day_tasks = (
                    session.query(Task)
                    .filter(
                        Task.status == TaskStatus.COMPLETED,
                        Task.completed_at >= day_start,
                        Task.completed_at <= day_end,
                        Task.description != "",
                    )
                    .order_by(Task.completed_at, Task.id)
                    .all()
                )
                export_path = str(rebuild_completed_tasks_export(day_tasks, corrected_at.date(), source="database"))
            return len(tasks), export_path
        finally:
            session.close()

    def _is_greeting_or_noise(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()
        return cleaned in {
            "hi",
            "hello",
            "hey",
            "start",
            "test",
            "testing",
            "ok",
            "okay",
        }

    def _is_question(self, text: str) -> bool:
        """Detect if the message is a question about existing data."""
        lowered = text.lower().strip()
        question_patterns = [
            r"\b(what|which|how many|show|list|tell me|give me|do i have|are there|remaining)\b",
            r"\?$",
        ]
        task_keywords = [
            r"\btasks?\b",
            r"\bto-?do\b",
            r"\bpending\b",
            r"\bcompleted\b",
            r"\bleft\b",
            r"\bdue\b",
            r"\boverdue\b",
            r"\bunfinished\b",
            r"\bremaining\b",
        ]
        food_keywords = [
            r"\bfood\b",
            r"\beat\b",
            r"\bdrank\b",
            r"\bmeals?\b",
        ]
        energy_keywords = [
            r"\benergy\b",
        ]

        # Check if it matches question pattern
        is_question_format = any(re.search(pattern, lowered) for pattern in question_patterns)

        # Check if it's about a specific data type
        is_about_tasks = any(re.search(keyword, lowered) for keyword in task_keywords)
        is_about_food = any(re.search(keyword, lowered) for keyword in food_keywords)
        is_about_energy = any(re.search(keyword, lowered) for keyword in energy_keywords)

        return is_question_format and (is_about_tasks or is_about_food or is_about_energy)

    async def _handle_question(self, text: str) -> str | None:
        """Handle questions about existing data."""
        lowered = text.lower()

        # Task questions - more comprehensive matching
        task_indicators = ["task", "pending", "left", "remaining", "unfinished", "due", "to do", "to-do", "todo"]
        if any(indicator in lowered for indicator in task_indicators):
            return self._answer_tasks_question(lowered)

        # Food questions
        food_indicators = ["food", "eat", "ate", "drink", "drank", "meal"]
        if any(indicator in lowered for indicator in food_indicators):
            if "today" in lowered or "did i" in lowered:
                return self._format_food_today()

        # Energy questions
        if "energy" in lowered:
            return self._answer_energy_question(lowered)

        return None

    def _answer_tasks_question(self, lowered: str) -> str:
        """Answer questions about tasks."""
        # Automatically roll over incomplete tasks from yesterday
        rollover_result = self.db.roll_over_incomplete_tasks()
        rolled_count = rollover_result.get("rolled_over", 0)

        pending = self.db.get_tasks(status=TaskStatus.PENDING, limit=50)

        # Get today's completed tasks
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
        session = self.db.get_session()
        try:
            completed_today = session.query(Task).filter(
                Task.status == TaskStatus.COMPLETED,
                Task.completed_at >= today_start,
                Task.completed_at <= today_end
            ).all()
        finally:
            session.close()

        # Check for specific filters in the question
        if any(word in lowered for word in ["pending", "left", "remaining", "to do", "unfinished"]):
            if not pending:
                return "✅ You have no pending tasks! Great job!"

            lines = []
            if rolled_count > 0:
                lines.append(f"📅 Auto-rolled over {rolled_count} incomplete task(s) from yesterday to today.\n")
            lines.append(f"📋 *You have {len(pending)} pending task(s):*\n")
            for task in pending[:15]:
                priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(task.priority, "⚪")
                focus_tag = " 🧠" if task.focus_required else ""
                deadline_str = ""
                if task.deadline:
                    deadline_str = f" (due {task.deadline.strftime('%b %d')})"
                lines.append(f"{priority_emoji} {task.description}{focus_tag}{deadline_str}")
            if len(pending) > 15:
                lines.append(f"\n... and {len(pending) - 15} more")
            return "\n".join(lines)

        if any(word in lowered for word in ["completed", "finished", "done"]):
            if not completed_today:
                return "You haven't completed any tasks today yet."
            lines = [f"✅ *Completed today ({len(completed_today)}):*\n"]
            for task in completed_today[:15]:
                time_str = task.completed_at.strftime("%-I:%M %p") if task.completed_at else ""
                lines.append(f"• {task.description} ({time_str})")
            if len(completed_today) > 15:
                lines.append(f"\n... and {len(completed_today) - 15} more")
            return "\n".join(lines)

        # General task overview
        lines = ["📊 *Task Overview:*\n"]
        lines.append(f"✅ Completed today: {len(completed_today)}")
        lines.append(f"📋 Pending: {len(pending)}")
        if pending:
            lines.append("\n*Top pending tasks:*")
            for task in pending[:5]:
                priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(task.priority, "⚪")
                lines.append(f"{priority_emoji} {task.description}")
        return "\n".join(lines)

    def _answer_energy_question(self, lowered: str) -> str:
        """Answer questions about energy."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        levels = self.db.get_energy_levels(start_date=today_start, limit=20)

        if not levels:
            return "No energy levels logged today. Log your energy with /energy or tell me how you're feeling!"

        actual_levels = [l for l in levels if not l.predicted]
        if not actual_levels:
            return "No actual energy levels logged today. Your current energy predictions are based on supplements and food."

        avg = sum(l.level for l in actual_levels) / len(actual_levels)
        latest = actual_levels[0]
        time_str = latest.timestamp.strftime("%-I:%M %p")

        lines = [f"⚡ *Energy Today:*\n"]
        lines.append(f"Average: {avg:.1f}/10")
        lines.append(f"Latest: {latest.level}/10 at {time_str}")
        if latest.context:
            lines.append(f"Note: {latest.context}")
        return "\n".join(lines)

    def _complete_or_create_task(self, description: str, source: str = "telegram", completed_at: str = None):
        description = self._clean_task_description(description)
        if not description:
            return None, False, None
        task = self.db.complete_task_by_description(description, completed_at=completed_at)
        created = False
        if not task:
            task = self._find_completed_task_for_day(description, completed_at)
            if task:
                return task, created, None
        if not task:
            task = self.db.create_task(
                description=description,
                status=TaskStatus.COMPLETED,
                priority="medium",
                category=self._task_category_from_text(description),
                focus_required=True,
                completed_at=completed_at,
            )
            created = True
        export_path = export_completed_task(task, source=source)
        return task, created, export_path

    def _find_completed_task_for_day(self, description: str, completed_at: str = None):
        timestamp = datetime.fromisoformat(completed_at) if completed_at else datetime.now()
        day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = timestamp.replace(hour=23, minute=59, second=59, microsecond=999999)
        session = self.db.get_session()
        try:
            return (
                session.query(Task)
                .filter(
                    Task.description == description,
                    Task.status == TaskStatus.COMPLETED,
                    Task.completed_at >= day_start,
                    Task.completed_at <= day_end,
                )
                .first()
            )
        finally:
            session.close()

    def _create_pending_task(self, description: str, deadline=None, priority="medium", focus_required=False):
        description = self._clean_task_description(description)
        if not description:
            return None, False

        normalized = description.lower()
        for task in self.db.get_tasks(status=TaskStatus.PENDING, limit=200):
            if self._clean_task_description(task.description).lower() == normalized:
                return task, False

        task = self.db.create_task(
            description=description,
            deadline=deadline,
            priority=priority,
            category=self._task_category_from_text(description),
            focus_required=focus_required,
        )
        return task, True

    def _parse_time_hint(self, text: str) -> str | None:
        match = re.search(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    def _parse_energy_from_message(self, text: str) -> dict | None:
        match = re.search(r"\b(?:energy(?:\s+level)?[^0-9]{0,30})?([1-9]|10)\s*/\s*10\b", text, re.IGNORECASE)
        if not match:
            return None
        return {
            "type": "energy_level",
            "level": int(match.group(1)),
            "context": text.strip(),
            "timestamp": datetime.now().isoformat(),
            "source": "multi_intent",
        }

    def _deadline_from_text(self, text: str) -> str | None:
        lowered = text.lower()
        now = datetime.now()
        if "tomorrow" in lowered:
            return (now + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0).isoformat()
        if "today" in lowered:
            return now.replace(hour=17, minute=0, second=0, microsecond=0).isoformat()
        return None

    def _parse_food_items(self, phrase: str) -> list[dict]:
        parts = [p.strip() for p in re.split(r"\s+(?:and|with)\s+|,", phrase) if p.strip()]
        parsed = []

        for part in parts:
            tokens = part.lower().split()
            quantity = 1
            if len(tokens) >= 2 and tokens[-2:] == ["half", "plate"]:
                quantity = 0.5
                tokens = tokens[:-2]
            elif len(tokens) >= 2 and tokens[-2:] == ["half", "bowl"]:
                quantity = 0.5
                tokens = tokens[:-2]
            if tokens and tokens[0] in NUMBER_WORDS:
                quantity = NUMBER_WORDS[tokens[0]]
                tokens = tokens[1:]
            elif tokens and tokens[0].isdigit():
                quantity = int(tokens[0])
                tokens = tokens[1:]

            if tokens and tokens[-1] in {"plate", "bowl", "serving"}:
                tokens = tokens[:-1]
            if tokens and tokens[0] in {"one", "single", "medium", "small", "large"}:
                tokens = tokens[1:]

            item = " ".join(tokens).strip(" -:.").lower()
            if item:
                parsed.append({"item": item, "quantity": quantity})

        return parsed

    def _parse_explicit_calorie_food(self, text: str, meal_type: str = None) -> dict | None:
        matches = list(re.finditer(
            r"(?P<item>[^,;\n]+?)\s*[-:]\s*(?P<calories>\d+(?:\.\d+)?)\s*k?cal\b",
            text,
            re.IGNORECASE,
        ))
        if not matches:
            return None

        items = []
        estimates = []
        for match in matches:
            item = re.sub(r"\b(?:from|at)\s+.+$", "", match.group("item"), flags=re.IGNORECASE)
            item = re.sub(r"\b(?:breakfast|lunch|dinner|snack)\s*:\s*", "", item, flags=re.IGNORECASE)
            item = item.strip(" -:,.").lower()
            calories = float(match.group("calories"))
            if not item:
                continue
            items.append(item)
            estimates.append({
                "item": item,
                "quantity": 1,
                "serving": "as logged",
                "calories": round(calories, 1),
                "carbs_g": None,
                "protein_g": None,
                "fat_g": None,
                "health_note": "Calories supplied by user.",
                "macros": {"carbs": "high", "protein": "low", "fat": "high"},
                "source": "user calories",
            })

        if not items:
            return None

        macros = merge_macros(estimates)
        calories = macros.get("calories")
        crash_time = (datetime.now() + timedelta(minutes=45)).isoformat()
        return {
            "type": "food_log",
            "timestamp": datetime.now().isoformat(),
            "items": items,
            "parsed_items": [{"item": item, "quantity": 1} for item in items],
            "macros": macros,
            "energy_prediction": {
                "status": "crash_warning",
                "time_of_crash": crash_time,
                "message": "Calorie-dense fast food. Watch for drowsiness or an energy dip.",
                "calories": calories,
                "user_calories_locked": True,
                "health_note": f"Logged as {meal_type}." if meal_type else "Calories supplied by user.",
                "nutrition": estimates,
            },
            "source": "explicit_calorie_food_parser",
        }

    def _parse_food_from_message(self, text: str) -> dict | None:
        lowered = text.lower()
        explicit = self._parse_explicit_calorie_food(text)
        if explicit:
            return explicit

        if not re.search(r"\b(ate|eat|had|having|drank|drink)\b", lowered):
            return None

        only_match = re.search(
            r"\bonly\s+(?:ate|had)\s+(.+?)(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|[.;,]|$)",
            text,
            re.IGNORECASE,
        )
        if only_match:
            phrase = only_match.group(1).strip()
        else:
            food_matches = list(re.finditer(
                r"\b(?:ate|eat|had|having)\s+(.+?)(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|[.;,]|$)",
                text,
                re.IGNORECASE,
            ))
            if not food_matches:
                return None
            phrase = food_matches[-1].group(1).strip()

        phrase = re.sub(r"\b(?:nothing|anything)\b", "", phrase, flags=re.IGNORECASE).strip()
        phrase = re.sub(r"\bnor\b.*$", "", phrase, flags=re.IGNORECASE).strip()
        phrase = re.split(
            r"\s+(?:and\s+)?(?:also\s+)?(?:did|walked|need to|have to|must|remind me to)\b",
            phrase,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        if not phrase:
            return None

        parsed_items = self._parse_food_items(phrase)
        items = [entry["item"] for entry in parsed_items]
        estimates = [estimate_food(entry["item"], quantity=entry["quantity"]) for entry in parsed_items]

        if not items:
            return None

        macros = merge_macros(estimates)
        calories = macros.get("calories")
        high_fat = macros.get("fat") == "high"
        high_carbs = macros.get("carbs") == "high"
        status = "crash_warning" if high_carbs or high_fat else "stable"
        crash_time = (datetime.now() + timedelta(minutes=45)).isoformat() if status == "crash_warning" else None
        message = "Calorie-dense or carb-heavy food. Watch for an energy dip." if status == "crash_warning" else "Balanced enough for steady energy."

        return {
            "type": "food_log",
            "timestamp": self._parse_time_hint(text) or datetime.now().isoformat(),
            "items": items,
            "parsed_items": parsed_items,
            "macros": macros,
            "energy_prediction": {
                "status": status,
                "time_of_crash": crash_time,
                "message": message,
                "calories": calories,
                "health_note": " ".join(e.get("health_note", "") for e in estimates if e.get("health_note")),
                "nutrition": estimates,
            },
            "source": "multi_intent",
        }

    def _parse_steps_from_message(self, text: str) -> dict | None:
        match = re.search(r"\b([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,6})\s*steps?\b", text, re.IGNORECASE)
        if not match:
            return None
        steps = int(match.group(1).replace(",", ""))
        return {
            "type": "health_metric",
            "timestamp": datetime.now().isoformat(),
            "supplements": [],
            "metrics": {"steps": steps},
            "source": "multi_intent",
        }

    def _parse_task_pending_from_message(self, text: str) -> dict | None:
        match = re.search(
            r"\b(?:need to|have to|must|remind me to)\s+(.+?)(?:[.;]|$)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        description = match.group(1).strip()
        description = re.sub(r"\s*-\s*$", "", description).strip(" )(").strip()
        if not description:
            return None
        return {
            "type": "task_pending",
            "description": description,
            "deadline": self._deadline_from_text(description),
            "priority": "high" if "tomorrow" in description.lower() else "medium",
            "focus_required": bool(re.search(r"\b(file|draft|write|prepare|research|circulation|case)\b", description, re.IGNORECASE)),
            "source": "multi_intent",
        }

    def _parse_supplement_from_message(self, text: str) -> dict | None:
        lowered = text.lower()
        if re.search(r"\b(didn'?t|didn’t|did not|no|not)\b.{0,30}\b(take|took)\b.{0,20}\bsupplements?\b", lowered):
            return {"type": "supplement_negative"}
        if not re.search(r"\b(took|take|had|log(?:ged)?|consumed)\b", lowered):
            return None
        if not re.search(r"\b(supplements?|tablet|tablets|capsule|capsules|magnesium|ashwa?gandha|adhwa?gandha)\b", lowered):
            return None

        supplements = []
        dose_map = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if re.search(r"\b(took|take|had|log(?:ged)?|consumed)\b", line, re.IGNORECASE) and re.search(r"\bsupplements?\b", line, re.IGNORECASE):
                continue
            match = re.match(
                r"(?:(\d+(?:\.\d+)?|one|two|three|half)\s*)?"
                r"(tablet|tablets|tab|tabs|capsule|capsules|softgel|softgels|serving|servings)?\s+"
                r"(.+)$",
                line,
                re.IGNORECASE,
            )
            if not match:
                continue
            quantity = match.group(1) or "1"
            unit = match.group(2) or "serving"
            name = re.sub(r"\b(?:supplements?|today|before sleeping|after sleeping)\b", "", match.group(3), flags=re.IGNORECASE)
            name = re.sub(r"[^A-Za-z0-9 +&-]", " ", name).strip(" -")
            if len(name) < 3:
                continue
            canonical = self._canonical_supplement_name(name)
            if canonical not in supplements:
                supplements.append(canonical)
                dose_map[canonical] = {"quantity": quantity, "unit": unit}

        if not supplements:
            return None

        return {
            "type": "health_metric",
            "timestamp": self._timestamp_from_time_hint(text),
            "supplements": supplements,
            "metrics": {
                "supplement_doses": dose_map,
                "context": "Before sleeping" if "sleep" in lowered else "",
            },
            "source": "supplement_text_parser",
        }

    def _canonical_supplement_name(self, raw_name: str) -> str:
        cleaned = re.sub(r"\s+", " ", raw_name).strip()
        aliases = {
            "adhwagandha": "Ashwagandha",
            "ashwagandha": "Ashwagandha",
            "aswagandha": "Ashwagandha",
            "magnesiun": "Magnesium",
            "magnesium": "Magnesium",
        }
        lowered = cleaned.lower()
        for alias, canonical in aliases.items():
            if alias in lowered:
                return canonical

        best_name = cleaned.title()
        best_score = 0.0
        for supplement in self.db.get_supplements():
            name = supplement.name.strip()
            score = SequenceMatcher(None, lowered, name.lower()).ratio()
            if score > best_score:
                best_name = name
                best_score = score
        return best_name if best_score >= 0.78 else cleaned.title()

    def _timestamp_from_time_hint(self, text: str) -> str:
        lowered = text.lower()
        base = datetime.now()
        if "yesterday" in lowered:
            base -= timedelta(days=1)

        matches = list(re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE))
        if not matches:
            return base.isoformat()

        match = matches[-1]
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


    def _is_court_board_message(self, text: str) -> bool:
        """Detect if text looks like a High Court Board paste"""
        court_patterns = [
            r'Court No\.',
            r'AA\s*:\s*\d+',
            r'A\s*:\s*\d+',
            r'F\s*:\s*\d+',
            r'R\s*:\s*\d+',
            r'\[Civil\]',
            r'\[Criminal\]',
            r'WP/\d+/\d+',
            r'APL/\d+/\d+',
        ]
        matches = sum(1 for p in court_patterns if re.search(p, text, re.IGNORECASE))
        return matches >= 3

    def _parse_multi_intent_message(self, text: str) -> list[dict]:
        entries = []
        
        # Auto-detect and handle court board messages first
        if self._is_court_board_message(text):
            try:
                board_date, board_entries = self._parse_court_board_entries(text)
                if board_entries:
                    saved = self.db.replace_court_board(board_date, board_entries)
                    return [{
                        "type": "court_board",
                        "board_date": board_date,
                        "entries_count": len(board_entries),
                        "saved": saved,
                        "response": f"✅ Saved {len(board_entries)} court board entries for {board_date}"
                    }]
            except Exception as e:
                logger.warning(f"Court board auto-detection failed: {e}")
        
        # First check for complex multi-food patterns (parentheses, multiple time hints)
        if ("(" in text and ")" in text) or ("+" in text and ("am" in text.lower() or "pm" in text.lower())):
            complex_foods = self._parse_complex_multi_food(text)
            if complex_foods:
                entries.extend(complex_foods)
                # If we got multiple food entries, still check for other intents
                energy = self._parse_energy_from_message(text)
                steps = self._parse_steps_from_message(text)
                task = self._parse_task_pending_from_message(text)
                saved_supplement = self._parse_saved_supplement_intake(text)
                supplement = None if saved_supplement else self._parse_supplement_from_message(text)
                if energy:
                    entries.append(energy)
                if steps:
                    entries.append(steps)
                if task:
                    entries.append(task)
                if saved_supplement:
                    entries.append(saved_supplement)
                if supplement:
                    entries.append(supplement)
                return entries
        
        # Standard parsing for simple messages
        energy = self._parse_energy_from_message(text)
        food = self._parse_food_from_message(text)
        steps = self._parse_steps_from_message(text)
        task = self._parse_task_pending_from_message(text)
        saved_supplement = self._parse_saved_supplement_intake(text)
        supplement = None if saved_supplement else self._parse_supplement_from_message(text)
        if energy:
            entries.append(energy)
        if food:
            entries.append(food)
        if steps:
            entries.append(steps)
        if task:
            entries.append(task)
        if saved_supplement:
            entries.append(saved_supplement)
        if supplement:
            entries.append(supplement)
        return entries
    
    def _parse_complex_multi_food(self, text: str) -> list[dict]:
        """Parse complex multi-instruction food messages like:
        'i added (2x Paneer Paratha at 6PM + and Dal + Rice at 10AM)'
        Returns multiple food_log entries with proper timestamps.
        """
        import re
        from datetime import datetime
        
        def extract_time_from_part(part: str) -> str | None:
            now = datetime.now()
            # Match "at 6PM", "at 10:30 AM"
            match = re.search(r"\bat\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", part, re.IGNORECASE)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2) or 0)
                meridiem = match.group(3).lower()
                if meridiem == "pm" and hour != 12:
                    hour += 12
                if meridiem == "am" and hour == 12:
                    hour = 0
                return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
            # Match meal keywords
            meal_times = {"breakfast": "08:00", "lunch": "13:00", "dinner": "19:00", "morning": "08:00", "afternoon": "14:00", "evening": "19:00"}
            for meal, time_str in meal_times.items():
                if re.search(rf"\b{meal}\b", part, re.IGNORECASE):
                    hour, minute = map(int, time_str.split(":"))
                    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()
            return None
        
        def extract_quantity(item: str) -> tuple:
            quantity = 1
            cleaned = item
            qty_match = re.match(r"^(\d+)\s*[xX]?\s*(.+)$", cleaned)
            if qty_match:
                try:
                    quantity = float(qty_match.group(1))
                    cleaned = qty_match.group(2)
                except:
                    pass
            size_match = re.match(r"^(medium|small|large)\s+size\s*(.+)$", cleaned, re.IGNORECASE)
            if size_match:
                size = size_match.group(1).lower()
                if size == "small":
                    quantity *= 0.5
                elif size == "large":
                    quantity *= 1.5
                cleaned = size_match.group(2)
            return quantity, cleaned.strip(" ,+")
        
        # Clean input
        cleaned = text.strip()
        for prefix in [r"^i\s+added\s+", r"^i\s+ate\s+", r"^ate\s+", r"^had\s+", r"^consumed\s+"]:
            cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)
        
        entries_by_time = {}
        current_time = None
        
        # Extract parenthesized groups with their context
        for match in re.finditer(r"\(([^)]+)\)", cleaned):
            group = match.group(1)
            pos = match.start()
            
            # Find time in group or before it
            group_time = extract_time_from_part(group)
            if not group_time:
                before = cleaned[max(0, pos-30):pos]
                group_time = extract_time_from_part(before)
            if group_time:
                current_time = group_time
            
            # Split by +, ,, and
            parts = re.split(r"\s*\+\s*|\s*,\s*|\s+and\s+", group, flags=re.IGNORECASE)
            for part in parts:
                part = part.strip()
                if part and part.lower() not in ["and", "or"]:
                    # Remove time words from food name
                    part = re.sub(r"\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)", "", part, flags=re.IGNORECASE)
                    part = re.sub(r"\s+(?:breakfast|lunch|dinner|morning|afternoon|evening)\b", "", part, flags=re.IGNORECASE)
                    qty, food = extract_quantity(part)
                    if food:
                        key = current_time or "default"
                        entries_by_time.setdefault(key, []).append({"item": food, "quantity": qty})
        
        # Process outside parentheses
        outside = re.sub(r"\([^)]+\)", " ", cleaned)
        parts = re.split(r"\s*\+\s*|\s*,\s*|\s+and\s+", outside, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            if part and part.lower() not in ["and", "or"]:
                part_time = extract_time_from_part(part)
                if part_time:
                    current_time = part_time
                part = re.sub(r"\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)", "", part, flags=re.IGNORECASE)
                qty, food = extract_quantity(part)
                if food:
                    key = current_time or "default"
                    entries_by_time.setdefault(key, []).append({"item": food, "quantity": qty})
        
        # Build result
        result = []
        for ts, items in entries_by_time.items():
            iso_ts = ts if ts != "default" else datetime.now().isoformat()
            result.append({
                "type": "food_log",
                "items": [i["item"] for i in items],
                "timestamp": iso_ts,
                "parsed_items": items,
                "source": "complex_multi_food"
            })
        return result

    def _today_bounds(self):
        today = datetime.now().date()
        return (
            datetime.combine(today, datetime.min.time()),
            datetime.combine(today, datetime.max.time()),
        )

    async def _supplement_research_async(self, supplements: list) -> str:
        """Enhanced supplement research using Gemini API when available."""
        names = [supp.name for supp in supplements]
        ingredients_text = " ".join(filter(None, [supp.ingredients or supp.name for supp in supplements]))
        
        # Use Gemini for detailed research if available
        if self.web_agent.configured:
            try:
                query = f"What are the benefits of these supplements: {', '.join(names)}? Focus on: sleep, energy, focus, and timing recommendations."
                result = await self.web_agent.browse_url(
                    "https://www.google.com/search?q=" + urllib.parse.quote_plus(query),
                    query
                )
                
                if result.get("success"):
                    analysis = result.get("analysis", "")
                    
                    # Calculate predicted energy levels
                    stimulant_terms = re.compile(r"\b(caffeine|green tea|guarana|ginseng|rhodiola|tyrosine|b12|coq10)\b", re.IGNORECASE)
                    calming_terms = re.compile(r"\b(magnesium|ashwagandha|l-theanine|glycine|melatonin)\b", re.IGNORECASE)
                    
                    morning = 6
                    afternoon = 5
                    evening = 5
                    if stimulant_terms.search(ingredients_text):
                        morning += 1
                        afternoon += 1
                    if calming_terms.search(ingredients_text):
                        evening -= 1
                    if len(supplements) >= 5:
                        afternoon -= 1
                    
                    morning = max(1, min(10, morning))
                    afternoon = max(1, min(10, afternoon))
                    evening = max(1, min(10, evening))
                    
                    today = datetime.now()
                    for hour, level, label in [(10, morning, "morning"), (14, afternoon, "afternoon"), (19, evening, "evening")]:
                        self.db.log_energy(
                            level=level,
                            timestamp=today.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(),
                            predicted=True,
                            context=f"Predicted {label} energy from supplement stack",
                        )
                    
                    lines = [
                        f"✅ *Supplements logged: {', '.join(names)}*\n\n",
                        f"📊 *Predicted energy:* morning {morning}/10, afternoon {afternoon}/10, evening {evening}/10.\n\n",
                        f"🔬 *Research summary:*\n{analysis[:800]}\n\n",
                        "_This is general information, not medical advice._"
                    ]
                    return "\n".join(lines)
            except Exception as e:
                logger.error(f"Gemini supplement research failed: {e}")
        
        # Fallback to basic research
        return self._supplement_research(supplements)
    
    def _supplement_research(self, supplements: list) -> str:
        names = [supp.name for supp in supplements]
        query = urllib.parse.quote_plus(" ".join(names) + " supplement energy fatigue mechanism")
        snippets = []
        try:
            with urllib.request.urlopen(f"https://duckduckgo.com/html/?q={query}", timeout=8) as response:
                page = response.read(6000).decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", page)
            text = re.sub(r"\s+", " ", text)
            for term in ["energy", "fatigue", "caffeine", "magnesium", "vitamin", "adaptogen"]:
                match = re.search(rf".{{0,90}}\b{term}\b.{{0,120}}", text, re.IGNORECASE)
                if match:
                    snippets.append(match.group(0).strip())
            snippets = snippets[:3]
        except Exception as error:
            logger.info(f"Supplement web research unavailable: {error}")

        stimulant_terms = re.compile(r"\b(caffeine|green tea|guarana|ginseng|rhodiola|tyrosine|b12|coq10)\b", re.IGNORECASE)
        calming_terms = re.compile(r"\b(magnesium|ashwagandha|l-theanine|glycine|melatonin)\b", re.IGNORECASE)
        ingredients_text = " ".join(filter(None, [supp.ingredients or supp.name for supp in supplements]))

        morning = 6
        afternoon = 5
        evening = 5
        if stimulant_terms.search(ingredients_text):
            morning += 1
            afternoon += 1
        if calming_terms.search(ingredients_text):
            evening -= 1
        if len(supplements) >= 5:
            afternoon -= 1

        morning = max(1, min(10, morning))
        afternoon = max(1, min(10, afternoon))
        evening = max(1, min(10, evening))
        today = datetime.now()
        for hour, level, label in [(10, morning, "morning"), (14, afternoon, "afternoon"), (19, evening, "evening")]:
            self.db.log_energy(
                level=level,
                timestamp=today.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(),
                predicted=True,
                context=f"Predicted {label} energy from supplement stack",
            )

        lines = [
            "Supplement stack logged.",
            f"Predicted energy: morning {morning}/10, afternoon {afternoon}/10, evening {evening}/10.",
            "This is a planning signal, not medical advice.",
        ]
        if snippets:
            lines.append("Web check used current search snippets about supplement effects.")
        else:
            lines.append("Web check was unavailable, so I used the saved ingredients and local rules.")
        return "\n".join(lines)

    def _format_food_today(self) -> str:
        start, end = self._today_bounds()
        logs = list(reversed(self.db.get_food_logs(start_date=start, end_date=end, limit=100)))
        if not logs:
            return "No food logged today."
        lines = ["Today you ate:"]
        for log in logs:
            time = log.timestamp.strftime("%I:%M %p") if log.timestamp else "Unknown time"
            items = ", ".join(log.items or [])
            calories = (log.macros or {}).get("calories") or (log.energy_prediction or {}).get("calories")
            suffix = f" ({calories} kcal estimated)" if calories else ""
            lines.append(f"- {time}: {items}{suffix}")
        return "\n".join(lines)

    def _fetch_page_summary(self, url: str) -> tuple[str | None, str | None, dict | None]:
        """Enhanced page scraper for Amazon product URLs. Extracts title, description, and additional metadata."""
        is_amazon = "amazon" in url.lower() or "amzn.in" in url.lower() or "amzn.com" in url.lower()
        metadata = {}

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5,en-IN;q=0.3",
                "Accept-Encoding": "gzip, deflate",
            }
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=8) as response:
                html = response.read(200000).decode("utf-8", errors="ignore")
        except Exception as error:
            logger.info(f"Could not fetch URL {url}: {error}")
            return None, None, None

        # Check for CAPTCHA page
        if "captcha" in html.lower() or "enter the characters you see below" in html.lower():
            logger.info(f"CAPTCHA detected for {url}")
            return None, None, None

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None

        # Extract description
        description_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        description = re.sub(r"\s+", " ", description_match.group(1)).strip() if description_match else None

        # Enhanced Amazon extraction
        if is_amazon and title:
            # Clean Amazon title (remove site name)
            title = re.sub(r"\s*-\s*Amazon(?:\.\w+)?\s*$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*\|\s*Amazon(?:\.\w+)?\s*$", "", title, flags=re.IGNORECASE)

            # Extract brand
            brand_match = re.search(r'#brand["\']\s*:\s*["\']([^"\']+)["\']', html)
            if brand_match:
                metadata['brand'] = brand_match.group(1).strip()

            # Extract product features/bullet points
            features_match = re.search(r'<div[^>]*id=["\']feature-bullets["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
            if features_match:
                feature_text = features_match.group(1)
                feature_items = re.findall(r'<span[^>]*class=["\']a-list-item["\'][^>]*>(.*?)</span>', feature_text, re.IGNORECASE | re.DOTALL)
                features = []
                for item in feature_items[:10]:  # Limit to first 10 features
                    clean_item = re.sub(r"<[^>]+>", "", item).strip()
                    clean_item = re.sub(r"\s+", " ", clean_item).strip()
                    if clean_item and len(clean_item) > 10:
                        features.append(clean_item)
                if features:
                    metadata['features'] = features
                    # Use features as enhanced description
                    if not description or len(description) < 50:
                        description = " | ".join(features[:3])

            # Extract price
            price_match = re.search(r'<span[^>]*id=["\']priceblock_ourprice["\'][^>]*>\s*([\d.,]+)', html, re.IGNORECASE)
            if not price_match:
                price_match = re.search(r'<span[^>]*class=["\']a-price-whole["\'][^>]*>(\d+)</span>\s*<span[^>]*class=["\']a-price-fraction["\'][^>]*>(\d+)</span>', html, re.IGNORECASE)
            if price_match:
                metadata['price'] = price_match.group(0)

            # Extract supplement facts (serving size, ingredients)
            if any(term in title.lower() for term in ['supplement', 'vitamin', 'mineral', 'omega', 'capsule', 'tablet', 'softgel']):
                # Try to find supplement facts section
                facts_match = re.search(r'<div[^>]*class=["\']supplement-facts["\'][^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
                if facts_match:
                    facts_text = re.sub(r"<[^>]+>", " ", facts_match.group(1))
                    facts_text = re.sub(r"\s+", " ", facts_text).strip()
                    if facts_text:
                        metadata['supplement_facts'] = facts_text[:500]

                # Extract ingredients from product description
                ingredients_match = re.search(r'(?:ingredients|supplement facts)[^:]*:\s*([^\n\.]{20,300})', html[50000:150000], re.IGNORECASE)
                if ingredients_match:
                    ingredients_text = re.sub(r"<[^>]+>", " ", ingredients_match.group(1))
                    ingredients_text = re.sub(r"\s+", " ", ingredients_text).strip()
                    if ingredients_text and len(ingredients_text) > 15:
                        metadata['ingredients_extracted'] = ingredients_text

            # Extract customer rating
            rating_match = re.search(r'<span[^>]*class=["\']a-icon-alt["\'][^>]*>([\d.]+ out of 5)', html, re.IGNORECASE)
            if rating_match:
                metadata['rating'] = rating_match.group(1)

            # Extract review count
            reviews_match = re.search(r'(\d+(?:,\d+)*)\s*ratings?', html, re.IGNORECASE)
            if reviews_match:
                metadata['total_ratings'] = reviews_match.group(1)

        # Build comprehensive description
        if description:
            description = re.sub(r"\s+", " ", description).strip()
        elif is_amazon and metadata.get('features'):
            description = " | ".join(metadata['features'][:2])

        return title, description, metadata if metadata else None

    def _classify_amazon_product(self, title: str, description: str) -> dict:
        """Classify Amazon product as supplement, food, or non-edible."""
        title_lower = title.lower() if title else ""
        desc_lower = description.lower() if description else ""
        combined = title_lower + " " + desc_lower

        # Supplement keywords
        supplement_keywords = [
            "supplement", "vitamin", "mineral", "capsule", "tablet", "softgel",
            "omega-3", "fish oil", "probiotic", "collagen", "protein powder",
            "creatine", "bcaa", "preworkout", "whey protein", "multivitamin"
        ]

        # Food keywords
        food_keywords = [
            "food", "snack", "chocolate", "coffee", "tea", "honey", "nuts",
            "dried fruit", "protein bar", "granola", "oats", "pasta", "rice"
        ]

        # Check supplement
        if any(keyword in combined for keyword in supplement_keywords):
            return {"type": "supplement", "confidence": "high"}

        # Check food
        if any(keyword in combined for keyword in food_keywords):
            return {"type": "food", "confidence": "high"}

        # Check department/category indicators
        if "health & household" in combined or "sports nutrition" in combined:
            return {"type": "supplement", "confidence": "medium"}

        if "grocery & gourmet food" in combined:
            return {"type": "food", "confidence": "medium"}

        # Default to non-edible
        return {"type": "non_edible", "confidence": "medium"}

    def _analyze_time_based_effects(self, name: str, ingredients: str, time_logged: datetime = None) -> dict:
        """Analyze effects based on ingredients and time of day."""
        if time_logged is None:
            time_logged = datetime.now()

        hour = time_logged.hour
        effects = {
            "energy_effect": None,
            "sleep_effect": None,
            "focus_effect": None,
            "recommendation": [],
        }

        if not ingredients:
            return effects

        ingredients_lower = ingredients.lower()

        # Stimulants (energy boost)
        stimulants = ["caffeine", "green tea", "guarana", "ginseng", "rhodiola", "tyrosine", "b12", "coq10", "l-carnitine"]
        has_stimulants = any(s in ingredients_lower for s in stimulants)

        # Calming (sleep aid) - ASHWAGANDHA IS CALMING, NOT STIMULATING
        calming = ["magnesium", "ashwagandha", "withania somnifera", "l-theanine", "glycine", "melatonin", "chamomile", "valerian", "passionflower", "5-htp", "gaba"]
        has_calming = any(c in ingredients_lower for c in calming)

        # Focus enhancers
        focus = ["bacopa", "ginkgo", "phosphatidylserine", "acetyl-l-carnitine", "curcumin"]
        has_focus = any(f in ingredients_lower for f in focus)

        # Time-based analysis
        if 6 <= hour < 12:  # Morning (6AM - 12PM)
            if has_stimulants:
                effects["energy_effect"] = "high"
                effects["recommendation"].append("Great timing! Stimulants in the morning will boost your energy for the day.")
            elif has_calming:
                effects["sleep_effect"] = "possible_drowsiness"
                effects["recommendation"].append("⚠️ Calming ingredients in the morning might cause drowsiness. Consider taking in the evening.")
            else:
                effects["recommendation"].append("Good morning timing. This should support your daily baseline.")

        elif 12 <= hour < 17:  # Afternoon (12PM - 5PM)
            if has_stimulants:
                effects["energy_effect"] = "medium"
                effects["recommendation"].append("Afternoon stimulants can help with post-lunch energy dip.")
            if has_calming:
                effects["recommendation"].append("Calming ingredients may help with afternoon stress.")

        elif 17 <= hour < 21:  # Evening (5PM - 9PM)
            if has_stimulants:
                effects["energy_effect"] = "might_interfere_sleep"
                effects["recommendation"].append("⚠️ Stimulants this late might interfere with sleep. Consider taking earlier tomorrow.")
            if has_calming:
                effects["sleep_effect"] = "promotes_sleep"
                effects["recommendation"].append("Perfect timing! Calming ingredients will help you wind down.")

        else:  # Night (9PM - 6AM)
            if has_stimulants:
                effects["energy_effect"] = "will_interfere_sleep"
                effects["recommendation"].append("❌ Late night stimulants will likely keep you awake!")
            if has_calming:
                effects["sleep_effect"] = "strongly_promotes_sleep"
                effects["recommendation"].append("Excellent timing for sleep support.")

        # Focus effects
        if has_focus:
            effects["focus_effect"] = "enhanced"
            effects["recommendation"].append("Contains ingredients that may enhance mental focus.")

        return effects

    def _supplement_from_text_or_url(self, raw: str) -> tuple[str | None, str | None, str | None, str | None, dict | None]:
        """
        Extract supplement info from text or URL.
        Returns (name, ingredients, notes, product_type, effects)
        """
        url_match = re.search(r"https?://\S+", raw)
        product_type = None
        effects = None

        if url_match:
            url = url_match.group(0).rstrip(").,")
            title, description, metadata = self._fetch_page_summary(url)

            if title:
                # Classify the product
                classification = self._classify_amazon_product(title, description or "")
                product_type = classification["type"]

                name = re.split(r"[-|:]", title)[0].strip()
                ingredients = description or title

                # Build comprehensive notes from metadata
                notes_parts = []
                if metadata:
                    if metadata.get('brand'):
                        notes_parts.append(f"Brand: {metadata['brand']}")
                    if metadata.get('price'):
                        notes_parts.append(f"Price: {metadata['price']}")
                    if metadata.get('rating'):
                        notes_parts.append(f"Rating: {metadata['rating']}")
                    if metadata.get('ingredients_extracted'):
                        notes_parts.append(f"Ingredients: {metadata['ingredients_extracted'][:300]}")
                    elif metadata.get('supplement_facts'):
                        notes_parts.append(f"Facts: {metadata['supplement_facts'][:300]}")

                notes = " | ".join(notes_parts) if notes_parts else None

                # Analyze time-based effects for supplements/food
                if product_type in ["supplement", "food"]:
                    effects = self._analyze_time_based_effects(
                        name,
                        ingredients,
                        datetime.now()
                    )

                return name[:80], ingredients[:500], notes, product_type, effects

        name, _, ingredients = raw.partition("|")
        name = name.strip()
        ingredients = ingredients.strip() or None
        return (name or None), ingredients, None, product_type, None

    def _looks_like_url_name(self, name: str | None) -> bool:
        if not name:
            return True
        return bool(re.match(r"^\s*https?://", name)) or name.lower().startswith("amazon product")

    def _product_candidate_from_analysis(
        self,
        analysis: str,
        url: str,
    ) -> tuple[str | None, str | None, str | None, str | None, dict | None]:
        """Extract a supplement candidate from Gemini's page analysis."""
        name = None
        patterns = [
            r"\*\*Product Name:\*\*\s*([^\n]+)",
            r"Product Name:\s*([^\n]+)",
            r"\*\*Product:\*\*\s*([^\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, analysis, re.IGNORECASE)
            if match:
                name = match.group(1).strip(" *:-")
                break

        if not name:
            first_line = next((line.strip(" *") for line in analysis.splitlines() if line.strip()), "")
            title_match = re.search(r"product page for (?:a |an |the )?(.+?)(?:\.|$)", first_line, re.IGNORECASE)
            if title_match:
                name = title_match.group(1).strip(" *:-")

        if not name:
            return None, None, None, None, None

        product_type = self._classify_amazon_product(name, analysis).get("type")
        ingredients = analysis[:500]
        notes = f"Source: {url} | Gemini analysis: {analysis[:700]}"
        effects = None
        if product_type in {"supplement", "food"}:
            effects = self._analyze_time_based_effects(name, ingredients, datetime.now())
        return name[:80], ingredients, notes, product_type, effects

    async def _resolve_supplement_candidate(
        self,
        raw: str,
    ) -> tuple[str | None, str | None, str | None, str | None, dict | None]:
        """Resolve text or URL into a supplement candidate, using Gemini when scraping is weak."""
        name, ingredients, notes, product_type, effects = self._supplement_from_text_or_url(raw)
        url_match = re.search(r"https?://\S+", raw)
        if not url_match or not self._looks_like_url_name(name):
            return name, ingredients, notes, product_type, effects

        url = url_match.group(0).rstrip(").,")
        if not self.web_agent.configured:
            return None, None, f"Source: {url}", None, None

        result = await self.web_agent.browse_url(url, "Identify the product or supplement on this page.")
        if not result.get("success"):
            logger.info("Gemini product resolution failed for %s: %s", url, result.get("error"))
            return None, None, f"Source: {url}", None, None

        return self._product_candidate_from_analysis(result.get("analysis", ""), url)

    def _format_supplement_candidate_message(
        self,
        name: str,
        ingredients: str | None,
        notes: str | None,
        effects: dict | None,
    ) -> str:
        msg = f"Found this supplement:\n\n{name}"
        if ingredients:
            msg += f"\n\n{ingredients[:350]}{'...' if len(ingredients) > 350 else ''}"
        if notes and "Source:" in notes:
            msg += f"\n\n{notes[:250]}{'...' if len(notes) > 250 else ''}"
        if effects and effects.get("recommendation"):
            msg += "\n\nTiming note:"
            for rec in effects["recommendation"][:3]:
                msg += f"\n• {rec}"
        return msg

    def _parse_saved_supplement_intake(self, text: str) -> dict | None:
        lowered = text.lower()
        if not re.search(r"\b(took|take|had|log(?:ged)?|consumed)\b", lowered):
            return None

        supplements = self.db.get_supplements()
        matches = []
        for supplement in supplements:
            name = supplement.name.strip()
            if not name or name.lower().startswith("http"):
                continue
            words = [word for word in re.split(r"\W+", name.lower()) if len(word) >= 4]
            if name.lower() in lowered or (words and sum(word in lowered for word in words) >= min(2, len(words))):
                matches.append(supplement)

        if not matches:
            return None

        quantity_match = re.search(
            r"\b(\d+(?:\.\d+)?|one|two|three|half)\s*(tablet|tablets|tab|tabs|capsule|capsules|softgel|softgels|scoop|scoops)?",
            lowered,
        )
        quantity = quantity_match.group(1) if quantity_match else "1"
        unit = quantity_match.group(2) if quantity_match and quantity_match.group(2) else "serving"
        selected = matches[:3]
        return {
            "type": "health_metric",
            "timestamp": datetime.now().isoformat(),
            "supplements": [supplement.name for supplement in selected],
            "metrics": {
                "supplement_doses": {
                    supplement.name: {"quantity": quantity, "unit": unit}
                    for supplement in selected
                },
                "supplement_ingredients": {
                    supplement.name: supplement.ingredients
                    for supplement in selected
                },
            },
            "source": "saved_supplement_match",
        }

    def _food_analysis(self, items: list[str], macros: dict, energy_prediction: dict) -> str:
        item_text = ", ".join(items)
        query = urllib.parse.quote_plus(f"{item_text} nutrition glycemic energy digestion")
        web_note = ""
        try:
            with urllib.request.urlopen(f"https://duckduckgo.com/html/?q={query}", timeout=8) as response:
                page = response.read(5000).decode("utf-8", errors="ignore")
            text = re.sub(r"<[^>]+>", " ", page)
            text = re.sub(r"\s+", " ", text)
            match = re.search(r".{0,80}\b(?:calories|carbohydrate|protein|glycemic|digestion|energy)\b.{0,120}", text, re.IGNORECASE)
            if match:
                web_note = " Web check: " + match.group(0).strip()[:220]
        except Exception as error:
            logger.info(f"Food web analysis unavailable: {error}")

        calories = macros.get("calories")
        carb = macros.get("carbs", "unknown")
        protein = macros.get("protein", "unknown")
        fat = macros.get("fat", "unknown")
        base = f"Coach note: {item_text} logged with carbs {carb}, protein {protein}, fat {fat}."
        if calories:
            base += f" Estimated {calories} kcal."
        if energy_prediction.get("status") == "crash_warning":
            base += " Expect a possible focus dip; pair the next work block with water or a short walk."
        else:
            base += " Energy impact looks steady unless portion size was larger than logged."
        return (base + web_note)[:700]
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = """
🌟 <b>Life OS Commands</b>

<b>Daily capture</b>
/task - Create, complete, remove, or uncomplete tasks
/newtask - Add a task directly
/delete_task - Remove a task directly
/eatery - Log food by meal type
/food - Food history with quick re-log
/foodtoday - Today's food with delete buttons
/delete_food - Delete today's food entries
/energy - Log energy levels
/supplements - Log your morning supplement stack
/delete_recent - Delete recent supplement or energy logs
/milestones - Add or view substantial work accomplishments
/board - Show today's High Court board or add a new board
/saved - Stuff for later archive
/expenses - Today's expenses or add one

<b>Supplements</b>
/addsupplement - Add a supplement or product link
/removesupplement - Remove a saved supplement
/clean_supplements - Remove broken supplement imports

<b>Reminders</b>
/remind - Create a reminder
/reminders - View, complete, or delete reminders

<b>Review</b>
/summary - Today's summary
/stats - Weekly statistics
/rollover - Move unfinished old tasks to today
/food_analysis - Nutrition analysis for today's food
/analyze - Full recent analysis
/analyze_hour - Past-hour performance analysis

<b>Memory and style</b>
/style - Brief, friendly, or analytical replies
/mood - Mood trends
/entities - Remembered people, projects, places
/memory - Recent conversation memory

<b>Operator mode</b>
/operator or /operator_on - Enable quick completion with "+"

<b>Natural language works too</b>
• "I ate poha and tea"
• "Took magnesium before sleeping"
• "Buy black garbage bags"
• "Done" or "completed affidavit +"
• "250Rs for lunch"
• "No. 9 is over"
• "save this for later: useful note"
• "What did I eat today?"
        """
        await update.message.reply_text(welcome_message, parse_mode='HTML')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await self.start_command(update, context)

    async def operator_on_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enable the simple operator workflow for this chat."""
        context.user_data['operator_on'] = True
        await update.message.reply_text(
            "Operator is on.\n\n"
            "Send a completed task like:\n"
            "completed affidavit of service +\n\n"
            "I will mark it completed and append it to today's offline Excel-compatible CSV."
        )
    
    async def eatery_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Interactive food logging menu"""
        keyboard = [
            [InlineKeyboardButton("🍳 Breakfast", callback_data='food_breakfast')],
            [InlineKeyboardButton("🍱 Lunch", callback_data='food_lunch')],
            [InlineKeyboardButton("🍽 Dinner", callback_data='food_dinner')],
            [InlineKeyboardButton("🍎 Snack", callback_data='food_snack')],
            [InlineKeyboardButton("💧 Water", callback_data='food_water')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '🍽 *What did you eat?*\n\nSelect a meal type or just describe what you ate:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Quick task creation/completion"""
        keyboard = [
            [InlineKeyboardButton("✅ Complete Task", callback_data='task_complete')],
            [InlineKeyboardButton("📝 New Task", callback_data='task_new')],
            [InlineKeyboardButton("📋 View Pending Tasks", callback_data='task_view_pending')],
            [InlineKeyboardButton("🗑 Remove Task", callback_data='task_delete')],
            [InlineKeyboardButton("↩️ Uncomplete Task", callback_data='task_view_completed')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '📋 *Task Manager*\n\nWhat would you like to do?',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def new_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create a pending task directly or prompt for one."""
        description = " ".join(context.args).strip()
        if not description:
            context.user_data['expecting'] = 'task_new'
            await update.message.reply_text("Describe your new task:")
            return

        task, created = self._create_pending_task(description)
        if created:
            await update.message.reply_text(f"✅ Task created: {task.description}")
        else:
            await update.message.reply_text(f"⚠️ Task already exists: {task.description}")

    async def milestones_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show milestones or add one directly."""
        raw = " ".join(context.args).strip()
        if raw and raw.lower() not in {"add", "new"}:
            parsed = self._parse_milestone_text(raw)
            if not parsed:
                await update.message.reply_text("Send it like: APL drafting 6 hours")
                return
            milestone = self.db.create_milestone(**parsed)
            hours = f" ({milestone.hours:g}h)" if milestone.hours else ""
            await update.message.reply_text(f"Milestone added: {milestone.title}{hours}")
            return

        if raw.lower() in {"add", "new"}:
            context.user_data["expecting"] = "milestone_add"
            await update.message.reply_text("Send the milestone with hours, e.g. Drafted APL 6 hours")
            return

        milestones = self.db.get_milestones(limit=10)
        keyboard = [[InlineKeyboardButton("Add milestone", callback_data="milestone_add")]]
        if not milestones:
            await update.message.reply_text(
                "No milestones yet. Add one when a substantial work block is completed.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        lines = ["*Recent milestones:*"]
        for item in milestones:
            hours = f" - {item.hours:g}h" if item.hours else ""
            lines.append(f"• {item.title}{hours} ({item.category})")
        await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def board_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show or replace today's High Court board."""
        raw = " ".join(context.args).strip()
        if raw.lower() in {"add", "new", "paste", "set"}:
            context.user_data["expecting"] = "board_add"
            await update.message.reply_text("Paste today's board now. I will replace the saved board for that date.")
            return
        entries = self.db.get_court_board(self._today_board_date())
        await update.message.reply_text(self._format_board(entries), parse_mode="Markdown")

    async def saved_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show saved stuff for later."""
        items = self.db.get_saved_items(limit=10)
        if not items:
            await update.message.reply_text("Nothing saved for later yet.")
            return
        lines = ["*Stuff for later:*"]
        for item in items:
            content = item.content or item.file_path or ""
            if len(content) > 160:
                content = content[:157] + "..."
            lines.append(f"• {item.item_type}: {content}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def expenses_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show today's expenses or add one directly."""
        raw = " ".join(context.args).strip()
        if raw:
            parsed = self._parse_expense_from_message(raw)
            if not parsed:
                await update.message.reply_text("Send it like: 250Rs for lunch")
                return
            expense = self.db.create_expense(**parsed)
            await update.message.reply_text(f"Expense logged: Rs {expense.amount:g} for {expense.description}")
            return
        start, end = self._today_bounds()
        expenses = self.db.get_expenses(start_date=start, end_date=end)
        if not expenses:
            await update.message.reply_text("No expenses logged today.")
            return
        total = sum(expense.amount for expense in expenses)
        lines = [f"*Today's expenses: Rs {total:g}*"]
        for expense in expenses:
            lines.append(f"• Rs {expense.amount:g} - {expense.description}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    
    async def energy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Log energy levels"""
        keyboard = [
            [
                InlineKeyboardButton("😴 1", callback_data='energy_1'),
                InlineKeyboardButton("😪 2", callback_data='energy_2'),
                InlineKeyboardButton("😐 3", callback_data='energy_3'),
                InlineKeyboardButton("😊 4", callback_data='energy_4'),
                InlineKeyboardButton("😄 5", callback_data='energy_5'),
            ],
            [
                InlineKeyboardButton("🙂 6", callback_data='energy_6'),
                InlineKeyboardButton("😃 7", callback_data='energy_7'),
                InlineKeyboardButton("🤩 8", callback_data='energy_8'),
                InlineKeyboardButton("⚡ 9", callback_data='energy_9'),
                InlineKeyboardButton("🚀 10", callback_data='energy_10'),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '⚡ *How\'s your energy right now?*\n\n1 = Exhausted, 10 = Peak Performance',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get today's summary"""
        await update.message.reply_text("📊 Generating your daily summary...")
        
        # Get today's data
        today = datetime.now().date()
        summary = self.db.get_daily_summary(today)
        
        if not summary:
            await update.message.reply_text("No data logged today yet. Start tracking!")
            return
        
        # Generate summary using LLM
        summary_text = await self.llm_parser.generate_daily_summary(summary)
        
        await update.message.reply_text(
            f"📊 *Daily Summary - {today.strftime('%B %d, %Y')}*\n\n{summary_text}",
            parse_mode='Markdown'
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show statistics"""
        stats = self.db.get_weekly_stats()
        
        stats_text = f"""
📈 *Weekly Statistics*

*Tasks:*
• Completed: {stats['tasks_completed']}
• Pending: {stats['tasks_pending']}
• Completion Rate: {stats['completion_rate']:.1f}%

*Energy:*
• Average: {stats['avg_energy']:.1f}/10
• Peak Time: {stats['peak_energy_time']}
• Low Time: {stats['low_energy_time']}

*Food:*
• Meals Logged: {stats['meals_logged']}
• Most Common: {stats['top_food']}

*Streaks:*
• Current Streak: {stats['current_streak']} days 🔥
        """
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def supplements_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        supplements = self.db.get_supplements()
        if not supplements:
            await update.message.reply_text("No supplements saved. Add one with /addsupplement Name | ingredients")
            return

        selected_doses = {
            int(supplement_id): int(quantity)
            for supplement_id, quantity in context.user_data.get("selected_supplement_doses", {}).items()
            if int(quantity) > 0
        }
        keyboard = []
        for supplement in supplements[:40]:
            quantity = selected_doses.get(supplement.id, 0)
            checked = f"✓ x{quantity} " if quantity else ""
            keyboard.append([InlineKeyboardButton(
                f"{checked}{supplement.name}",
                callback_data=f"supp_toggle_{supplement.id}",
            )])
            if quantity:
                keyboard.append([
                    InlineKeyboardButton("-1", callback_data=f"supp_dec_{supplement.id}"),
                    InlineKeyboardButton("+1", callback_data=f"supp_inc_{supplement.id}"),
                ])
        keyboard.append([InlineKeyboardButton("Submit morning stack", callback_data="supp_submit")])
        keyboard.append([InlineKeyboardButton("Clear selection", callback_data="supp_clear")])
        await update.message.reply_text(
            "Select what you took this morning. Tap once for x1, use +1/-1 for dose, then Submit.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def add_supplement_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw = " ".join(context.args).strip()
        if not raw:
            context.user_data["expecting"] = "supplement_add"
            await update.message.reply_text("Send the supplement name, a product link, or: Name | ingredient 1, ingredient 2")
            return

        # Send "processing" message first
        processing_msg = await update.message.reply_text("🔍 Fetching product details...")

        try:
            name, ingredients, notes, product_type, effects = await self._resolve_supplement_candidate(raw)
        except Exception as e:
            logger.error(f"Error fetching product: {e}")
            # Fallback: extract name from URL or use raw text
            if "amzn" in raw.lower() or "amazon" in raw.lower():
                # Extract product ID from URL for name
                url_match = re.search(r'/([A-Z0-9]{10})(?:/|$)', raw)
                if url_match:
                    name = f"Amazon Product ({url_match.group(1)})"
                else:
                    name = "Amazon Product"
                ingredients = None
                notes = f"URL: {raw.split()[0]}"
                product_type = "supplement"  # Default for Amazon links
                effects = None
            else:
                await processing_msg.edit_text("❌ Could not fetch product details. Please try with the product name.")
                return

        # Delete processing message
        try:
            await processing_msg.delete()
        except:
            pass

        if not name:
            await update.message.reply_text("I could not find a product name. Send: Name | ingredients")
            return

        if "http" in raw.lower() and product_type != "non_edible":
            context.user_data["pending_supplement"] = {
                "name": name,
                "ingredients": ingredients,
                "notes": notes,
                "effects": effects,
                "raw": raw,
            }
            keyboard = [
                [InlineKeyboardButton("💊 Save supplement", callback_data="confirm_add_supplement")],
                [InlineKeyboardButton("🛒 Purchase reminder", callback_data="confirm_supp_purchase")],
                [InlineKeyboardButton("❌ Cancel", callback_data="confirm_supp_cancel")],
            ]
            await update.message.reply_text(
                self._format_supplement_candidate_message(name, ingredients, notes, effects)
                + "\n\nSave this to your supplement list?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # If product type was detected, ask for confirmation
        if product_type == "non_edible":
            # Create a purchase reminder
            reminder = self.db.create_reminder(
                description=f"Purchase: {name}",
                reminder_type="purchase",
                url=raw.strip().split()[0] if "http" in raw else None
            )

            confirm_msg = f"🛍️ *Non-edible product detected: {name}*"
            if notes:
                confirm_msg += f"\n{notes[:200]}{'...' if len(notes) > 200 else ''}"
            confirm_msg += f"\n\n💾 I've created a purchase reminder for you."
            confirm_msg += f"\n\nUse /reminders to view all reminders."
            await update.message.reply_text(confirm_msg, parse_mode='Markdown')
            return

        elif product_type == "food":
            # Ask if they want to add to food log or supplement list
            context.user_data["pending_food"] = {
                "name": name,
                "ingredients": ingredients,
                "notes": notes,
                "effects": effects,
                "raw": raw
            }

            keyboard = [
                [InlineKeyboardButton("🍽 Log as food", callback_data="add_as_food")],
                [InlineKeyboardButton("💊 Add to supplements", callback_data="add_as_supplement")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg = f"🍽️ *Food product detected: {name}*"
            if ingredients:
                msg += f"\n\n{ingredients[:200]}..."
            if effects and effects.get("recommendation"):
                msg += f"\n\n⏰ *Timing Analysis:*"
                for rec in effects["recommendation"][:2]:
                    msg += f"\n• {rec}"
            msg += f"\n\nHow would you like to add this?"

            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
            return

        # Default: add as supplement
        confirm_msg = f"✅ *Added: {name}*\n"
        if ingredients:
            confirm_msg += f"📋 {ingredients[:200]}{'...' if len(ingredients) > 200 else ''}\n"
        if notes:
            confirm_msg += f"ℹ️ {notes[:300]}{'...' if len(notes) > 300 else ''}"

        if effects and effects.get("recommendation"):
            confirm_msg += f"\n\n⏰ *Timing Analysis:*"
            for rec in effects["recommendation"][:3]:
                confirm_msg += f"\n• {rec}"

        supplement = self.db.create_supplement(
            name=name.strip(),
            ingredients=ingredients.strip() if ingredients else None,
            notes=notes
        )
        await update.message.reply_text(confirm_msg, parse_mode='Markdown')

    async def remove_supplement_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        supplements = self.db.get_supplements()
        if not supplements:
            await update.message.reply_text("No supplements saved.")
            return
        keyboard = [
            [InlineKeyboardButton(f"Delete {supplement.name}", callback_data=f"supp_delete_{supplement.id}")]
            for supplement in supplements[:30]
        ]
        await update.message.reply_text("Choose a supplement to remove:", reply_markup=InlineKeyboardMarkup(keyboard))

    def _is_broken_supplement(self, supplement) -> bool:
        name = (supplement.name or "").strip().lower()
        notes = (supplement.notes or "").strip().lower()
        return (
            name.startswith("http://")
            or name.startswith("https://")
            or name in {"amazon product", "amazon product (unknown)", "product"}
            or (name.startswith("amazon product (") and "source:" in notes)
        )

    async def clean_supplements_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Deactivate malformed supplement entries, usually failed URL imports."""
        broken = [
            supplement
            for supplement in self.db.get_supplements(active_only=False)
            if supplement.active and self._is_broken_supplement(supplement)
        ]

        if not broken:
            await update.message.reply_text("No broken active supplement entries found.")
            return

        removed = []
        for supplement in broken:
            removed_supplement = self.db.remove_supplement(supplement.id)
            if removed_supplement:
                removed.append(removed_supplement.name)

        await update.message.reply_text(
            "Removed broken supplement entries:\n" + "\n".join(f"- {name}" for name in removed)
        )

    async def food_history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Interactive food history with clickable buttons to re-log meals"""
        # Get recent food logs (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        logs = list(reversed(self.db.get_food_logs(
            start_date=thirty_days_ago,
            limit=100
        )))

        if not logs:
            await update.message.reply_text("No food logged yet. Start by logging your first meal!")
            return

        # Group by unique meal combinations
        meal_groups = {}
        for log in logs:
            items = log.items or []
            if not items:
                continue
            key = tuple(sorted(items))
            if key not in meal_groups:
                meal_groups[key] = {
                    'items': items,
                    'count': 0,
                    'last_logged': log.timestamp,
                    'macros': log.macros,
                    'calories': (log.macros or {}).get('calories') or (log.energy_prediction or {}).get('calories')
                }
            meal_groups[key]['count'] += 1

        # Sort by frequency and recency
        sorted_meals = sorted(
            meal_groups.values(),
            key=lambda m: (m['count'], m['last_logged']),
            reverse=True
        )

        # Build keyboard with top meals
        keyboard = []
        displayed = 0
        for meal in sorted_meals[:20]:  # Show top 20
            items_text = ', '.join(meal['items'][:2])  # Show first 2 items
            if len(meal['items']) > 2:
                items_text += f" +{len(meal['items']) - 2} more"

            # Build button label
            label = f"{items_text}"
            if meal['count'] > 1:
                label += f" ({meal['count']}x)"
            if meal['calories']:
                label += f" [{meal['calories']} kcal]"

            relog_choices = context.user_data.setdefault("food_relog_choices", {})
            relog_choices[str(displayed)] = {
                "items": meal["items"],
                "macros": meal.get("macros") or {},
            }
            callback_data = f"food_relog_{displayed}"

            keyboard.append([InlineKeyboardButton(label[:60], callback_data=callback_data)])
            displayed += 1

        keyboard.append([InlineKeyboardButton("📝 Log New Food", callback_data="food_new")])
        keyboard.append([InlineKeyboardButton("📖 View Full History", callback_data="food_full_history")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        header = f"🍽 *Food History - Quick Re-log*\n\n"
        header += f"Found {len(sorted_meals)} unique meals. Tap to re-log:\n"

        await update.message.reply_text(
            header,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def food_today_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show today's food with edit/delete options"""
        start, end = self._today_bounds()
        logs = list(reversed(self.db.get_food_logs(start_date=start, end_date=end, limit=30)))

        if not logs:
            await update.message.reply_text("No food logged today.")
            return

        # Build keyboard with delete options
        keyboard = []
        for log in logs[:15]:
            time = log.timestamp.strftime("%-I:%M %p") if log.timestamp else "??"
            items_text = ', '.join(log.items or [])[:40]
            keyboard.append([
                InlineKeyboardButton(f"🗑 {time}: {items_text}", callback_data=f"delete_food_{log.id}")
            ])

        if len(logs) > 15:
            keyboard.append([InlineKeyboardButton(f"📋 View all {len(logs)} entries", callback_data="food_full_list")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Build text summary
        lines = [f"*Today's Food ({len(logs)} entries):*\n"]
        total_calories = 0
        for log in logs:
            time = log.timestamp.strftime("%-I:%M %p") if log.timestamp else "??"
            items = ', '.join(log.items or [])
            calories = (log.macros or {}).get('calories') or (log.energy_prediction or {}).get('calories')
            if calories:
                total_calories += calories

            # Show enriched analysis if available
            detailed = (log.energy_prediction or {}).get("detailed_analysis")
            if detailed and detailed.get("summary"):
                lines.append(f"• *{time}:* {items}")
                lines.append(f"  {detailed['summary'][:150]}...")
            else:
                lines.append(f"• {time}: {items}")

        if total_calories:
            lines.append(f"\n*Total: ~{total_calories} kcal*")

        # Add info about enrichment
        any_enriched = any((log.energy_prediction or {}).get("detailed_analysis") for log in logs)
        if any_enriched:
            lines.append("\n📊 *Detailed nutritional analysis via internet research included*")

        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def food_analysis_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed nutritional analysis for today's food"""
        start, end = self._today_bounds()
        logs = list(reversed(self.db.get_food_logs(start_date=start, end_date=end, limit=10)))

        if not logs:
            await update.message.reply_text("No food logged today.")
            return

        lines = ["🍽️ *Detailed Nutritional Analysis*\n"]

        for log in logs:
            time = log.timestamp.strftime("%-I:%M %p") if log.timestamp else "??"
            items = ', '.join(log.items or [])

            detailed = (log.energy_prediction or {}).get("detailed_analysis")
            if detailed and detailed.get("summary"):
                lines.append(f"⏰ *{time}:* {items}")
                lines.append(detailed["summary"])
                lines.append("\n" + "─" * 30 + "\n")
            else:
                lines.append(f"⏰ *{time}:* {items}")
                lines.append("_Analysis pending... (runs hourly)_")
                lines.append("\n")

        await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

    async def reminders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show and manage reminders"""
        reminders = self.db.get_reminders(active_only=True, limit=20)

        if not reminders:
            await update.message.reply_text("No active reminders. Use /remind to create one!")
            return

        keyboard = []
        for reminder in reminders[:15]:
            reminder_type_emoji = {"purchase": "🛒", "task": "📋", "general": "📌"}.get(reminder.reminder_type, "📌")
            label = f"{reminder_type_emoji} {reminder.description[:35]}"
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"complete_reminder_{reminder.id}"),
                InlineKeyboardButton("🗑", callback_data=f"delete_reminder_{reminder.id}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        lines = [f"📋 *Your Reminders ({len(reminders)})*\n"]
        for reminder in reminders[:10]:
            reminder_type_emoji = {"purchase": "🛒", "task": "📋", "general": "📌"}.get(reminder.reminder_type, "📌")
            time_str = f" (due {reminder.remind_at.strftime('%b %d %-I:%M%p')})" if reminder.remind_at else ""
            lines.append(f"{reminder_type_emoji} {reminder.description}{time_str}")

        if len(reminders) > 10:
            lines.append(f"\n... and {len(reminders) - 10} more")

        lines.append("\nTap to mark complete, or use 🗑 to delete.")

        await update.message.reply_text("\n".join(lines), reply_markup=reply_markup, parse_mode='Markdown')

    async def delete_recent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show and delete recent entries with smart energy cleanup"""
        from database import HealthLog, EnergyLevel
        from datetime import datetime, timedelta

        # Get recent entries with predicted energy count
        health_entries = self.db.get_recent_health_logs_with_energy(hours=2, limit=10)

        session = self.db.get_session()
        try:
            # Get recent actual energy logs (manually logged)
            recent = datetime.now() - timedelta(hours=2)
            energy_logs = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= recent,
                EnergyLevel.predicted == False  # Only actual logged energy
            ).order_by(EnergyLevel.timestamp.desc()).limit(5).all()
        finally:
            session.close()

        lines = ["🗑️ *Recent Entries (Tap to delete)*\n"]
        lines.append("_Deleting supplements also removes their predicted energy_\n")

        keyboard = []

        if health_entries:
            lines.append("*Supplement Intake:*")
            for entry in health_entries:
                time_str = entry["timestamp"].strftime("%-I:%M %p") if entry["timestamp"] else "??"
                supp_str = ', '.join(entry["supplements"]) if entry["supplements"] else "Empty"
                energy_info = f" +{entry['predicted_energy_count']} predicted energy" if entry['predicted_energy_count'] > 0 else ""

                lines.append(f"• {time_str}: {supp_str}{energy_info}")
                keyboard.append([InlineKeyboardButton(f"🗑 {time_str}: {supp_str[:25]}", callback_data=f"delete_health_{entry['id']}")])

        if energy_logs:
            lines.append("\n*Energy Logs (manual):*")
            for log in energy_logs:
                time_str = log.timestamp.strftime("%-I:%M %p") if log.timestamp else "??"
                lines.append(f"• {time_str}: Level {log.level}/10")
                keyboard.append([InlineKeyboardButton(f"🗑 Energy {log.level}/10", callback_data=f"delete_energy_{log.id}")])

        if not health_entries and not energy_logs:
            lines.append("No recent entries found.")

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

        await update.message.reply_text("\n".join(lines), reply_markup=reply_markup, parse_mode='Markdown')

    async def remind_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create a new reminder"""
        reminder_text = " ".join(context.args).strip()

        if not reminder_text:
            context.user_data["expecting"] = "remind_add"
            await update.message.reply_text(
                "What should I remind you about?\n\n"
                "Examples:\n"
                "• Remind me to buy X\n"
                "• Remind me to complete task Y\n"
                "• Remind me at 5pm to call Z\n\n"
                "Or send /remind followed by your reminder.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Purchase reminder", callback_data="remind_type_purchase")],
                    [InlineKeyboardButton("📋 Task reminder", callback_data="remind_type_task")],
                    [InlineKeyboardButton("📌 General reminder", callback_data="remind_type_general")]
                ])
            )
            return

        # Simple reminder - parse time if present
        remind_at = self._parse_time_hint(reminder_text)
        reminder = self.db.create_reminder(
            description=reminder_text,
            reminder_type="general",
            remind_at=remind_at.isoformat() if remind_at else None
        )

        msg = f"📋 *Reminder created:*\n{reminder.description}"
        if remind_at:
            msg += f"\n⏰ Will remind at {remind_at.strftime('%-I:%M %p')}"
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def rollover_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger task rollover from yesterday to today"""
        result = self.db.roll_over_incomplete_tasks()
        count = result.get("rolled_over", 0)
        tasks = result.get("tasks", [])

        if count == 0:
            await update.message.reply_text("✅ No incomplete tasks to roll over. All caught up!")
        else:
            lines = [f"📅 *Rolled over {count} task(s) to today:*\n"]
            for task in tasks[:10]:
                lines.append(f"• {task}")
            if len(tasks) > 10:
                lines.append(f"\n... and {len(tasks) - 10} more")
            lines.append(f"\nNew deadline: End of day today")
            await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

    # ===== NEW: Smart Feature Commands =====

    async def style_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Change response style preference"""
        user_id = update.effective_user.id

        keyboard = [
            [InlineKeyboardButton("🤖 Brief", callback_data='setstyle_brief')],
            [InlineKeyboardButton("😊 Friendly", callback_data='setstyle_friendly')],
            [InlineKeyboardButton("📊 Analytical", callback_data='setstyle_analytical')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        current_style = self.get_preference(user_id, 'response_style', 'friendly')

        await update.message.reply_text(
            f"*Choose your response style:*\n\n"
            f"Current: **{current_style.title()}**\n\n"
            f"• **Brief**: Short, direct responses\n"
            f"• **Friendly**: Warm, conversational\n"
            f"• **Analytical**: Data-focused, detailed",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def mood_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View mood trends"""
        user_id = update.effective_user.id

        mood_summary = self.get_mood_summary(user_id, hours=168)  # Week

        avg = mood_summary.get('avg', 0)
        trend = mood_summary.get('trend', 'neutral')
        count = mood_summary.get('count', 0)

        # Convert avg to emoji
        if avg >= 0.5:
            emoji = "😄"
            description = "mostly positive"
        elif avg >= 0.2:
            emoji = "🙂"
            description = "slightly positive"
        elif avg >= -0.2:
            emoji = "😐"
            description = "neutral"
        elif avg >= -0.5:
            emoji = "😔"
            description = "slightly negative"
        else:
            emoji = "😢"
            description = "mostly negative"

        trend_emoji = {
            'improving': '📈',
            'declining': '📉',
            'stable': '➡️'
        }.get(trend, '➡️')

        lines = [
            f"💭 *Mood Summary (Last 7 Days)*\n",
            f"{emoji} Average sentiment: {description}",
            f"{trend_emoji} Trend: {trend.title()}",
            f"📊 Based on {count} logged messages"
        ]

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def entities_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View and manage remembered entities"""
        user_id = update.effective_user.id

        entities = self.get_entities(user_id)

        if not entities:
            await update.message.reply_text(
                "I haven't remembered any people, projects, or places yet. "
                "Just mention them in conversation and I'll remember! 🧠"
            )
            return

        # Group by type
        by_type = {}
        for e in entities:
            t = e['type']
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)

        lines = ["🧠 *Remembered Entities*\n"]

        for entity_type, items in by_type.items():
            lines.append(f"\n*{entity_type.title()}:*")
            for item in items[:10]:
                count = item.get('mention_count', 1)
                lines.append(f"• {item['name']} ({count}x)")

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View conversation memory"""
        user_id = update.effective_user.id

        history = self.get_conversation_history(user_id, limit=10)

        if not history:
            await update.message.reply_text("No conversation history yet.")
            return

        lines = ["💬 *Recent Conversation History*\n"]
        for msg in history[-10:]:
            role = "👤 You" if msg['role'] == 'user' else "🤖 Bot"
            timestamp = msg.get('timestamp', '')
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    timestamp = dt.strftime('%H:%M')
                except:
                    timestamp = ""
            content = msg['content'][:60]
            lines.append(f"{timestamp} {role}: {content}...")

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        caption = (update.message.caption or "").strip()
        if self._is_save_for_later(caption) or context.user_data.get("expecting") == "save_item":
            photo = update.message.photo[-1]
            photo_file = await photo.get_file()
            save_dir = Path("data/stuff_for_later")
            save_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = save_dir / f"saved_{timestamp}_{photo.file_unique_id}.jpg"
            await photo_file.download_to_drive(str(image_path))
            item = self.db.create_saved_item(
                item_type="image",
                content=self._clean_saved_text(caption) if caption else None,
                file_path=str(image_path),
                tags=["stuff_for_later"],
            )
            context.user_data.pop("expecting", None)
            await update.message.reply_text(f"Saved image for later #{item.id}.")
            return
        if self._is_health_image_caption(caption):
            await self.health_photo_message(update, context)
            return

        if "supplement" not in caption.lower() and context.user_data.get("expecting") != "supplement_add" and "http" not in caption.lower():
            await update.message.reply_text("I received the image. To add a supplement from it, send it with a caption like: Supplement Name | ingredients")
            return

        # Check for Amazon link in caption
        name, ingredients, notes, product_type, effects = self._supplement_from_text_or_url(caption)

        if not name:
            await update.message.reply_text("I cannot reliably read that screenshot yet. Send the product link, or caption it as: Name | ingredients")
            return

        # Handle non-edible products
        if product_type == "non_edible":
            reminder = self.db.create_reminder(
                description=f"Purchase: {name}",
                reminder_type="purchase",
                url=next((x for x in caption.split() if "http" in x), None)
            )
            await update.message.reply_text(f"🛍️ *Non-edible product detected*\n\nCreated purchase reminder: {name}\n\nUse /reminders to view.", parse_mode='Markdown')
            return

        # Handle food products
        if product_type == "food":
            context.user_data["pending_food"] = {
                "name": name,
                "ingredients": ingredients,
                "notes": notes,
                "effects": effects
            }
            keyboard = [
                [InlineKeyboardButton("🍽 Log as food", callback_data="add_as_food")],
                [InlineKeyboardButton("💊 Add to supplements", callback_data="add_as_supplement")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            msg = f"🍽️ *Food product detected: {name}*"
            if effects and effects.get("recommendation"):
                msg += f"\n\n⏰ *Timing Analysis:*"
                for rec in effects["recommendation"][:2]:
                    msg += f"\n• {rec}"
            msg += f"\n\nHow would you like to add this?"

            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
            return

        # Default: add as supplement
        confirm_msg = f"✅ *Added: {name}*"
        if ingredients:
            confirm_msg += f"\n📋 {ingredients[:200]}{'...' if len(ingredients) > 200 else ''}"
        if notes:
            confirm_msg += f"\nℹ️ {notes[:300]}{'...' if len(notes) > 300 else ''}"

        if effects and effects.get("recommendation"):
            confirm_msg += f"\n\n⏰ *Timing Analysis:*"
            for rec in effects["recommendation"][:3]:
                confirm_msg += f"\n• {rec}"

        supplement = self.db.create_supplement(name=name, ingredients=ingredients, notes=notes)
        context.user_data.pop("expecting", None)
        await update.message.reply_text(confirm_msg, parse_mode='Markdown')
        if name:
            confirm_msg = f"✅ *Added: {name}*"
            if ingredients:
                confirm_msg += f"\n📋 {ingredients[:200]}{'...' if len(ingredients) > 200 else ''}"
            if notes:
                confirm_msg += f"\nℹ️ {notes[:300]}{'...' if len(notes) > 300 else ''}"

            supplement = self.db.create_supplement(
                name=name,
                ingredients=ingredients,
                notes=notes
            )
            await update.message.reply_text(confirm_msg, parse_mode='Markdown')
            context.user_data.pop("expecting", None)
        else:
            await update.message.reply_text("I cannot reliably read that screenshot yet. Send the product link, or caption it as: Name | ingredients")

    async def document_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save arbitrary Telegram documents into stuff for later."""
        caption = (update.message.caption or "").strip()
        document = update.message.document
        if not document:
            return
        if not self._is_save_for_later(caption):
            await update.message.reply_text("I received the file. Caption it 'save for later' to archive it.")
            return
        doc_file = await document.get_file()
        save_dir = Path("data/stuff_for_later")
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", document.file_name or document.file_unique_id)
        file_path = save_dir / f"saved_{timestamp}_{safe_name}"
        await doc_file.download_to_drive(str(file_path))
        item = self.db.create_saved_item(
            item_type="document",
            content=self._clean_saved_text(caption) if caption else None,
            file_path=str(file_path),
            tags=["stuff_for_later"],
        )
        await update.message.reply_text(f"Saved file for later #{item.id}.")

    def _is_health_image_caption(self, caption: str) -> bool:
        text = caption.lower()
        health_terms = {
            "sleep",
            "steps",
            "step count",
            "workout",
            "exercise",
            "heart rate",
            "hrv",
            "calories burned",
            "activity",
            "health",
            "fitness",
            "recovery",
            "oura",
            "fitbit",
            "apple health",
            "garmin",
        }
        return any(term in text for term in health_terms)

    async def health_photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Analyze health tracking screenshots sent via Telegram."""
        await update.message.reply_text("📊 Got your health image. Analyzing it now...")

        try:
            photo = update.message.photo[-1]
            photo_file = await photo.get_file()

            temp_dir = Path("data/health_images")
            temp_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = temp_dir / f"health_{timestamp}_{photo.file_unique_id}.jpg"
            await photo_file.download_to_drive(str(image_path))

            from health_image_analyzer import HealthImageAnalyzer

            analyzer = HealthImageAnalyzer()
            previous_images = context.user_data.get("recent_health_images", [])
            if self._wants_health_comparison(update.message.caption or "") and previous_images:
                image_paths = previous_images[-3:] + [str(image_path)]
                result = await analyzer.compare_health_trends(image_paths, update.message.caption or None)
                self._remember_health_image(context, str(image_path))

                if result.get("success"):
                    data = result.get("data") or {}
                    if "raw_analysis" in data:
                        await update.message.reply_text(
                            "✅ Trend analysis complete.\n\n"
                            f"{data.get('raw_analysis', '').strip()[:3500]}"
                        )
                    else:
                        await update.message.reply_text(self._format_health_comparison(data))
                else:
                    await update.message.reply_text(
                        f"❌ Couldn't compare the images: {result.get('error', 'Unknown error')}"
                    )
                return

            result = await analyzer.analyze_health_image(str(image_path), update.message.caption or None)
            self._remember_health_image(context, str(image_path))

            if not result.get("success"):
                await update.message.reply_text(
                    f"❌ Couldn't analyze the image: {result.get('error', 'Unknown error')}"
                )
                return

            data = result.get("data") or {}
            if "raw_analysis" in data:
                await update.message.reply_text(
                    "✅ Health analysis complete.\n\n"
                    f"{data.get('raw_analysis', '').strip()[:3500]}"
                )
                return

            await update.message.reply_text(self._format_health_analysis(data))
        except Exception as e:
            logger.error("Error handling health image: %s", e, exc_info=True)
            await update.message.reply_text(
                "Sorry, something went wrong analyzing that image. Try again?"
            )

    def _wants_health_comparison(self, caption: str) -> bool:
        text = caption.lower()
        return any(term in text for term in ("compare", "trend", "vs", "versus", "last month", "this month"))

    def _remember_health_image(self, context: ContextTypes.DEFAULT_TYPE, image_path: str) -> None:
        recent_images = context.user_data.setdefault("recent_health_images", [])
        recent_images.append(image_path)
        del recent_images[:-5]

    def _format_health_analysis(self, data: dict) -> str:
        insights = data.get("insights") or {}
        strengths = insights.get("strengths") or []
        weaknesses = insights.get("weaknesses") or []
        recommendations = insights.get("recommendations") or []
        statistics = data.get("statistics") or {}

        lines = [
            "✅ Health Analysis Complete!",
            "",
            f"📊 Type: {str(data.get('data_type', 'unknown')).replace('_', ' ').title()}",
            f"📅 Period: {str(data.get('time_period', 'N/A')).title()}",
            f"⭐ Health Score: {data.get('health_score', 'N/A')}/10",
        ]

        if any(statistics.get(key) is not None for key in ("average", "best", "worst", "consistency_score")):
            lines.extend(
                [
                    "",
                    "Stats:",
                    f"Average: {statistics.get('average', 'N/A')}",
                    f"Best: {statistics.get('best', 'N/A')}",
                    f"Worst: {statistics.get('worst', 'N/A')}",
                    f"Consistency: {statistics.get('consistency_score', 'N/A')}/10",
                ]
            )

        if strengths:
            lines.extend(["", "Key Insights:"])
            lines.extend(f"✓ {item}" for item in strengths[:3])

        if weaknesses:
            lines.extend(["", "Areas to Improve:"])
            lines.extend(f"⚠️ {item}" for item in weaknesses[:3])

        if recommendations:
            lines.extend(["", "Recommendations:"])
            lines.extend(f"💡 {item}" for item in recommendations[:3])

        coach_message = data.get("coach_message")
        if coach_message:
            lines.extend(["", "Coach Says:", str(coach_message)])

        return "\n".join(lines)

    def _format_health_comparison(self, data: dict) -> str:
        comparison = data.get("comparison") or {}
        improvements = comparison.get("improvements") or []
        declines = comparison.get("declines") or []
        stable_areas = comparison.get("stable_areas") or []
        recommendations = data.get("recommendations") or []

        lines = [
            "✅ Trend Analysis Complete!",
            "",
            f"📊 Comparing: {str(data.get('data_type', 'health')).replace('_', ' ').title()}",
            f"📅 Time Span: {data.get('time_span', 'N/A')}",
            f"Trend: {str(data.get('trend', 'unknown')).upper()}",
        ]

        if improvements:
            lines.extend(["", "Improvements:"])
            lines.extend(f"✓ {item}" for item in improvements[:4])

        if declines:
            lines.extend(["", "Concerns:"])
            lines.extend(f"⚠️ {item}" for item in declines[:4])

        if stable_areas:
            lines.extend(["", "Stable Areas:"])
            lines.extend(f"• {item}" for item in stable_areas[:3])

        if recommendations:
            lines.extend(["", "Recommendations:"])
            lines.extend(f"💡 {item}" for item in recommendations[:3])

        coach_message = data.get("coach_message")
        if coach_message:
            lines.extend(["", "Coach Says:", str(coach_message)])

        return "\n".join(lines)

    async def delete_task_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tasks = self.db.get_tasks(limit=30)
        if not tasks:
            await update.message.reply_text("No tasks to delete.")
            return
        keyboard = [
            [InlineKeyboardButton(f"Delete {task.description[:42]}", callback_data=f"delete_task_{task.id}")]
            for task in tasks
            if (task.description or "").strip()
        ][:20]
        await update.message.reply_text("Choose a task to delete:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def delete_food_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Interactive food log deletion - now redirects to food_today which shows delete options"""
        await self.food_today_command(update, context)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith('food_relog_'):
            # Handle re-logging a meal from history
            try:
                choice_id = data[len('food_relog_'):]
                meal_data = context.user_data.get("food_relog_choices", {}).get(choice_id, {})
                items = meal_data.get('items', [])
                macros = meal_data.get('macros', {})

                if not items:
                    await query.edit_message_text("Could not re-log that meal. Please try logging manually.")
                    return

                # Log the food
                self.db.log_food(
                    items=items,
                    timestamp=datetime.now().isoformat(),
                    macros=macros,
                    energy_prediction={}
                )

                # Build confirmation message
                items_text = ', '.join(items)
                response = f"✅ *Re-logged: {items_text}*\n\n"
                if macros:
                    response += f"Macros: Carbs {macros.get('carbs', 'N/A')}, Protein {macros.get('protein', 'N/A')}, Fat {macros.get('fat', 'N/A')}"
                if macros and macros.get('calories'):
                    response += f"\nEstimated: {macros['calories']} kcal"

                await query.edit_message_text(response, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error re-logging food: {e}")
                await query.edit_message_text("Could not re-log that meal. Please try logging manually.")

        elif data == 'food_new':
            await query.edit_message_text("🍽 Describe what you ate:")
            context.user_data['expecting'] = 'food_new'

        elif data == 'food_full_history':
            # Show full food history
            thirty_days_ago = datetime.now() - timedelta(days=30)
            logs = list(reversed(self.db.get_food_logs(start_date=thirty_days_ago, limit=50)))
            if not logs:
                await query.edit_message_text("No food logged in the last 30 days.")
                return

            lines = ["*Food Log - Last 30 Days:*"]
            for log in logs[:30]:  # Limit to 30 entries
                time = log.timestamp.strftime("%I:%M %p") if log.timestamp else "??"
                items = ', '.join(log.items or [])
                macros = log.macros or {}
                calories = macros.get('calories') or (log.energy_prediction or {}).get('calories')
                line = f"- {time}: {items}"
                if calories:
                    line += f" ({calories} kcal)"
                lines.append(line)

            await query.edit_message_text('\n'.join(lines), parse_mode='Markdown')

        elif data.startswith('food_'):
            meal_type = data.split('_')[1]
            await query.edit_message_text(
                f"Great! Describe what you ate for {meal_type}:"
            )
            # Store context for next message
            context.user_data['expecting'] = f'food_{meal_type}'
        
        elif data.startswith('energy_'):
            level = int(data.split('_')[1])
            self.db.log_energy(level, predicted=False)
            
            emoji = ["😴", "😪", "😐", "😊", "😄", "🙂", "😃", "🤩", "⚡", "🚀"][level-1]
            await query.edit_message_text(
                f"Energy logged: {emoji} {level}/10\n\n"
                f"{'Low energy detected. Consider a break or healthy snack.' if level <= 3 else 'Good energy! Great time to tackle important tasks.' if level >= 7 else 'Moderate energy. Pace yourself.'}"
            )
            
        elif data == 'task_complete':
            # Get pending tasks
            tasks = self.db.get_tasks(status=TaskStatus.PENDING)
            if not tasks:
                await query.edit_message_text("No pending tasks! 🎉")
                return
            
            keyboard = [
                [InlineKeyboardButton(f"✅ {task.description[:40]}", callback_data=f'complete_{task.id}')]
                for task in tasks[:10]  # Show max 10
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Which task did you complete?",
                reply_markup=reply_markup
            )
        
        elif re.fullmatch(r'complete_\d+', data):
            task_id = int(data.split('_')[1])
            task = self.db.update_task_status(task_id, TaskStatus.COMPLETED)
            if task:
                export_completed_task(task, source="telegram_button")
            await query.edit_message_text("Task marked complete and saved to today's offline sheet.")
        
        elif data == 'task_new':
            await query.edit_message_text("Describe your new task:")
            context.user_data['expecting'] = 'task_new'

        elif data == 'task_view_pending':
            tasks = self.db.get_tasks(status=TaskStatus.PENDING)
            if not tasks:
                await query.edit_message_text("No pending tasks! 🎉")
                return

            task_list = "\n".join([f"• {task.description}" for task in tasks])
            await query.edit_message_text(f"*Pending Tasks ({len(tasks)}):*\n\n{task_list}", parse_mode='Markdown')

        elif data == 'task_delete':
            tasks = self.db.get_tasks(limit=30)
            tasks = [task for task in tasks if (task.description or "").strip()]
            if not tasks:
                await query.edit_message_text("No tasks to remove.")
                return

            keyboard = [
                [InlineKeyboardButton(f"🗑 {task.description[:40]}", callback_data=f"delete_task_{task.id}")]
                for task in tasks[:20]
            ]
            await query.edit_message_text(
                "Choose a task to remove:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'task_view_completed':
            tasks = self.db.get_completed_tasks(limit=20)
            if not tasks:
                await query.edit_message_text("No completed tasks yet!")
                return

            keyboard = [
                [InlineKeyboardButton(f"↩️ {task.description[:35]}", callback_data=f'uncomplete_{task.id}')]
                for task in tasks[:10]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"*Completed Tasks (tap to uncomplete):*\n\nSelect a task to mark as incomplete:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

        elif data.startswith('uncomplete_'):
            task_id = int(data.split('_')[1])
            task = self.db.update_task_status(task_id, TaskStatus.PENDING)
            if task:
                await query.edit_message_text(f"↩️ Marked as pending: {task.description}")
            else:
                await query.edit_message_text("Task not found.")

        elif data.startswith('supp_toggle_'):
            supplement_id = int(data.split('_')[-1])
            selected_doses = {
                int(key): int(value)
                for key, value in context.user_data.get("selected_supplement_doses", {}).items()
            }
            if selected_doses.get(supplement_id, 0):
                selected_doses.pop(supplement_id, None)
            else:
                selected_doses[supplement_id] = 1
            context.user_data["selected_supplement_doses"] = {
                str(key): value for key, value in selected_doses.items()
            }
            await query.edit_message_text("Selection updated. Send /supplements to review doses or submit.")

        elif data.startswith('supp_inc_'):
            supplement_id = int(data.split('_')[-1])
            selected_doses = {
                int(key): int(value)
                for key, value in context.user_data.get("selected_supplement_doses", {}).items()
            }
            selected_doses[supplement_id] = min(10, selected_doses.get(supplement_id, 0) + 1)
            context.user_data["selected_supplement_doses"] = {
                str(key): value for key, value in selected_doses.items()
            }
            await query.edit_message_text("Dose updated. Send /supplements to review or submit.")

        elif data.startswith('supp_dec_'):
            supplement_id = int(data.split('_')[-1])
            selected_doses = {
                int(key): int(value)
                for key, value in context.user_data.get("selected_supplement_doses", {}).items()
            }
            quantity = selected_doses.get(supplement_id, 0) - 1
            if quantity > 0:
                selected_doses[supplement_id] = quantity
            else:
                selected_doses.pop(supplement_id, None)
            context.user_data["selected_supplement_doses"] = {
                str(key): value for key, value in selected_doses.items()
            }
            await query.edit_message_text("Dose updated. Send /supplements to review or submit.")

        elif data == 'supp_clear':
            context.user_data["selected_supplement_doses"] = {}
            await query.edit_message_text("Supplement selection cleared.")

        elif data == 'supp_submit':
            selected_doses = {
                int(key): int(value)
                for key, value in context.user_data.get("selected_supplement_doses", {}).items()
                if int(value) > 0
            }
            supplements = [self.db.get_supplement(supplement_id) for supplement_id in selected_doses]
            supplements = [supplement for supplement in supplements if supplement and supplement.active]
            if not supplements:
                await query.edit_message_text("No supplements selected. Send /supplements and choose what you took.")
                return

            dose_map = {
                supplement.name: {
                    "quantity": selected_doses.get(supplement.id, 1),
                    "unit": "serving",
                }
                for supplement in supplements
            }

            # Log to database
            self.db.log_health(
                supplements=[supplement.name for supplement in supplements],
                metrics={
                    "supplement_doses": dose_map,
                    "supplement_ingredients": {
                        supplement.name: supplement.ingredients
                        for supplement in supplements
                    },
                    "source": "telegram_supplements_button",
                },
                timestamp=datetime.now().isoformat(),
            )
            energy_note = await self._supplement_research_async(supplements)
            context.user_data["selected_supplement_doses"] = {}

            # Build detailed confirmation with ingredients
            lines = ["✅ *Logged supplements:*\n"]
            for supp in supplements:
                dose = dose_map.get(supp.name, {})
                lines.append(f"• {dose.get('quantity', 1)} {dose.get('unit', 'serving')} {supp.name}")
                if supp.ingredients:
                    lines.append(f"  Ingredients: {supp.ingredients}")
                if supp.notes:
                    lines.append(f"  Notes: {supp.notes[:100]}{'...' if len(supp.notes) > 100 else ''}")
            lines.extend(["", energy_note])

            await query.edit_message_text("\n".join(lines), parse_mode='Markdown')

        elif data.startswith('supp_delete_'):
            supplement_id = int(data.split('_')[-1])
            supplement = self.db.remove_supplement(supplement_id)
            await query.edit_message_text(
                f"Removed supplement: {supplement.name}" if supplement else "Supplement not found."
            )

        elif data.startswith('delete_task_'):
            task_id = int(data.split('_')[-1])
            task = self.db.delete_task(task_id)
            await query.edit_message_text(
                f"Deleted task: {task.description}" if task else "Task not found."
            )

        elif data.startswith('delete_food_'):
            food_id = int(data.split('_')[-1])
            food = self.db.delete_food_log(food_id)
            await query.edit_message_text(
                f"🗑 Deleted: {', '.join(food.items or [])}" if food else "Food log not found."
            )

        elif data == 'food_full_list':
            # Show all food logs for today with delete options
            start, end = self._today_bounds()
            logs = list(reversed(self.db.get_food_logs(start_date=start, end_date=end, limit=50)))
            if not logs:
                await query.edit_message_text("No food logged today.")
                return

            keyboard = []
            for log in logs[:25]:
                time = log.timestamp.strftime("%-I:%M %p") if log.timestamp else "??"
                items_text = ', '.join(log.items or [])[:35]
                keyboard.append([
                    InlineKeyboardButton(f"🗑 {time}: {items_text}", callback_data=f"delete_food_{log.id}")
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"*All food logs ({len(logs)}):*\nTap to delete:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

        elif data == 'add_as_food':
            # Log as food
            pending = context.user_data.get("pending_food", {})
            if not pending:
                await query.edit_message_text("Session expired. Please send the product link again.")
                return

            name = pending.get("name", "Product")
            effects = pending.get("effects", {})

            # Log the food
            self.db.log_food(
                items=[name],
                timestamp=datetime.now().isoformat(),
                macros={},
                energy_prediction={"timing_analysis": effects} if effects else {}
            )

            msg = f"✅ *Logged as food: {name}*"
            if effects and effects.get("recommendation"):
                msg += f"\n\n⏰ *Timing Analysis:*"
                for rec in effects["recommendation"][:3]:
                    msg += f"\n• {rec}"

            context.user_data.pop("pending_food", None)
            await query.edit_message_text(msg, parse_mode='Markdown')

        elif data == 'add_as_supplement':
            # Add to supplement list
            pending = context.user_data.get("pending_food", {})
            if not pending:
                await query.edit_message_text("Session expired. Please send the product link again.")
                return

            name = pending.get("name", "Product")
            ingredients = pending.get("ingredients")
            notes = pending.get("notes")
            effects = pending.get("effects", {})

            supplement = self.db.create_supplement(
                name=name,
                ingredients=ingredients,
                notes=notes
            )

            msg = f"✅ *Added to supplements: {name}*"
            if ingredients:
                msg += f"\n📋 {ingredients[:200]}{'...' if len(ingredients) > 200 else ''}"
            if effects and effects.get("recommendation"):
                msg += f"\n\n⏰ *Timing Analysis:*"
                for rec in effects["recommendation"][:3]:
                    msg += f"\n• {rec}"

            context.user_data.pop("pending_food", None)
            await query.edit_message_text(msg, parse_mode='Markdown')

        elif data == 'confirm_add_supplement':
            pending = context.user_data.get("pending_supplement", {})
            if not pending:
                await query.edit_message_text("Session expired. Please send the product link again.")
                return

            name = pending.get("name")
            ingredients = pending.get("ingredients")
            notes = pending.get("notes")
            effects = pending.get("effects", {})

            self.db.create_supplement(name=name, ingredients=ingredients, notes=notes)
            context.user_data.pop("pending_supplement", None)

            msg = f"Saved supplement:\n\n{name}"
            msg += f"\n\nYou can now log it by saying: took 1 tablet of {name}"
            if effects and effects.get("recommendation"):
                msg += "\n\nTiming note:"
                for rec in effects["recommendation"][:3]:
                    msg += f"\n• {rec}"
            await query.edit_message_text(msg)

        elif data == 'confirm_supp_purchase':
            pending = context.user_data.get("pending_supplement", {})
            if not pending:
                await query.edit_message_text("Session expired. Please send the product link again.")
                return

            name = pending.get("name", "Product")
            raw = pending.get("raw", "")
            self.db.create_reminder(
                description=f"Purchase: {name}",
                reminder_type="purchase",
                url=raw.strip().split()[0] if "http" in raw else None,
            )
            context.user_data.pop("pending_supplement", None)
            await query.edit_message_text(f"Purchase reminder created:\n\n{name}")

        elif data == 'confirm_supp_cancel':
            context.user_data.pop("pending_supplement", None)
            await query.edit_message_text("Cancelled.")

        elif data.startswith('complete_reminder_'):
            reminder_id = int(data.split('_')[-1])
            reminder = self.db.complete_reminder(reminder_id)
            await query.edit_message_text(
                f"✅ Completed: {reminder.description}" if reminder else "Reminder not found."
            )

        elif data.startswith('delete_reminder_'):
            reminder_id = int(data.split('_')[-1])
            reminder = self.db.delete_reminder(reminder_id)
            await query.edit_message_text(
                f"🗑 Deleted: {reminder.description}" if reminder else "Reminder not found."
            )

        elif data.startswith('remind_type_'):
            reminder_type = data.split('_')[-1]
            context.user_data['expecting'] = f'remind_add_{reminder_type}'
            type_text = {"purchase": "purchase", "task": "task", "general": "general"}[reminder_type]
            await query.edit_message_text(f"Send me the reminder details for a {type_text} reminder:")

        elif data == 'url_add_supplement':
            url = context.user_data.get("pending_url")
            if not url:
                await query.edit_message_text("Session expired. Please send the link again.")
                return

            await query.edit_message_text("Fetching product details...")
            name, ingredients, notes, product_type, effects = await self._resolve_supplement_candidate(url)

            if not name:
                await query.edit_message_text(
                    "I could not identify the supplement from that link. Send the product name, or use: /addsupplement Name | ingredients"
                )
                return

            context.user_data["pending_supplement"] = {
                "name": name,
                "ingredients": ingredients,
                "notes": notes or f"Source: {url}",
                "effects": effects,
                "raw": url,
            }
            context.user_data.pop("pending_url", None)
            keyboard = [
                [InlineKeyboardButton("💊 Save supplement", callback_data="confirm_add_supplement")],
                [InlineKeyboardButton("🛒 Purchase reminder", callback_data="confirm_supp_purchase")],
                [InlineKeyboardButton("❌ Cancel", callback_data="confirm_supp_cancel")],
            ]
            await query.edit_message_text(
                self._format_supplement_candidate_message(name, ingredients, notes, effects)
                + "\n\nSave this to your supplement list?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        elif data == 'url_add_reminder':
            # Create purchase reminder
            url = context.user_data.get("pending_url")
            if not url:
                await query.edit_message_text("Session expired. Please send the link again.")
                return

            await query.edit_message_text("🔍 Fetching product details...")
            name, ingredients, notes, product_type, effects = self._supplement_from_text_or_url(url)

            if not name:
                url_id = re.search(r'/([A-Z0-9]{10})', url)
                name = f"Amazon Product ({url_id.group(1) if url_id else 'Unknown'})"

            self.db.create_reminder(
                description=f"Purchase: {name}",
                reminder_type="purchase",
                url=url
            )

            context.user_data.pop("pending_url", None)
            await query.edit_message_text(f"🛒 *Purchase reminder created:*\n\n{name}\n\nUse /reminders to view.", parse_mode='Markdown')

        elif data == 'url_cancel':
            context.user_data.pop("pending_url", None)
            await query.edit_message_text("Cancelled. Send me a command when you're ready!")

        elif data.startswith('delete_health_'):
            log_id = int(data.split('_')[-1])
            # Use smart delete that also removes predicted energy
            result = self.db.delete_health_log_with_energy(log_id)
            if result:
                supp_str = ', '.join(result.supplements) if result.supplements else "Empty"
                energy_count = getattr(result, '_deleted_energy_count', 0)
                msg = f"🗑 Deleted supplement log: {supp_str}"
                if energy_count > 0:
                    msg += f"\n\n✅ Also removed {energy_count} auto-generated energy prediction(s)"
                await query.edit_message_text(msg)
            else:
                await query.edit_message_text("Log not found.")

        elif data.startswith('delete_energy_'):
            log_id = int(data.split('_')[-1])
            session = self.db.get_session()
            try:
                from database import EnergyLevel
                log = session.query(EnergyLevel).filter(EnergyLevel.id == log_id).first()
                if log:
                    level = log.level
                    session.delete(log)
                    session.commit()
                    await query.edit_message_text(f"🗑 Deleted energy log: Level {level}/10")
                else:
                    await query.edit_message_text("Log not found.")
            finally:
                session.close()

        # NEW: Style selection handlers
        elif data.startswith('setstyle_'):
            style = data.split('_')[1]
            user_id = update.effective_user.id
            self.set_preference(user_id, 'response_style', style)

            style_descriptions = {
                'brief': '🤖 Brief - Short and direct',
                'friendly': '😊 Friendly - Warm and conversational',
                'analytical': '📊 Analytical - Data-focused'
            }

            await query.edit_message_text(
                f"Response style updated!\n\n{style_descriptions.get(style, style)}"
            )

        # NEW: Clarification response handlers
        elif data.startswith('clarify_task_'):
            task_id = int(data.split('_')[-1])
            task = self.db.update_task_status(task_id, TaskStatus.COMPLETED)
            if task:
                export_completed_task(task, source="telegram_button")
            await query.edit_message_text(f"✅ Marked as complete: {task.description if task else 'Task'}")

        elif data == 'clarify_type':
            await query.edit_message_text("Go ahead and type what you meant:")

        elif data == 'milestone_add':
            context.user_data["expecting"] = "milestone_add"
            await query.edit_message_text("Send the milestone with hours, e.g. Drafted APL 6 hours")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle natural language messages"""
        message_text = update.message.text
        user_id = update.message.from_user.id

        logger.info(f"Received message from {user_id}: {message_text}")

        board_over_no = self._parse_board_over_message(message_text)
        if board_over_no is not None:
            entry = self.db.mark_board_entry_over(self._today_board_date(), serial_no=board_over_no)
            if entry:
                await update.message.reply_text(f"Marked No. {board_over_no} over.\n\n{self._format_board(self.db.get_court_board(self._today_board_date()))}", parse_mode="Markdown")
            else:
                await update.message.reply_text(f"I could not find No. {board_over_no} on today's board.")
            return

        if re.search(r"\b(show|send|display)\b.*\b(today'?s)?\s*board\b|\btoday'?s\s+board\b", message_text, re.IGNORECASE):
            await update.message.reply_text(self._format_board(self.db.get_court_board(self._today_board_date())), parse_mode="Markdown")
            return

        if self._is_save_for_later(message_text):
            saved = self.db.create_saved_item(
                item_type="text",
                content=self._clean_saved_text(message_text),
                tags=["stuff_for_later"],
            )
            await update.message.reply_text(f"Saved for later #{saved.id}.")
            return

        expense = self._parse_expense_from_message(message_text)
        if expense:
            logged = self.db.create_expense(**expense)
            await update.message.reply_text(f"Expense logged: Rs {logged.amount:g} for {logged.description}")
            return

        urls = self._extract_urls(message_text)
        if urls and await self._handle_url_message(update, context, message_text, urls):
            return

        # Check for questions first - these should be answered directly
        if self._is_question(message_text):
            answer = await self._handle_question(message_text)
            # Always return a response for questions, even if it's a generic one
            if not answer:
                answer = "I'm not sure what you're asking about. Try asking about:\n• Tasks: \"what are the tasks left?\"\n• Food: \"what did I eat today?\"\n• Energy: \"how's my energy?\""
            await update.message.reply_text(answer, parse_mode='Markdown')
            return

        if self._is_greeting_or_noise(message_text):
            await update.message.reply_text(
                "Operator is ready. Send /operator_on, then send completed tasks like: completed affidavit of service +"
            )
            return

        if re.search(r"\bwhat\s+did\s+i\s+(?:eat|have|drink)\s+today\b", message_text, re.IGNORECASE):
            await update.message.reply_text(self._format_food_today())
            return

        if re.fullmatch(r"\s*(?:consume|take|took|log|logged|had)\s+(?:my\s+)?supplements?\s*", message_text, re.IGNORECASE):
            await update.message.reply_text(
                "Use /supplements so I can record exactly which supplements and how many servings you took."
            )
            return
        
        # Check if we're expecting specific input
        expecting = context.user_data.get('expecting')
        
        if expecting:
            if expecting.startswith('food_'):
                meal_type = expecting.split('_')[1]
                context.user_data.pop('expecting')
                food_entry = self._parse_explicit_calorie_food(message_text, meal_type=meal_type)
                if not food_entry:
                    food_entry = self._parse_food_from_message(f"I ate {message_text}")
                    if food_entry:
                        food_entry["energy_prediction"] = {
                            **(food_entry.get("energy_prediction") or {}),
                            "health_note": f"Logged as {meal_type}. " + ((food_entry.get("energy_prediction") or {}).get("health_note") or ""),
                        }
                if food_entry:
                    response = await self.process_parsed_data(food_entry)
                    await update.message.reply_text(response)
                    return

                await update.message.reply_text("I could not log that as food. Try: 2 burgers - 724 kcal, fries - 332 kcal")
                return
            elif expecting == 'task_new':
                # Directly create a pending task, don't go through LLM parser
                context.user_data.pop('expecting')
                description = message_text.strip()
                if not description:
                    await update.message.reply_text("Task description cannot be empty. Try again with /task")
                    return

                task, created = self._create_pending_task(description)
                if created:
                    await update.message.reply_text(f"✅ Task created: {task.description}")
                else:
                    await update.message.reply_text(f"⚠️ Task already exists: {task.description}")
                return
            elif expecting == 'milestone_add':
                context.user_data.pop('expecting')
                parsed = self._parse_milestone_text(message_text)
                if not parsed:
                    await update.message.reply_text("I could not read that milestone. Try: Drafted APL 6 hours")
                    return
                milestone = self.db.create_milestone(**parsed)
                hours = f" ({milestone.hours:g}h)" if milestone.hours else ""
                await update.message.reply_text(f"Milestone added: {milestone.title}{hours}")
                return
            elif expecting == 'board_add':
                context.user_data.pop('expecting')
                board_date, entries = self._parse_court_board_entries(message_text)
                if not entries:
                    await update.message.reply_text("I could not parse the board. Paste lines starting with Court No. ...")
                    return
                saved_entries = self.db.replace_court_board(board_date, entries)
                await update.message.reply_text(f"Saved board for {board_date}: {len(saved_entries)} matters.")
                return
            elif expecting == 'supplement_add':
                name, ingredients, notes, product_type, effects = await self._resolve_supplement_candidate(message_text)
                context.user_data.pop('expecting')

                if not name:
                    await update.message.reply_text("I could not identify that supplement. Send: Name | ingredients")
                    return

                # Handle product classification
                if product_type == "non_edible":
                    reminder = self.db.create_reminder(
                        description=f"Purchase: {name}",
                        reminder_type="purchase",
                        url=next((x for x in message_text.split() if "http" in x), None)
                    )
                    await update.message.reply_text(f"🛍️ Created purchase reminder: {name}", parse_mode='Markdown')
                    return

                if "http" in message_text.lower():
                    context.user_data["pending_supplement"] = {
                        "name": name,
                        "ingredients": ingredients,
                        "notes": notes,
                        "effects": effects,
                        "raw": message_text,
                    }
                    keyboard = [
                        [InlineKeyboardButton("💊 Save supplement", callback_data="confirm_add_supplement")],
                        [InlineKeyboardButton("🛒 Purchase reminder", callback_data="confirm_supp_purchase")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="confirm_supp_cancel")],
                    ]
                    await update.message.reply_text(
                        self._format_supplement_candidate_message(name, ingredients, notes, effects)
                        + "\n\nSave this to your supplement list?",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                    return

                confirm_msg = f"✅ *Added: {name}*"
                if ingredients:
                    confirm_msg += f"\n📋 {ingredients[:200]}{'...' if len(ingredients) > 200 else ''}"
                if notes:
                    confirm_msg += f"\nℹ️ {notes[:300]}{'...' if len(notes) > 300 else ''}"
                if effects and effects.get("recommendation"):
                    confirm_msg += f"\n\n⏰ *Timing Analysis:*"
                    for rec in effects["recommendation"][:3]:
                        confirm_msg += f"\n• {rec}"

                supplement = self.db.create_supplement(name=name, ingredients=ingredients, notes=notes)
                await update.message.reply_text(confirm_msg, parse_mode='Markdown')
                return

            elif expecting.startswith('remind_add_'):
                reminder_type = expecting.split('_')[-1]
                context.user_data.pop('expecting')

                remind_at = self._parse_time_hint(message_text)
                reminder = self.db.create_reminder(
                    description=message_text,
                    reminder_type=reminder_type,
                    remind_at=remind_at.isoformat() if remind_at else None
                )

                msg = f"📋 *Reminder created:*\n{reminder.description}"
                if remind_at:
                    msg += f"\n⏰ Will remind at {remind_at.strftime('%-I:%M %p')}"

                await update.message.reply_text(msg, parse_mode='Markdown')
                return

        operator_data = self._parse_operator_task(message_text)
        if operator_data:
            response = await self.process_parsed_data(operator_data)
            await update.message.reply_text(response)
            return

        batch_entries = self._parse_batch_tasks(message_text)
        if batch_entries:
            completed_count = 0
            pending_count = 0
            export_path = None
            for entry in batch_entries:
                response = await self.process_parsed_data(entry)
                if entry["type"] == "task_complete":
                    completed_count += 1
                    match = re.search(r"Saved offline: (.+)$", response, re.MULTILINE)
                    if match:
                        export_path = match.group(1)
                elif entry["type"] == "task_pending":
                    pending_count += 1
            parts = []
            if completed_count:
                parts.append(f"Logged {completed_count} completed tasks.")
            if pending_count:
                parts.append(f"Logged {pending_count} pending tasks.")
            if export_path:
                parts.append(f"Saved offline: {export_path}")
            await update.message.reply_text("\n".join(parts))
            return

        correction = self._parse_completion_time_correction(message_text)
        if correction:
            count, export_path = self._apply_recent_completion_time_correction(correction["timestamp"])
            if count:
                response = f"Corrected {count} recent completed tasks to {correction['timestamp']}."
                if export_path:
                    response += f"\nRebuilt offline sheet: {export_path}"
            else:
                response = "I understood the correction, but I could not find recent completed tasks to update."
            await update.message.reply_text(response)
            return

        multi_entries = self._parse_multi_intent_message(message_text)
        actionable_entries = [entry for entry in multi_entries if entry.get("type") != "supplement_negative"]
        if actionable_entries:
            responses = []
            for entry in actionable_entries:
                responses.append(await self.process_parsed_data(entry))
            if any(entry.get("type") == "supplement_negative" for entry in multi_entries):
                responses.append("Supplements not logged because your message says you did not take them.")
            await update.message.reply_text("\n\n".join(responses))
            return
        
        # Send to LLM for parsing (use enhanced parsing with context)
        try:
            await update.message.reply_text("🤔 Processing...")

            user_id = update.message.from_user.id

            # NEW: Try enhanced parsing first with conversation memory and context
            enhanced_result = await self.parse_message_with_context(message_text, user_id)

            if enhanced_result:
                # Handle the enhanced result
                intent = enhanced_result.get('intent')
                needs_clarification = enhanced_result.get('needs_clarification', False)
                action = enhanced_result.get('action', {})
                response_text = enhanced_result.get('response', '')

                # If clarification needed, ask with options
                if needs_clarification:
                    clarification_question = enhanced_result.get('clarification_question', 'What did you mean?')

                    # Get pending tasks for context
                    pending = self.db.get_tasks(status='pending', limit=5)

                    if pending:
                        keyboard = []
                        for task in pending[:4]:
                            keyboard.append([
                                InlineKeyboardButton(task.description[:40], callback_data=f'clarify_task_{task.id}')
                            ])
                        keyboard.append([InlineKeyboardButton("✍️ Something else", callback_data='clarify_type')])
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await update.message.reply_text(clarification_question, reply_markup=reply_markup)
                    else:
                        await update.message.reply_text(clarification_question)
                    return

                # Execute the action
                action_type = action.get('type')

                if action_type == 'store':
                    data = action.get('data', {})
                    # Store data based on intent
                    if intent == 'log_task':
                        description = data.get('description', '')
                        if description:
                            task = self.db.create_task(description=description, category=self._task_category_from_text(description))
                            response_text = f"Logged: {description}"
                    elif intent == 'log_energy':
                        level = data.get('level')
                        context_note = data.get('context', '')
                        if level:
                            self.db.log_energy(level=int(level), context=context_note)
                    elif intent == 'log_food':
                        items = data.get('items', [])
                        if items:
                            self.db.log_food(items=items)

                # Send the response
                if response_text:
                    await update.message.reply_text(response_text)
                return

            # Fallback to original parsing
            parsed_data = await self.llm_parser.parse_message(message_text)
            
            if not parsed_data:
                await update.message.reply_text(
                    "Sorry, I couldn't understand that. Could you rephrase?"
                )
                return
            
            parsed_entries = self._coerce_parsed_entries(parsed_data)
            responses = []
            for entry in parsed_entries:
                responses.append(await self.process_parsed_data(entry))
            
            await update.message.reply_text("\n\n".join(responses))
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await update.message.reply_text(
                "Oops! Something went wrong. Please try again."
            )
    
    async def process_parsed_data(self, data: dict) -> str:
        """Process parsed data and store in database"""
        data_type = data.get('type')
        
        if data_type == 'task_complete':
            # Mark task as complete
            description = data.get('description')
            if not self._clean_task_description(description):
                return "Ignored empty completed task."
            task, created, export_path = self._complete_or_create_task(
                description,
                source=data.get('source', 'telegram'),
                completed_at=data.get('timestamp'),
            )
            if not task:
                return "Ignored empty completed task."
            action = "Created and completed" if created else "Marked completed"
            response = f"{action}: {task.description}"
            if export_path:
                response += f"\nSaved offline: {export_path}"
            return response
        
        elif data_type == 'task_pending':
            description = data.get('description')
            if not self._clean_task_description(description):
                return "Ignored empty pending task."
            deadline = data.get('deadline')
            priority = data.get('priority', 'medium')
            focus_required = data.get('focus_required', False)
            
            task, created = self._create_pending_task(
                description=description,
                deadline=deadline,
                priority=priority,
                focus_required=focus_required
            )
            if not task:
                return "Ignored empty pending task."
            
            # Get optimal time suggestion based on energy patterns
            suggestion = ""
            if focus_required:
                best_time = self.db.get_peak_energy_time()
                if best_time:
                    suggestion = f"\n\n💡 *Tip:* You're usually most energized around {best_time}. Consider scheduling this task then."
            
            action = "Task created" if created else "Task already exists"
            return f"{action}: {task.description}{suggestion}"
        
        elif data_type == 'food_log':
            items = data.get('items', [])
            items = [item for item in items if str(item).strip()]
            if not items:
                return "Ignored empty food log."
            timestamp = data.get('timestamp')
            macros = data.get('macros', {})
            energy_prediction = data.get('energy_prediction', {})

            parsed_items = data.get("parsed_items")
            if not parsed_items:
                parsed_items = [{"item": item, "quantity": 1} for item in items]

            if (
                data.get("source") != "explicit_calorie_food_parser"
                and
                os.getenv("GEMINI_API_KEY")
                and os.getenv("NUTRITION_PROVIDER", "local").lower() in {"gemini", "auto"}
            ):
                estimates = [
                    await estimate_food_smart(entry["item"], quantity=entry.get("quantity", 1))
                    for entry in parsed_items
                ]
                macros = merge_macros(estimates)
                energy_prediction = {
                    **energy_prediction,
                    "calories": macros.get("calories"),
                    "nutrition": estimates,
                    "health_note": " ".join(
                        estimate.get("health_note", "")
                        for estimate in estimates
                        if estimate.get("health_note")
                    ),
                }

            energy_prediction = {
                **energy_prediction,
                "calories": macros.get("calories"),
                "nutrition": estimates,
                "health_note": " ".join(
                    estimate.get("health_note", "")
                    for estimate in estimates
                    if estimate.get("health_note")
                ),
                # Ensure all required fields are populated
                "energy_impact": energy_prediction.get("energy_impact") or self._calculate_energy_impact(macros or {}),
                "health_score": energy_prediction.get("health_score") or self._calculate_health_score(macros or {}),
                "energy_timeline": energy_prediction.get("energy_timeline") or self._get_energy_timeline(macros or {}),
                "analysis": self._food_analysis(items, macros or {}, energy_prediction or {}),
            }
            
            self.db.log_food(
                items=items,
                timestamp=timestamp,
                macros=macros,
                energy_prediction=energy_prediction
            )
            
            # Schedule energy prediction if crash expected
            response = f"Food logged: {', '.join(items)}\n"
            
            if macros:
                response += f"Macros: Carbs {macros.get('carbs', 'N/A')}, Protein {macros.get('protein', 'N/A')}, Fat {macros.get('fat', 'N/A')}"
                if macros.get('calories'):
                    response += f"\nEstimated calories: {macros.get('calories')}"
            
            if energy_prediction.get('status') == 'crash_warning':
                crash_time = energy_prediction.get('time_of_crash')
                message = energy_prediction.get('message')
                response += f"\nEnergy alert: {message}"
                if energy_prediction.get('health_note'):
                    response += f"\nHealth note: {energy_prediction.get('health_note')}"
                
                # Log predicted energy dip
                self.db.log_energy(
                    level=4,  # Predicted low level
                    timestamp=crash_time,
                    predicted=True,
                    context="Predicted from food intake"
                )
            
            return response
        
        elif data_type == 'health_metric':
            supplements = data.get('supplements', [])
            metrics = data.get('metrics', {})
            timestamp = data.get('timestamp')
            
            self.db.log_health(
                supplements=supplements,
                metrics=metrics,
                timestamp=timestamp
            )
            
            parts = []
            if supplements:
                doses = metrics.get("supplement_doses") or {}
                if doses:
                    dose_parts = []
                    for supplement in supplements:
                        dose = doses.get(supplement) or {}
                        dose_parts.append(
                            f"{dose.get('quantity', 1)} {dose.get('unit', 'serving')} {supplement}"
                        )
                    parts.append(f"Supplements logged: {', '.join(dose_parts)}")
                else:
                    parts.append(f"Supplements logged: {', '.join(supplements)}")
            if metrics.get("steps"):
                parts.append(f"Steps logged: {metrics['steps']}")
            return "\n".join(parts) if parts else "Health entry logged."
        
        elif data_type == 'energy_level':
            level = data.get('level')
            context_note = data.get('context', '')
            
            self.db.log_energy(level=level, context=context_note, predicted=False)
            
            return f"Energy logged: {level}/10"
        
        elif data_type == 'court_board':
            # Court board was already saved in _parse_multi_intent_message
            return data.get('response', f"✅ Court board saved for {data.get('board_date')}")
        
        else:
            return "I understood your message but couldn't categorize it. Could you be more specific?"

    def _coerce_parsed_entries(self, parsed_data):
        if isinstance(parsed_data, list):
            return [entry for entry in parsed_data if isinstance(entry, dict)]
        if isinstance(parsed_data, dict):
            if isinstance(parsed_data.get("entries"), list):
                return [entry for entry in parsed_data["entries"] if isinstance(entry, dict)]
            return [parsed_data]
        return []

    # ===== ANALYSIS COACH COMMANDS =====

    def __init_analysis_coach(self):
        """Initialize the analysis coach with scheduler"""
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.llm_model = os.getenv('LLM_MODEL', 'llama3.1:8b')
        self.analysis_scheduler = AsyncIOScheduler()
        self._start_analysis_scheduler()

    def _check_ollama_connectivity(self):
        """Check if Ollama is accessible on startup"""
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        try:
            import httpx
            response = httpx.get(f"{ollama_url}/api/tags", timeout=3.0)
            if response.status_code == 200:
                logger.info(f"✅ Ollama is running at {ollama_url}")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Ollama not available at {ollama_url}: {e}")
            logger.warning("LLM parsing features will be disabled. Start Ollama with: ollama serve")
        return False

    def _start_analysis_scheduler(self):
        """Start the background analysis scheduler"""
        if not hasattr(self, 'analysis_scheduler'):
            self.analysis_scheduler = AsyncIOScheduler()

        # Schedule hourly analysis
        self.analysis_scheduler.add_job(
            self._hourly_analysis_task,
            'cron',
            minute=0,
            id='hourly_analysis',
            replace_existing=True
        )
        # Also at :30
        self.analysis_scheduler.add_job(
            self._hourly_analysis_task,
            'cron',
            minute=30,
            id='half_hourly_analysis',
            replace_existing=True
        )

        if not self.analysis_scheduler.running:
            self.analysis_scheduler.start()
            logger.info("✅ Analysis Coach scheduler started")

    async def _hourly_analysis_task(self):
        """Background task for hourly analysis"""
        try:
            logger.info("🔍 Running hourly analysis...")
            now = datetime.now()
            one_hour_ago = now - timedelta(hours=1)

            # Analyze food logs from past hour
            food_logs = self.db.get_food_logs(start_date=one_hour_ago)
            for food_log in food_logs:
                await self._deep_analyze_food(food_log)

            # Analyze tasks from past hour
            session = self.db.get_session()
            try:
                tasks = session.query(Task).filter(
                    Task.created_at >= one_hour_ago
                ).all()
                for task in tasks:
                    await self._analyze_task_context(task)
            finally:
                session.close()

            logger.info("✅ Hourly analysis complete")
        except Exception as e:
            logger.error(f"Error in hourly analysis: {e}")

    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Run full analysis on demand"""
        await update.message.reply_text("🔍 *Running deep analysis...* This may take a moment.", parse_mode='Markdown')

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        results = []

        # Analyze recent food
        food_logs = self.db.get_food_logs(start_date=one_hour_ago)
        if food_logs:
            results.append(f"🍽️ *Food Analysis ({len(food_logs)} logs)*")
            for food_log in food_logs:
                analysis = await self._deep_analyze_food(food_log)
                if analysis:
                    results.append(f"  • {analysis}")

        # Analyze recent tasks
        session = self.db.get_session()
        try:
            tasks = session.query(Task).filter(
                Task.created_at >= one_hour_ago
            ).limit(5).all()

            if tasks:
                results.append(f"\n📋 *Task Analysis ({len(tasks)} tasks)*")
                for task in tasks:
                    analysis = await self._analyze_task_context(task, return_result=True)
                    if analysis:
                        results.append(f"  • {analysis}")
        finally:
            session.close()

        # Hour performance
        hour_analysis = await self._analyze_hour_performance(one_hour_ago, now)
        if hour_analysis:
            results.append(f"\n📈 *Hour Performance*")
            results.append(f"  {hour_analysis}")

        if results:
            await update.message.reply_text("\n".join(results), parse_mode='Markdown')
        else:
            await update.message.reply_text("No recent data to analyze. Log some food or tasks first!")

    async def analyze_food_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Deep analyze recent food logs"""
        await update.message.reply_text("🍽️ Analyzing your recent food...")

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        food_logs = self.db.get_food_logs(start_date=today_start)
        if not food_logs:
            await update.message.reply_text("No food logged today.")
            return

        results = [f"*🍽️ Food Analysis - {len(food_logs)} logs*\n"]

        for food_log in food_logs[-5:]:  # Last 5 logs
            time = food_log.timestamp.strftime("%-I:%M %p") if food_log.timestamp else "??"
            items = ', '.join(food_log.items or [])

            analysis = await self._deep_analyze_food(food_log)
            if analysis:
                results.append(f"• *{time}: {items}*\n  {analysis}")
            else:
                results.append(f"• {time}: {items}")

        await update.message.reply_text("\n".join(results), parse_mode='Markdown')

    async def analyze_hour_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Analyze the past hour's performance"""
        await update.message.reply_text("📈 Analyzing the past hour...")

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        analysis = await self._analyze_hour_performance(one_hour_ago, now)

        if analysis:
            await update.message.reply_text(
                f"📈 *Hour Analysis: {one_hour_ago.strftime('%-I:%M')} - {now.strftime('%-I:%M')}*\n\n{analysis}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("Not enough data from the past hour to analyze.")

    async def _set_bot_commands(self, app: Application):
        """Keep Telegram's command menu aligned with /help."""
        commands = [
            BotCommand("help", "Show all Life OS commands"),
            BotCommand("task", "Create, complete, remove, or uncomplete tasks"),
            BotCommand("newtask", "Add a task directly"),
            BotCommand("delete_task", "Remove a task"),
            BotCommand("eatery", "Log food by meal type"),
            BotCommand("food", "Food history with quick re-log"),
            BotCommand("foodtoday", "Show today's food with delete buttons"),
            BotCommand("delete_food", "Delete today's food entries"),
            BotCommand("energy", "Log energy level"),
            BotCommand("milestones", "Add or view milestones"),
            BotCommand("board", "Show or add today's High Court board"),
            BotCommand("saved", "View stuff for later"),
            BotCommand("expenses", "Log or view daily expenses"),
            BotCommand("supplements", "Log morning supplement stack"),
            BotCommand("addsupplement", "Add a supplement or product link"),
            BotCommand("removesupplement", "Remove a saved supplement"),
            BotCommand("delete_recent", "Delete recent supplement or energy logs"),
            BotCommand("remind", "Create a reminder"),
            BotCommand("reminders", "View, complete, or delete reminders"),
            BotCommand("summary", "Show today's summary"),
            BotCommand("stats", "Show weekly statistics"),
            BotCommand("rollover", "Move unfinished old tasks to today"),
            BotCommand("analyze", "Run full recent analysis"),
            BotCommand("style", "Change response style"),
            BotCommand("mood", "Show mood trends"),
            BotCommand("operator", "Enable quick completion mode"),
        ]
        await app.bot.set_my_commands(commands)

    async def _deep_analyze_food(self, food_log) -> str:
        """Deep analyze a food log, returns summary text"""
        try:
            if not food_log.items:
                return None

            # Calculate/enrich nutrition
            enriched_data = {}
            for food_item in food_log.items:
                nutrition_info = await self._search_nutrition(food_item)
                enriched_data[food_item] = nutrition_info

            total_calories = sum(item.get('calories', 0) for item in enriched_data.values())
            total_protein = sum(item.get('protein_g', 0) for item in enriched_data.values())
            total_carbs = sum(item.get('carbs_g', 0) for item in enriched_data.values())
            total_fat = sum(item.get('fat_g', 0) for item in enriched_data.values())

            # Energy prediction
            energy_analysis = await self._analyze_energy_impact(
                food_log.timestamp if food_log.timestamp else datetime.now(),
                total_calories, total_carbs, total_protein, total_fat
            )

            # Update the food log
            session = self.db.get_session()
            try:
                from database import FoodLog
                db_food_log = session.query(FoodLog).filter(FoodLog.id == food_log.id).first()
                if db_food_log:
                    db_food_log.macros = {
                        'calories': total_calories,
                        'protein_g': total_protein,
                        'carbs_g': total_carbs,
                        'fat_g': total_fat,
                        'detailed_breakdown': enriched_data
                    }
                    db_food_log.energy_prediction = energy_analysis
                    session.commit()
            finally:
                session.close()

            # Return summary
            msg = f"{total_calories} cal | {total_protein}g protein | {total_carbs}g carbs"
            if energy_analysis and energy_analysis.get('message'):
                msg += f"\n  ⚡ {energy_analysis['message']}"
            return msg

        except Exception as e:
            logger.error(f"Error analyzing food: {e}")
            return None

    async def _search_nutrition(self, food_item: str) -> dict:
        """Search for nutritional information"""
        try:
            search_query = f"{food_item} nutrition facts calories protein carbs"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"https://api.duckduckgo.com/?q={search_query}&format=json"
                )
                if response.status_code == 200:
                    data = response.json()
                    abstract = data.get('Abstract', '')
                    nutrition = await self._extract_nutrition_from_text(food_item, abstract)
                    return nutrition
        except Exception as e:
            logger.error(f"Error searching nutrition: {e}")

        return await self._estimate_nutrition_llm(food_item)

    async def _extract_nutrition_from_text(self, food_item: str, text: str) -> dict:
        """Extract nutrition from search results using LLM"""
        prompt = f"""Extract nutritional information for: {food_item}

Search result: {text[:500]}

Return JSON only:
{{
  "food": "{food_item}",
  "calories": 0,
  "protein_g": 0,
  "carbs_g": 0,
  "fat_g": 0,
  "health_notes": "brief note"
}}"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.llm_model, "prompt": prompt, "format": "json", "stream": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    return json.loads(result.get('response', '{}'))
        except Exception as e:
            logger.error(f"Error extracting nutrition: {e}")

        return {"food": food_item, "calories": 100, "protein_g": 3, "carbs_g": 20, "fat_g": 2}

    async def _estimate_nutrition_llm(self, food_item: str) -> dict:
        """Estimate nutrition using LLM knowledge"""
        prompt = f"""Estimate nutrition for: {food_item}

Return JSON only:
{{
  "food": "{food_item}",
  "calories": 0,
  "protein_g": 0,
  "carbs_g": 0,
  "fat_g": 0,
  "health_notes": "brief note"
}}"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.llm_model, "prompt": prompt, "format": "json", "stream": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    return json.loads(result.get('response', '{}'))
        except Exception as e:
            logger.error(f"Error estimating nutrition: {e}")

        return {"food": food_item, "calories": 100, "protein_g": 3, "carbs_g": 20, "fat_g": 2}

    async def _analyze_energy_impact(self, eat_time, calories, carbs, protein, fat) -> dict:
        """Predict energy impact"""
        prompt = f"""Analyze energy impact:
Time: {eat_time.strftime('%I:%M %p')}
Calories: {calories}, Carbs: {carbs}g, Protein: {protein}g, Fat: {fat}g

Return JSON only:
{{
  "immediate_effect": "boost/stable/sluggish",
  "crash_expected": true/false,
  "crash_time_minutes": 0,
  "recommendation": "brief advice"
}}"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.llm_model, "prompt": prompt, "format": "json", "stream": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    analysis = json.loads(result.get('response', '{}'))
                    return {
                        "status": "crash_warning" if analysis.get('crash_expected') else "stable",
                        "message": analysis.get('recommendation', 'Meal logged')
                    }
        except Exception as e:
            logger.error(f"Error analyzing energy: {e}")

        return {"status": "analyzed", "message": f"Logged: {calories} cal"}

    async def _analyze_task_context(self, task, return_result=False) -> str:
        """Analyze task in context"""
        prompt = f"""Analyze this task:
Task: {task.description}
Time: {task.created_at.strftime('%I:%M %p')}
Status: {task.status}

Return JSON only:
{{
  "productivity_score": 0-10,
  "timing_analysis": "good/suboptimal",
  "suggestions": ["tip1"]
}}"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.llm_model, "prompt": prompt, "format": "json", "stream": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    analysis = json.loads(result.get('response', '{}'))

                    self.db.log_system_event(
                        event_type='task_analysis',
                        data={'task_id': task.id, 'analysis': analysis},
                        triggered_by='analysis_coach'
                    )

                    if return_result:
                        return f"Score: {analysis.get('productivity_score', 'N/A')}/10 - {analysis.get('timing_analysis', 'analyzed')}"
        except Exception as e:
            logger.error(f"Error analyzing task: {e}")

        return None

    async def _analyze_hour_performance(self, start_time, end_time) -> str:
        """Analyze hour performance"""
        summary = self.db.get_daily_summary(start_time.date())

        prompt = f"""Analyze this hour: {start_time.strftime('%I:%M')} - {end_time.strftime('%I:%M')}

Data: {json.dumps(summary, indent=2)[:1000]}

Return JSON only:
{{
  "hour_rating": 0-10,
  "highlights": ["win1"],
  "concerns": ["issue1"],
  "next_hour_advice": "brief advice"
}}"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.llm_model, "prompt": prompt, "format": "json", "stream": False}
                )
                if response.status_code == 200:
                    result = response.json()
                    analysis = json.loads(result.get('response', '{}'))

                    self.db.log_system_event(
                        event_type='hourly_performance',
                        data={'time_period': f"{start_time.isoformat()} to {end_time.isoformat()}", 'analysis': analysis},
                        triggered_by='analysis_coach'
                    )

                    rating = analysis.get('hour_rating', 'N/A')
                    advice = analysis.get('next_hour_advice', 'Keep going!')
                    return f"Rating: {rating}/10\n💡 {advice}"
        except Exception as e:
            logger.error(f"Error analyzing hour: {e}")

        return "Analysis complete. Keep tracking!"

    # ===== END ANALYSIS COACH =====

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def run(self):
        """Start the bot"""
        logger.info("Starting Life OS Bot...")
        
        # Create application
        self.app = Application.builder().token(self.token).post_init(self._set_bot_commands).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        # NEW: Smart feature commands
        self.app.add_handler(CommandHandler("style", self.style_command))
        self.app.add_handler(CommandHandler("mood", self.mood_command))
        self.app.add_handler(CommandHandler("entities", self.entities_command))
        self.app.add_handler(CommandHandler("memory", self.memory_command))
        self.app.add_handler(CommandHandler(["operator_on", "operator"], self.operator_on_command))
        self.app.add_handler(CommandHandler("eatery", self.eatery_command))
        self.app.add_handler(CommandHandler("task", self.task_command))
        self.app.add_handler(CommandHandler(["newtask", "addtask"], self.new_task_command))
        self.app.add_handler(CommandHandler("energy", self.energy_command))
        self.app.add_handler(CommandHandler(["milestones", "milestone"], self.milestones_command))
        self.app.add_handler(CommandHandler(["board", "courtboard"], self.board_command))
        self.app.add_handler(CommandHandler(["saved", "later"], self.saved_command))
        self.app.add_handler(CommandHandler(["expenses", "expense"], self.expenses_command))
        self.app.add_handler(CommandHandler("summary", self.summary_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("supplements", self.supplements_command))
        self.app.add_handler(CommandHandler(["addsupplement", "add_supplement"], self.add_supplement_command))
        self.app.add_handler(CommandHandler(["removesupplement", "remove_supplement"], self.remove_supplement_command))
        self.app.add_handler(CommandHandler(["clean_supplements", "cleansupplements"], self.clean_supplements_command))
        self.app.add_handler(CommandHandler(["delete_task", "deletetask"], self.delete_task_command))
        self.app.add_handler(CommandHandler(["delete_food", "deletefood"], self.delete_food_command))
        self.app.add_handler(CommandHandler("food", self.food_history_command))
        self.app.add_handler(CommandHandler(["food_today", "foodtoday"], self.food_today_command))
        self.app.add_handler(CommandHandler(["food_analysis", "foodanalysis"], self.food_analysis_command))
        self.app.add_handler(CommandHandler(["reminders", "reminder"], self.reminders_command))
        self.app.add_handler(CommandHandler(["remind", "reminder_add"], self.remind_command))
        self.app.add_handler(CommandHandler(["delete_recent", "deleterecent"], self.delete_recent_command))
        self.app.add_handler(CommandHandler("rollover", self.rollover_command))

        # Analysis Coach commands
        self.app.add_handler(CommandHandler(["analyze", "analysis"], self.analyze_command))
        self.app.add_handler(CommandHandler(["analyze_food", "analyzefood"], self.analyze_food_command))
        self.app.add_handler(CommandHandler(["analyze_hour", "analyzehour"], self.analyze_hour_command))

        # Callback query handler
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.photo_message))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.document_message))
        
        # Message handler (for natural language)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_message
        ))
        
        # Error handler
        self.app.add_error_handler(self.error_handler)
        
        # Start polling
        logger.info("Bot is running! Press Ctrl+C to stop.")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    acquire_instance_lock()
    bot = LifeOSBot()
    bot.run()

    # Helper methods for calculating nutrition fields
    
    def _calculate_energy_impact(self, macros: dict) -> str:
        """Calculate energy impact from macros."""
        carbs = macros.get("carbs", "medium")
        fat = macros.get("fat", "medium")
        protein = macros.get("protein", "low")
        
        if carbs == "high" and fat == "high":
            return "spike_then_crash"
        elif carbs == "high":
            return "spike_then_crash"
        elif protein == "high" and fat == "medium":
            return "steady_energy"
        elif carbs == "low" and protein == "high":
            return "boost"
        else:
            return "stable"
    
    def _calculate_health_score(self, macros: dict) -> int:
        """Calculate health score from macros (1-10)."""
        carbs = macros.get("carbs", "medium")
        protein = macros.get("protein", "low")
        fat = macros.get("fat", "medium")
        calories = macros.get("calories", 0)
        
        score = 5  # Base score
        
        # Protein is good
        if protein == "high":
            score += 2
        elif protein == "medium":
            score += 1
        
        # Very high carbs or fat reduces score
        if carbs == "high" and fat == "high":
            score -= 2
        elif carbs == "high":
            score -= 1
        
        # Very high calories reduce score
        if calories > 800:
            score -= 1
        
        return max(1, min(10, score))
    
    def _get_energy_timeline(self, macros: dict) -> str:
        """Get energy timeline description."""
        impact = self._calculate_energy_impact(macros)
        if impact == "spike_then_crash":
            return "Energy boost for 30-60 min, then possible crash"
        elif impact == "steady_energy":
            return "Steady energy for 2-3 hours"
        elif impact == "boost":
            return "Sustained energy boost without crash"
        else:
            return "Stable energy levels expected"
