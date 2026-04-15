#!/usr/bin/env python3
"""
LLM Parser for Life OS
Uses local Ollama to parse natural language into structured data.
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Union, List
import httpx

logger = logging.getLogger(__name__)

class LLMParser:
    def __init__(self):
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('LLM_MODEL', 'llama3.1:8b')
        
    async def parse_message(self, message: str) -> Optional[Union[Dict, List[Dict]]]:
        """Parse a natural language message into structured data"""
        
        system_prompt = self._get_system_prompt()
        
        prompt = f"""
Analyze this user input and extract structured data:

"{message}"

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}

Return ONLY a JSON object. No preamble, no explanation, just the JSON.
"""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "format": "json"
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Ollama error: {response.status_code}")
                    return None
                
                result = response.json()
                response_text = result.get('response', '')
                
                # Clean and parse JSON
                parsed = self._extract_json(response_text)
                
                if parsed:
                    # Post-process the parsed data
                    if isinstance(parsed, list):
                        parsed = [self._post_process(entry, message) for entry in parsed if isinstance(entry, dict)]
                    elif isinstance(parsed, dict) and isinstance(parsed.get("entries"), list):
                        parsed["entries"] = [
                            self._post_process(entry, message)
                            for entry in parsed["entries"]
                            if isinstance(entry, dict)
                        ]
                    elif isinstance(parsed, dict):
                        parsed = self._post_process(parsed, message)
                    logger.info(f"Parsed: {json.dumps(parsed, indent=2)}")
                    return parsed
                else:
                    logger.error(f"Could not parse JSON from: {response_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error calling Ollama: {e}")
            return None
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the LLM"""
        return """You are a life-logging data extraction AI. Your ONLY job is to analyze short chat messages and return structured JSON data.

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no explanation, no preamble
2. If the user mentions multiple things in one message, return:
   {"entries": [entry1, entry2, ...]}
3. Categorize each entry into one of these types:
   - task_complete: User finished a task
   - task_pending: User needs to do something
   - food_log: User ate/drank something
   - health_metric: User logged supplements or health data
   - energy_level: User described their energy state
4. Do not log negative statements as positive entries. If the user says they did not take supplements, do not create a supplements entry.

JSON SCHEMAS:

task_complete:
{
  "type": "task_complete",
  "description": "clear task description",
  "timestamp": "ISO datetime or null"
}

task_pending:
{
  "type": "task_pending",
  "description": "clear task description",
  "deadline": "ISO datetime or null",
  "priority": "low/medium/high",
  "focus_required": true/false
}

food_log:
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

health_metric:
{
  "type": "health_metric",
  "timestamp": "ISO datetime",
  "supplements": ["supplement1", "supplement2"],
  "metrics": {"steps": 8000}
}

energy_level:
{
  "type": "energy_level",
  "level": 1-10,
  "context": "why this energy level",
  "timestamp": "ISO datetime"
}

ENERGY PREDICTION RULES:
- High carbs (rice, bread, pasta) → crash_warning in 30-60 mins
- High sugar (sweets, soda) → crash_warning in 20-45 mins  
- Balanced protein+fat+carbs → stable
- High protein+fat → boost_expected
- Coffee/tea → boost_expected for 2-3 hours

TIME PARSING:
- "at 3 PM" → 15:00 today
- "yesterday" → yesterday's date
- "lunch" → 12:00-14:00
- "breakfast" → 07:00-09:00
- "dinner" → 18:00-21:00
- No time specified → current time

PRIORITY DETECTION:
- Words like "urgent", "ASAP", "critical" → high
- Words like "when you get a chance", "eventually" → low
- Default → medium

FOCUS REQUIRED:
- Tasks with "draft", "write", "design", "analyze", "research" → true
- Simple tasks like "call", "email", "buy" → false

Examples:

Input: "Finished drafting the affidavit"
Output: {"type": "task_complete", "description": "Draft the affidavit", "timestamp": null}

Input: "Ate dal and rice at 3 PM"
Output: {"type": "food_log", "timestamp": "2024-01-15T15:00:00", "items": ["dal", "rice"], "macros": {"carbs": "high", "protein": "medium", "fat": "low"}, "energy_prediction": {"status": "crash_warning", "time_of_crash": "2024-01-15T15:45:00", "message": "Heavy carbs detected. Energy dip expected in 45 mins."}}

Input: "Need to file petition by Friday"
Output: {"type": "task_pending", "description": "File petition", "deadline": "2024-01-19T17:00:00", "priority": "high", "focus_required": true}

Input: "Took vitamin D and magnesium"
Output: {"type": "health_metric", "timestamp": "2024-01-15T09:00:00", "supplements": ["vitamin D", "magnesium"], "metrics": {}}

Input: "Feeling sluggish after lunch"
Output: {"type": "energy_level", "level": 4, "context": "Sluggish feeling after lunch", "timestamp": "2024-01-15T13:30:00"}

Input: "ate tarri poha half plate and also did 8000 steps today and need to file circulation for tomorrow for x case"
Output: {"entries":[{"type":"food_log","timestamp":"2024-01-15T13:30:00","items":["tarri poha"],"macros":{"carbs":"high","protein":"medium","fat":"high"},"energy_prediction":{"status":"crash_warning","time_of_crash":"2024-01-15T14:15:00","message":"Tarri poha can be carb-heavy and oily."}},{"type":"health_metric","timestamp":"2024-01-15T13:30:00","supplements":[],"metrics":{"steps":8000}},{"type":"task_pending","description":"File circulation for x case","deadline":"2024-01-16T17:00:00","priority":"high","focus_required":true}]}

Remember: ONLY return the JSON object. Nothing else."""
    
    def _extract_json(self, text: str):
        """Extract JSON from possibly messy text"""
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
        
        # Try to find any JSON object
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _post_process(self, data: Dict, original_message: str) -> Dict:
        """Post-process parsed data for consistency"""
        
        # Ensure timestamps are ISO format
        if 'timestamp' in data and data['timestamp']:
            if isinstance(data['timestamp'], str):
                try:
                    dt = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
                    data['timestamp'] = dt.isoformat()
                except:
                    data['timestamp'] = datetime.now().isoformat()
        
        # Handle relative times
        if 'deadline' in data and data['deadline']:
            data['deadline'] = self._parse_deadline(data['deadline'])
        
        # Ensure energy level is integer
        if 'level' in data:
            try:
                data['level'] = int(data['level'])
                data['level'] = max(1, min(10, data['level']))  # Clamp to 1-10
            except:
                data['level'] = 5
        
        return data
    
    def _parse_deadline(self, deadline_str: str) -> Optional[str]:
        """Parse deadline string to ISO datetime"""
        try:
            # If already ISO format, return as-is
            dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
            return dt.isoformat()
        except:
            pass
        
        # Try relative parsing
        now = datetime.now()
        deadline_lower = deadline_str.lower()
        
        if 'today' in deadline_lower:
            return now.replace(hour=17, minute=0, second=0).isoformat()
        elif 'tomorrow' in deadline_lower:
            return (now + timedelta(days=1)).replace(hour=17, minute=0, second=0).isoformat()
        elif 'monday' in deadline_lower:
            days_ahead = 0 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (now + timedelta(days=days_ahead)).replace(hour=17, minute=0).isoformat()
        # Add more day parsing as needed
        
        # Default: 1 week from now
        return (now + timedelta(days=7)).replace(hour=17, minute=0).isoformat()
    
    async def generate_daily_summary(self, data: Dict) -> str:
        """Generate a daily summary from aggregated data"""
        
        summary_prompt = f"""Generate a brief, encouraging daily summary based on this data:

Tasks Completed: {data.get('tasks_completed', 0)}
Tasks Pending: {data.get('tasks_pending', 0)}
Meals Logged: {data.get('meals_logged', 0)}
Average Energy: {data.get('avg_energy', 'N/A')}/10
Energy Range: {data.get('min_energy', 'N/A')} - {data.get('max_energy', 'N/A')}

Top Foods: {', '.join(data.get('top_foods', []))}
Supplements Taken: {', '.join(data.get('supplements', []))}

Write a 2-3 sentence summary that:
1. Celebrates accomplishments
2. Notes energy patterns
3. Gives a supportive tip for tomorrow

Keep it personal, warm, and actionable. No bullet points."""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": summary_prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get('response', 'No summary available.')
                else:
                    return 'Summary generation unavailable.'
                    
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return 'Summary generation failed.'
    
    async def suggest_optimal_time(self, task_description: str, energy_history: list) -> str:
        """Suggest optimal time for a task based on energy patterns"""
        
        if not energy_history:
            return "No energy data available yet."
        
        # Find average energy by hour
        hourly_energy = {}
        for entry in energy_history:
            hour = entry['hour']
            level = entry['level']
            if hour not in hourly_energy:
                hourly_energy[hour] = []
            hourly_energy[hour].append(level)
        
        # Calculate averages
        avg_by_hour = {
            hour: sum(levels) / len(levels) 
            for hour, levels in hourly_energy.items()
        }
        
        # Find peak hours
        sorted_hours = sorted(avg_by_hour.items(), key=lambda x: x[1], reverse=True)
        
        if sorted_hours:
            best_hour = sorted_hours[0][0]
            best_energy = sorted_hours[0][1]
            
            return f"Based on your patterns, you're usually at {best_energy:.1f}/10 energy around {best_hour}:00. Great time for: {task_description}"
        
        return "Track your energy for a few more days to get personalized suggestions!"
