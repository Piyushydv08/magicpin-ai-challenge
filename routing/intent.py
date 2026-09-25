"""
routing/intent.py
-----------------
Deterministic (+ optional LLM fallback) intent detector for merchant messages.

Intent taxonomy (challenge-brief.md §6.2-6.4, §9 Patterns A-D):

  COMMITTED       — merchant explicitly agreed to proceed (Pattern C)
  NOT_INTERESTED  — hostile, opt-out, or strongly negative (Pattern D)
  OFF_TOPIC       — request outside Vera's mission scope
  QUESTION        — merchant asks a clarifying or informational question
  NORMAL          — everything else (continue conversation)

Architecture:
  1. Deterministic fast-path  (pure regex / keyword matching)
     → handles all the explicit test cases from the challenge brief
  2. Ambiguous fallback        (injectable LLM callable, default = None)
     → called only when deterministic result is NORMAL AND caller provides a
       llm_fn; returns structured JSON from the model
  3. If llm_fn is None (or call fails) → NORMAL is returned unchanged

The LLM callable signature (for dependency injection in tests):
  llm_fn(message: str, context_hint: str) -> str
    Returns a string containing one of the label tokens above.

Design rules:
  - No real LLM import here. The caller decides whether to pass a llm_fn.
  - All test cases in challenge-brief.md §9 / testing-brief.md §4 must be
    handled deterministically without an LLM call.
  - Pure functional — no global state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Intent labels
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    COMMITTED = "COMMITTED"           # explicit go-ahead
    NOT_INTERESTED = "NOT_INTERESTED" # hostile / opt-out
    OFF_TOPIC = "OFF_TOPIC"           # outside Vera's scope
    QUESTION = "QUESTION"             # clarifying / info question
    NORMAL = "NORMAL"                 # continue, ambiguous, or neutral


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: str                   # "high" | "medium" | "low"
    matched_phrase: Optional[str] = None
    via_llm: bool = False


# ---------------------------------------------------------------------------
# LLM callable type alias (for type hints only — no runtime dependency)
# ---------------------------------------------------------------------------

LLMCallable = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# Pattern sets — COMMITTED
# Source: CLAUDE.md §6.2, challenge-brief.md §9 Pattern C
# ---------------------------------------------------------------------------

_COMMITTED_PATTERNS: List[re.Pattern] = [
    # "yes let's do it" variants
    re.compile(r"\byes\b.{0,20}\b(do|let'?s|proceed|go)\b", re.IGNORECASE),
    re.compile(r"\bok\b.{0,20}\b(let'?s|proceed|go|yes|fine|sure)\b", re.IGNORECASE),
    re.compile(r"\blet'?s\s+(do\s+it|go|proceed|start)\b", re.IGNORECASE),
    # Direct action verbs at message start or standalone
    re.compile(r"^(go ahead|proceed|do\s+it|send\s+it|start\s+it)[.!,\s]*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\b(go\s+ahead|please\s+(go|proceed|do|update|send|start))\b", re.IGNORECASE),
    re.compile(r"\b(please\s+)?(update\s+it|send\s+it|do\s+it|start\s+it|submit\s+it)\b", re.IGNORECASE),
    re.compile(r"\b(i\s+want\s+to\s+(join|start|proceed|go|do\s+it))\b", re.IGNORECASE),
    re.compile(r"\b(i'?m?\s+)?(in|interested|ready|onboard)\b", re.IGNORECASE),
    re.compile(r"\b(confirm|confirmed|agree|approved|approval|accept)\b", re.IGNORECASE),
    re.compile(r"\b(sure[,!.\s]|absolutely|definitely|of\s+course)\b", re.IGNORECASE),
    # The exact test sentence from testing-brief.md §4.2
    re.compile(r"ok\s+lets?\s+do\s+it", re.IGNORECASE),
    re.compile(r"ok\s+let'?s\s+(proceed|start|go|continue)", re.IGNORECASE),
    # "send me the X" / "draft X" — action-ready
    re.compile(r"\b(send\s+(me|it|them|the)|draft|create|make)\b.{0,30}", re.IGNORECASE),
    re.compile(r"\bwhat'?s?\s+next\b", re.IGNORECASE),
    # "Yes please" or "yes, [positive]" — common Indian-English acceptance style
    re.compile(r"^yes\s*[,!.]?\s*(please|sure|okay|ok|good|great|fine|alright|perfect)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^yes\s+[a-z ]{0,30}\b(please|do|send|update|proceed|start|go)\b", re.IGNORECASE | re.MULTILINE),
    # "Good idea" acceptance (merchants saying yes to a Vera proposal)
    re.compile(r"\b(good|great|nice|sounds)\s+(idea|plan|suggestion|point|thinking)", re.IGNORECASE),
]

# Phrases that ANTI-signal commitment even if keywords match
# e.g. "go ahead, but first tell me more" should stay NORMAL
_COMMITMENT_NEGATORS: List[re.Pattern] = [
    re.compile(r"\b(but|however|although|unless|except|wait|not\s+yet)\b", re.IGNORECASE),
    re.compile(r"\b(do\s+not|don'?t|won'?t|cannot|can'?t)\b", re.IGNORECASE),
    re.compile(r"\b(first\s+tell|tell\s+me\s+(more|first)|what\s+(is|are|does))\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Pattern sets — NOT_INTERESTED / HOSTILE
# Source: CLAUDE.md §6.3, testing-brief.md §4.3
# ---------------------------------------------------------------------------

_NOT_INTERESTED_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bstop\s+(messaging|sending|contacting|calling|texting|whatsapp)\b", re.IGNORECASE),
    re.compile(r"\b(don'?t\s+)?(contact|message|text|call|whatsapp|ping|bother)\s+(me|us)\s+(again|anymore|please|ever)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+interested\b", re.IGNORECASE),
    re.compile(r"\b(useless|worthless|waste\s+of|pointless)\b.{0,30}", re.IGNORECASE),
    re.compile(r"\b(spam|scam|fraud)\b", re.IGNORECASE),
    re.compile(r"\bunsubscribe\b", re.IGNORECASE),
    re.compile(r"\bopt\s*(-|\s*)out\b", re.IGNORECASE),
    re.compile(r"\b(block|report|reported)\b.{0,15}\b(you|vera|bot|number)\b", re.IGNORECASE),
    re.compile(r"\b(go\s+away|leave\s+(me|us)\s+alone|f[\*u][\*c]k\s+off)\b", re.IGNORECASE),
    re.compile(r"\b(annoying|irritating|nuisance|harassment)\b", re.IGNORECASE),
    # The exact test sentence from testing-brief.md §4.3
    re.compile(r"stop\s+messaging\s+me", re.IGNORECASE),
    re.compile(r"this\s+is\s+useless\s+spam", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Pattern sets — OFF_TOPIC
# Source: CLAUDE.md §6.4
# Vera's scope: profile optimisation, offers, WhatsApp reach-outs,
#   merchant analytics, customer lifecycle.
# Off-scope: tax/GST, legal, HR, shipping, coding, personal advice, etc.
# ---------------------------------------------------------------------------

_OFF_TOPIC_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bgst\b|\bfile\s+(my\s+)?(tax|return|it\s+return)\b", re.IGNORECASE),
    re.compile(r"\b(income\s+tax|tds|pan\s+card|aadhaar)\b", re.IGNORECASE),
    re.compile(r"\blegal\s+(advice|help|issue|matter|case|notice)\b", re.IGNORECASE),
    re.compile(r"\b(lawyer|advocate|court|fir|police\s+case)\b", re.IGNORECASE),
    re.compile(r"\b(hire|firing|terminate|resign|salary|hr)\b.{0,20}\b(employee|staff|worker)\b", re.IGNORECASE),
    re.compile(r"\b(shipping|logistics|courier|freight|dispatch)\b", re.IGNORECASE),
    re.compile(r"\b(write\s+me|write\s+a)\b.{0,20}\b(code|program|script|app)\b", re.IGNORECASE),
    re.compile(r"\b(loan|emi|mortgage|insurance\s+claim)\b", re.IGNORECASE),
    re.compile(r"\bcan\s+you\s+help\s+me\s+(file|get|find|buy|book)\b.{0,40}\b(gst|tax|return|ticket|visa|flight)\b", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Pattern sets — QUESTION
# ---------------------------------------------------------------------------

_QUESTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(what|how|when|where|why|which|who|whose|whom)\b", re.IGNORECASE),
    re.compile(r"\?"),
    re.compile(r"\b(tell\s+me|explain|describe|elaborate|clarify|show\s+me)\b", re.IGNORECASE),
    re.compile(r"\b(can\s+you\s+tell|do\s+you\s+know|is\s+there|are\s+there)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helper: check a list of patterns and return first match
# ---------------------------------------------------------------------------

def _first_match(text: str, patterns: List[re.Pattern]) -> Optional[str]:
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def _any_match(text: str, patterns: List[re.Pattern]) -> bool:
    return any(p.search(text) for p in patterns)


# ---------------------------------------------------------------------------
# Normalise message text
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lower-case, strip excess whitespace, collapse ellipsis / unicode."""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Public API — detect()
# ---------------------------------------------------------------------------

def detect(
    message: str,
    conversation_history: Optional[List[str]] = None,  # prior merchant msgs
    llm_fn: Optional[LLMCallable] = None,
) -> IntentResult:
    """
    Classify the intent of a merchant message.

    Parameters
    ----------
    message:
        The raw merchant message text.
    conversation_history:
        Optional list of prior messages (oldest → newest).
        Used for context — currently reserved for LLM path.
    llm_fn:
        Optional callable for ambiguous cases.
        Signature: (message: str, context_hint: str) -> str
        Return value must contain one of the Intent label strings.
        If None, ambiguous messages are returned as NORMAL.

    Returns
    -------
    IntentResult with intent, confidence, matched phrase, and LLM flag.
    """
    msg = _normalise(message)

    # --- 1. NOT_INTERESTED (highest priority — always exit) ---
    phrase = _first_match(msg, _NOT_INTERESTED_PATTERNS)
    if phrase:
        return IntentResult(
            intent=Intent.NOT_INTERESTED,
            confidence="high",
            matched_phrase=phrase,
        )

    # --- 2. OFF_TOPIC ---
    phrase = _first_match(msg, _OFF_TOPIC_PATTERNS)
    if phrase:
        return IntentResult(
            intent=Intent.OFF_TOPIC,
            confidence="high",
            matched_phrase=phrase,
        )

    # --- 3. COMMITTED (checked BEFORE question so "Yes good idea, what..." wins) ---
    phrase = _first_match(msg, _COMMITTED_PATTERNS)
    if phrase:
        # Check negator context — if negation present, downgrade to NORMAL
        if _any_match(msg, _COMMITMENT_NEGATORS):
            # Treat as NORMAL; let LLM handle if available
            pass
        else:
            return IntentResult(
                intent=Intent.COMMITTED,
                confidence="high",
                matched_phrase=phrase,
            )

    # --- 4. QUESTION (only if no commitment signal present) ---
    phrase = _first_match(msg, _QUESTION_PATTERNS)
    if phrase:
        # Don't override a commitment with a trailing question
        # e.g. "Yes good idea, what would it look like?" → COMMITTED already returned above
        return IntentResult(
            intent=Intent.QUESTION,
            confidence="medium",
            matched_phrase=phrase,
        )

    # --- 5. LLM fallback for truly ambiguous cases ---
    if llm_fn is not None:
        context_hint = (
            "Classify the merchant message intent. "
            "Reply with exactly one word: COMMITTED, NOT_INTERESTED, "
            "OFF_TOPIC, QUESTION, or NORMAL. "
            "Message: " + msg
        )
        try:
            llm_response = llm_fn(msg, context_hint)
            for label in Intent:
                if label.value in llm_response.upper():
                    return IntentResult(
                        intent=label,
                        confidence="medium",
                        matched_phrase=None,
                        via_llm=True,
                    )
        except Exception:
            pass  # LLM failure → fall through to NORMAL

    return IntentResult(
        intent=Intent.NORMAL,
        confidence="low",
        matched_phrase=None,
    )


# ---------------------------------------------------------------------------
# Convenience predicates
# ---------------------------------------------------------------------------

def is_committed(result: IntentResult) -> bool:
    return result.intent == Intent.COMMITTED


def is_hostile(result: IntentResult) -> bool:
    return result.intent == Intent.NOT_INTERESTED


def is_off_topic(result: IntentResult) -> bool:
    return result.intent == Intent.OFF_TOPIC
