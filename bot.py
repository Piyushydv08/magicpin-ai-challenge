"""
bot.py
------
Vera Bot — FastAPI application.

Five HTTP endpoints required by challenge-testing-brief.md §2:
  GET  /v1/healthz   — liveness probe
  GET  /v1/metadata  — bot identity
  POST /v1/context   — receive context push from judge
  POST /v1/tick      — periodic wake-up; initiate proactive messages
  POST /v1/reply     — receive merchant/customer reply; respond

Architecture:
  HTTP layer (this file)
    └─ ContextStore   (state/context_store.py)
    └─ ConversationStore (state/conversation_store.py)
    └─ Composer       (composer/composer.py)  ← wired in Part 3
    └─ TriggerRouter  (routing/trigger_router.py) ← wired in Part 3

Run with:
  uvicorn bot:app --host 0.0.0.0 --port 8080 --reload
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Load .env before anything that reads env-vars
load_dotenv()

from models.schemas import (
    VALID_SCOPES,
    ContextPushAccepted,
    ContextPushRejected,
    ContextPushRequest,
    ReplyEnd,
    ReplyRequest,
    ReplySend,
    ReplyWait,
    TickAction,
    TickRequest,
    TickResponse,
)
from state.context_store import ContextStore
from state.conversation_store import ConversationStore, Conversation
from routing.trigger_router import TriggerRouter
from routing.auto_reply import detect as detect_auto_reply, AutoReplyLabel
from routing.intent import detect as detect_intent, Intent
from composer.composer import EngagementComposer

composer_instance = EngagementComposer()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Vera Bot — magicpin AI Challenge",
    version=os.getenv("BOT_VERSION", "0.2.0"),
    description="Merchant AI assistant (Vera) — Build Vera Better submission.",
)

# ---------------------------------------------------------------------------
# Singletons — one instance shared across all requests (in-process)
# ---------------------------------------------------------------------------

START_TIME: float = time.time()
context_store = ContextStore()
conversation_store = ConversationStore()

# ---------------------------------------------------------------------------
# Global exception handler for validation errors → 400 with useful detail
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return 400 with structured detail instead of FastAPI's default 422."""
    return JSONResponse(
        status_code=400,
        content={
            "accepted": False,
            "reason": "invalid_request",
            "details": str(exc.errors()),
        },
    )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _uptime() -> int:
    return int(time.time() - START_TIME)


# ---------------------------------------------------------------------------
# GET /v1/healthz
# ---------------------------------------------------------------------------

@app.get(
    "/v1/healthz",
    summary="Liveness probe",
    tags=["infrastructure"],
)
async def healthz() -> Dict[str, Any]:
    """
    Returns HTTP 200 as long as the bot process is alive.

    The judge polls this every 60 s during the test window.
    Three consecutive failures → bot disqualified for that slot.

    Response shape (challenge-testing-brief.md §2.4):
      { "status": "ok",
        "uptime_seconds": 3600,
        "contexts_loaded": {"category": 5, "merchant": 50, ...} }
    """
    return {
        "status": "ok",
        "uptime_seconds": _uptime(),
        "contexts_loaded": context_store.counts(),
    }


# ---------------------------------------------------------------------------
# GET /v1/metadata
# ---------------------------------------------------------------------------

@app.get(
    "/v1/metadata",
    summary="Bot identity",
    tags=["infrastructure"],
)
async def metadata() -> Dict[str, Any]:
    """
    Returns bot/team identity information.
    All values are read from the .env file — edit .env to personalise.

    Response shape (challenge-testing-brief.md §2.5):
      { "team_name": "...", "team_members": [...], "model": "...",
        "approach": "...", "contact_email": "...", "version": "...",
        "submitted_at": "..." }
    """
    members_raw = os.getenv("TEAM_MEMBERS", "")
    members = [m.strip() for m in members_raw.split(",") if m.strip()]
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    model = (
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        if provider == "gemini"
        else os.getenv("LLM_MODEL", provider)
    )

    return {
        "team_name": os.getenv("TEAM_NAME", "Team Vera"),
        "team_members": members,
        "model": model,
        "approach": os.getenv(
            "BOT_APPROACH",
            "4-context composer with LLM + deterministic routing",
        ),
        "contact_email": os.getenv("CONTACT_EMAIL", "team@example.com"),
        "version": os.getenv("BOT_VERSION", "0.2.0"),
        "submitted_at": os.getenv("SUBMITTED_AT", _now_iso()),
    }


# ---------------------------------------------------------------------------
# POST /v1/context
# ---------------------------------------------------------------------------

@app.post(
    "/v1/context",
    summary="Receive a context push from the judge",
    tags=["context"],
    responses={
        200: {"description": "Accepted (new or idempotent same-version)"},
        409: {"description": "Stale version — current version is higher"},
        400: {"description": "Malformed request"},
    },
)
async def push_context(
    body: ContextPushRequest,
) -> Union[ContextPushAccepted, ContextPushRejected]:
    """
    Stores or updates one context entry.

    Rules (challenge-testing-brief.md §2.1):
    - Idempotent by (context_id, version): same version → no-op, 200.
    - Higher version → atomically replaces, 200.
    - Lower version → stale_version, 409.
    - Invalid scope → invalid_scope, 400.

    Response shapes:
      200: { "accepted": true,  "ack_id": "ack_...", "stored_at": "..." }
      409: { "accepted": false, "reason": "stale_version", "current_version": N }
      400: { "accepted": false, "reason": "invalid_scope", "details": "..." }
    """
    # Extra scope check (on top of Pydantic) so we can return a precise 400
    if body.scope not in VALID_SCOPES:
        return JSONResponse(
            status_code=400,
            content=ContextPushRejected(
                accepted=False,
                reason="invalid_scope",
                details=f"scope must be one of {sorted(VALID_SCOPES)}",
            ).model_dump(),
        )

    result = context_store.upsert(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
    )

    stored_at = _now_iso()

    if result.accepted:
        return ContextPushAccepted(
            accepted=True,
            ack_id=f"ack_{body.context_id}_v{body.version}",
            stored_at=stored_at,
        )
    else:
        # stale_version → HTTP 409 Conflict (matching brief §2.1 "Response (409)")
        return JSONResponse(
            status_code=409,
            content=ContextPushRejected(
                accepted=False,
                reason=result.reason or "stale_version",
                current_version=result.current_version,
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /v1/tick
# ---------------------------------------------------------------------------

@app.post(
    "/v1/tick",
    summary="Periodic wake-up; bot may initiate proactive messages",
    tags=["core"],
)
async def tick(body: TickRequest) -> TickResponse:
    """
    Called by the judge every 5 simulated minutes.

    The bot inspects its context state and available triggers, then returns
    zero or more proactive send actions.

    This is a STUB that returns an empty action list.
    Real trigger routing + LLM composition are wired in Part 3.

    Response shape (challenge-testing-brief.md §2.2):
      { "actions": [ ... ] }   or   { "actions": [] }
    """
    actions = []
    
    # 1. Use TriggerRouter to select and rank triggers
    router = TriggerRouter(context_store, conversation_store)
    selected_triggers = router.route(
        available_trigger_ids=body.available_triggers,
        now_str=body.now
    )
    
    # 2 & 3. For each selected trigger, compose and validate
    for sel in selected_triggers:
        trigger = sel.trigger
        merchant = sel.merchant
        category = sel.category
        customer = sel.customer
        
        comp_msg = composer_instance.compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conv_state="NEW"
        )
        
        conv_id = f"conv_{merchant.get('merchant_id')}_{trigger.get('id')}_{uuid.uuid4().hex[:8]}"
        
        # Create new conversation
        conv = conversation_store.create(
            conversation_id=conv_id,
            merchant_id=merchant.get("merchant_id", ""),
            customer_id=customer.get("customer_id") if customer else None,
            trigger_id=trigger.get("id", ""),
            suppression_key=trigger.get("suppression_key")
        )
        conv.state = "PITCHING"
        conv.add_message("vera", comp_msg.body, _now_iso())
        conv.record_sent(comp_msg.body)
        conversation_store.update(conv)
        
        # Mark suppression key as sent if available
        sup_key = trigger.get("suppression_key")
        if sup_key:
            conversation_store.suppress(sup_key, conv_id)
            
        actions.append(
            TickAction(
                conversation_id=conv_id,
                merchant_id=merchant.get("merchant_id", ""),
                customer_id=customer.get("customer_id") if customer else None,
                send_as=comp_msg.send_as,
                trigger_id=trigger.get("id", ""),
                body=comp_msg.body,
                cta=comp_msg.cta,
                suppression_key=sup_key,
                rationale=comp_msg.rationale
            )
        )
        
    return TickResponse(actions=actions)


# ---------------------------------------------------------------------------
# POST /v1/reply
# ---------------------------------------------------------------------------

@app.post(
    "/v1/reply",
    summary="Receive a merchant/customer reply; return next bot move",
    tags=["core"],
)
async def reply(
    body: ReplyRequest,
) -> Union[ReplySend, ReplyWait, ReplyEnd]:
    """
    Called synchronously whenever the judge simulates a merchant/customer reply.

    Must respond within 30 seconds (challenge-testing-brief.md §2.3).

    Valid response shapes:
      send: { "action": "send", "body": "...", "cta": "...", "rationale": "..." }
      wait: { "action": "wait", "wait_seconds": N, "rationale": "..." }
      end:  { "action": "end", "rationale": "..." }

    This is a STUB returning a generic send.
    Real intent detection + auto-reply detection + LLM composition are wired
    in Part 6 (reply_handler).
    """
    # Lookup conversation
    conv = conversation_store.get(body.conversation_id)
    if conv is None:
        # Create a new conversation on-the-fly for judge testing
        conv = Conversation(
            conversation_id=body.conversation_id,
            merchant_id=body.merchant_id,
            customer_id=body.customer_id,
            trigger_id="unknown_trigger"
        )
        conversation_store.update(conv)
        
    # Add incoming message
    conv.add_message(
        role=body.from_role,
        body=body.message,
        received_at=body.received_at,
    )

    # Load contexts for this conversation
    merchant = context_store.get("merchant", conv.merchant_id) or {}
    trigger = context_store.get("trigger", conv.trigger_id) or {}
    category_slug = merchant.get("category_slug")
    category = context_store.get("category", category_slug) if category_slug else {}
    customer = context_store.get("customer", conv.customer_id) if conv.customer_id else None

    # Run AutoReplyDetector
    merchant_messages = [m.body for m in conv.messages if m.role == "merchant"]
    ar_result = detect_auto_reply(
        incoming=body.message,
        prior_merchant_messages=merchant_messages[:-1], # Exclude the current message we just added
        current_streak=conv.auto_reply_streak
    )
    conv.auto_reply_streak = ar_result.new_streak
    
    if ar_result.label == AutoReplyLabel.CONFIRMED_AUTO_REPLY:
        conv.state = "AUTO_REPLY"
        conversation_store.update(conv)
        if conv.auto_reply_streak == 2:
            return ReplyWait(
                action="wait",
                wait_seconds=3600,
                rationale="Confirmed auto-reply streak of 2. Backing off for 1 hour."
            )
        else:
            return ReplyEnd(action="end", rationale="Confirmed auto-reply streak >= 3. Ending.")
    elif ar_result.label == AutoReplyLabel.LIKELY_AUTO_REPLY:
        # Nudge once
        comp_msg = composer_instance.compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conv_state="AUTO_REPLY",
            sent_history=conv.last_sent_bodies,
            intent="NORMAL"
        )
        conv.add_message("vera", comp_msg.body, _now_iso())
        conversation_store.update(conv)
        return ReplySend(
            action="send",
            body=comp_msg.body,
            cta=comp_msg.cta,
            rationale="Nudging on likely auto-reply"
        )

    # Run IntentDetector
    intent_res = detect_intent(body.message)
    
    if intent_res.intent == Intent.NOT_INTERESTED:
        conv.state = "NOT_INTERESTED"
        conversation_store.update(conv)
        return ReplyEnd(action="end", rationale=f"Customer intent is {intent_res.intent.name}")
        
    elif intent_res.intent == Intent.OFF_TOPIC:
        # Generate redirect
        comp_msg = composer_instance.compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conv_state=conv.state,
            sent_history=conv.last_sent_bodies,
            intent="OFF_TOPIC"
        )
        conv.add_message("vera", comp_msg.body, _now_iso())
        conversation_store.update(conv)
        return ReplySend(
            action="send",
            body=comp_msg.body,
            cta=comp_msg.cta,
            rationale="Redirecting off-topic response"
        )
        
    elif intent_res.intent == Intent.COMMITTED:
        conv.state = "ACTIONING"
        
    # Cap at 5 turns
    if conv.turn_number >= 5:
        conversation_store.update(conv)
        return ReplyEnd(action="end", rationale="Reached 5-turn conversation limit.")

    # Normal engaged reply
    comp_msg = composer_instance.compose(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
        conv_state=conv.state,
        sent_history=conv.last_sent_bodies,
        intent=intent_res.intent.value
    )
    
    conv.add_message("vera", comp_msg.body, _now_iso())
    conv.record_sent(comp_msg.body)
    conversation_store.update(conv)

    return ReplySend(
        action="send",
        body=comp_msg.body,
        cta=comp_msg.cta,
        rationale=comp_msg.rationale
    )


# ---------------------------------------------------------------------------
# POST /v1/teardown  (optional — spec §11; wipe state on judge signal)
# ---------------------------------------------------------------------------

@app.post(
    "/v1/teardown",
    summary="Wipe all in-memory state (judge calls this at end of test)",
    tags=["infrastructure"],
    include_in_schema=True,  # hide from docs to avoid confusion
)
async def teardown() -> Dict[str, str]:
    context_store.clear()
    conversation_store.clear()
    return {"status": "wiped"}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bot:app",
        host=os.getenv("BOT_HOST", "0.0.0.0"),
        port=int(os.getenv("BOT_PORT", "8080")),
        reload=True,
        log_level="info",
    )
