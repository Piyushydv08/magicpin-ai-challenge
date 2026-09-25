"""
models/schemas.py
-----------------
Pydantic v2 models for all four context types and API request/response bodies.
Field shapes are derived directly from challenge-testing-brief.md §3 and the
real dataset files (dataset/categories/*.json, dataset/merchants_seed.json,
dataset/customers_seed.json, dataset/triggers_seed.json).

Design principles
-----------------
- Use `model_config = ConfigDict(extra="allow")` everywhere so that the store
  can hold arbitrary JSON that the judge might inject without breaking validation.
- All optional fields use `Optional[...]` with a `None` default so partial
  payloads accepted mid-test don't raise validation errors.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared / primitive models
# ---------------------------------------------------------------------------

class VoiceProfile(BaseModel):
    """Category voice rules (tone, vocabulary, taboos)."""
    model_config = ConfigDict(extra="allow")

    tone: Optional[str] = None
    voice_register: Optional[str] = Field(None, alias="register")
    code_mix: Optional[str] = None
    vocab_allowed: List[str] = Field(default_factory=list)
    vocab_taboo: List[str] = Field(default_factory=list)
    salutation_examples: List[str] = Field(default_factory=list)
    tone_examples: List[str] = Field(default_factory=list)


class OfferTemplate(BaseModel):
    """A canonical offer from the category offer catalog."""
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: str
    value: Optional[str] = None
    audience: Optional[str] = None
    type: Optional[str] = None


class PeerStats(BaseModel):
    """Peer benchmarks for the category (city-scoped)."""
    model_config = ConfigDict(extra="allow")

    scope: Optional[str] = None
    avg_rating: Optional[float] = None
    avg_review_count: Optional[int] = None
    avg_views_30d: Optional[int] = None
    avg_calls_30d: Optional[int] = None
    avg_directions_30d: Optional[int] = None
    avg_ctr: Optional[float] = None
    avg_photos: Optional[int] = None
    avg_post_freq_days: Optional[int] = None
    retention_6mo_pct: Optional[float] = None


class DigestItem(BaseModel):
    """One item from the weekly category research/compliance/trend digest."""
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    kind: Optional[str] = None          # research | compliance | cde | trend | tech
    title: Optional[str] = None
    source: Optional[str] = None
    trial_n: Optional[int] = None
    patient_segment: Optional[str] = None
    summary: Optional[str] = None
    actionable: Optional[str] = None
    date: Optional[str] = None
    credits: Optional[int] = None


class ContentItem(BaseModel):
    """Patient-/customer-facing content the merchant can reshare."""
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: Optional[str] = None
    channel: Optional[str] = None
    length_seconds: Optional[int] = None
    body: Optional[str] = None


class SeasonalBeat(BaseModel):
    """Seasonal pattern for the category."""
    model_config = ConfigDict(extra="allow")

    month_range: Optional[str] = None
    note: Optional[str] = None


class TrendSignal(BaseModel):
    """Search-query trend signal."""
    model_config = ConfigDict(extra="allow")

    query: Optional[str] = None
    delta_yoy: Optional[float] = None
    segment_age: Optional[str] = None
    skew: Optional[str] = None


# ---------------------------------------------------------------------------
# 3.1  CategoryContext
# ---------------------------------------------------------------------------

class CategoryContext(BaseModel):
    """
    Slow-changing knowledge pack for one vertical.
    Shared across all merchants in that vertical.
    Matches challenge-testing-brief.md §3.1.
    """
    model_config = ConfigDict(extra="allow")

    slug: str
    display_name: Optional[str] = None
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    offer_catalog: List[OfferTemplate] = Field(default_factory=list)
    peer_stats: PeerStats = Field(default_factory=PeerStats)
    digest: List[DigestItem] = Field(default_factory=list)
    patient_content_library: List[ContentItem] = Field(default_factory=list)
    seasonal_beats: List[SeasonalBeat] = Field(default_factory=list)
    trend_signals: List[TrendSignal] = Field(default_factory=list)
    regulatory_authorities: List[str] = Field(default_factory=list)
    professional_journals: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.2  MerchantContext
# ---------------------------------------------------------------------------

class MerchantIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    place_id: Optional[str] = None
    verified: Optional[bool] = None
    languages: List[str] = Field(default_factory=list)
    owner_first_name: Optional[str] = None
    established_year: Optional[int] = None


class MerchantSubscription(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Optional[str] = None          # active | expired | trial
    plan: Optional[str] = None
    days_remaining: Optional[int] = None
    days_since_expiry: Optional[int] = None
    renewed_at: Optional[str] = None


class PerformanceDelta(BaseModel):
    model_config = ConfigDict(extra="allow")

    views_pct: Optional[float] = None
    calls_pct: Optional[float] = None
    ctr_pct: Optional[float] = None


class PerformanceSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    window_days: Optional[int] = None
    views: Optional[int] = None
    calls: Optional[int] = None
    directions: Optional[int] = None
    ctr: Optional[float] = None
    leads: Optional[int] = None
    delta_7d: Optional[PerformanceDelta] = None


class MerchantOffer(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None         # active | expired | paused
    started: Optional[str] = None
    ended: Optional[str] = None


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: Optional[str] = None
    from_: Optional[str] = Field(None, alias="from")
    body: Optional[str] = None
    engagement: Optional[str] = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CustomerAggregate(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_unique_ytd: Optional[int] = None
    lapsed_180d_plus: Optional[int] = None
    retention_6mo_pct: Optional[float] = None
    high_risk_adult_count: Optional[int] = None


class ReviewTheme(BaseModel):
    model_config = ConfigDict(extra="allow")

    theme: Optional[str] = None
    sentiment: Optional[str] = None
    occurrences_30d: Optional[int] = None
    common_quote: Optional[str] = None


class MerchantContext(BaseModel):
    """
    Current state of one merchant.
    Matches challenge-testing-brief.md §3.2.
    """
    model_config = ConfigDict(extra="allow")

    merchant_id: str
    category_slug: Optional[str] = None
    identity: MerchantIdentity = Field(default_factory=MerchantIdentity)
    subscription: MerchantSubscription = Field(default_factory=MerchantSubscription)
    performance: PerformanceSnapshot = Field(default_factory=PerformanceSnapshot)
    offers: List[MerchantOffer] = Field(default_factory=list)
    conversation_history: List[ConversationTurn] = Field(default_factory=list)
    customer_aggregate: CustomerAggregate = Field(default_factory=CustomerAggregate)
    signals: List[str] = Field(default_factory=list)
    review_themes: List[ReviewTheme] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3.3  CustomerContext
# ---------------------------------------------------------------------------

class CustomerIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    phone_redacted: Optional[str] = None
    language_pref: Optional[str] = None
    age_band: Optional[str] = None
    senior_citizen: Optional[bool] = None


class CustomerRelationship(BaseModel):
    model_config = ConfigDict(extra="allow")

    first_visit: Optional[str] = None
    last_visit: Optional[str] = None
    visits_total: Optional[int] = None
    services_received: List[str] = Field(default_factory=list)
    lifetime_value: Optional[float] = None


class CustomerPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    preferred_slots: Optional[str] = None
    channel: Optional[str] = None
    reminder_opt_in: Optional[bool] = None


class CustomerConsent(BaseModel):
    model_config = ConfigDict(extra="allow")

    opted_in_at: Optional[str] = None
    scope: List[str] = Field(default_factory=list)


CustomerState = str  # "new" | "active" | "lapsed_soft" | "lapsed_hard" | "churned"


class CustomerContext(BaseModel):
    """
    Per-customer state with a specific merchant.
    Matches challenge-testing-brief.md §3.3.
    """
    model_config = ConfigDict(extra="allow")

    customer_id: str
    merchant_id: Optional[str] = None
    identity: CustomerIdentity = Field(default_factory=CustomerIdentity)
    relationship: CustomerRelationship = Field(default_factory=CustomerRelationship)
    state: Optional[CustomerState] = None
    preferences: CustomerPreferences = Field(default_factory=CustomerPreferences)
    consent: CustomerConsent = Field(default_factory=CustomerConsent)


# ---------------------------------------------------------------------------
# 3.4  TriggerContext
# ---------------------------------------------------------------------------

class TriggerContext(BaseModel):
    """
    The event that prompts this specific message right now.
    Matches challenge-testing-brief.md §3.4.
    """
    model_config = ConfigDict(extra="allow")

    id: str
    scope: Optional[str] = None          # "merchant" | "customer"
    kind: Optional[str] = None
    source: Optional[str] = None         # "external" | "internal"
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    urgency: Optional[int] = None        # 1-5
    suppression_key: Optional[str] = None
    expires_at: Optional[str] = None


# ---------------------------------------------------------------------------
# HTTP API request/response bodies (used by bot.py endpoints)
# ---------------------------------------------------------------------------

ContextScope = str  # "category" | "merchant" | "customer" | "trigger"
VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


class ContextPushRequest(BaseModel):
    """Request body for POST /v1/context."""
    model_config = ConfigDict(extra="forbid")

    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class ContextPushAccepted(BaseModel):
    accepted: bool = True
    ack_id: str
    stored_at: str


class ContextPushRejected(BaseModel):
    accepted: bool = False
    reason: str
    current_version: Optional[int] = None
    details: Optional[str] = None


class TickRequest(BaseModel):
    """Request body for POST /v1/tick."""
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class TickAction(BaseModel):
    """One proactive send action returned from /v1/tick."""
    model_config = ConfigDict(extra="allow")

    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: str = "vera"               # "vera" | "merchant_on_behalf"
    trigger_id: Optional[str] = None
    template_name: Optional[str] = None
    template_params: List[str] = Field(default_factory=list)
    body: str
    cta: str = "open_ended"             # "open_ended" | "binary_yes_stop" | "none"
    suppression_key: Optional[str] = None
    rationale: str = ""


class TickResponse(BaseModel):
    actions: List[TickAction] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    """Request body for POST /v1/reply."""
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str                      # "merchant" | "customer"
    message: str
    received_at: Optional[str] = None
    turn_number: Optional[int] = None


class ReplySend(BaseModel):
    action: str = "send"
    body: str
    cta: str = "open_ended"
    rationale: str = ""


class ReplyWait(BaseModel):
    action: str = "wait"
    wait_seconds: int = 1800
    rationale: str = ""


class ReplyEnd(BaseModel):
    action: str = "end"
    rationale: str = ""
