#!/usr/bin/env python3
"""
Gemini-backed health screenshot analyzer for Life OS.
"""

import base64
import json
import logging
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from database import Database

logger = logging.getLogger(__name__)

try:
    import certifi
except ImportError:
    certifi = None


class HealthImageAnalyzer:
    """
    Analyzes health tracking images such as sleep schedules, step counts,
    workout logs, heart rate charts, and mixed health app screenshots.
    """

    def __init__(self):
        self.db = Database()
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_HEALTH_MODEL") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if self.api_key:
            logger.info("Gemini health image analyzer initialized with %s", self.model)
        else:
            logger.warning("GEMINI_API_KEY not set - health image analysis disabled")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def analyze_health_image(self, image_path: str, user_context: Optional[str] = None) -> Dict:
        if not self.configured:
            return {
                "success": False,
                "error": "Gemini is not configured. Set GEMINI_API_KEY in .env.",
            }

        try:
            path = Path(image_path)
            image_data = path.read_bytes()
            mime_type = self._guess_mime_type(path)
            logger.info("Analyzing health image: %s", image_path)

            prompt = self._analysis_prompt(user_context)
            analysis_text = await self._generate_content(prompt, [(image_data, mime_type)])
            data = self._parse_json_response(analysis_text)

            self._store_analysis(image_path=image_path, data=data, user_context=user_context)

            logger.info(
                "Health image analyzed: %s - Score: %s/10",
                data.get("data_type"),
                data.get("health_score"),
            )
            return {
                "success": True,
                "data": data,
                "message": data.get("coach_message", "Analysis complete."),
            }
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini health JSON: %s", exc)
            return {
                "success": True,
                "data": {"raw_analysis": getattr(exc, "doc", "")},
                "message": "Analysis complete, but I could not structure the data cleanly.",
            }
        except Exception as exc:
            logger.error("Error analyzing health image: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    async def compare_health_trends(self, image_paths: List[str], comparison_context: Optional[str] = None) -> Dict:
        if not self.configured:
            return {"success": False, "error": "Gemini is not configured. Set GEMINI_API_KEY in .env."}
        if len(image_paths) < 2:
            return {"success": False, "error": "Need at least 2 images to compare."}

        try:
            images = []
            for image_path in image_paths:
                path = Path(image_path)
                images.append((path.read_bytes(), self._guess_mime_type(path)))

            prompt = self._comparison_prompt(comparison_context)
            analysis_text = await self._generate_content(prompt, images)
            data = self._parse_json_response(analysis_text)

            self.db.log_system_event(
                event_type="health_trend_comparison",
                data={
                    "images": image_paths,
                    "comparison_timestamp": datetime.now().isoformat(),
                    "analysis": data,
                    "context": comparison_context,
                },
                triggered_by="health_image_analyzer",
            )

            return {
                "success": True,
                "data": data,
                "message": data.get("coach_message", "Comparison complete."),
            }
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini trend JSON: %s", exc)
            return {
                "success": True,
                "data": {"raw_analysis": getattr(exc, "doc", "")},
                "message": "Comparison complete, but I could not structure the data cleanly.",
            }
        except Exception as exc:
            logger.error("Error comparing health images: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    async def _generate_content(self, prompt: str, images: List[tuple[bytes, str]]) -> str:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        parts = [{"text": prompt}]
        for image_data, mime_type in images:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(image_data).decode("ascii"),
                    }
                }
            )

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        verify = certifi.where() if certifi else True
        async with httpx.AsyncClient(timeout=90.0, verify=verify) as client:
            response = await client.post(api_url, params={"key": self.api_key}, json=payload)
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            raise ValueError("Gemini returned an empty response")
        return text

    def _store_analysis(self, image_path: str, data: Dict, user_context: Optional[str]) -> None:
        self.db.log_system_event(
            event_type="health_image_analysis",
            data={
                "image_path": image_path,
                "analysis_timestamp": datetime.now().isoformat(),
                "data_type": data.get("data_type"),
                "time_period": data.get("time_period"),
                "extracted_data": data.get("extracted_data"),
                "patterns": data.get("patterns"),
                "statistics": data.get("statistics"),
                "health_score": data.get("health_score"),
                "insights": data.get("insights"),
                "coach_message": data.get("coach_message"),
                "user_context": user_context,
            },
            triggered_by="health_image_analyzer",
        )

        data_type = data.get("data_type")
        step_metrics = self._extract_step_metrics(data)
        if data_type == "sleep_schedule":
            self.db.log_health(
                supplements=[],
                metrics={
                    "sleep_analysis": data.get("extracted_data", {}),
                    "sleep_score": data.get("health_score"),
                    "sleep_average_hours": (data.get("statistics") or {}).get("average"),
                    "image_source": image_path,
                },
            )
        elif data_type == "step_count" or step_metrics:
            self.db.log_health(
                supplements=[],
                metrics={
                    **step_metrics,
                    "steps_analysis": data.get("extracted_data", {}),
                    "activity_score": data.get("health_score"),
                    "steps_average": (data.get("statistics") or {}).get("average"),
                    "image_source": image_path,
                },
            )

    def _extract_step_metrics(self, data: Dict) -> Dict:
        """Pull dashboard-ready step fields from step or mixed health screenshots."""
        extracted = data.get("extracted_data") or {}
        metrics = {}

        candidates = [
            extracted.get("steps"),
            extracted.get("step_count"),
            extracted.get("today_steps"),
            extracted.get("steps_today"),
            extracted.get("total_steps"),
        ]
        for value in candidates:
            if isinstance(value, dict):
                value = (
                    value.get("today_steps")
                    or value.get("steps")
                    or value.get("value")
                    or value.get("total")
                )
            steps = self._coerce_int(value)
            if steps is not None:
                metrics["steps"] = steps
                break

        distance_candidates = [
            extracted.get("distance_km"),
            extracted.get("step_distance"),
            extracted.get("today_distance_km"),
            extracted.get("distance"),
        ]
        for value in distance_candidates:
            if isinstance(value, dict):
                value = (
                    value.get("today_distance_km")
                    or value.get("distance_km")
                    or value.get("value")
                    or value.get("total")
                )
            distance = self._coerce_float(value)
            if distance is not None:
                metrics["distance_km"] = distance
                break

        rings = extracted.get("activity_rings") or {}
        if isinstance(rings, dict):
            for source_key, target_key in (
                ("move_calories_current", "active_calories"),
                ("exercise_minutes_current", "exercise_minutes"),
                ("stand_hours_current", "stand_hours"),
            ):
                value = self._coerce_int(rings.get(source_key))
                if value is not None:
                    metrics[target_key] = value

        return metrics

    def _coerce_int(self, value) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        match = re.search(r"\d[\d,]*", str(value))
        return int(match.group(0).replace(",", "")) if match else None

    def _coerce_float(self, value) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None

    def _parse_json_response(self, text: str) -> Dict:
        cleaned = text.strip()
        json_match = re.search(r"```json\s*(.*?)\s*```", cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(1).strip()
        else:
            object_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if object_match:
                cleaned = object_match.group(0)
        return json.loads(cleaned)

    def _guess_mime_type(self, path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(path.name)
        return mime_type or "image/jpeg"

    def _analysis_prompt(self, user_context: Optional[str]) -> str:
        return f"""
You are analyzing a health tracking screenshot/image.

USER CONTEXT: {user_context or "No specific context provided"}

Identify the health data type, extract every visible number/date/time/label,
analyze patterns, and provide practical coaching. Do not invent data that is
not visible. If text is unreadable, say so in the extracted data.

Return only valid JSON with this shape:
{{
  "data_type": "sleep_schedule|step_count|workout_log|heart_rate|mixed|other",
  "time_period": "today|week|month|6months|other",
  "extracted_data": {{}},
  "patterns": {{
    "positive_patterns": [],
    "concerning_patterns": [],
    "trends": "improving|declining|stable|mixed|unknown",
    "notable_events": []
  }},
  "statistics": {{
    "average": null,
    "best": null,
    "worst": null,
    "consistency_score": null
  }},
  "health_score": null,
  "insights": {{
    "strengths": [],
    "weaknesses": [],
    "recommendations": []
  }},
  "coach_message": "Warm, encouraging 2-3 sentence summary with actionable advice"
}}
"""

    def _comparison_prompt(self, comparison_context: Optional[str]) -> str:
        return f"""
You are comparing multiple health tracking screenshots to identify changes.

CONTEXT: {comparison_context or "User wants to understand changes in their health patterns"}

Extract the key metrics from each image, compare them, and return only valid JSON:
{{
  "images_analyzed": 0,
  "data_type": "sleep|steps|workouts|mixed",
  "time_span": "description of total time covered",
  "comparison": {{
    "improvements": [],
    "declines": [],
    "stable_areas": []
  }},
  "trend": "improving|declining|mixed|stable|unknown",
  "key_insights": [],
  "recommendations": [],
  "coach_message": "Encouraging summary with specific next steps"
}}
"""
