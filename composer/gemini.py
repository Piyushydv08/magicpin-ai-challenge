"""
composer/gemini.py
------------------
Isolated Google Gemini integration.

Responsibilities:
  - Configure the google-genai client
  - Generate content using the specified model
  - Enforce timeouts (preventing 30-second /v1/reply limit breaches)
  - Handle all SDK errors and return None (graceful degradation)
  - Request structured output via JSON schema

Design rules:
  - No prompt assembly logic here (that belongs in prompts.py)
  - No validation logic here (that belongs in validators.py)
  - The rest of the app must never import google.genai
"""

import json
import logging
import os
from typing import Any, Dict, Optional
import urllib.request
import urllib.error

logger = logging.getLogger("vera.gemini")

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "body": {
            "type": "string",
            "description": "The WhatsApp message text to send to the merchant (50-350 chars)."
        },
        "cta": {
            "type": "string",
            "enum": ["open_ended", "binary_yes_stop", "none"],
            "description": "Call to action type."
        },
        "send_as": {
            "type": "string",
            "enum": ["vera", "merchant_on_behalf"],
            "description": "Persona to send the message as."
        },
        "rationale": {
            "type": "string",
            "description": "Internal 1-2 sentence explanation of why this message is being sent."
        }
    },
    "required": ["body", "cta", "send_as", "rationale"]
}

class GeminiClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        system_instruction: str,
        user_turn: str,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_configured():
            logger.warning("Gemini client called but GEMINI_API_KEY is not set.")
            return None

        body = {
            "contents": [{"parts": [{"text": user_turn}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.15,
                "responseMimeType": "application/json",
                "responseSchema": _OUTPUT_SCHEMA,
            }
        }

        req_body = json.dumps(body).encode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        try:
            req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=15.0)
            data = json.loads(resp.read().decode("utf-8"))
            if "candidates" in data and len(data["candidates"]) > 0:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            logger.error("Gemini returned empty text or no candidates.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Gemini client: {e}")
            return None
