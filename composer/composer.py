"""
composer/composer.py
--------------------
Main composition orchestration.

Coordinates:
  1. Prompt building (prompts.py)
  2. LLM generation (gemini.py)
  3. Output validation (validators.py)
  4. Deterministic fallbacks

Returns a ComposedMessage ready for the /v1/reply or /v1/tick response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from composer.gemini import GeminiClient
from composer.prompts import build_prompt
from composer.validators import validate

logger = logging.getLogger("vera.composer")


# ---------------------------------------------------------------------------
# Output Model
# ---------------------------------------------------------------------------

@dataclass
class ComposedMessage:
    body: str
    cta: str
    send_as: str
    rationale: str
    is_fallback: bool = False


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------

def _fallback_message(trigger_kind: str) -> ComposedMessage:
    """Safe, deterministic fallback when LLM fails or configuration is missing."""
    if trigger_kind == "active_planning_intent":
        body = "Got it! I've noted that down. Let me know if you need anything else to proceed."
    elif trigger_kind in ("supply_alert", "regulation_change"):
        body = "Important update: Please check your dashboard for an urgent regulatory or supply alert."
    elif trigger_kind in ("recall_due", "chronic_refill_due"):
        body = "Just a quick reminder that you have a service or refill due soon. Please check your schedule!"
    else:
        body = "Hi, this is Vera. I have an update regarding your magicpin profile. Please reply when you have a moment."

    return ComposedMessage(
        body=body,
        cta="open_ended",
        send_as="vera",
        rationale="Fallback message due to LLM failure/timeout.",
        is_fallback=True,
    )


# ---------------------------------------------------------------------------
# Composer Pipeline
# ---------------------------------------------------------------------------

class EngagementComposer:
    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self.client = gemini_client or GeminiClient()

    def compose(
        self,
        category: Dict[str, Any],
        merchant: Dict[str, Any],
        trigger: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
        conv_state: str = "NEW",
        sent_history: Optional[List[str]] = None,
        intent: str = "NORMAL",
    ) -> ComposedMessage:
        """
        Generate a merchant-facing message using Gemini.

        Steps:
          1. Build the prompt using the 4 contexts.
          2. Call Gemini (with timeout/schema).
          3. Fallback on API failure.
          4. Validate the structured output.
          5. Fallback on validation failure.
        """
        trigger_kind = trigger.get("kind", "unknown")

        # 1. Build prompt
        sys_instr, user_turn = build_prompt(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conv_state=conv_state,
            sent_history=sent_history,
            intent=intent,
        )

        # 2. Call LLM
        raw_output = self.client.generate(sys_instr, user_turn)
        if raw_output is None:
            logger.warning("Gemini generation failed, using fallback.")
            return _fallback_message(trigger_kind)

        # 3. Validate
        val_result = validate(
            data=raw_output, 
            category=category, 
            merchant=merchant, 
            trigger=trigger, 
            customer=customer, 
            sent_history=sent_history
        )
        
        # 4. Retry once on validation failure
        if not val_result.ok:
            logger.warning(f"Validation failed: {val_result.errors}. Retrying once.")
            
            # Append correction instructions to the user turn
            correction_instruction = (
                "\n\nYOUR PREVIOUS ATTEMPT FAILED VALIDATION WITH THESE ERRORS:\n" +
                "\n".join(f"- {err}" for err in val_result.errors) +
                "\n\nFIX THESE ERRORS STRICTLY. DO NOT FABRICATE FACTS."
            )
            retry_user_turn = user_turn + correction_instruction
            
            raw_output = self.client.generate(sys_instr, retry_user_turn)
            if raw_output is None:
                logger.warning("Gemini generation failed on retry, using fallback.")
                return _fallback_message(trigger_kind)
                
            val_result = validate(
                data=raw_output, 
                category=category, 
                merchant=merchant, 
                trigger=trigger, 
                customer=customer, 
                sent_history=sent_history
            )
            
            if not val_result.ok:
                logger.warning(f"Validation failed on retry: {val_result.errors}. Falling back.")
                return _fallback_message(trigger_kind)

        # 5. Log warnings if any
        if val_result.warnings:
            logger.info(f"Composer warnings: {val_result.warnings}")

        # 6. Return valid message
        return ComposedMessage(
            body=raw_output["body"],
            cta=raw_output["cta"],
            send_as=raw_output["send_as"],
            rationale=raw_output["rationale"],
            is_fallback=False,
        )
