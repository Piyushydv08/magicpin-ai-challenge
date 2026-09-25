"""
composer/validators.py
-----------------------
Post-generation validation for Gemini output.

Validates the raw parsed dict from Gemini before it is returned as a
ComposedMessage. Checks implemented (challenge-brief.md rules):

  1. Factual grounding: extracts numbers and URLs from the body and ensures
     they exist in the provided context dictionaries. (Names are hard to reliably
     extract deterministically without NLP, so we focus on hard facts).
  2. No URL: unless the URL is explicitly present in the context.
  3. Single primary CTA: rejects competing choices (e.g. "reply YES or NO").
  4. Repetition: >90% Jaccard overlap with prior sent bodies.
  5. Taboo vocabulary: from category.voice.vocab_taboo.
  6. Length sanity: warns if body is > 300 chars (not a hard fail).
  7. Internal jargon exposure.

Returns a ValidationResult with ok=True or ok=False + list of errors.
The Composer will use the errors to drive a 1-shot LLM correction retry.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CTA = {"open_ended", "binary_yes_stop", "none"}
VALID_SEND_AS = {"vera", "merchant_on_behalf"}

INTERNAL_JARGON = [
    "trigger_id", "suppression_key", "context_id", "urgency",
    "merchant_id", "customer_id", "trg_", "m_00", "c_00",
    "perf_dip", "winback_eligible", "recall_due", "LLM", "Gemini",
    "category_slug", "payload", "expires_at",
]

_MULTI_CTA_PATTERN = re.compile(
    r"\b(yes|no|reply\s+\d|option\s+[A-C]|1\.\s|2\.\s)\b.*"
    r"\b(yes|no|reply\s+\d|option\s+[A-C]|1\.\s|2\.\s)\b",
    re.IGNORECASE | re.DOTALL,
)

_URL_PATTERN = re.compile(r"https?://[^\s]+|www\.[^\s]+")

# Strict numbers (including percentages and decimals)
_NUMBER_PATTERN = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?\b")

_DUP_THRESHOLD = 0.90


def _tokenize(text: str) -> set:
    return set(re.findall(r"\w+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return len(ta & tb) / union


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def validate(
    data: Dict[str, Any],
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    sent_history: Optional[List[str]] = None,
) -> ValidationResult:
    """
    Validate a parsed Gemini output dict against factual context.
    """
    res = ValidationResult()
    sent_history = sent_history or []

    # ── 1. Required fields ────────────────────────────────────────────────
    for field_name in ("body", "cta", "send_as", "rationale"):
        if not data.get(field_name):
            res.fail(f"Missing required field: '{field_name}'")

    if not res.ok:
        return res  # can't continue without body

    body: str = str(data["body"]).strip()
    cta: str = str(data.get("cta", "")).strip()
    send_as: str = str(data.get("send_as", "")).strip()
    
    body_lower = body.lower()

    # Create a giant string of all context values for quick existence checks
    # Lowercase everything to make it case-insensitive
    context_dump = (
        json.dumps(category) + 
        json.dumps(merchant) + 
        json.dumps(trigger) + 
        (json.dumps(customer) if customer else "")
    ).lower()

    # ── Factual Grounding (Numbers) ───────────────────────────────────────
    # Extract all numbers and check if they exist in the context
    found_numbers = _NUMBER_PATTERN.findall(body_lower)
    for num in found_numbers:
        # Some tiny numbers (like "1" in "step 1" or "30" in "30 days") 
        # might naturally occur in text without being specific facts.
        # But for the challenge, we strictly check ALL numbers against context.
        # However, to avoid false positives on '24 hours' or '1 question',
        # we allow single digits 1-9 to pass freely.
        if num.isdigit() and 1 <= int(num) <= 9:
            continue
            
        # Strip trailing % if present to check the raw number too
        raw_num = num.rstrip('%')
        
        # Is the number or its stripped version in the context payload string?
        if num not in context_dump and raw_num not in context_dump:
            res.fail(f"Fabrication detected: The number '{num}' is not present in any context payload.")

    # ── No URL ────────────────────────────────────────────────────────────
    urls = _URL_PATTERN.findall(body_lower)
    for url in urls:
        if url not in context_dump:
            res.fail(f"Fabrication detected: The URL '{url}' is not present in the context.")

    # ── Length Sanity ─────────────────────────────────────────────────────
    if len(body) < 20:
        res.fail(f"Body too short ({len(body)} chars, minimum 20)")
    if len(body) > 300:
        # The prompt says "flag (not hard-fail)"
        res.warn(f"Body is unusually long for WhatsApp ({len(body)} chars > 300)")

    # ── CTA validity ──────────────────────────────────────────────────────
    if cta not in VALID_CTA:
        res.fail(f"Invalid cta '{cta}' — must be one of {VALID_CTA}")

    # ── send_as validity ──────────────────────────────────────────────────
    if send_as not in VALID_SEND_AS:
        res.fail(f"Invalid send_as '{send_as}' — must be one of {VALID_SEND_AS}")

    # ── Taboo words ───────────────────────────────────────────────────────
    taboo_words = category.get("voice", {}).get("vocab_taboo", [])
    for word in taboo_words:
        if word.lower() in body_lower:
            res.fail(f"Body contains taboo word: '{word}'")

    # ── Internal jargon exposure ──────────────────────────────────────────
    for jargon in INTERNAL_JARGON:
        if jargon.lower() in body_lower:
            res.fail(f"Body exposes internal term: '{jargon}'")

    # ── Repetition ────────────────────────────────────────────────────────
    for prior in sent_history:
        sim = _jaccard(body, prior)
        if sim >= _DUP_THRESHOLD:
            res.fail(f"Repetition detected: Body is {sim:.0%} similar to a prior message. Do NOT repeat.")
            break

    # ── Multiple competing CTAs in body ───────────────────────────────────
    if _MULTI_CTA_PATTERN.search(body):
        res.fail("Multiple CTAs detected: Provide exactly ONE primary call-to-action choice.")

    return res
