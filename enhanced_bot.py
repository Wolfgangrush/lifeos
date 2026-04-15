#!/usr/bin/env python3
"""
Enhanced Telegram Bot for Life OS
Integrates all smart features:
- Conversation memory
- Temporal pattern recognition
- Entity extraction
- Sentiment/mood tracking
- Adaptive response styles
- Ambiguity resolution with options
- Proactive insights
- Scheduled reminders
"""

import os
import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv

from database import Database, TaskStatus
from enhanced_llm_parser import EnhancedLLMParser
from conversation_memory import ConversationMemory
from insights_engine import InsightsEngine, InsightsScheduler

load_dotenv()

Path('logs').mkdir(exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class EnhancedLifeOSBot:
    """
    Enhanced bot with all smart features.
    Falls back to the original bot's functions for compatibility.
    """

    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment")

        self.db = Database()
        self.memory = ConversationMemory(self.db)
        self.llm = EnhancedLLMParser(self.db)
        self.insights_engine = InsightsEngine(self.db)

        # Import the original bot for command handlers
        from bot import LifeOSBot
        self.original_bot = LifeOSBot()

        self.app = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with enhanced features"""
        user_id = update.effective_user.id

        # Set default preference if new
        if not self.memory.get_preference(user_id, 'response_style'):
            self.memory.set_preference(user_id, 'response_style', 'friendly')

        welcome_message = f"""
🌟 <b>Welcome to Your Enhanced Life OS!</b>

I'm your AI-powered life assistant with <b>memory</b> and <b>proactive insights</b>.

<b>✨ New Smart Features:</b>
• 🧠 I remember our conversations
• ⏰ I understand time and context
• 👥 I remember people, projects, places
• 💭 I track your mood trends
• 💡 I send proactive insights
• 🎯 I adapt to your style

<b>Quick Commands:</b>
/style - Change how I respond to you
/insights - View recent insights
/mood - See your mood trends
/entities - Manage remembered entities

<b>All Original Commands:</b>
/food - Food history and logging
/task - Task management
/energy - Log energy levels
/supplements - Supplement tracking
/summary - Daily summary
/stats - Weekly statistics
/help - Full command list

Just talk to me naturally and I'll figure it out! 🚀
        """
        await update.message.reply_text(welcome_message, parse_mode='HTML')

    async def style_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Change response style preference"""
        user_id = update.effective_user.id

        keyboard = [
            [InlineKeyboardButton("🤖 Brief", callback_data='style_brief')],
            [InlineKeyboardButton("😊 Friendly", callback_data='style_friendly')],
            [InlineKeyboardButton("📊 Analytical", callback_data='style_analytical')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        current_style = self.memory.get_preference(user_id, 'response_style', 'friendly')

        await update.message.reply_text(
            f"*Choose your response style:*\n\n"
            f"Current: **{current_style.title()}**\n\n"
            f"• **Brief**: Short, direct responses\n"
            f"• **Friendly**: Warm, conversational\n"
            f"• **Analytical**: Data-focused, detailed",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def insights_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View recent insights"""
        user_id = update.effective_user.id

        # Get pending insights from database
        from sqlalchemy import desc
        from conversation_memory import ScheduledInsight

        session = self.db.get_session()
        try:
            insights = session.query(ScheduledInsight).filter(
                ScheduledInsight.user_id == user_id,
                ScheduledInsight.sent == True
            ).order_by(desc(ScheduledInsight.created_at)).limit(5).all()
        finally:
            session.close()

        if not insights:
            await update.message.reply_text(
                "No insights generated yet. Keep logging and I'll find patterns! 🔍"
            )
            return

        lines = ["💡 *Recent Insights*\n"]
        for insight in insights:
            created = insight.created_at.strftime('%b %d')
            lines.append(f"\n*{created}* - {insight.insight_type}")
            lines.append(insight.content[:200])

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

    async def mood_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View mood trends"""
        user_id = update.effective_user.id

        mood_summary = self.memory.get_mood_summary(user_id, hours=168)  # Week

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

        entities = self.memory.get_entities(user_id)

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

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Enhanced message handler with all smart features.
        Falls back to original handler for recognized patterns.
        """
        message_text = update.message.text
        user_id = update.effective_user.id

        logger.info(f"[Enhanced] Received from {user_id}: {message_text}")

        # Show typing indicator
        await update.message.chat.send_action("typing")

        # Check for URL-only messages (use original handler)
        url_match = re.match(r'^\s*(https?://\S+)\s*$', message_text)
        if url_match:
            await self.original_bot.handle_message(update, context)
            return

        # Check for simple operator syntax (use original handler)
        if self.original_bot._parse_operator_task(message_text):
            await self.original_bot.handle_message(update, context)
            return

        # Check for batch task format (use original handler)
        if self.original_bot._parse_batch_tasks(message_text):
            await self.original_bot.handle_message(update, context)
            return

        # Check for questions (use original handler for now)
        if self.original_bot._is_question(message_text):
            answer = await self.original_bot._handle_question(message_text)
            if answer:
                await update.message.reply_text(answer, parse_mode='Markdown')
                return

        # Use enhanced LLM parser for everything else
        try:
            user_context = self.llm.get_user_context(user_id)
            result = await self.llm.parse_message(message_text, user_id, user_context)

            if not result:
                await update.message.reply_text(
                    "I'm having trouble understanding that. Could you rephrase?"
                )
                return

            # Handle the parsed result
            await self._process_enhanced_result(update, context, result, user_id)

        except Exception as e:
            logger.error(f"Error in enhanced handler: {e}", exc_info=True)
            # Fallback to original handler
            await self.original_bot.handle_message(update, context)

    async def _process_enhanced_result(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        result: Dict,
        user_id: int
    ):
        """Process the enhanced LLM parser result"""
        intent = result.get('intent')
        needs_clarification = result.get('needs_clarification', False)
        action = result.get('action', {})
        response_text = result.get('response', '')

        # If clarification needed, show options
        if needs_clarification:
            await self._send_clarification_with_options(update, result, user_id)
            return

        # Execute the action
        action_type = action.get('type')

        if action_type == 'store':
            data = action.get('data', {})
            await self._store_data(intent, data, user_id)

        elif action_type == 'retrieve':
            data = action.get('data', {})
            response_text = await self._retrieve_data(data, result, user_id)

        elif action_type == 'analyze':
            response_text = await self._analyze_data(result, user_id)

        elif action_type == 'delete':
            data = action.get('data', {})
            await self._delete_data(data, user_id)

        # Send the response
        if response_text:
            await update.message.reply_text(response_text)

    async def _send_clarification_with_options(
        self,
        update: Update,
        result: Dict,
        user_id: int
    ):
        """Send clarification question with actual options from user data"""
        question = result.get('clarification_question', 'What did you mean?')

        # Get ambiguity options
        options = self.llm.get_ambiguity_options(user_id, question)

        if options:
            # Create inline keyboard with options
            keyboard = []
            for option in options[:6]:
                keyboard.append([
                    InlineKeyboardButton(option, callback_data=f'clarify_{option[:50]}')
                ])

            keyboard.append([InlineKeyboardButton("✍️ Type my answer", callback_data='clarify_type')])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(question, reply_markup=reply_markup)
        else:
            await update.message.reply_text(question)

    async def _store_data(self, intent: str, data: dict, user_id: int):
        """Store data based on intent"""
        try:
            if intent == 'log_task':
                description = data.get('description', '')
                status = data.get('status', 'pending')

                if status == 'completed' or status == 'in_progress':
                    # For completed tasks, find and complete
                    task = self.db.complete_task_by_description(description)
                    if not task:
                        self.db.create_task(
                            description=description,
                            status=TaskStatus.COMPLETED if status == 'completed' else TaskStatus.PENDING
                        )
                else:
                    self.db.create_task(description=description)

            elif intent == 'log_food':
                items = data.get('items', [])
                if items:
                    from datetime import datetime
                    self.db.log_food(
                        items=items,
                        timestamp=datetime.now().isoformat(),
                        macros=data.get('macros', {}),
                        energy_prediction=data.get('energy_prediction', {})
                    )

            elif intent == 'log_energy':
                level = data.get('level')
                context_note = data.get('context', '')
                if level:
                    self.db.log_energy(level=int(level), context=context_note)

            elif intent == 'log_health':
                supplements = data.get('supplements', [])
                metrics = data.get('metrics', {})
                if supplements or metrics:
                    self.db.log_health(supplements=supplements, metrics=metrics)

            logger.info(f"Stored data for intent: {intent}")

        except Exception as e:
            logger.error(f"Error storing data: {e}", exc_info=True)

    async def _retrieve_data(self, query: dict, result: dict, user_id: int) -> str:
        """Retrieve and format data"""
        try:
            data_type = query.get('type', 'summary')
            timeframe = query.get('timeframe', 'today')

            if data_type == 'energy':
                if timeframe == 'yesterday':
                    from datetime import timedelta
                    yesterday = datetime.now() - timedelta(days=1)
                    levels = self.db.get_energy_levels(
                        start_date=yesterday.replace(hour=0, minute=0),
                        end_date=yesterday.replace(hour=23, minute=59),
                        limit=20
                    )
                else:
                    from datetime import datetime
                    today = datetime.now().replace(hour=0, minute=0)
                    levels = self.db.get_energy_levels(start_date=today, limit=20)

                if levels:
                    actual = [l for l in levels if not l.predicted]
                    if actual:
                        avg = sum(l.level for l in actual) / len(actual)
                        return f"Your energy averaged {avg:.1f}/10. You ranged from {min(l.level for l in actual)} to {max(l.level for l in actual)}."
                    return "No actual energy logged, only predictions."
                return "No energy data found."

            elif data_type == 'tasks':
                pending = self.db.get_tasks(status='pending', limit=10)
                if pending:
                    lines = [f"You have {len(pending)} pending tasks:"]
                    for task in pending[:5]:
                        lines.append(f"• {task.description}")
                    return '\n'.join(lines)
                return "You have no pending tasks!"

            elif data_type == 'food':
                from datetime import datetime
                today = datetime.now().replace(hour=0, minute=0)
                logs = self.db.get_food_logs(start_date=today, limit=10)
                if logs:
                    lines = ["Today you ate:"]
                    for log in logs:
                        items = ', '.join(log.items or [])
                        lines.append(f"• {items}")
                    return '\n'.join(lines)
                return "No food logged today."

            # Use LLM to generate a response
            return result.get('response', 'Here\'s what I found.')

        except Exception as e:
            logger.error(f"Error retrieving data: {e}")
            return "I had trouble retrieving that data."

    async def _analyze_data(self, result: dict, user_id: int) -> str:
        """Generate analysis from data"""
        # For now, return the LLM's response
        # In the future, could call insights engine
        return result.get('response', 'Analysis complete.')

    async def _delete_data(self, data: dict, user_id: int):
        """Delete data"""
        # Implement deletion logic if needed
        pass

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()

        data = query.data

        # Style selection
        if data.startswith('style_'):
            style = data.split('_')[1]
            user_id = update.effective_user.id
            self.memory.set_preference(user_id, 'response_style', style)

            style_descriptions = {
                'brief': '🤖 Brief - Short and direct',
                'friendly': '😊 Friendly - Warm and conversational',
                'analytical': '📊 Analytical - Data-focused'
            }

            await query.edit_message_text(
                f"Response style updated!\n\n{style_descriptions.get(style, style)}"
            )

        # Clarification responses
        elif data.startswith('clarify_'):
            if data == 'clarify_type':
                await query.edit_message_text("Go ahead and type your answer:")
                context.user_data['expecting_clarification'] = True
            else:
                option = data[len('clarify_'):]
                # Store the clarification and process
                context.user_data['clarification_response'] = option
                await query.edit_message_text(f"Got it: {option}\n\nProcessing...")
                # Would re-process the original message with this clarification

        else:
            # Pass to original bot's button handler
            await self.original_bot.button_callback(update, context)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")

    def run(self):
        """Start the enhanced bot"""
        logger.info("Starting Enhanced Life OS Bot...")

        # Create application
        self.app = Application.builder().token(self.token).build()

        # Add enhanced command handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("style", self.style_command))
        self.app.add_handler(CommandHandler("insights", self.insights_command))
        self.app.add_handler(CommandHandler("mood", self.mood_command))
        self.app.add_handler(CommandHandler("entities", self.entities_command))

        # Add original command handlers (delegate)
        self.app.add_handler(CommandHandler("help", self.original_bot.help_command))
        self.app.add_handler(CommandHandler("eatery", self.original_bot.eatery_command))
        self.app.add_handler(CommandHandler("task", self.original_bot.task_command))
        self.app.add_handler(CommandHandler("energy", self.original_bot.energy_command))
        self.app.add_handler(CommandHandler("summary", self.original_bot.summary_command))
        self.app.add_handler(CommandHandler("stats", self.original_bot.stats_command))
        self.app.add_handler(CommandHandler("supplements", self.original_bot.supplements_command))
        self.app.add_handler(CommandHandler(["addsupplement", "add_supplement"], self.original_bot.add_supplement_command))
        self.app.add_handler(CommandHandler(["removesupplement", "remove_supplement"], self.original_bot.remove_supplement_command))
        self.app.add_handler(CommandHandler(["delete_task", "deletetask"], self.original_bot.delete_task_command))
        self.app.add_handler(CommandHandler(["delete_food", "deletefood"], self.original_bot.delete_food_command))
        self.app.add_handler(CommandHandler("food", self.original_bot.food_history_command))
        self.app.add_handler(CommandHandler(["food_today", "foodtoday"], self.original_bot.food_today_command))
        self.app.add_handler(CommandHandler(["food_analysis", "foodanalysis"], self.original_bot.food_analysis_command))
        self.app.add_handler(CommandHandler(["reminders", "reminder"], self.original_bot.reminders_command))
        self.app.add_handler(CommandHandler(["remind", "reminder_add"], self.original_bot.remind_command))
        self.app.add_handler(CommandHandler(["delete_recent", "deleterecent"], self.original_bot.delete_recent_command))
        self.app.add_handler(CommandHandler("rollover", self.original_bot.rollover_command))
        self.app.add_handler(CommandHandler(["operator_on", "operator"], self.original_bot.operator_on_command))

        # Callback query handler
        self.app.add_handler(CallbackQueryHandler(self.button_callback))

        # Photo message handler
        self.app.add_handler(MessageHandler(filters.PHOTO, self.original_bot.photo_message))

        # Enhanced message handler
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_message
        ))

        # Error handler
        self.app.add_error_handler(self.error_handler)

        # Start polling
        logger.info("🤖 Enhanced Bot is running with all smart features!")

        # Start insights scheduler in background
        if os.getenv('ENABLE_INSIGHTS_SCHEDULER', 'true').lower() == 'true':
            import asyncio
            from telegram.ext import Application

            # Run scheduler in background
            async def run_scheduler():
                scheduler = InsightsScheduler(self.db, self.token)
                await scheduler.start()

            # Create background task
            loop = self.app.updater.executor.loop
            loop.create_task(run_scheduler())
            logger.info("📊 Insights scheduler started in background")

        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = EnhancedLifeOSBot()
    bot.run()
