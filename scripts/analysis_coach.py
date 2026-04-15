#!/usr/bin/env python3
"""
Background Analysis Coach
Runs every hour, analyzes all data, enriches it with internet research
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx
import json
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AnalysisCoach:
    def __init__(self):
        self.db = Database()
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('LLM_MODEL', 'llama3.1:8b')
        self.scheduler = AsyncIOScheduler()

    async def hourly_analysis(self):
        """Run comprehensive analysis every hour"""
        logger.info("🔍 Starting hourly life performance analysis...")

        # Get last hour's data
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # Analyze food logs
        food_logs = self.db.get_food_logs(start_date=one_hour_ago)
        for food_log in food_logs:
            await self._deep_analyze_food(food_log)

        # Analyze tasks
        from database import Task
        session = self.db.get_session()
        try:
            tasks = session.query(Task).filter(
                Task.created_at >= one_hour_ago
            ).all()

            for task in tasks:
                await self._analyze_task_context(task)
        finally:
            session.close()

        # Overall hour analysis
        await self._analyze_hour_performance(one_hour_ago, now)

        logger.info("✅ Hourly analysis complete!")

    async def _deep_analyze_food(self, food_log):
        """Deep analysis of food with internet research"""

        logger.info(f"🍽️ Analyzing food: {food_log.items}")

        # Step 1: Research each food item
        enriched_data = {}

        for food_item in food_log.items:
            # Search internet for nutritional info
            nutrition_info = await self._search_nutrition(food_item)
            enriched_data[food_item] = nutrition_info

        # Step 2: Calculate total nutrition
        total_calories = sum(item.get('calories', 0) for item in enriched_data.values())
        total_protein = sum(item.get('protein_g', 0) for item in enriched_data.values())
        total_carbs = sum(item.get('carbs_g', 0) for item in enriched_data.values())
        total_fat = sum(item.get('fat_g', 0) for item in enriched_data.values())

        # Step 3: Predict energy impact based on time
        eat_time = food_log.timestamp
        hour = eat_time.hour

        energy_analysis = await self._analyze_energy_impact(
            eat_time=eat_time,
            calories=total_calories,
            carbs=total_carbs,
            protein=total_protein,
            fat=total_fat
        )

        # Step 4: Update the food log with analysis
        session = self.db.get_session()
        try:
            from database import FoodLog
            db_food_log = session.query(FoodLog).filter(FoodLog.id == food_log.id).first()

            if db_food_log:
                # Store enriched analysis
                db_food_log.macros = {
                    'calories': total_calories,
                    'protein_g': total_protein,
                    'carbs_g': total_carbs,
                    'fat_g': total_fat,
                    'detailed_breakdown': enriched_data
                }

                db_food_log.energy_prediction = energy_analysis

                session.commit()
                logger.info(f"✅ Enriched food log with {total_calories} calories")
        finally:
            session.close()

    async def _search_nutrition(self, food_item: str) -> dict:
        """Search internet for nutritional information"""

        try:
            # Use DuckDuckGo or similar search
            search_query = f"{food_item} nutrition facts calories protein carbs"

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Simple search approach
                response = await client.get(
                    f"https://api.duckduckgo.com/?q={search_query}&format=json"
                )

                if response.status_code == 200:
                    data = response.json()
                    abstract = data.get('Abstract', '')

                    # Let LLM extract nutrition from search result
                    nutrition = await self._extract_nutrition_from_text(food_item, abstract)
                    return nutrition

        except Exception as e:
            logger.error(f"Error searching nutrition for {food_item}: {e}")

        # Fallback: Ask LLM to estimate
        return await self._estimate_nutrition_llm(food_item)

    async def _extract_nutrition_from_text(self, food_item: str, text: str) -> dict:
        """Use LLM to extract nutrition facts from search results"""

        prompt = f"""
Extract nutritional information for: {food_item}

Search result text:
{text[:500]}

Return JSON with estimated values per standard serving:
{{
  "food": "{food_item}",
  "serving_size": "100g or 1 cup",
  "calories": 0,
  "protein_g": 0,
  "carbs_g": 0,
  "fat_g": 0,
  "fiber_g": 0,
  "sugar_g": 0,
  "health_notes": "brief health impact"
}}

If text doesn't have info, use your knowledge to estimate.
"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    nutrition_text = result.get('response', '{}')
                    return json.loads(nutrition_text)

        except Exception as e:
            logger.error(f"Error extracting nutrition: {e}")

        return {
            "food": food_item,
            "calories": 0,
            "protein_g": 0,
            "carbs_g": 0,
            "fat_g": 0
        }

    async def _estimate_nutrition_llm(self, food_item: str) -> dict:
        """Ask LLM to estimate nutrition based on knowledge"""

        prompt = f"""
Based on your knowledge, estimate nutritional values for: {food_item}

Provide realistic estimates per typical serving.

Return JSON:
{{
  "food": "{food_item}",
  "serving_size": "estimate",
  "calories": 0,
  "protein_g": 0,
  "carbs_g": 0,
  "fat_g": 0,
  "health_notes": "brief impact on energy and health"
}}
"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    nutrition_text = result.get('response', '{}')
                    return json.loads(nutrition_text)

        except Exception as e:
            logger.error(f"Error estimating nutrition: {e}")

        return {
            "food": food_item,
            "calories": 100,
            "protein_g": 3,
            "carbs_g": 20,
            "fat_g": 2
        }

    async def _analyze_energy_impact(self, eat_time, calories, carbs, protein, fat) -> dict:
        """Predict energy impact based on meal composition and timing"""

        hour = eat_time.hour

        # Calculate glycemic load
        glycemic_impact = "high" if carbs > 50 else "medium" if carbs > 20 else "low"

        # Predict crash time
        if carbs > 50 and protein < 15:
            # High carb, low protein = crash incoming
            crash_time = eat_time + timedelta(minutes=45)
            crash_severity = "moderate"
        elif carbs > 70:
            crash_time = eat_time + timedelta(minutes=30)
            crash_severity = "significant"
        elif carbs > 30 and fat < 10:
            crash_time = eat_time + timedelta(minutes=60)
            crash_severity = "mild"
        else:
            crash_time = None
            crash_severity = "none"

        # LLM analysis for detailed prediction
        prompt = f"""
As a nutritionist, analyze this meal's energy impact:

Eaten at: {eat_time.strftime('%I:%M %p')}
- Calories: {calories}
- Carbs: {carbs}g
- Protein: {protein}g
- Fat: {fat}g

Predict:
1. Immediate energy (0-30 mins)
2. Peak energy time
3. When energy will drop
4. Recommendations

Return JSON:
{{
  "immediate_effect": "energy boost/stable/sluggish",
  "peak_time_minutes": 0,
  "crash_expected": true/false,
  "crash_time_minutes": 0,
  "energy_curve": "spike and crash/sustained/slow burn",
  "recommendation": "brief advice",
  "optimal_for": "what this meal is good for"
}}
"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    analysis_text = result.get('response', '{}')
                    analysis = json.loads(analysis_text)

                    return {
                        "status": "crash_warning" if analysis.get('crash_expected') else "stable",
                        "time_of_crash": crash_time.isoformat() if crash_time else None,
                        "glycemic_impact": glycemic_impact,
                        "detailed_analysis": analysis,
                        "message": analysis.get('recommendation', 'Meal logged')
                    }

        except Exception as e:
            logger.error(f"Error analyzing energy: {e}")

        return {
            "status": "analyzed",
            "message": f"Logged: {calories} cal, {carbs}g carbs, {protein}g protein"
        }

    async def _analyze_task_context(self, task):
        """Analyze task in context of user's patterns"""

        prompt = f"""
As a productivity coach, analyze this task:

Task: {task.description}
Created: {task.created_at.strftime('%I:%M %p')}
Status: {task.status}
Priority: {task.priority}

Consider:
1. Is this task scheduled at user's optimal time?
2. What might help complete it?
3. Any patterns or insights?

Return JSON:
{{
  "productivity_score": 0-10,
  "timing_analysis": "good/suboptimal time for this",
  "estimated_effort": "low/medium/high",
  "suggestions": ["tip1", "tip2"],
  "context": "brief insight"
}}
"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    analysis_text = result.get('response', '{}')
                    analysis = json.loads(analysis_text)

                    # Store analysis in system events
                    self.db.log_system_event(
                        event_type='task_analysis',
                        data={
                            'task_id': task.id,
                            'task_description': task.description,
                            'analysis': analysis
                        },
                        triggered_by='analysis_coach'
                    )

                    logger.info(f"📊 Analyzed task: {task.description}")

        except Exception as e:
            logger.error(f"Error analyzing task: {e}")

    async def _analyze_hour_performance(self, start_time, end_time):
        """Overall analysis of the past hour"""

        # Get all data from the hour
        summary = self.db.get_daily_summary(start_time.date())

        prompt = f"""
As a life performance coach, analyze this hour:

Time period: {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')}

Data:
{json.dumps(summary, indent=2)}

Provide:
1. What went well this hour?
2. What could be improved?
3. Pattern observations
4. Recommendation for next hour

Keep it brief and actionable.

Return JSON:
{{
  "hour_rating": 0-10,
  "highlights": ["achievement1", "achievement2"],
  "concerns": ["issue1"],
  "patterns": ["pattern observed"],
  "next_hour_advice": "brief actionable advice"
}}
"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False
                    }
                )

                if response.status_code == 200:
                    result = response.json()
                    analysis_text = result.get('response', '{}')
                    analysis = json.loads(analysis_text)

                    # Store hourly performance analysis
                    self.db.log_system_event(
                        event_type='hourly_performance',
                        data={
                            'time_period': f"{start_time.isoformat()} to {end_time.isoformat()}",
                            'analysis': analysis
                        },
                        triggered_by='analysis_coach'
                    )

                    logger.info(f"📈 Hour rating: {analysis.get('hour_rating', 'N/A')}/10")
                    logger.info(f"💡 Next hour: {analysis.get('next_hour_advice', 'Keep going!')}")

        except Exception as e:
            logger.error(f"Error analyzing hour: {e}")

    def start(self):
        """Start the analysis coach"""
        logger.info("🚀 Starting Analysis Coach...")

        # Schedule hourly analysis
        self.scheduler.add_job(
            self.hourly_analysis,
            'cron',
            minute=0,  # Every hour at :00
            id='hourly_analysis'
        )

        # Also run at :30 for half-hour check
        self.scheduler.add_job(
            self.hourly_analysis,
            'cron',
            minute=30,  # Every hour at :30
            id='half_hourly_analysis'
        )

        self.scheduler.start()
        logger.info("✅ Analysis Coach running! Will analyze every hour.")

    async def run_forever(self):
        """Keep running"""
        self.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down Analysis Coach...")
            self.scheduler.shutdown()

if __name__ == "__main__":
    coach = AnalysisCoach()
    asyncio.run(coach.run_forever())
