#!/usr/bin/env python3
"""
Gemini-backed URL analyzer for Life OS.

Fetches page text locally, then asks Gemini to summarize the useful parts.
"""

import logging
import os
import asyncio
import urllib.request
from typing import Dict, Optional

import certifi
import httpx

logger = logging.getLogger(__name__)


class GeminiWebBrowsingAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_WEB_MODEL") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set - web browsing disabled")
        else:
            logger.info("Gemini web browsing agent initialized with %s", self.model)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def browse_url(self, url: str, user_question: Optional[str] = None) -> Dict:
        if not self.configured:
            return {
                "success": False,
                "error": "Web browsing is not configured. Set GEMINI_API_KEY in .env.",
            }

        try:
            page_content = await self._fetch_page(url)
            analysis = await self._analyze_page(url, page_content, user_question)
            return {"success": True, "url": url, "analysis": analysis}
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP status error fetching URL: %s", exc)
            return {
                "success": False,
                "error": f"The page returned HTTP {exc.response.status_code}. It may be blocked or require login.",
            }
        except httpx.HTTPError as exc:
            logger.error("HTTP error fetching URL: %s", exc)
            return {
                "success": False,
                "error": f"Couldn't fetch the URL. It may be blocked or require login. Error: {exc}",
            }
        except Exception as exc:
            logger.error("Error analyzing URL with Gemini: %s", exc, exc_info=True)
            return {"success": False, "error": f"Error analyzing page: {exc}"}

    async def _fetch_page(self, url: str) -> str:
        logger.info("Fetching URL for Gemini analysis: %s", url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }

        def fetch() -> str:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30.0) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                content = response.read(100000)
                return content.decode(charset, errors="replace")

        return await asyncio.to_thread(fetch)

    async def _analyze_page(self, url: str, page_content: str, user_question: Optional[str]) -> str:
        question_block = f'\nThey asked: "{user_question}"\n' if user_question else ""
        prompt = f"""
The user sent this URL: {url}
{question_block}
Here is the fetched page content, truncated if necessary:

{page_content}

Analyze the page and answer the user directly.

If it is a product or shopping page, include:
- Product name
- Price, preserving the currency shown on the page
- What it does
- Top 3-5 features
- Review summary if visible
- Honest recommendation: worth considering or not, and why

If it is an article or blog, include:
- Main topic
- 3-5 key points
- One sentence takeaway

If it is something else, include:
- What the page is about
- Key information the user should know
- Why it may be useful

Be concise, practical, and conversational. Do not invent details that are not visible in the page content.
"""

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }

        async with httpx.AsyncClient(timeout=45.0, verify=certifi.where()) as client:
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
