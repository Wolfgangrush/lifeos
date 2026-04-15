#!/usr/bin/env python3
"""
Automation Engine for Life OS
Handles scheduled tasks, reminders, and predictions
"""

import os
import asyncio
import logging
import json
from datetime import datetime, timedelta, time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from database import Database
from llm_parser import LLMParser
import httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutomationEngine:
    def __init__(self):
        self.db = Database()
        self.llm_parser = LLMParser()
        self.scheduler = AsyncIOScheduler()
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def _extract_json(self, text: str) -> dict | None:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None

    def _system_event_exists(self, session, event_type: str, object_key: str, object_id: int) -> bool:
        from database import SystemEvent

        events = (
            session.query(SystemEvent.id, SystemEvent.data)
            .filter(SystemEvent.event_type == event_type)
            .order_by(SystemEvent.timestamp.desc())
            .limit(300)
            .all()
        )
        for _, data in events:
            if isinstance(data, dict) and data.get(object_key) == object_id:
                return True
        return False

    async def analyze_task_intelligence(self, task) -> dict | None:
        """Classify a task and store its effort/domain intelligence once."""
        prompt = f"""
Analyze this life-log task: "{task.description}"

You understand Indian legal/professional shorthand:
- APL can mean Appeal/Application depending on context.
- FIR means First Information Report.
- Quashing of FIR is a criminal-law procedure.

Return ONLY valid JSON:
{{
  "complexity": "low|medium|high|expert",
  "estimated_hours_min": number,
  "estimated_hours_max": number,
  "domain": "legal|technical|administrative|creative|personal|health|other",
  "requires_deep_focus": true,
  "coach_note": "one practical, specific sentence"
}}
"""
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                response = await client.post(
                    f"{self.llm_parser.ollama_url}/api/generate",
                    json={
                        "model": self.llm_parser.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
            if response.status_code != 200:
                logger.warning("Task intelligence skipped; Ollama returned %s", response.status_code)
                return None

            data = self._extract_json(response.json().get("response", ""))
            if not data:
                logger.warning("Task intelligence skipped; invalid JSON for task %s", task.id)
                return None

            self.db.log_system_event(
                event_type="task_intelligence",
                data={
                    "task_id": task.id,
                    "task_description": task.description,
                    "status": task.status,
                    "complexity": data.get("complexity"),
                    "estimated_hours_min": data.get("estimated_hours_min"),
                    "estimated_hours_max": data.get("estimated_hours_max"),
                    "domain": data.get("domain"),
                    "requires_deep_focus": data.get("requires_deep_focus"),
                    "coach_note": data.get("coach_note"),
                },
                triggered_by="automation",
            )
            logger.info("Task intelligence saved for task %s", task.id)
            return data
        except Exception as error:
            logger.error("Task intelligence failed for task %s: %s", getattr(task, "id", None), error)
            return None

    async def analyze_food_with_gemini(self, food_log) -> dict | None:
        """Use the existing Gemini API key to enrich a full meal with nutrition and energy impact."""
        if not self.gemini_api_key:
            logger.info("Gemini food intelligence skipped; GEMINI_API_KEY is not configured")
            return None

        items = [str(item).strip() for item in (food_log.items or []) if str(item).strip()]
        if not items:
            return None

        prompt = f"""
Analyze this Indian meal as a journaling estimate: {", ".join(items)}

Assume normal Indian home/restaurant portions unless quantities are included.
Return ONLY valid JSON:
{{
  "total_calories": number,
  "carbs_grams": number,
  "protein_grams": number,
  "fat_grams": number,
  "carbs_level": "low|medium|high",
  "protein_level": "low|medium|high",
  "fat_level": "low|medium|high",
  "key_micronutrients": ["nutrient"],
  "energy_impact": "stable|spike_then_crash|steady_energy|boost",
  "energy_timeline": "plain English timing",
  "health_score": number,
  "coach_note": "one concise practical recommendation"
}}
Do not give medical advice. Make numbers conservative approximations.
"""
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                response = await client.post(
                    api_url,
                    params={"key": self.gemini_api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2},
                    },
                )
            if response.status_code != 200:
                logger.warning("Gemini food intelligence skipped; Gemini returned %s", response.status_code)
                return None

            gemini_payload = response.json()
            parts = gemini_payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts)
            data = self._extract_json(text)
            if not data:
                logger.warning("Gemini food intelligence skipped; invalid JSON for food log %s", food_log.id)
                return None

            existing_macros = food_log.macros or {}
            existing_prediction = food_log.energy_prediction or {}
            locked_calories = bool(existing_prediction.get("user_calories_locked"))
            calories = existing_macros.get("calories") if locked_calories else data.get("total_calories") or existing_macros.get("calories")

            macros = {
                **existing_macros,
                "carbs": data.get("carbs_level") or existing_macros.get("carbs"),
                "protein": data.get("protein_level") or existing_macros.get("protein"),
                "fat": data.get("fat_level") or existing_macros.get("fat"),
                "calories": calories,
                "nutrition": existing_macros.get("nutrition", []),
            }
            energy_prediction = {
                **existing_prediction,
                "calories": calories,
                "carbs_g": data.get("carbs_grams"),
                "protein_g": data.get("protein_grams"),
                "fat_g": data.get("fat_grams"),
                "micronutrients": data.get("key_micronutrients") or [],
                "energy_impact": data.get("energy_impact"),
                "energy_timeline": data.get("energy_timeline"),
                "health_score": data.get("health_score"),
                "health_note": data.get("coach_note") or (food_log.energy_prediction or {}).get("health_note"),
                "analysis": (
                    f"Coach note: {', '.join(items)} logged with carbs {macros.get('carbs', 'unknown')}, "
                    f"protein {macros.get('protein', 'unknown')}, fat {macros.get('fat', 'unknown')}. "
                    f"{data.get('coach_note') or data.get('energy_timeline') or 'Energy impact looks portion-dependent.'}"
                )[:700],
                "gemini_analysis": {
                    "enriched_at": datetime.now().isoformat(),
                    "model": self.gemini_model,
                    "health_score": data.get("health_score"),
                },
            }
            food_log.macros = macros
            food_log.energy_prediction = energy_prediction

            self.db.log_system_event(
                event_type="food_intelligence",
                data={
                    "food_log_id": food_log.id,
                    "items": items,
                    "timestamp": food_log.timestamp.isoformat() if food_log.timestamp else None,
                    "calories": data.get("total_calories"),
                    "carbs_g": data.get("carbs_grams"),
                    "protein_g": data.get("protein_grams"),
                    "fat_g": data.get("fat_grams"),
                    "micronutrients": data.get("key_micronutrients") or [],
                    "energy_impact": data.get("energy_impact"),
                    "energy_timeline": data.get("energy_timeline"),
                    "health_score": data.get("health_score"),
                    "coach_note": data.get("coach_note"),
                },
                triggered_by="automation",
            )
            logger.info("Gemini food intelligence saved for food log %s", food_log.id)
            return data
        except Exception as error:
            logger.error("Gemini food intelligence failed for food log %s: %s", getattr(food_log, "id", None), error)
            return None

    async def analyze_energy_patterns(self, energy_logs: list) -> dict | None:
        if len(energy_logs) < 3:
            return None

        timeline = [
            {
                "time": log.timestamp.strftime("%H:%M") if log.timestamp else None,
                "level": log.level,
                "context": log.context or "",
            }
            for log in energy_logs
        ]
        prompt = f"""
Analyze today's energy timeline and predict useful next actions.

Timeline: {timeline}

Return ONLY valid JSON:
{{
  "pattern_type": "morning_person|night_owl|afternoon_peak|inconsistent",
  "peak_hours": "HH:MM-HH:MM or unknown",
  "low_hours": "HH:MM-HH:MM or unknown",
  "likely_triggers": ["trigger"],
  "next_predicted_crash": "HH:MM or unknown",
  "coach_note": "one specific actionable sentence"
}}
"""
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                response = await client.post(
                    f"{self.llm_parser.ollama_url}/api/generate",
                    json={
                        "model": self.llm_parser.model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                )
            if response.status_code != 200:
                return None
            data = self._extract_json(response.json().get("response", ""))
            if not data:
                return None
            self.db.log_system_event(
                event_type="energy_pattern_intelligence",
                data={
                    "date": datetime.now().date().isoformat(),
                    "pattern_type": data.get("pattern_type"),
                    "peak_hours": data.get("peak_hours"),
                    "low_hours": data.get("low_hours"),
                    "triggers": data.get("likely_triggers") or [],
                    "next_crash": data.get("next_predicted_crash"),
                    "coach_note": data.get("coach_note"),
                },
                triggered_by="automation",
            )
            logger.info("Energy pattern intelligence saved")
            return data
        except Exception as error:
            logger.error("Energy pattern intelligence failed: %s", error)
            return None

    async def run_hourly_intelligence(self) -> dict:
        """Analyze entries added or completed since the previous hourly intelligence pass."""
        from database import EnergyLevel, FoodLog, SystemEvent, Task

        logger.info("Running hourly intelligence enrichment...")
        now = datetime.now()
        session = self.db.get_session()
        try:
            latest_check = (
                session.query(SystemEvent.timestamp)
                .filter(SystemEvent.event_type == "background_intelligence_check")
                .order_by(SystemEvent.timestamp.desc())
                .first()
            )
            since = latest_check[0] if latest_check else now - timedelta(hours=1, minutes=5)
            analysis_start = min(since, now - timedelta(hours=24))

            tasks = session.query(Task).filter(
                (
                    (Task.created_at >= analysis_start)
                    | ((Task.completed_at.isnot(None)) & (Task.completed_at >= analysis_start))
                ),
                Task.created_at <= now,
            ).all()
            foods = session.query(FoodLog).filter(
                FoodLog.timestamp >= analysis_start,
                FoodLog.timestamp <= now,
            ).all()

            task_count = 0
            for task in tasks:
                if self._system_event_exists(session, "task_intelligence", "task_id", task.id):
                    continue
                result = await self.analyze_task_intelligence(task)
                if result:
                    task_count += 1
                await asyncio.sleep(0.5)

            food_count = 0
            for food in foods:
                if self._system_event_exists(session, "food_intelligence", "food_log_id", food.id):
                    continue
                result = await self.analyze_food_with_gemini(food)
                if result:
                    food_count += 1
                await asyncio.sleep(0.5)

            today_start = datetime.combine(now.date(), datetime.min.time())
            energy_logs = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= today_start,
                EnergyLevel.timestamp <= now,
                EnergyLevel.predicted == False,
            ).order_by(EnergyLevel.timestamp).all()

            energy_result = None
            last_energy_event = (
                session.query(SystemEvent.timestamp)
                .filter(
                    SystemEvent.event_type == "energy_pattern_intelligence",
                    SystemEvent.timestamp >= today_start,
                )
                .order_by(SystemEvent.timestamp.desc())
                .first()
            )
            if len(energy_logs) >= 3 and (
                not last_energy_event or now - last_energy_event[0] >= timedelta(hours=1)
            ):
                energy_result = await self.analyze_energy_patterns(energy_logs)

            session.commit()
        finally:
            session.close()

        result = {
            "since": since.isoformat(),
            "analysis_start": analysis_start.isoformat(),
            "checked_at": now.isoformat(),
            "tasks_analyzed": task_count,
            "food_logs_analyzed": food_count,
            "energy_pattern_analyzed": bool(energy_result),
        }
        self.db.log_system_event(
            event_type="background_intelligence_check",
            data=result,
            triggered_by="automation",
        )
        logger.info("Hourly intelligence complete: %s", result)
        return result
    
    async def send_telegram_message(self, message: str):
        """Send a message via Telegram bot"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials not configured")
            return
        
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                })
                
                if response.status_code == 200:
                    logger.info("Telegram message sent successfully")
                else:
                    logger.error(f"Failed to send Telegram message: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
    
    async def nightly_summary(self):
        """Generate and send nightly summary at 11:59 PM"""
        logger.info("Generating nightly summary...")
        
        today = datetime.now().date()
        summary_data = self.db.get_daily_summary(today)
        
        if not summary_data or summary_data['tasks_completed'] == 0:
            logger.info("No significant data for summary today")
            return
        
        # Generate AI summary
        summary_text = await self.llm_parser.generate_daily_summary(summary_data)
        
        # Format message
        message = f"""
🌙 *Daily Summary - {today.strftime('%B %d, %Y')}*

{summary_text}

*Stats:*
• Tasks: {summary_data['tasks_completed']} completed, {summary_data['tasks_pending']} pending
• Meals: {summary_data['meals_logged']} logged
• Energy: {'%.1f' % summary_data['avg_energy'] if summary_data['avg_energy'] else 'N/A'}/10

Rest well! 😴
        """
        
        # Send to Telegram
        await self.send_telegram_message(message)
        
        # Log to database
        self.db.log_system_event(
            event_type='daily_summary',
            data=summary_data,
            triggered_by='automation'
        )
        
        logger.info("Nightly summary completed")
    
    async def weekly_review(self):
        """Generate weekly review on Sunday at 9 PM"""
        logger.info("Generating weekly review...")
        
        stats = self.db.get_weekly_stats()
        
        message = f"""
📊 *Weekly Review*

*Productivity:*
• {stats['tasks_completed']} tasks completed
• {stats['completion_rate']:.1f}% completion rate
• {stats['current_streak']} day streak 🔥

*Energy Patterns:*
• Average: {stats['avg_energy']:.1f}/10
• Peak time: {stats['peak_energy_time']}
• Low time: {stats['low_energy_time']}

*Nutrition:*
• {stats['meals_logged']} meals logged
• Top food: {stats['top_food']}

Keep up the great work! 💪
        """
        
        await self.send_telegram_message(message)
        
        self.db.log_system_event(
            event_type='weekly_review',
            data=stats,
            triggered_by='automation'
        )
        
        logger.info("Weekly review completed")
    
    async def check_energy_predictions(self):
        """Check for upcoming energy crashes and send reminders"""
        logger.info("Checking energy predictions...")
        
        # Get food logs from the last 2 hours
        two_hours_ago = datetime.now() - timedelta(hours=2)
        food_logs = self.db.get_food_logs(start_date=two_hours_ago)
        
        now = datetime.now()
        
        for log in food_logs:
            prediction = log.energy_prediction
            if not prediction or prediction.get('status') != 'crash_warning':
                continue
            
            crash_time_str = prediction.get('time_of_crash')
            if not crash_time_str:
                continue
            
            try:
                crash_time = datetime.fromisoformat(crash_time_str)
                
                # If crash is within next 10 minutes, send reminder
                time_until_crash = (crash_time - now).total_seconds() / 60
                
                if 0 <= time_until_crash <= 10:
                    message = f"""
⚠️ *Energy Alert*

{prediction.get('message', 'Energy dip expected soon')}

Consider:
• Taking a short walk
• Having a healthy snack
• Taking a brief break

Stay energized! ⚡
                    """
                    await self.send_telegram_message(message)
                    logger.info(f"Energy warning sent for crash at {crash_time}")
            except Exception as e:
                logger.error(f"Error processing crash time: {e}")
    
    async def contextual_reminders(self):
        """Send contextual reminders based on energy patterns and pending tasks"""
        logger.info("Checking for contextual reminders...")
        
        from database import TaskStatus, Task
        
        # Get pending high-priority or focus-required tasks
        session = self.db.get_session()
        try:
            tasks = session.query(Task).filter(
                Task.status == TaskStatus.PENDING,
                Task.focus_required == True
            ).all()
            
            if not tasks:
                return
            
            # Get current hour
            current_hour = datetime.now().hour
            
            # Get peak energy time
            peak_time = self.db.get_peak_energy_time()
            
            if peak_time:
                peak_hour = int(peak_time.split(':')[0])
                
                # If we're at peak time, suggest focus tasks
                if current_hour == peak_hour:
                    task = tasks[0]  # Get first focus task
                    
                    message = f"""
🎯 *Perfect Timing!*

You're usually at peak energy right now. Great time to tackle:

*{task.description}*

Make it count! 💪
                    """
                    await self.send_telegram_message(message)
                    logger.info(f"Contextual reminder sent for task: {task.description}")
        finally:
            session.close()
    
    async def deadline_reminders(self):
        """Send reminders for upcoming deadlines"""
        logger.info("Checking deadlines...")
        
        from database import TaskStatus, Task
        
        session = self.db.get_session()
        try:
            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            
            # Get tasks due tomorrow or overdue
            tasks = session.query(Task).filter(
                Task.status == TaskStatus.PENDING,
                Task.deadline != None,
                Task.deadline <= tomorrow
            ).all()
            
            if not tasks:
                return
            
            overdue = [t for t in tasks if t.deadline < now]
            due_soon = [t for t in tasks if t.deadline >= now]
            
            if overdue:
                message = "⚠️ *Overdue Tasks*\n\n"
                for task in overdue[:5]:  # Max 5
                    message += f"• {task.description}\n"
                await self.send_telegram_message(message)
            
            if due_soon:
                message = "📅 *Due Tomorrow*\n\n"
                for task in due_soon[:5]:  # Max 5
                    message += f"• {task.description}\n"
                await self.send_telegram_message(message)
            
            logger.info(f"Deadline reminders sent: {len(overdue)} overdue, {len(due_soon)} due soon")
        finally:
            session.close()
    
    async def morning_briefing(self):
        """Send morning briefing at 8 AM"""
        logger.info("Generating morning briefing...")
        
        from database import TaskStatus, Task
        
        session = self.db.get_session()
        try:
            # Get today's pending tasks
            tasks = session.query(Task).filter(
                Task.status == TaskStatus.PENDING
            ).order_by(Task.priority.desc()).limit(5).all()
            
            # Get yesterday's stats
            yesterday = (datetime.now() - timedelta(days=1)).date()
            yesterday_summary = self.db.get_daily_summary(yesterday)
            
            message = f"""
☀️ *Good Morning!*

*Yesterday:*
• {yesterday_summary['tasks_completed']} tasks completed
• Energy avg: {'%.1f' % yesterday_summary['avg_energy'] if yesterday_summary['avg_energy'] else 'N/A'}/10

*Today's Top Tasks:*
"""
            for i, task in enumerate(tasks, 1):
                priority_emoji = "🔴" if task.priority == "high" else "🟡" if task.priority == "medium" else "🟢"
                message += f"{i}. {priority_emoji} {task.description}\n"
            
            # Add peak energy tip
            peak_time = self.db.get_peak_energy_time()
            if peak_time:
                message += f"\n💡 *Tip:* You're usually most energized at {peak_time}"
            
            message += "\n\nHave a productive day! 🚀"
            
            await self.send_telegram_message(message)
            logger.info("Morning briefing sent")
        finally:
            session.close()
    
    async def water_reminder(self):
        """Remind to drink water if not logged by 2 PM"""
        logger.info("Checking water intake...")
        
        today = datetime.now().date()
        start = datetime.combine(today, datetime.min.time())
        
        food_logs = self.db.get_food_logs(start_date=start)
        
        # Check if water was logged
        water_logged = any('water' in [item.lower() for item in log.items] for log in food_logs)
        
        if not water_logged:
            message = """
💧 *Hydration Reminder*

Don't forget to drink water today!

Staying hydrated helps with:
• Energy levels
• Focus and concentration
• Overall health

Take a sip now! 😊
            """
            await self.send_telegram_message(message)
            logger.info("Water reminder sent")

    async def analyze_single_food_item(self, food_item: str) -> dict:
        """Analyze a single food item using internet research for detailed nutritional info."""
        import urllib.parse
        import urllib.request
        import re

        analysis = {
            "item": food_item,
            "researched": False,
            "calories": None,
            "protein_g": None,
            "carbs_g": None,
            "fat_g": None,
            "fiber_g": None,
            "health_notes": [],
            "warnings": [],
        }

        try:
            # Search for nutritional information
            query = urllib.parse.quote_plus(f"{food_item} nutrition facts calories protein carbs fat health benefits")
            url = f"https://duckduckgo.com/html/?q={query}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=8) as response:
                html = response.read(8000).decode("utf-8", errors="ignore")

            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)

            # Extract nutritional info patterns
            calorie_match = re.search(rf"{{0,60}}\b(\d+)\s*k?cal\b.{{0,30}}\b{re.escape(food_item)}\b|{{0,60}}\b{re.escape(food_item)}\b.{{0,30}}\b(\d+)\s*k?cal\b", text, re.IGNORECASE)
            if calorie_match:
                analysis["calories"] = int(calorie_match.group(1) or calorie_match.group(2))

            protein_match = re.search(rf"{{0,40}}\b(\d+\.?\d*)\s*g\s*protein\b", text, re.IGNORECASE)
            if protein_match:
                analysis["protein_g"] = float(protein_match.group(1))

            carb_match = re.search(rf"{{0,40}}\b(\d+\.?\d*)\s*g\s*carb(?:ohydrate)?s?\b", text, re.IGNORECASE)
            if carb_match:
                analysis["carbs_g"] = float(carb_match.group(1))

            fat_match = re.search(rf"{{0,40}}\b(\d+\.?\d*)\s*g\s*fat\b", text, re.IGNORECASE)
            if fat_match:
                analysis["fat_g"] = float(fat_match.group(1))

            # Look for health benefits
            health_keywords = ["rich in", "good source", "contains", "provides", "high in", "antioxidant", "vitamin", "mineral"]
            for keyword in health_keywords:
                matches = re.finditer(rf"{{0,10}}\b{keyword}\b.{{0,100}}", text, re.IGNORECASE)
                for match in matches:
                    snippet = match.group(0).strip()
                    if len(snippet) > 15 and len(snippet) < 150:
                        if snippet not in analysis["health_notes"]:
                            analysis["health_notes"].append(snippet[:200])
                            if len(analysis["health_notes"]) >= 3:
                                break
                if len(analysis["health_notes"]) >= 3:
                    break

            analysis["researched"] = True
            logger.info(f"Analyzed {food_item}: {analysis.get('calories')} kcal")

        except Exception as error:
            logger.error(f"Error analyzing {food_item}: {error}")

        return analysis

    async def enrich_food_logs_with_analysis(self):
        """Enrich today's food logs with detailed nutritional analysis from internet research."""
        logger.info("Enriching food logs with detailed analysis...")

        from database import FoodLog

        today = datetime.now().date()
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())

        session = self.db.get_session()
        try:
            foods = session.query(FoodLog).filter(
                FoodLog.timestamp >= start,
                FoodLog.timestamp <= end
            ).all()

            enriched_count = 0
            for food in foods:
                if not food.items:
                    continue

                # Skip if already enriched recently
                existing_analysis = (food.energy_prediction or {}).get("detailed_analysis")
                if existing_analysis and existing_analysis.get("enriched_at"):
                    enriched_time = datetime.fromisoformat(existing_analysis["enriched_at"])
                    if datetime.now() - enriched_time < timedelta(hours=2):
                        continue

                # Analyze each food item
                detailed_analyses = []
                for item in food.items:
                    analysis = await self.analyze_single_food_item(item)
                    detailed_analyses.append(analysis)

                # Update the food log with enriched data
                energy_prediction = dict(food.energy_prediction or {})
                energy_prediction["detailed_analysis"] = {
                    "enriched_at": datetime.now().isoformat(),
                    "items": detailed_analyses,
                    "summary": self._summarize_food_analyses(detailed_analyses),
                }
                food.energy_prediction = energy_prediction

                enriched_count += 1

            session.commit()
            logger.info(f"Enriched {enriched_count} food logs with analysis")
            return enriched_count

        finally:
            session.close()

    def _summarize_food_analyses(self, analyses: list) -> str:
        """Create a human-readable summary of food analyses."""
        if not analyses:
            return "No analysis available."

        lines = ["🍽️ Detailed Nutritional Analysis:\n"]

        total_calories = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0

        for analysis in analyses:
            item = analysis.get("item", "Unknown")
            lines.append(f"• **{item}**")

            if analysis.get("calories"):
                cal = analysis["calories"]
                total_calories += cal
                lines.append(f"  - Calories: {cal} kcal")

            if analysis.get("protein_g"):
                protein = analysis["protein_g"]
                total_protein += protein
                lines.append(f"  - Protein: {protein}g")

            if analysis.get("carbs_g"):
                carbs = analysis["carbs_g"]
                total_carbs += carbs
                lines.append(f"  - Carbs: {carbs}g")

            if analysis.get("fat_g"):
                fat = analysis["fat_g"]
                total_fat += fat
                lines.append(f"  - Fat: {fat}g")

            if analysis.get("health_notes"):
                lines.append(f"  - Health: {analysis['health_notes'][0][:80]}...")

            lines.append("")

        if total_calories > 0:
            lines.append(f"**Totals:** {total_calories} kcal | P: {total_protein:.1f}g | C: {total_carbs:.1f}g | F: {total_fat:.1f}g")

        return "\n".join(lines)

    async def hourly_life_coach_analysis(self):
        """Analyze today's behavior and save a running coach note."""
        logger.info("Running hourly life coach analysis...")

        from database import EnergyLevel, FoodLog, HealthLog, SystemEvent, Task

        today = datetime.now().date()
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
        summary = self.db.get_daily_summary(today)

        intelligence_result = await self.run_hourly_intelligence()

        # First, enrich food logs with detailed analysis
        enriched_count = await self.enrich_food_logs_with_analysis()

        session = self.db.get_session()
        try:
            tasks = session.query(Task).filter(
                ((Task.created_at >= start) & (Task.created_at <= end))
                | ((Task.completed_at >= start) & (Task.completed_at <= end))
            ).all()
            foods = session.query(FoodLog).filter(FoodLog.timestamp >= start, FoodLog.timestamp <= end).all()
            energy = session.query(EnergyLevel).filter(EnergyLevel.timestamp >= start, EnergyLevel.timestamp <= end).all()
            health = session.query(HealthLog).filter(HealthLog.timestamp >= start, HealthLog.timestamp <= end).all()
            task_intelligence = session.query(SystemEvent).filter(
                SystemEvent.event_type == "task_intelligence",
                SystemEvent.timestamp >= start,
                SystemEvent.timestamp <= end,
            ).order_by(SystemEvent.timestamp.desc()).limit(8).all()
            food_intelligence = session.query(SystemEvent).filter(
                SystemEvent.event_type == "food_intelligence",
                SystemEvent.timestamp >= start,
                SystemEvent.timestamp <= end,
            ).order_by(SystemEvent.timestamp.desc()).limit(8).all()
            energy_intelligence = session.query(SystemEvent).filter(
                SystemEvent.event_type == "energy_pattern_intelligence",
                SystemEvent.timestamp >= start,
                SystemEvent.timestamp <= end,
            ).order_by(SystemEvent.timestamp.desc()).limit(3).all()
        finally:
            session.close()

        task_insights = [event.data for event in task_intelligence if isinstance(event.data, dict)]
        food_insights = [event.data for event in food_intelligence if isinstance(event.data, dict)]
        energy_insights = [event.data for event in energy_intelligence if isinstance(event.data, dict)]

        data = {
            **summary,
            "background_intelligence": intelligence_result,
            "task_descriptions": [task.description for task in tasks if (task.description or "").strip()][:20],
            "task_intelligence": [
                {
                    "task": insight.get("task_description"),
                    "complexity": insight.get("complexity"),
                    "estimated_hours": (
                        f"{insight.get('estimated_hours_min')}-{insight.get('estimated_hours_max')}"
                        if insight.get("estimated_hours_min") is not None and insight.get("estimated_hours_max") is not None
                        else None
                    ),
                    "domain": insight.get("domain"),
                    "coach_note": insight.get("coach_note"),
                }
                for insight in task_insights
            ],
            "food_entries": [
                {
                    "time": food.timestamp.isoformat() if food.timestamp else None,
                    "items": food.items,
                    "macros": food.macros,
                    "analysis": (food.energy_prediction or {}).get("analysis") if food.energy_prediction else None,
                }
                for food in foods
                if food.items
            ],
            "food_intelligence": [
                {
                    "meal": ", ".join(insight.get("items") or []),
                    "calories": insight.get("calories"),
                    "energy_impact": insight.get("energy_impact"),
                    "health_score": insight.get("health_score"),
                    "coach_note": insight.get("coach_note"),
                }
                for insight in food_insights
            ],
            "energy_entries": [
                {
                    "time": entry.timestamp.isoformat() if entry.timestamp else None,
                    "level": entry.level,
                    "predicted": entry.predicted,
                    "context": entry.context,
                }
                for entry in energy
            ],
            "energy_intelligence": [
                {
                    "pattern": insight.get("pattern_type"),
                    "peak_hours": insight.get("peak_hours"),
                    "low_hours": insight.get("low_hours"),
                    "next_crash": insight.get("next_crash"),
                    "coach_note": insight.get("coach_note"),
                }
                for insight in energy_insights
            ],
            "supplements": [
                supplement
                for log in health
                for supplement in (log.supplements or [])
            ],
        }

        prompt = f"""You are a direct life performance coach. Analyze this day so far.
Use the food timing, work completed, pending work, supplements, energy levels, and the task/food/energy intelligence.
Give: 1) what is helping, 2) what is hurting, 3) the next two actions for the next hour.
Keep it concise and practical. Data: {data}"""

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{self.llm_parser.ollama_url}/api/generate",
                    json={
                        "model": self.llm_parser.model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
            note = response.json().get("response", "Hourly analysis unavailable.") if response.status_code == 200 else "Hourly analysis unavailable."
        except Exception as error:
            logger.error(f"Hourly life coach analysis failed: {error}")
            completed = summary.get("tasks_completed", 0)
            pending = summary.get("tasks_pending", 0)
            meals = summary.get("meals_logged", 0)
            avg_energy = summary.get("avg_energy")
            energy_text = f"{avg_energy:.1f}/10" if avg_energy else "not logged"
            next_action = "log one energy level now" if not avg_energy else "pick one pending task and work it for 25 minutes"
            if meals == 0:
                next_action = "log your first meal or water intake"
            note = (
                f"So far: {completed} tasks completed, {pending} pending, {meals} food entries, "
                f"energy {energy_text}. Helping: visible tracking and task capture. Hurting: gaps in logs make prediction weaker. "
                f"Next hour: {next_action}; then update energy so the pattern gets sharper."
            )

        self.db.log_system_event(
            event_type="hourly_life_coach_analysis",
            data={
                "date": today.isoformat(),
                "summary": summary,
                "background_intelligence": intelligence_result,
                "task_intelligence": data["task_intelligence"],
                "food_intelligence": data["food_intelligence"],
                "energy_intelligence": data["energy_intelligence"],
                "note": note,
            },
            triggered_by="automation",
        )
        logger.info("Hourly life coach analysis saved")
    
    def setup_schedules(self):
        """Set up all scheduled tasks"""
        logger.info("Setting up automation schedules...")
        
        # Nightly summary at 11:59 PM
        self.scheduler.add_job(
            self.nightly_summary,
            CronTrigger(hour=23, minute=59),
            id='nightly_summary'
        )
        
        # Weekly review on Sunday at 9 PM
        self.scheduler.add_job(
            self.weekly_review,
            CronTrigger(day_of_week='sun', hour=21, minute=0),
            id='weekly_review'
        )
        
        # Morning briefing at 8 AM
        self.scheduler.add_job(
            self.morning_briefing,
            CronTrigger(hour=8, minute=0),
            id='morning_briefing'
        )
        
        # Check energy predictions every 15 minutes
        self.scheduler.add_job(
            self.check_energy_predictions,
            CronTrigger(minute='*/15'),
            id='energy_predictions'
        )
        
        # Contextual reminders at peak hours (every hour from 9 AM to 5 PM)
        self.scheduler.add_job(
            self.contextual_reminders,
            CronTrigger(hour='9-17', minute=0),
            id='contextual_reminders'
        )
        
        # Deadline reminders at 9 AM
        self.scheduler.add_job(
            self.deadline_reminders,
            CronTrigger(hour=9, minute=0),
            id='deadline_reminders'
        )
        
        # Water reminder at 2 PM
        self.scheduler.add_job(
            self.water_reminder,
            CronTrigger(hour=14, minute=0),
            id='water_reminder'
        )

        # Running life coach analysis every hour
        self.scheduler.add_job(
            self.hourly_life_coach_analysis,
            CronTrigger(minute=0),
            id='hourly_life_coach_analysis'
        )

        # Half-hourly refresh to enrich food logs with Gemini data (runs every 30 minutes)
        self.scheduler.add_job(
            self.run_hourly_intelligence,
            CronTrigger(minute='*/30'),
            id='half_hourly_refresh'
        )

        logger.info("All schedules configured")
    
    def start(self):
        """Start the automation engine"""
        logger.info("Starting automation engine...")
        self.setup_schedules()
        self.scheduler.start()
        try:
            asyncio.get_running_loop().create_task(self.hourly_life_coach_analysis())
            logger.info("Initial hourly intelligence check scheduled")
        except RuntimeError:
            logger.info("Initial hourly intelligence check skipped; no running event loop")
        logger.info("Automation engine running")
    
    async def run_forever(self):
        """Keep the automation engine running"""
        self.start()
        try:
            # Keep running
            while True:
                await asyncio.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down automation engine...")
            self.scheduler.shutdown()

if __name__ == "__main__":
    engine = AutomationEngine()
    asyncio.run(engine.run_forever())
