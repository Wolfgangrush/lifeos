#!/usr/bin/env python3
"""Nutrition estimates for food logging.

Values are rough per-serving estimates. They are meant for journaling and trend
tracking, not medical nutrition accounting.
"""

from __future__ import annotations

import json
import os

import httpx


LOCAL_FOOD_ESTIMATES = {
    "samosa": {
        "serving": "1 medium samosa",
        "calories": 260,
        "carbs_g": 32,
        "protein_g": 5,
        "fat_g": 13,
        "health_note": "Fried pastry with a potato filling. Fine occasionally, but low protein and calorie dense.",
        "macros": {"carbs": "high", "protein": "low", "fat": "high"},
    },
    "dal": {
        "serving": "1 bowl",
        "calories": 180,
        "carbs_g": 24,
        "protein_g": 10,
        "fat_g": 5,
        "health_note": "Good protein and fiber source when oil is moderate.",
        "macros": {"carbs": "medium", "protein": "medium", "fat": "low"},
    },
    "rice": {
        "serving": "1 cooked cup",
        "calories": 205,
        "carbs_g": 45,
        "protein_g": 4,
        "fat_g": 0,
        "health_note": "High carbohydrate staple. Pair with protein and vegetables for steadier energy.",
        "macros": {"carbs": "high", "protein": "low", "fat": "low"},
    },
    "chapati": {
        "serving": "1 medium chapati",
        "calories": 120,
        "carbs_g": 18,
        "protein_g": 4,
        "fat_g": 3,
        "health_note": "Useful staple. Better energy profile when paired with protein.",
        "macros": {"carbs": "medium", "protein": "low", "fat": "low"},
    },
    "roti": {
        "serving": "1 medium roti",
        "calories": 120,
        "carbs_g": 18,
        "protein_g": 4,
        "fat_g": 3,
        "health_note": "Useful staple. Better energy profile when paired with protein.",
        "macros": {"carbs": "medium", "protein": "low", "fat": "low"},
    },
    "idli": {
        "serving": "1 idli",
        "calories": 60,
        "carbs_g": 12,
        "protein_g": 2,
        "fat_g": 0,
        "health_note": "Light fermented food. Add sambar for protein.",
        "macros": {"carbs": "medium", "protein": "low", "fat": "low"},
    },
    "dosa": {
        "serving": "1 plain dosa",
        "calories": 170,
        "carbs_g": 28,
        "protein_g": 4,
        "fat_g": 5,
        "health_note": "Moderate meal base. Filling and balance depend heavily on oil and sides.",
        "macros": {"carbs": "medium", "protein": "low", "fat": "medium"},
    },
    "poha": {
        "serving": "1 plate",
        "calories": 250,
        "carbs_g": 45,
        "protein_g": 6,
        "fat_g": 7,
        "health_note": "Carb heavy breakfast. Add peanuts, curd, or eggs for steadier energy.",
        "macros": {"carbs": "high", "protein": "low", "fat": "medium"},
    },
    "tarri poha": {
        "serving": "1 plate",
        "calories": 380,
        "carbs_g": 55,
        "protein_g": 9,
        "fat_g": 14,
        "health_note": "Poha with tarri is carb heavy and can be oily. Half plate is reasonable, but add protein later.",
        "macros": {"carbs": "high", "protein": "medium", "fat": "high"},
    },
}


NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "half": 0.5,
}


def estimate_food(item: str, quantity: float = 1) -> dict:
    key = item.lower().strip()
    base = LOCAL_FOOD_ESTIMATES.get(key)
    if not base:
        return {
            "item": item,
            "quantity": quantity,
            "serving": "1 serving",
            "calories": None,
            "carbs_g": None,
            "protein_g": None,
            "fat_g": None,
            "health_note": "No local estimate yet. Add this food to the nutrition table for better tracking.",
            "macros": {"carbs": "medium", "protein": "low", "fat": "medium"},
            "source": "local fallback",
        }

    estimate = {
        "item": item,
        "quantity": quantity,
        "serving": base["serving"],
        "source": "local estimate",
        "health_note": base["health_note"],
        "macros": base["macros"],
    }
    for field in ("calories", "carbs_g", "protein_g", "fat_g"):
        estimate[field] = round(base[field] * quantity, 1)
    return estimate


def _extract_json(text: str) -> dict | None:
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


async def estimate_food_with_gemini(item: str, quantity: float = 1) -> dict | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = f"""
Estimate nutrition for this Indian food entry: {quantity} serving(s) of "{item}".

Return ONLY valid JSON:
{{
  "item": "{item}",
  "quantity": {quantity},
  "serving": "plain English serving basis",
  "calories": number,
  "carbs_g": number,
  "protein_g": number,
  "fat_g": number,
  "health_note": "one practical sentence",
  "macros": {{"carbs": "low|medium|high", "protein": "low|medium|high", "fat": "low|medium|high"}},
  "source": "gemini estimate"
}}

Use conservative approximate values. Do not provide medical advice.
"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                params={"key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            if response.status_code != 200:
                return None
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = _extract_json(text)
            if not parsed:
                return None
            parsed["source"] = parsed.get("source") or "gemini estimate"
            parsed["item"] = parsed.get("item") or item
            parsed["quantity"] = parsed.get("quantity") or quantity
            parsed["macros"] = parsed.get("macros") or {
                "carbs": "medium",
                "protein": "low",
                "fat": "medium",
            }
            return parsed
    except Exception:
        return None


async def estimate_food_smart(item: str, quantity: float = 1) -> dict:
    mode = os.getenv("NUTRITION_PROVIDER", "local").lower()
    local = estimate_food(item, quantity=quantity)

    should_use_gemini = (
        mode in {"gemini", "auto"}
        and (mode == "gemini" or local.get("source") == "local fallback")
    )
    if should_use_gemini:
        gemini = await estimate_food_with_gemini(item, quantity=quantity)
        if gemini:
            return gemini
    return local


def merge_macros(estimates: list[dict]) -> dict:
    if not estimates:
        return {}
    totals = {
        "carbs_g": sum(e.get("carbs_g") or 0 for e in estimates),
        "protein_g": sum(e.get("protein_g") or 0 for e in estimates),
        "fat_g": sum(e.get("fat_g") or 0 for e in estimates),
    }
    return {
        "carbs": "high" if totals["carbs_g"] >= 30 else "medium" if totals["carbs_g"] >= 12 else "low",
        "protein": "high" if totals["protein_g"] >= 20 else "medium" if totals["protein_g"] >= 8 else "low",
        "fat": "high" if totals["fat_g"] >= 12 else "medium" if totals["fat_g"] >= 5 else "low",
        "calories": sum(e.get("calories") or 0 for e in estimates) or None,
        "nutrition": estimates,
    }
