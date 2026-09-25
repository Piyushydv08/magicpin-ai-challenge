"""
routing/auto_reply.py
---------------------
Deterministic auto-reply detector.

Problem (challenge-brief.md §9 Pattern B, §12 open challenge #1):
  40-70% of "merchant replies" on WhatsApp Business are canned auto-replies.
  Production Vera burns 2-3 turns on them. We must detect and exit fast.

Detection strategy — two independent signals, both purely deterministic:

Signal 1 — PHRASE MATCH
  The message matches one of a curated set of canned-reply indicator phrases
  (case-insensitive substring or regex match).

Signal 2 — REPETITION MATCH
  The incoming message is near-identical (≥90% token overlap or exact match)
  to a prior merchant message in the same conversation.

Classification:
  NORMAL              — no signal detected
  LIKELY_AUTO_REPLY   — phrase OR repetition signal fires once
  CONFIRMED_AUTO_REPLY — streak >= 2 (bot must exit / wait)

Streak logic:
  - Each time LIKELY or CONFIRMED fires, auto_reply_streak increments.
  - A NORMAL message resets the streak to 0.
  - The caller (bot.py reply handler) reads streak to decide send/wait/end.

Design rules:
  - Pure deterministic code — no LLM call.
  - All state lives in the Conversation object (streak counter, last message).
  - No imports from routing.intent or routing.trigger_router (no circular deps).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class AutoReplyLabel(str, Enum):
    NORMAL = "NORMAL"
    LIKELY_AUTO_REPLY = "LIKELY_AUTO_REPLY"
    CONFIRMED_AUTO_REPLY = "CONFIRMED_AUTO_REPLY"


@dataclass(frozen=True)
class AutoReplyResult:
    label: AutoReplyLabel
    new_streak: int              # updated streak to write back to Conversation
    matched_phrase: Optional[str] = None   # which canned phrase triggered it
    similarity: Optional[float] = None     # token overlap ratio if repetition fired


# ---------------------------------------------------------------------------
# Canned phrase patterns
# Tuned to match WhatsApp Business auto-reply wording seen in the wild and
# explicitly referenced in challenge-brief.md §6.1 and §9 Pattern B.
# ---------------------------------------------------------------------------

_CANNED_PATTERNS: List[re.Pattern] = [
    # Classic WhatsApp Business templates
    re.compile(r"thank\s+you\s+for\s+contacting", re.IGNORECASE),
    re.compile(r"thanks?\s+for\s+(reaching|getting\s+in)\s+touch", re.IGNORECASE),
    re.compile(r"thanks?\s+for\s+reaching\s+out", re.IGNORECASE),
    re.compile(r"we('?ll|\s+will)\s+be\s+in\s+touch", re.IGNORECASE),
    re.compile(r"our\s+team\s+will\s+(respond|get\s+back|revert)", re.IGNORECASE),
    re.compile(r"will\s+respond\s+shortly", re.IGNORECASE),
    re.compile(r"(reply|respond|revert)\s+(as\s+soon|within|shortly|in\s+\d+)", re.IGNORECASE),
    re.compile(r"i\s+am\s+(an?\s+)?automated\s+assistant", re.IGNORECASE),
    re.compile(r"this\s+is\s+an?\s+(automated|auto)\s+(message|reply|response)", re.IGNORECASE),
    re.compile(r"currently\s+(unavailable|away|busy|not\s+available)", re.IGNORECASE),
    re.compile(r"out\s+of\s+(office|town)", re.IGNORECASE),
    re.compile(r"we\s+(have\s+received|received)\s+your\s+(message|query|inquiry)", re.IGNORECASE),
    re.compile(r"your\s+(message|query|inquiry)\s+has\s+been\s+received", re.IGNORECASE),
    re.compile(r"business\s+hours?\s+(are|:)", re.IGNORECASE),
    re.compile(r"for\s+immediate\s+(assistance|help|support)", re.IGNORECASE),
    re.compile(r"please\s+(leave|send)\s+your\s+(name|number|details)", re.IGNORECASE),
    # Hindi variants seen in Indian WhatsApp Business accounts
    re.compile(r"aapki\s+(madad|jaankari|pareshani)", re.IGNORECASE),
    re.compile(r"hamari\s+team\s+aapko", re.IGNORECASE),
    re.compile(r"shukriya.*jaankari", re.IGNORECASE),
    # Generic "pass to team" deflection (seen in Pattern B)
    re.compile(r"pahuncha\s+d(eti|eta)\s+h(oon|ain)", re.IGNORECASE),
    re.compile(r"team\s+tak\s+pahuncha", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Token-overlap similarity (Jaccard on word tokens)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set:
    """Lower-case word tokens — strip punctuation, split on whitespace."""
    return set(re.findall(r"\w+", text.lower()))


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity between two strings' word-token sets (0.0 – 1.0)."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Threshold for "near-identical" repetition detection
REPETITION_SIMILARITY_THRESHOLD = 0.85

# Streak value at which we escalate to CONFIRMED
CONFIRMED_STREAK_THRESHOLD = 2


def detect(
    incoming: str,
    prior_merchant_messages: List[str],
    current_streak: int,
) -> AutoReplyResult:
    """
    Classify an incoming merchant message as NORMAL / LIKELY / CONFIRMED auto-reply.

    Parameters
    ----------
    incoming:
        The raw text of the merchant's latest message.
    prior_merchant_messages:
        All previous merchant messages in this conversation (oldest → newest),
        used for repetition detection.
    current_streak:
        The conversation's current auto_reply_streak before this message.

    Returns
    -------
    AutoReplyResult with updated streak and classification label.
    """
    # --- Signal 1: phrase match ---
    matched_phrase: Optional[str] = None
    for pattern in _CANNED_PATTERNS:
        m = pattern.search(incoming)
        if m:
            matched_phrase = m.group(0)
            break

    # --- Signal 2: repetition match (vs prior merchant messages) ---
    best_similarity: float = 0.0
    if prior_merchant_messages:
        for prior in prior_merchant_messages:
            sim = _token_overlap(incoming, prior)
            if sim > best_similarity:
                best_similarity = sim

    repetition_hit = best_similarity >= REPETITION_SIMILARITY_THRESHOLD

    # --- Classify ---
    is_auto = matched_phrase is not None or repetition_hit

    if not is_auto:
        # Clean NORMAL message — reset streak
        return AutoReplyResult(
            label=AutoReplyLabel.NORMAL,
            new_streak=0,
            matched_phrase=None,
            similarity=best_similarity if best_similarity > 0 else None,
        )

    new_streak = current_streak + 1

    if new_streak >= CONFIRMED_STREAK_THRESHOLD:
        label = AutoReplyLabel.CONFIRMED_AUTO_REPLY
    else:
        label = AutoReplyLabel.LIKELY_AUTO_REPLY

    return AutoReplyResult(
        label=label,
        new_streak=new_streak,
        matched_phrase=matched_phrase,
        similarity=best_similarity if repetition_hit else None,
    )


def is_auto_reply(result: AutoReplyResult) -> bool:
    """Convenience: True when the label is LIKELY or CONFIRMED."""
    return result.label != AutoReplyLabel.NORMAL


def should_exit(result: AutoReplyResult) -> bool:
    """True when the bot should stop engaging (CONFIRMED or streak >= threshold)."""
    return result.label == AutoReplyLabel.CONFIRMED_AUTO_REPLY
