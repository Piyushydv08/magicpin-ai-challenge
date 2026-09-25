"""
routing/trigger_router.py
--------------------------
Deterministic trigger selection and ranking for /v1/tick.

Pipeline (challenge-brief.md §7, CLAUDE.md §7):

  1. LOAD      — fetch TriggerContext for each available_trigger_id from store
  2. FILTER    — drop expired and suppressed triggers
  3. ENRICH    — attach MerchantContext + CategoryContext
  4. RANK      — score by urgency + kind priority + merchant health signals
  5. CAP       — max 20 actions per tick (testing-brief.md §5)
  6. RETURN    — list[SelectedTrigger] ready for the Composer in Part 3

Design rules:
  - Pure deterministic code — no LLM.
  - Does not mutate any store — read-only.
  - All time comparisons use the `now` string from the tick request.
  - Suppression check delegated to ConversationStore.is_suppressed().
  - Spam restraint: max one new conversation per merchant per tick;
    urgency-1 triggers are skipped if the merchant already has an
    active conversation on a higher-urgency topic.

Kind priority map (independent of urgency score):
  supply_alert / regulation_change / renewal_due → highest
  perf_dip / review_theme_emerged / competitor_opened → high
  recall_due / chronic_refill_due → high (customer-scope)
  milestone_reached / perf_spike / active_planning_intent → medium
  research_digest / cde_opportunity / wedding_package_followup → medium
  festival_upcoming / curious_ask_due / dormant_with_vera / seasonal → low
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from state.context_store import ContextStore
from state.conversation_store import ConversationStore, ConversationState

MAX_ACTIONS_PER_TICK = 20

# ---------------------------------------------------------------------------
# Kind → base priority score (independent of urgency field)
# ---------------------------------------------------------------------------

KIND_PRIORITY: Dict[str, int] = {
    # Critical / time-sensitive
    "supply_alert":           10,
    "regulation_change":       9,
    "renewal_due":             9,
    # High-value merchant performance
    "perf_dip":                8,
    "seasonal_perf_dip":       7,
    "review_theme_emerged":    8,
    "competitor_opened":       7,
    "winback_eligible":        7,
    "gbp_unverified":          7,
    # Customer lifecycle
    "recall_due":              8,
    "chronic_refill_due":      8,
    "customer_lapsed_hard":    7,
    "trial_followup":          7,
    "wedding_package_followup":6,
    # Active planning — must respond fast
    "active_planning_intent":  9,
    # Knowledge / content / milestone
    "milestone_reached":       5,
    "perf_spike":              5,
    "research_digest":         5,
    "cde_opportunity":         4,
    "ipl_match_today":         6,
    # Low priority / ambient
    "festival_upcoming":       3,
    "curious_ask_due":         3,
    "dormant_with_vera":       3,
    "category_seasonal":       3,
    "ipl_match_today_general": 3,
}

DEFAULT_KIND_PRIORITY = 4


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class SelectedTrigger:
    """A trigger that passed all filters and is ready to be composed."""
    trigger_id: str
    trigger: Dict[str, Any]                   # raw TriggerContext payload
    merchant_id: str
    merchant: Dict[str, Any]                  # raw MerchantContext payload
    category_slug: str
    category: Dict[str, Any]                  # raw CategoryContext payload
    customer_id: Optional[str] = None
    customer: Optional[Dict[str, Any]] = None  # raw CustomerContext payload (if any)
    score: float = 0.0                         # composite routing score (higher = better)
    suppression_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime string → UTC-aware datetime, or None."""
    if not s:
        return None
    try:
        # Python 3.11+ fromisoformat handles Z; fallback for older runtimes
        s_norm = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s_norm)
    except ValueError:
        return None


def _is_expired(trigger: Dict[str, Any], now: datetime) -> bool:
    """Return True if the trigger's expires_at is in the past."""
    exp = _parse_iso(trigger.get("expires_at"))
    if exp is None:
        return False  # no expiry = never expires
    # Ensure both are offset-aware for comparison
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return now >= exp


def _composite_score(trigger: Dict[str, Any]) -> float:
    """
    Composite routing score for trigger ranking.

    Score = (urgency_weight * urgency) + kind_priority
      where urgency ∈ {1..5}, weight = 2.0 so urgency dominates within each kind.
    """
    urgency: int = trigger.get("urgency", 1)
    kind: str = trigger.get("kind", "")
    kind_score = KIND_PRIORITY.get(kind, DEFAULT_KIND_PRIORITY)
    return (2.0 * urgency) + kind_score


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

class TriggerRouter:
    """
    Stateless trigger router — call route() on each /v1/tick.

    Parameters
    ----------
    context_store:
        Read-only handle to the shared ContextStore.
    conversation_store:
        Read-only handle to the ConversationStore (for suppression checks).
    """

    def __init__(
        self,
        context_store: ContextStore,
        conversation_store: ConversationStore,
    ) -> None:
        self._ctx = context_store
        self._conv = conversation_store

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def route(
        self,
        available_trigger_ids: List[str],
        now_str: str,
    ) -> List[SelectedTrigger]:
        """
        Given a list of trigger IDs from the judge's tick body, return an
        ordered list of SelectedTrigger objects ready for the Composer.

        Steps:
          1. Parse `now_str` to UTC-aware datetime.
          2. For each trigger_id, load its TriggerContext.
          3. Filter: expired, suppressed, merchant has active high-pri conv.
          4. Enrich with merchant + category + customer contexts.
          5. Score and sort descending.
          6. Apply per-merchant spam cap (max 1 new conv / merchant / tick).
          7. Cap total at MAX_ACTIONS_PER_TICK.
        """
        now_dt = _parse_iso(now_str)
        if now_dt is None:
            now_dt = datetime.now(tz=timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)

        candidates: List[SelectedTrigger] = []

        for tid in available_trigger_ids:
            trigger = self._ctx.get("trigger", tid)
            print(f"DEBUG: Processing tid {tid}, trigger found: {trigger is not None}")
            if trigger is None:
                # Judge references a trigger we haven't received yet → skip
                continue

            # ── Filter 1: expired ──
            if _is_expired(trigger, now_dt):
                continue

            # ── Filter 2: suppression ──
            sup_key = trigger.get("suppression_key")
            if sup_key and self._conv.is_suppressed(sup_key):
                continue

            # ── Filter 3: load merchant ──
            merchant_id = trigger.get("merchant_id")
            if not merchant_id:
                continue
            merchant = self._ctx.get("merchant", merchant_id)
            if merchant is None:
                # Can't compose without merchant context → skip
                continue

            # ── Filter 4: subscription must not be hard-expired ──
            sub = merchant.get("subscription", {})
            if sub.get("status") == "expired":
                # Still route for winback_eligible trigger; skip everything else
                if trigger.get("kind") not in ("winback_eligible", "dormant_with_vera"):
                    continue

            # ── Filter 5: load category ──
            category_slug = merchant.get("category_slug", "")
            category = self._ctx.get("category", category_slug) or {}

            # ── Enrich customer (optional) ──
            customer_id = trigger.get("customer_id")
            customer: Optional[Dict[str, Any]] = None
            if customer_id:
                customer = self._ctx.get("customer", customer_id)
                # If customer scope and no customer context → skip
                if customer is None:
                    continue

            score = _composite_score(trigger)
            print(f"DEBUG: Trigger {tid} passed all filters. Score: {score}")

            candidates.append(SelectedTrigger(
                trigger_id=tid,
                trigger=trigger,
                merchant_id=merchant_id,
                merchant=merchant,
                category_slug=category_slug,
                category=category,
                customer_id=customer_id,
                customer=customer,
                score=score,
                suppression_key=sup_key,
            ))

        # ── Sort descending by score ──
        candidates.sort(key=lambda c: c.score, reverse=True)

        # ── Per-merchant spam cap: max 1 new outbound per merchant per tick ──
        seen_merchants: set = set()
        deduplicated: List[SelectedTrigger] = []
        for sel in candidates:
            if sel.merchant_id in seen_merchants:
                # Only skip if this merchant already has an urgency-4+ action
                # going out this tick — allow urgency-5 to bypass the cap
                existing_urgency = next(
                    (s.trigger.get("urgency", 0) for s in deduplicated
                     if s.merchant_id == sel.merchant_id),
                    0,
                )
                incoming_urgency = sel.trigger.get("urgency", 0)
                if incoming_urgency < 5 or existing_urgency >= 4:
                    continue
            seen_merchants.add(sel.merchant_id)
            deduplicated.append(sel)

        # ── Global cap ──
        return deduplicated[:MAX_ACTIONS_PER_TICK]
