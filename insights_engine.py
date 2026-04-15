#!/usr/bin/env python3
"""
Proactive Insights Engine for Life OS
Analyzes patterns and sends unsolicited insights to users
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Bot
from sqlalchemy import desc, and_

from database import Database, Task, TaskStatus, FoodLog, EnergyLevel
from conversation_memory import (
    ScheduledInsight,
    ProactiveReminder,
    ConversationMemory
)

logger = logging.getLogger(__name__)


class InsightsEngine:
    """
    Proactively analyzes user data and generates insights.
    Runs periodically to find patterns and send helpful messages.
    """

    def __init__(self, db: Database, telegram_bot: Bot = None):
        self.db = db
        self.telegram_bot = telegram_bot
        self.memory = ConversationMemory(db)

        # Default user ID (can be overridden per message)
        self.default_user_id = int(os.getenv('TELEGRAM_USER_ID', 0))

    async def generate_daily_insight(self, user_id: int = None) -> Optional[Dict]:
        """Generate a daily insight about the user's patterns"""
        if user_id is None:
            user_id = self.default_user_id

        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        # Get yesterday's data
        yesterday_summary = self.db.get_daily_summary(yesterday)
        weekly_stats = self.db.get_weekly_stats()

        insights = []

        # Task completion insight
        tasks_completed = yesterday_summary.get('tasks_completed', 0)
        if tasks_completed >= 5:
            insights.append({
                'type': 'productivity',
                'title': '🔥 Productive Day!',
                'content': f'You completed {tasks_completed} tasks yesterday! Your momentum is strong.',
                'suggestion': 'Keep the momentum going today. Start with your hardest task.'
            })
        elif tasks_completed == 0:
            pending_count = len(self.db.get_tasks(status=TaskStatus.PENDING))
            insights.append({
                'type': 'productivity',
                'title': '📋 Fresh Start',
                'content': f'No tasks were completed yesterday. You have {pending_count} pending tasks.',
                'suggestion': 'Pick one small task to start with today.'
            })

        # Energy pattern insight
        energy_logs = self.db.get_energy_levels(
            start_date=datetime.combine(yesterday, datetime.min.time()),
            end_date=datetime.combine(yesterday, datetime.max.time()),
            predicted_only=False,
            limit=20
        )

        if energy_logs:
            avg_energy = sum(e.level for e in energy_logs) / len(energy_logs)
            min_energy = min(e.level for e in energy_logs)

            if min_energy <= 3:
                # Find when energy was low
                low_periods = [e for e in energy_logs if e.level <= 3]
                if low_periods:
                    low_hour = low_periods[0].timestamp.hour
                    insights.append({
                        'type': 'energy',
                        'title': '⚡ Energy Pattern',
                        'content': f'Your energy dropped to {min_energy}/10 yesterday around {low_hour}:00.',
                        'suggestion': 'Consider a light walk or healthy snack before this time today.'
                    })

            if avg_energy >= 7:
                insights.append({
                    'type': 'energy',
                    'title': '⚡ High Energy Day!',
                    'content': f'Your average energy was {avg_energy:.1f}/10 yesterday!',
                    'suggestion': 'Great energy! Tackle your most challenging tasks today.'
                })

        # Food pattern insight
        food_logs = self.db.get_food_logs(
            start_date=datetime.combine(yesterday, datetime.min.time()),
            end_date=datetime.combine(yesterday, datetime.max.time()),
            limit=10
        )

        heavy_carb_meals = []
        for log in food_logs:
            macros = log.macros or {}
            if macros.get('carbs') == 'high':
                heavy_carb_meals.append(log)

        if len(heavy_carb_meals) >= 2:
            insights.append({
                'type': 'nutrition',
                'title': '🍽️ Food Pattern',
                'content': f'You had {len(heavy_carb_meals)} heavy carb meals yesterday.',
                'suggestion': 'Consider adding more protein to stabilize your energy.'
            })

        # Streak insight
        streak = weekly_stats.get('current_streak', 0)
        if streak >= 7:
            insights.append({
                'type': 'streak',
                'title': f'🔥 {streak} Day Streak!',
                'content': f"You've been logging for {streak} days straight!",
                'suggestion': 'Amazing consistency! Keep it going.'
            })

        return {
            'user_id': user_id,
            'date': today.isoformat(),
            'insights': insights[:3],  # Max 3 insights
            'yesterday_summary': yesterday_summary,
            'weekly_stats': weekly_stats
        }

    async def generate_weekly_insight(self, user_id: int = None) -> Optional[Dict]:
        """Generate a comprehensive weekly insight"""
        if user_id is None:
            user_id = self.default_user_id

        weekly_stats = self.db.get_weekly_stats()
        mood_summary = self.memory.get_mood_summary(user_id, hours=168)  # 7 days

        insights = []

        # Productivity trend
        completion_rate = weekly_stats.get('completion_rate', 0)
        if completion_rate >= 80:
            insights.append({
                'type': 'productivity',
                'title': '🏆 High Performance Week!',
                'content': f'You completed {completion_rate:.0f}% of your tasks this week.',
                'suggestion': 'You\'re crushing it! Keep this momentum going.'
            })
        elif completion_rate < 40:
            insights.append({
                'type': 'productivity',
                'title': '📈 Room for Growth',
                'content': f'Only {completion_rate:.0f}% of tasks were completed this week.',
                'suggestion': 'Consider breaking large tasks into smaller chunks.'
            })

        # Energy patterns
        peak_time = weekly_stats.get('peak_energy_time', 'N/A')
        low_time = weekly_stats.get('low_energy_time', 'N/A')
        insights.append({
            'type': 'energy',
            'title': '⚡ Weekly Energy Pattern',
            'content': f'Peak energy: {peak_time}, Lowest: {low_time}',
            'suggestion': f'Schedule focused work around {peak_time} for best results.'
        })

        # Mood trend
        if mood_summary.get('trend') == 'declining':
            insights.append({
                'type': 'wellbeing',
                'title': '💚 Check-in',
                'content': 'Your mood has been trending down this week.',
                'suggestion': 'Consider scheduling some downtime or self-care activities.'
            })
        elif mood_summary.get('trend') == 'improving':
            insights.append({
                'type': 'wellbeing',
                'title': '🌟 Positive Trend!',
                'content': 'Your mood has been improving this week!',
                'suggestion': 'Whatever you\'re doing, keep it up!'
            })

        return {
            'user_id': user_id,
            'week_ending': datetime.now().date().isoformat(),
            'insights': insights,
            'weekly_stats': weekly_stats,
            'mood_summary': mood_summary
        }

    async def detect_energy_dip_reminder(self, user_id: int = None) -> Optional[Dict]:
        """Detect when user is likely experiencing an energy dip"""
        if user_id is None:
            user_id = self.default_user_id

        now = datetime.now()
        hour = now.hour

        # Common dip times: after lunch (1-3 PM), late afternoon (4-5 PM)
        if hour not in [13, 14, 15, 16, 17]:
            return None

        # Check if there was a heavy carb meal 30-90 minutes ago
        check_time = now - timedelta(minutes=45)
        food_logs = self.db.get_food_logs(
            start_date=check_time - timedelta(minutes=30),
            end_date=check_time + timedelta(minutes=30),
            limit=5
        )

        for log in food_logs:
            macros = log.macros or {}
            if macros.get('carbs') == 'high':
                return {
                    'user_id': user_id,
                    'type': 'energy_dip',
                    'trigger_time': now.isoformat(),
                    'message': f'⚡ Energy dip alert! You had a heavy meal about 45 minutes ago.',
                    'suggestion': 'Consider a short walk, water, or light movement to boost energy.'
                }

        return None

    async def detect_task_overdue(self, user_id: int = None) -> List[Dict]:
        """Detect overdue tasks and generate reminders"""
        if user_id is None:
            user_id = self.default_user_id

        overdue_tasks = self.db.get_tasks_overdue(hours=0)

        reminders = []
        for task in overdue_tasks[:5]:  # Max 5
            days_overdue = (datetime.now() - task.deadline).days
            reminders.append({
                'user_id': user_id,
                'type': 'task_overdue',
                'task_id': task.id,
                'task_description': task.description,
                'deadline': task.deadline.isoformat(),
                'days_overdue': days_overdue,
                'message': f'📋 Task overdue: "{task.description}" was due {days_overdue} day(s) ago.',
                'suggestion': 'Can this task be delegated, broken down, or removed?'
            })

        return reminders

    async def detect_patterns(self, user_id: int = None) -> List[Dict]:
        """Detect patterns in user behavior"""
        if user_id is None:
            user_id = self.default_user_id

        patterns = []

        # Check for consistent low energy times
        session = self.db.get_session()
        try:
            from sqlalchemy import func
            from database import EnergyLevel

            week_ago = datetime.now() - timedelta(days=7)
            energy_data = session.query(
                func.extract('hour', EnergyLevel.timestamp).label('hour'),
                func.avg(EnergyLevel.level).label('avg_level')
            ).filter(
                EnergyLevel.timestamp >= week_ago,
                EnergyLevel.predicted == False
            ).group_by(
                func.extract('hour', EnergyLevel.timestamp)
            ).having(
                func.count(EnergyLevel.id) >= 3
            ).all()

            # Find consistently low energy hours
            low_hours = [h for h, avg in energy_data if avg < 5]
            if len(low_hours) >= 2:
                patterns.append({
                    'type': 'low_energy_pattern',
                    'hours': sorted(set(low_hours)),
                    'message': f'You tend to have low energy around {", ".join(f"{h}:00" for h in sorted(set(low_hours))}.',
                    'suggestion': 'Avoid high-focus tasks during these times.'
                })

            # Check for consistently high energy hours
            high_hours = [h for h, avg in energy_data if avg >= 7]
            if len(high_hours) >= 2:
                patterns.append({
                    'type': 'high_energy_pattern',
                    'hours': sorted(set(high_hours)),
                    'message': f'Your peak energy hours are {", ".join(f"{h}:00" for h in sorted(set(high_hours)))}.',
                    'suggestion': 'Schedule your most important tasks during these hours!'
                })

        finally:
            session.close()

        return patterns

    async def schedule_insight(self, user_id: int, insight_type: str,
                              content: str, scheduled_for: datetime,
                              data_summary: dict = None):
        """Schedule an insight to be sent later"""
        session = self.db.get_session()
        try:
            insight = ScheduledInsight(
                user_id=user_id,
                insight_type=insight_type,
                content=content,
                data_summary=data_summary or {},
                scheduled_for=scheduled_for,
                sent=False
            )
            session.add(insight)
            session.commit()
            logger.info(f"Scheduled {insight_type} insight for {scheduled_for}")
        finally:
            session.close()

    async def schedule_reminder(self, user_id: int, trigger_type: str,
                              message: str, scheduled_for: datetime,
                              trigger_data: dict = None):
        """Schedule a proactive reminder"""
        session = self.db.get_session()
        try:
            reminder = ProactiveReminder(
                user_id=user_id,
                trigger_type=trigger_type,
                message=message,
                trigger_data=trigger_data or {},
                scheduled_for=scheduled_for,
                sent=False
            )
            session.add(reminder)
            session.commit()
            logger.info(f"Scheduled {trigger_type} reminder for {scheduled_for}")
        finally:
            session.close()

    async def send_insight(self, user_id: int, insight: Dict) -> bool:
        """Send an insight message to the user via Telegram"""
        if not self.telegram_bot:
            logger.warning("No Telegram bot configured for sending insights")
            return False

        try:
            # Format the insight message
            lines = [f"*{insight.get('title', '💡 Insight')}*\n"]
            lines.append(insight.get('content', ''))
            if insight.get('suggestion'):
                lines.append(f"\n💡 {insight['suggestion']}")

            message = '\n'.join(lines)

            await self.telegram_bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='Markdown'
            )
            return True

        except Exception as e:
            logger.error(f"Error sending insight to user {user_id}: {e}")
            return False

    async def process_pending_insights(self):
        """Send all pending scheduled insights"""
        session = self.db.get_session()
        try:
            now = datetime.now()
            pending = session.query(ScheduledInsight).filter(
                ScheduledInsight.sent == False,
                ScheduledInsight.scheduled_for <= now
            ).all()

            for insight in pending:
                # Parse the content if it's stored as JSON
                try:
                    import json
                    if isinstance(insight.content, str):
                        content_data = json.loads(insight.content)
                    else:
                        content_data = insight.content
                except:
                    content_data = {'content': insight.content}

                # Send the insight
                sent = await self.send_insight(insight.user_id, content_data)

                if sent:
                    insight.sent = True
                    session.commit()
                    logger.info(f"Sent insight {insight.id} to user {insight.user_id}")

        finally:
            session.close()

    async def process_pending_reminders(self):
        """Send all pending proactive reminders"""
        session = self.db.get_session()
        try:
            now = datetime.now()
            pending = session.query(ProactiveReminder).filter(
                ProactiveReminder.sent == False,
                ProactiveReminder.scheduled_for <= now
            ).all()

            for reminder in pending:
                sent = await self.send_reminder(reminder)

                if sent:
                    reminder.sent = True
                    session.commit()
                    logger.info(f"Sent reminder {reminder.id} to user {reminder.user_id}")

        finally:
            session.close()

    async def send_reminder(self, reminder: ProactiveReminder) -> bool:
        """Send a proactive reminder to the user"""
        if not self.telegram_bot:
            return False

        try:
            await self.telegram_bot.send_message(
                chat_id=reminder.user_id,
                text=reminder.message,
                parse_mode='Markdown'
            )
            return True
        except Exception as e:
            logger.error(f"Error sending reminder: {e}")
            return False

    async def run_proactive_checks(self, user_id: int = None):
        """Run all proactive checks and generate insights/reminders"""
        if user_id is None:
            user_id = self.default_user_id

        # Check for energy dip reminders
        dip_reminder = await self.detect_energy_dip_reminder(user_id)
        if dip_reminder:
            await self.schedule_reminder(
                user_id=user_id,
                trigger_type='energy_dip',
                message=dip_reminder['message'],
                scheduled_for=datetime.now(),
                trigger_data=dip_reminder
            )

        # Check for overdue tasks
        overdue_reminders = await self.detect_task_overdue(user_id)
        for reminder in overdue_reminders[:2]:  # Max 2 overdue reminders
            await self.schedule_reminder(
                user_id=user_id,
                trigger_type='task_overdue',
                message=reminder['message'],
                scheduled_for=datetime.now() + timedelta(minutes=5),
                trigger_data=reminder
            )

        # Detect patterns
        patterns = await self.detect_patterns(user_id)
        for pattern in patterns[:2]:  # Max 2 patterns
            await self.schedule_insight(
                user_id=user_id,
                insight_type='pattern',
                content=pattern['message'],
                scheduled_for=datetime.now() + timedelta(minutes=10),
                data_summary=pattern
            )


class InsightsScheduler:
    """
    Background scheduler for running proactive insights.
    Can be run as a standalone service or integrated with the bot.
    """

    def __init__(self, db: Database, telegram_bot_token: str):
        self.db = db
        from telegram import Bot
        self.bot = Bot(token=telegram_bot_token)
        self.engine = InsightsEngine(db, self.bot)
        self.running = False

    async def daily_job(self):
        """Run daily insights generation"""
        logger.info("Running daily insights job")

        # Generate daily insight
        insight = await self.engine.generate_daily_insight()
        if insight and insight.get('insights'):
            # Schedule for 9 AM
            scheduled_for = datetime.now().replace(hour=9, minute=0, second=0)
            if scheduled_for < datetime.now():
                scheduled_for += timedelta(days=1)

            for item in insight['insights']:
                await self.engine.schedule_insight(
                    user_id=insight['user_id'],
                    insight_type='daily',
                    content=json.dumps(item),
                    scheduled_for=scheduled_for,
                    data_summary={'yesterday': insight['yesterday_summary']}
                )

    async def weekly_job(self):
        """Run weekly insights generation"""
        logger.info("Running weekly insights job")

        # Generate weekly insight
        insight = await self.engine.generate_weekly_insight()
        if insight and insight.get('insights'):
            # Schedule for Sunday 9 AM
            scheduled_for = datetime.now()
            days_until_sunday = (6 - scheduled_for.weekday()) % 7
            if days_until_sunday == 0 and scheduled_for.hour > 9:
                days_until_sunday = 7
            scheduled_for = (scheduled_for + timedelta(days=days_until_sunday)).replace(hour=9, minute=0, second=0)

            for item in insight['insights']:
                await self.engine.schedule_insight(
                    user_id=insight['user_id'],
                    insight_type='weekly',
                    content=json.dumps(item),
                    scheduled_for=scheduled_for,
                    data_summary={'weekly': insight['weekly_stats']}
                )

    async def hourly_job(self):
        """Run hourly checks (energy dips, etc.)"""
        logger.info("Running hourly checks")

        # Process pending insights and reminders
        await self.engine.process_pending_insights()
        await self.engine.process_pending_reminders()

        # Run proactive checks
        await self.engine.run_proactive_checks()

    async def start(self):
        """Start the scheduler"""
        self.running = True
        logger.info("Insights scheduler started")

        # Run initial jobs
        await self.daily_job()
        await self.weekly_job()
        await self.hourly_job()

        # Keep running with periodic checks
        while self.running:
            try:
                # Sleep for an hour
                await asyncio.sleep(3600)
                await self.hourly_job()

                # Check if we should run daily/weekly jobs
                now = datetime.now()
                if now.hour == 9 and now.minute < 5:
                    await self.daily_job()
                if now.weekday() == 6 and now.hour == 9 and now.minute < 5:  # Sunday 9 AM
                    await self.weekly_job()

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry

    def stop(self):
        """Stop the scheduler"""
        self.running = False
        logger.info("Insights scheduler stopped")


# Standalone runner for testing
async def main():
    """Run the insights scheduler standalone"""
    import os
    from database import Database

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        print("TELEGRAM_BOT_TOKEN not found")
        return

    db = Database()
    scheduler = InsightsScheduler(db, token)

    try:
        await scheduler.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
