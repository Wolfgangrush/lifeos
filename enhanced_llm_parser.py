#!/usr/bin/env python3
"""
Enhanced LLM Parser for Life OS
Features:
- Conversation memory
- Temporal pattern recognition
- Entity extraction
- Sentiment/mood tracking
- Adaptive response styles
- Model selection optimization
- JSON schema validation
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import httpx

from conversation_memory import ConversationMemory

logger = logging.getLogger(__name__)


class EnhancedLLMParser:
    """
    Enhanced LLM parser with all smart features:
    - Multi-turn conversation memory
    - Temporal context awareness
    - Entity extraction and memory
    - Sentiment analysis
    - Adaptive response styles per user
    - Model selection for speed vs accuracy
    - Structured JSON output with schema validation
    """

    # Response styles
    STYLE_BRIEF = "brief"
    STYLE_FRIENDLY = "friendly"
    STYLE_ANALYTICAL = "analytical"

    # Models for different use cases
    FAST_MODEL = "llama3.1:8b"
    SMART_MODEL = "llama3.1:70b"

    def __init__(self, db):
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.default_model = os.getenv('LLM_MODEL', self.FAST_MODEL)
        self.memory = ConversationMemory(db)
        self.db = db

    def get_temporal_context(self) -> Dict:
        """Get rich temporal context for the current moment"""
        now = datetime.now()

        return {
            'hour': now.hour,
            'hour_12': now.strftime('%-I:%M %p'),
            'day_of_week': now.strftime('%A'),
            'day_of_week_num': now.weekday(),
            'date': now.strftime('%B %d, %Y'),
            'is_weekend': now.weekday() >= 5,
            'is_morning': 6 <= now.hour < 12,
            'is_afternoon': 12 <= now.hour < 17,
            'is_evening': 17 <= now.hour < 21,
            'is_night': now.hour >= 21 or now.hour < 6,
            'part_of_day': self._get_part_of_day(now.hour),
            'quarter': (now.month - 1) // 3 + 1,
            'week_of_year': now.isocalendar()[1],
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

    def get_user_context(self, user_id: int) -> Dict:
        """Get comprehensive user context for the LLM"""
        context = {
            'temporal': self.get_temporal_context(),
            'entities': self.memory.get_entities(user_id),
            'preferences': self.memory.get_all_preferences(user_id),
            'mood': self.memory.get_mood_summary(user_id, hours=24),
        }

        # Add recent data from database
        try:
            # Recent tasks
            tasks = self.db.get_tasks(limit=5)
            context['recent_tasks'] = [
                {'description': t.description, 'status': t.status, 'priority': t.priority}
                for t in tasks[:5]
            ]

            # Recent food
            from datetime import timedelta
            yesterday = datetime.now() - timedelta(days=1)
            food_logs = self.db.get_food_logs(start_date=yesterday, limit=5)
            context['recent_foods'] = []
            for log in food_logs:
                context['recent_foods'].extend(log.items)
            context['recent_foods'] = list(set(context['recent_foods']))[:5]

            # Current energy
            energy_logs = self.db.get_energy_levels(limit=1)
            context['current_energy'] = energy_logs[0].level if energy_logs else None

        except Exception as e:
            logger.error(f"Error getting user context: {e}")

        return context

    def select_model(self, message: str, context: Dict) -> str:
        """Select appropriate model based on query complexity"""
        message_lower = message.lower()

        # Use smart model for:
        # - Analysis questions
        # - Complex queries
        # - Emotional content
        # - Pattern recognition
        smart_indicators = [
            'analyze', 'analysis', 'pattern', 'trend', 'insight',
            'how do i feel', 'why am i', 'what\'s wrong',
            'stressed', 'anxious', 'overwhelmed', 'exhausted',
            'recommend', 'suggest', 'should i',
        ]

        if any(indicator in message_lower for indicator in smart_indicators):
            return self.SMART_MODEL

        # Use fast model for simple logging
        fast_indicators = [
            'done', 'finished', 'completed', 'ate', 'had',
            'energy', 'supplement',
        ]

        if any(indicator in message_lower for indicator in fast_indicators):
            # But only if message is short
            if len(message) < 100:
                return self.FAST_MODEL

        # Default to configured model
        return self.default_model

    def get_response_style_instructions(self, user_id: int) -> str:
        """Get response style instructions based on user preference"""
        style = self.memory.get_preference(user_id, 'response_style', self.STYLE_FRIENDLY)

        styles = {
            self.STYLE_BRIEF: (
                "Be BRIEF and CONCISE. Acknowledge actions in minimal words. "
                "Use short sentences. No small talk unless asked."
            ),
            self.STYLE_FRIENDLY: (
                "Be FRIENDLY and WARM. Use emojis occasionally. "
                "Sound like a helpful friend. Show enthusiasm for accomplishments."
            ),
            self.STYLE_ANALYTICAL: (
                "Be ANALYTICAL and PRECISE. Focus on data, patterns, and insights. "
                "Use structured responses. Quantify when possible."
            )
        }

        return styles.get(style, styles[self.STYLE_FRIENDLY])

    async def parse_message(
        self,
        message: str,
        user_id: int,
        user_context: Dict = None
    ) -> Optional[Dict]:
        """
        Parse a message with full context awareness.

        Returns a dict with:
        - intent: The detected intent
        - understanding: What the bot understood
        - needs_clarification: Whether clarification is needed
        - clarification_question: Question to ask if unclear
        - action: Action to take (store, retrieve, analyze, respond_only)
        - entities: Extracted entities
        - sentiment: Detected sentiment (-1 to 1)
        - emotion: Detected emotion
        - response: Natural language response to user
        - suggestions: Optional proactive suggestions
        """
        # Get full context
        if user_context is None:
            user_context = self.get_user_context(user_id)

        # Add conversation history
        conversation_history = self.memory.get_conversation_context(user_id)

        # Add entities
        entities_context = self.memory.get_entities_context(user_id)

        # Select model
        model = self.select_model(message, user_context)

        # Get response style
        style_instructions = self.get_response_style_instructions(user_id)

        # Build the prompt
        temporal = user_context['temporal']
        context_prompt = f"""
CURRENT CONTEXT:
- Time: {temporal['hour_12']} on {temporal['day_of_week']}, {temporal['date']}
- Part of day: {temporal['part_of_day']}
- Is weekend: {temporal['is_weekend']}
- Current energy level: {user_context.get('current_energy', 'unknown')}/10
- Recent tasks: {[t['description'] for t in user_context.get('recent_tasks', [])]}
- Recent foods: {user_context.get('recent_foods', [])}
- Mood trend: {user_context.get('mood', {}).get('trend', 'neutral')} (avg: {user_context.get('mood', {}).get('avg', 0)})
{f'{conversation_history}' if conversation_history else ''}
{f'{entities_context}' if entities_context else ''}

RESPONSE STYLE INSTRUCTIONS:
{style_instructions}
"""

        system_prompt = self._get_system_prompt()

        user_prompt = f"""
{context_prompt}

USER MESSAGE: "{message}"

Analyze this message and return a JSON response with the following structure:

{{
  "intent": "log_task|log_food|log_energy|log_health|question|chat|unclear|correction",
  "understanding": "brief explanation of what you understood",
  "needs_clarification": true/false,
  "clarification_question": "specific question if unclear, otherwise null",
  "action": {{
    "type": "store|retrieve|analyze|respond_only|delete",
    "data": {{}}
  }},
  "entities": {{
    "people": ["names mentioned"],
    "projects": ["projects mentioned"],
    "locations": ["places mentioned"],
    "organizations": ["companies/organizations mentioned"]
  }},
  "sentiment": -1.0 to 1.0,
  "emotion": "happy|sad|tired|stressed|excited|frustrated|neutral|accomplished",
  "response": "your natural conversational response to the user",
  "suggestions": ["optional proactive suggestions based on context"]
}}

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no preamble
2. If the message is vague like "Done" or "That thing", set needs_clarification to true and ask specifically
3. Extract and remember entities (people, projects) for future reference
4. Detect sentiment from emotional words and tone
5. Be context-aware - reference their recent activity
6. For questions about data, set action.type to "retrieve" with appropriate query
7. For logging, set action.type to "store" with the data to log
8. Response should be natural and match the user's communication style
9. If asking about tasks, use the recent_tasks context
10. Use temporal context - "good morning" if morning, "good evening" if evening

EXAMPLE INTERACTIONS:

User: "I'm exhausted"
Response: {{"intent":"log_energy","understanding":"User is expressing low energy","needs_clarification":false,"action":{{"type":"store","data":{{"level":3,"context":"feeling exhausted"}}}},"sentiment":-0.6,"emotion":"tired","response":"That sounds tough. When did you start feeling this way?"}}

User: "Done"
Response: {{"intent":"unclear","understanding":"User said 'done' but context unclear","needs_clarification":true,"clarification_question":"Done with what? I see you have these active tasks: [list from context]","response":"Which task did you complete?"}}

User: "Working on the Peterson report"
Response: {{"intent":"log_task","understanding":"User is working on a task","entities":{{"projects":["Peterson report"]}},"action":{{"type":"store","data":{{"description":"Work on Peterson report","status":"in_progress"}}}},"response":"Got it! I'll track that. Let me know when it's done."}}

User: "What was my energy yesterday?"
Response: {{"intent":"question","understanding":"User asking about historical energy data","action":{{"type":"retrieve","data":{{"type":"energy","timeframe":"yesterday"}}}},"response":"Let me check your energy levels from yesterday..."}}

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Return ONLY the JSON object, nothing else.
"""

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": user_prompt,
                        "system": system_prompt,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": 0.7,
                            "num_ctx": 4096,  # Larger context for conversation memory
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"Ollama error: {response.status_code}")
                    return self._fallback_response(message)

                result = response.json()
                response_text = result.get('response', '')

                # Parse JSON with fallback
                parsed = self._extract_json(response_text)

                if parsed:
                    # Store entities if found
                    self._store_entities_from_parse(user_id, parsed, message)

                    # Log mood/sentiment
                    if 'sentiment' in parsed:
                        self.memory.log_mood(
                            user_id=user_id,
                            sentiment=parsed.get('sentiment', 0),
                            emotion=parsed.get('emotion'),
                            context=parsed.get('understanding'),
                            message=message
                        )

                    # Store conversation message
                    self.memory.add_message(user_id, 'user', message, metadata={
                        'intent': parsed.get('intent'),
                        'sentiment': parsed.get('sentiment'),
                    })

                    # Store assistant response too
                    self.memory.add_message(user_id, 'assistant', parsed.get('response', ''), metadata={
                        'intent': parsed.get('intent'),
                        'action': parsed.get('action', {}),
                    })

                    logger.info(f"Enhanced LLM parsed: {parsed.get('intent')} - {parsed.get('understanding')}")
                    return parsed
                else:
                    logger.error(f"Could not parse JSON from: {response_text[:500]}")
                    return self._fallback_response(message)

        except Exception as e:
            logger.error(f"Error calling Ollama: {e}")
            return self._fallback_response(message)

    def _store_entities_from_parse(self, user_id: int, parsed: Dict, original_message: str):
        """Store extracted entities for future reference"""
        entities = parsed.get('entities', {})
        if not entities:
            return

        for entity_type, names in entities.items():
            if entity_type == 'people':
                for name in names:
                    self.memory.store_entity(user_id, 'person', name, source_message=original_message)
            elif entity_type == 'projects':
                for name in names:
                    self.memory.store_entity(user_id, 'project', name, source_message=original_message)
            elif entity_type == 'locations':
                for name in names:
                    self.memory.store_entity(user_id, 'location', name, source_message=original_message)
            elif entity_type == 'organizations':
                for name in names:
                    self.memory.store_entity(user_id, 'organization', name, source_message=original_message)

    def _get_system_prompt(self) -> str:
        """Get the enhanced system prompt"""
        return """You are an intelligent personal life assistant with memory and context awareness.

CORE CAPABILITIES:
1. Remember conversations - reference what was said before
2. Understand temporal context - time of day, day of week affects interpretation
3. Extract and remember entities - people, projects, locations mentioned
4. Detect sentiment and emotion - respond appropriately to user's mood
5. Ask smart clarification questions - use context to disambiguate
6. Adapt communication style - match user's preferred style

INTENT CATEGORIES:
- log_task: User mentions something they did or need to do
- log_food: User mentions eating/drinking something
- log_energy: User describes their energy level
- log_health: User mentions supplements, exercise, health metrics
- question: User asks about their data
- chat: General conversation, venting, casual talk
- unclear: Message is ambiguous - needs clarification
- correction: User is correcting a previous entry

SENTIMENT SCALE:
- -1.0 to -0.5: Very negative (angry, devastated, hopeless)
- -0.5 to -0.2: Negative (sad, frustrated, tired)
- -0.2 to 0.2: Neutral (factual, calm)
- 0.2 to 0.5: Positive (happy, content, okay)
- 0.5 to 1.0: Very positive (excited, accomplished, great)

ENTITY TYPES TO EXTRACT:
- people: Names of people (clients, colleagues, family)
- projects: Work projects, cases, initiatives
- locations: Places (office, gym, home, client sites)
- organizations: Companies, agencies, institutions

SMART CLARIFICATION:
When unclear, reference the actual context. Don't just say "What did you complete?"
Say: "Which task did you complete? I see you have: [task1], [task2], [task3] active"

TEMPORAL AWARENESS:
- Morning (6-12): Greet appropriately, expect energy logging
- Afternoon (12-17): Check for lunch energy dips
- Evening (17-21): Wrap-up, tomorrow planning
- Night (21-6): Quiet mode, brief responses

PATTERN RECOGNITION:
- Notice and mention patterns: "You often say you're tired around this time"
- Connect dots: "That heavy lunch might explain the 2 PM dip"
- Celebrate streaks: "3 days in a row of hitting your step goal!"

RESPONSE PRINCIPLES:
1. Be context-aware - reference their actual data
2. Be helpful - offer relevant suggestions
3. Be concise - don't over-explain unless asked
4. Be proactive - anticipate needs based on patterns
5. Be human - occasional warmth, not robotic

Remember: You're building a relationship with the user, not just processing data."""

    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract JSON from possibly messy text with multiple fallback strategies"""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object (more permissive)
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try fixing common JSON issues
        try:
            # Remove trailing commas
            cleaned = re.sub(r',\s*([}\]])', r'\1', text)
            return json.loads(cleaned)
        except:
            pass

        return None

    def _fallback_response(self, message: str) -> Dict:
        """Fallback when LLM fails"""
        return {
            "intent": "unclear",
            "understanding": f"Could not process: {message[:50]}",
            "needs_clarification": True,
            "clarification_question": "I'm having trouble understanding that. Could you rephrase?",
            "action": {
                "type": "respond_only",
                "data": {}
            },
            "entities": {},
            "sentiment": 0,
            "emotion": "neutral",
            "response": "Sorry, I'm having trouble processing that right now. Could you try rephrasing?",
            "suggestions": []
        }

    async def generate_insight(
        self,
        user_id: int,
        insight_type: str,
        data: Dict
    ) -> str:
        """Generate insights from user data"""
        model = self.SMART_MODEL  # Use smart model for insights

        temporal = self.get_temporal_context()
        mood_summary = self.memory.get_mood_summary(user_id, hours=168)  # Week

        prompt = f"""
Generate a {insight_type} insight based on this user data:

DATA SUMMARY:
{json.dumps(data, indent=2)}

USER MOOD SUMMARY (last week):
- Average sentiment: {mood_summary.get('avg', 0)}
- Trend: {mood_summary.get('trend', 'neutral')}
- Total entries: {mood_summary.get('count', 0)}

CURRENT TIME: {temporal['hour_12']} on {temporal['day_of_week']}

Generate a brief, actionable insight (2-3 sentences). Be specific, mention actual numbers,
and provide a concrete suggestion based on their patterns.

Return ONLY the insight text, nothing else.
"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get('response', 'Unable to generate insight.')

        except Exception as e:
            logger.error(f"Error generating insight: {e}")

        return "I'm having trouble generating insights right now."

    def get_ambiguity_options(self, user_id: int, vague_message: str) -> List[str]:
        """Get specific options based on user's actual data for clarification"""
        options = []

        # Get pending tasks
        pending = self.db.get_tasks(status='pending', limit=10)
        if pending:
            options.extend([f"Task: {t.description}" for t in pending[:5]])

        # Get recent projects/entities
        projects = self.memory.get_entities(user_id, 'project')
        if projects:
            options.extend([f"Project: {p['name']}" for p in projects[:3]])

        return options
