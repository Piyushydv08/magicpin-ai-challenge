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


class _HttpModels:
    def __init__(self, owner: "GeminiClient"):
        self._owner = owner

    def generate_content(self, **kwargs: Any) -> Any:
        return self._owner._generate_http(kwargs)


class _HttpClient:
    def __init__(self, owner: "GeminiClient"):
        self.models = _HttpModels(owner)

class GeminiClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = _HttpClient(self) if self.api_key else None

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

        if self.client is None:
            logger.warning("Gemini client called but GEMINI_API_KEY is not set.")
            return None

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[{"parts": [{"text": user_turn}]}],
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.15,
                    "response_mime_type": "application/json",
                    "response_schema": _OUTPUT_SCHEMA,
                },
            )
            text = getattr(response, "text", None)
            if text:
                return json.loads(text)
            logger.error("Gemini returned empty text.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Gemini client: {e}")
            return None

    def _generate_http(self, kwargs: Dict[str, Any]) -> Any:
        contents = kwargs.get("contents", [])
        config = kwargs.get("config", {})
        body = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": config.get("system_instruction", "")}]},
            "generationConfig": {
                "temperature": config.get("temperature", 0.15),
                "responseMimeType": config.get("response_mime_type", "application/json"),
                "responseSchema": config.get("response_schema", _OUTPUT_SCHEMA),
            }
        }

        req_body = json.dumps(body).encode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15.0)
        return type("GeminiResponse", (), {"text": json.loads(resp.read().decode("utf-8"))["candidates"][0]["content"]["parts"][0]["text"]})()
