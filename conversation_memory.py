#!/usr/bin/env python3
"""
Conversation Memory Module for Life OS
Enables multi-turn context and follow-up conversations
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from sqlalchemy import desc, func

from database import (
    Base,
    Database,
    ConversationMessage,
    ConversationEntity,
    ConversationMood,
    UserPreference,
    ScheduledInsight,
    ProactiveReminder,
)

logger = logging.getLogger(__name__)


class ConversationMemory:
    """
    Manages conversation history and context for each user.
    Enables multi-turn conversations where the bot remembers what was said.
    """

    # Max messages to keep in memory per user
    MAX_HISTORY = 20
    # History TTL in days
    HISTORY_TTL = 7

    def __init__(self, db: Database):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self):
        """Create conversation tables if they don't exist"""
        from sqlalchemy import inspect
        inspector = inspect(self.db.engine)
        existing_tables = inspector.get_table_names()

        if 'conversation_messages' not in existing_tables:
            ConversationMessage.__table__.create(self.db.engine, checkfirst=True)
        if 'conversation_entities' not in existing_tables:
            ConversationEntity.__table__.create(self.db.engine, checkfirst=True)
        if 'conversation_mood' not in existing_tables:
            ConversationMood.__table__.create(self.db.engine, checkfirst=True)
        if 'user_preferences' not in existing_tables:
            UserPreference.__table__.create(self.db.engine, checkfirst=True)
        if 'scheduled_insights' not in existing_tables:
            ScheduledInsight.__table__.create(self.db.engine, checkfirst=True)
        if 'proactive_reminders' not in existing_tables:
            ProactiveReminder.__table__.create(self.db.engine, checkfirst=True)

    def add_message(self, user_id: int, role: str, content: str, metadata: dict = None):
        """Add a message to conversation history"""
        session = self.db.get_session()
        try:
            # Clean old messages first
            cutoff = datetime.now() - timedelta(days=self.HISTORY_TTL)
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

            # Prune to MAX_HISTORY
            recent = session.query(ConversationMessage).filter(
                ConversationMessage.user_id == user_id
            ).order_by(desc(ConversationMessage.timestamp)).offset(self.MAX_HISTORY).all()
            for msg in recent:
                session.delete(msg)

            session.commit()
        finally:
            session.close()

    def get_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get recent conversation history for a user"""
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
        """Get formatted conversation history for LLM context"""
        history = self.get_history(user_id, limit=6)
        if not history:
            return ""

        lines = ["RECENT CONVERSATION:"]
        for msg in history:
            role_name = "User" if msg['role'] == 'user' else "Assistant"
            timestamp = msg.get('timestamp', '')
            if timestamp:
                # Show just the time
                try:
                    dt = datetime.fromisoformat(timestamp)
                    timestamp = f" [{dt.strftime('%H:%M')}]"
                except:
                    timestamp = ""
            lines.append(f"{role_name}{timestamp}: {msg['content']}")

        return "\n".join(lines)

    def store_entity(self, user_id: int, entity_type: str, name: str,
                     attributes: dict = None, source_message: str = None):
        """Store an entity (person, project, location) for future reference"""
        session = self.db.get_session()
        try:
            # Check if entity exists
            existing = session.query(ConversationEntity).filter(
                ConversationEntity.user_id == user_id,
                func.lower(ConversationEntity.name) == name.lower(),
                ConversationEntity.entity_type == entity_type
            ).first()

            if existing:
                # Update attributes and last_seen
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

    def get_entities(self, user_id: int, entity_type: str = None) -> List[Dict]:
        """Get stored entities for a user"""
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
        """Get formatted entities for LLM context"""
        entities = self.get_entities(user_id)
        if not entities:
            return ""

        # Group by type
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

    def log_mood(self, user_id: int, sentiment: float, emotion: str = None,
                 context: str = None, message: str = None):
        """Log user mood/sentiment from a message"""
        session = self.db.get_session()
        try:
            mood = ConversationMood(
                user_id=user_id,
                sentiment=sentiment,  # -1.0 to 1.0
                emotion=emotion,
                context=context,
                message=message
            )
            session.add(mood)
            session.commit()
        finally:
            session.close()

    def get_mood_summary(self, user_id: int, hours: int = 24) -> Dict:
        """Get mood summary for recent period"""
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

            # Determine trend
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

    def set_preference(self, user_id: int, key: str, value: any):
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

    def get_all_preferences(self, user_id: int) -> Dict:
        """Get all user preferences"""
        session = self.db.get_session()
        try:
            prefs = session.query(UserPreference).filter(
                UserPreference.user_id == user_id
            ).all()
            return {p.key: p.value for p in prefs}
        finally:
            session.close()


# ORM models are imported from database.py to avoid duplicate mappings.
