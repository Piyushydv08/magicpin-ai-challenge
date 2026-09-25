"""
composer/prompts.py
-------------------
Gemini prompt templates for each trigger kind.

Design goals (challenge-brief.md §5, CLAUDE.md §4-§8):
  - Every prompt injects ONLY data from the four context objects — never invents.
  - Prompts are grounded: merchant name, numbers, trigger-specific facts are
    mandatory slots in the system instruction.
  - Output is WhatsApp-appropriate: concise, single CTA, no jargon.
  - Tone is controlled by CategoryContext.voice (tone, vocab_taboo, salutation).
  - First-touch messages use template-style; free-form for active conversations.
  - Low temperature (0.15) keeps output factual and consistent.

Entry point used by composer.py:
    build_prompt(category, merchant, trigger, customer, conv_state)
        -> (system_instruction: str, user_turn: str)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ── Conversation states that indicate an open free-form window ──────────────
ACTIVE_STATES = {"PITCHING", "QUALIFYING", "COMMITTED", "ACTIONING", "WAITING"}


# ---------------------------------------------------------------------------
# Master system instruction — injected for every call
# ---------------------------------------------------------------------------

_MASTER_SYSTEM = """\
You are Vera, a professional AI business assistant embedded inside the magicpin \
platform. You help local merchants grow through data-driven insights, \
personalised offers, and proactive engagement.

STRICT RULES — never break these:
1. Use ONLY facts from the context sections below. Never invent names, numbers, \
dates, discounts, or capabilities.
2. Address the merchant by their first name or the salutation shown in \
<CATEGORY_VOICE>.
3. Respect <CATEGORY_VOICE> tone and taboo words — never use taboo words.
4. Write in WhatsApp style: short sentences, conversational, NO bullet-point \
walls, NO ALL-CAPS shouting.
5. Include exactly ONE primary call-to-action. No competing CTAs.
6. Do NOT repeat any message body listed in <SENT_HISTORY>.
7. Do NOT use emojis unless the category voice explicitly permits them.
8. If the merchant has already committed to an action (<INTENT>=COMMITTED), \
acknowledge and move forward using clear action words (e.g. "done", "sending", \
"draft", "here", "confirm", "proceed", "next") — do NOT re-qualify or ask \
qualifying questions (e.g. "would you", "do you", "how about").
9. If customer context is absent, do NOT guess customer preferences or history.
10. Never expose internal system terms (trigger_id, suppression_key, urgency, \
context_id) in the message body.
11. Respond ONLY with valid JSON matching the schema — no markdown fences, \
no extra keys.

OUTPUT JSON SCHEMA (respond with this exact structure):
{
  "body": "<WhatsApp message text, 50-350 chars>",
  "cta": "<one of: open_ended | binary_yes_stop | none>",
  "send_as": "<one of: vera | merchant_on_behalf>",
  "rationale": "<1-2 sentences explaining why this message now>"
}
"""

# ---------------------------------------------------------------------------
# Context injection helpers
# ---------------------------------------------------------------------------

def _voice_block(category: Dict[str, Any]) -> str:
    voice = category.get("voice", {})
    taboo = voice.get("vocab_taboo", [])
    allowed = voice.get("vocab_allowed", [])
    tone = voice.get("tone", "professional")
    salutations = voice.get("salutation_examples", [])
    examples = voice.get("tone_examples", [])
    lines = [
        f"Tone: {tone}",
        f"Register: {voice.get('register', 'respectful')}",
        f"Code-mix: {voice.get('code_mix', 'english')}",
    ]
    if salutations:
        lines.append(f"Salutation examples: {', '.join(salutations)}")
    if taboo:
        lines.append(f"FORBIDDEN words/phrases: {', '.join(taboo)}")
    if allowed:
        lines.append(f"Preferred clinical/domain vocab: {', '.join(allowed[:8])}")
    if examples:
        lines.append("Tone examples (mirror this register):")
        for ex in examples[:3]:
            lines.append(f"  - \"{ex}\"")
    return "\n".join(lines)


def _merchant_block(merchant: Dict[str, Any]) -> str:
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    sub = merchant.get("subscription", {})
    offers = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
    signals = merchant.get("signals", [])
    review_themes = merchant.get("review_themes", [])
    cust_agg = merchant.get("customer_aggregate", {})

    lines = [
        f"Merchant ID: {merchant.get('merchant_id', '')}",
        f"Name: {identity.get('name', '')}",
        f"Owner first name: {identity.get('owner_first_name', '')}",
        f"City: {identity.get('city', '')} / Locality: {identity.get('locality', '')}",
        f"Established: {identity.get('established_year', 'N/A')}",
        f"GBP verified: {identity.get('verified', False)}",
        f"Languages: {', '.join(identity.get('languages', ['en']))}",
        f"Subscription: {sub.get('status', 'unknown')} / {sub.get('plan', '')} / "
        f"{sub.get('days_remaining', 'N/A')} days remaining",
        "",
        "PERFORMANCE (last 30 days):",
        f"  Views: {perf.get('views', 'N/A')}   Calls: {perf.get('calls', 'N/A')}   "
        f"Directions: {perf.get('directions', 'N/A')}   CTR: {perf.get('ctr', 'N/A')}",
    ]
    delta = perf.get("delta_7d", {})
    if delta:
        parts = []
        for k, v in delta.items():
            if v is not None:
                pct = f"{v*100:+.0f}%"
                parts.append(f"{k.replace('_pct', '')}: {pct}")
        if parts:
            lines.append(f"  7-day delta: {', '.join(parts)}")

    if offers:
        lines.append(f"Active offers: {' | '.join(o.get('title','') for o in offers)}")
    if signals:
        lines.append(f"Platform signals: {', '.join(signals)}")
    if review_themes:
        pos = [r.get("theme") for r in review_themes if r.get("sentiment") == "pos"]
        neg = [r.get("theme") for r in review_themes if r.get("sentiment") == "neg"]
        if pos:
            lines.append(f"Positive review themes: {', '.join(pos)}")
        if neg:
            lines.append(f"Negative review themes (mention sensitively): {', '.join(neg)}")
    if cust_agg:
        total = cust_agg.get("total_unique_ytd", cust_agg.get("total_active_members"))
        if total:
            lines.append(f"Customer base: {total} unique YTD")

    return "\n".join(lines)


def _trigger_block(trigger: Dict[str, Any]) -> str:
    payload = trigger.get("payload", {})
    lines = [
        f"Trigger ID: {trigger.get('id', '')}",
        f"Kind: {trigger.get('kind', '')}",
        f"Scope: {trigger.get('scope', 'merchant')}",
        f"Source: {trigger.get('source', '')}",
        f"Urgency: {trigger.get('urgency', 1)} / 5",
        f"Expires at: {trigger.get('expires_at', 'N/A')}",
        "Payload:",
    ]
    for k, v in payload.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def _customer_block(customer: Optional[Dict[str, Any]]) -> str:
    if not customer:
        return "No customer context available — do NOT invent customer data."
    identity = customer.get("identity", {})
    rel = customer.get("relationship", {})
    prefs = customer.get("preferences", {})
    consent = customer.get("consent", {})
    consent_scope = consent.get("scope", [])
    lines = [
        f"Customer ID: {customer.get('customer_id', '')}",
        f"Name: {identity.get('name', 'Customer')}",
        f"Language pref: {identity.get('language_pref', 'en')}",
        f"Age band: {identity.get('age_band', 'unknown')}",
        f"State: {customer.get('state', 'unknown')}",
        f"Visits: {rel.get('visits_total', 0)}   LTV: ₹{rel.get('lifetime_value', 0)}",
        f"Last visit: {rel.get('last_visit', 'N/A')}",
        f"Services: {', '.join(rel.get('services_received', [])[:4])}",
        f"Preferred slots: {prefs.get('preferred_slots', 'N/A')}",
        f"Consent scope: {', '.join(consent_scope) if consent_scope else 'none'}",
    ]
    if not consent_scope:
        lines.append("WARNING: No consent — do NOT send unsolicited messages.")
    return "\n".join(lines)


def _digest_block(category: Dict[str, Any], top_item_id: Optional[str]) -> str:
    """Find the specific digest item referenced by a trigger payload."""
    digest = category.get("digest", [])
    if not digest:
        return ""
    if top_item_id:
        item = next((d for d in digest if d.get("id") == top_item_id), None)
        if item:
            return (
                f"Relevant research/digest item:\n"
                f"  Title: {item.get('title', '')}\n"
                f"  Source: {item.get('source', '')}\n"
                f"  Summary: {item.get('summary', '')}\n"
                f"  Actionable: {item.get('actionable', '')}\n"
                f"  Kind: {item.get('kind', '')}"
            )
    # Fallback: first item
    item = digest[0]
    return f"Top digest item: {item.get('title', '')} ({item.get('source', '')})"


def _conv_block(conv_state: str, sent_history: list, intent: str) -> str:
    lines = [
        f"Conversation state: {conv_state}",
        f"Merchant intent: {intent}",
        f"Is first touch: {conv_state in ('NEW', 'PITCHING')}",
    ]
    if sent_history:
        lines.append("Previous Vera messages (DO NOT repeat):")
        for body in sent_history[-3:]:
            lines.append(f"  - \"{body[:120]}\"")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Kind-specific user-turn instructions
# ---------------------------------------------------------------------------

_KIND_INSTRUCTIONS: Dict[str, str] = {
    "research_digest": (
        "Write a peer-to-peer message sharing ONE specific clinical/professional "
        "insight from the digest item in <DIGEST>. Lead with the finding, cite "
        "the source, state why it affects this merchant's specific patient "
        "cohort. End with a soft question or resource offer. "
        "CTA: open_ended."
    ),
    "regulation_change": (
        "Alert the merchant to a specific regulatory change with a concrete "
        "deadline from the trigger payload. Name the authority, the change, "
        "and ONE specific action they can take before the deadline. "
        "Tone: calm, precise. CTA: binary_yes_stop."
    ),
    "perf_dip": (
        "Reference the specific metric that dropped (from trigger payload: "
        "metric, delta_pct, window, vs_baseline). Connect it to a concrete "
        "hypothesis. Offer ONE specific recovery action. "
        "No generic 'your performance is down' copy. "
        "CTA: binary_yes_stop."
    ),
    "seasonal_perf_dip": (
        "Acknowledge that the dip is expected seasonally (trigger payload: "
        "season_note). Offer a proactive counter-strategy specific to this "
        "category and merchant's offer profile. CTA: open_ended."
    ),
    "renewal_due": (
        "Reference days_remaining from trigger payload exactly. State the plan "
        "name. Make the business-case for renewal using the merchant's actual "
        "performance data (views, CTR, calls). CTA: binary_yes_stop."
    ),
    "winback_eligible": (
        "Acknowledge that the merchant's subscription lapsed. Reference "
        "days_since_expiry and perf_dip_pct from trigger payload. "
        "Frame reactivation as reclaiming lost ground. CTA: binary_yes_stop."
    ),
    "recall_due": (
        "Remind the merchant's patient/customer that their service is due. "
        "Use exact dates from trigger payload. Offer the available slot times. "
        "send_as: merchant_on_behalf. Warm, not clinical. CTA: binary_yes_stop."
    ),
    "chronic_refill_due": (
        "Proactively remind about medication refill timing using molecules "
        "from trigger payload. Reference stock_runs_out_iso date. "
        "Offer delivery if delivery_address_saved=true. "
        "send_as: merchant_on_behalf. CTA: binary_yes_stop."
    ),
    "customer_lapsed_hard": (
        "Re-engage a lapsed customer. Reference previous_focus and "
        "days_since_last_visit from trigger. Acknowledge their absence warmly. "
        "Offer one concrete re-entry path. send_as: merchant_on_behalf. "
        "CTA: binary_yes_stop."
    ),
    "trial_followup": (
        "Follow up after a trial session. Reference trial_date from payload. "
        "Offer the next available session from next_session_options. "
        "send_as: merchant_on_behalf. CTA: binary_yes_stop."
    ),
    "wedding_package_followup": (
        "Follow up on a bridal package. Use wedding_date and days_to_wedding "
        "from payload. Propose the next logical step "
        "(next_step_window_open). send_as: merchant_on_behalf. "
        "Warm and personal. CTA: binary_yes_stop."
    ),
    "active_planning_intent": (
        "The merchant is in active planning mode (intent_topic from payload). "
        "Respond to their last message (merchant_last_message from payload). "
        "Provide ONE concrete next step or draft plan. "
        "Do NOT re-qualify — they already said yes. CTA: open_ended."
    ),
    "milestone_reached": (
        "Celebrate an imminent milestone (value_now → milestone_value from "
        "payload). Propose one action to capitalise on the milestone "
        "(e.g. a post, a promo). Energetic but grounded. CTA: binary_yes_stop."
    ),
    "perf_spike": (
        "Celebrate the positive metric spike. Reference metric, delta_pct, "
        "likely_driver from payload. Suggest capitalising on momentum "
        "with one specific follow-on action. CTA: binary_yes_stop."
    ),
    "review_theme_emerged": (
        "Flag a review theme that has emerged (theme, occurrences_30d, "
        "trend, common_quote from payload). Frame constructively. "
        "Offer ONE specific fix or response strategy. CTA: binary_yes_stop."
    ),
    "competitor_opened": (
        "A competitor has opened nearby (competitor_name, distance_km, "
        "their_offer from payload). Frame as market intelligence, not panic. "
        "Suggest ONE defensive action. CTA: binary_yes_stop."
    ),
    "gbp_unverified": (
        "Merchant's Google Business Profile is unverified. Reference "
        "estimated_uplift_pct from payload. Walk them through the "
        "verification_path in one sentence. CTA: binary_yes_stop."
    ),
    "supply_alert": (
        "URGENT: reference the specific molecule, affected_batches, and "
        "manufacturer from trigger payload. State the actionable step "
        "clearly. Calm, precise pharmacy-voice. CTA: binary_yes_stop."
    ),
    "festival_upcoming": (
        "Upcoming festival: reference festival name and days_until from "
        "payload. Propose ONE category-appropriate seasonal action. "
        "Not generic hype. CTA: binary_yes_stop."
    ),
    "ipl_match_today": (
        "Match day: reference match name and match_time_iso from payload. "
        "Connect to a specific restaurant opportunity (dine-in spike, "
        "delivery surge). CTA: binary_yes_stop."
    ),
    "category_seasonal": (
        "Reference the season and ONE specific trend from the trends list "
        "in the payload. Propose a concrete shelf/stock action. "
        "CTA: open_ended."
    ),
    "cde_opportunity": (
        "Share a continuing education opportunity from the digest item. "
        "Reference credits and fee from payload. Peer-voice, collegial. "
        "CTA: binary_yes_stop."
    ),
    "curious_ask_due": (
        "Ask ONE genuinely curious question about what's working / what "
        "the merchant needs this week. Short, friendly, open. "
        "CTA: open_ended."
    ),
    "dormant_with_vera": (
        "Re-open the conversation after dormancy. Reference last_topic "
        "and days_since_last_merchant_message from payload. "
        "Low-pressure check-in. CTA: open_ended."
    ),
}

_DEFAULT_KIND_INSTRUCTION = (
    "Write a relevant, grounded merchant message based on the trigger payload. "
    "Be specific — reference at least two concrete facts from the context. "
    "CTA: open_ended."
)


# ---------------------------------------------------------------------------
# Public: build_prompt()
# ---------------------------------------------------------------------------

def build_prompt(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    conv_state: str = "NEW",
    sent_history: Optional[list] = None,
    intent: str = "NORMAL",
) -> tuple[str, str]:
    """
    Build the (system_instruction, user_turn) pair for a Gemini call.

    Returns
    -------
    system_instruction : str
        The full Gemini system prompt with all four context blocks.
    user_turn : str
        The task instruction for this specific trigger kind.
    """
    sent_history = sent_history or []
    trigger_kind = trigger.get("kind", "unknown")

    # ── Digest item lookup for research/CDE triggers ──
    digest_section = ""
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id") or payload.get("digest_item_id")
    if top_item_id or trigger_kind in ("research_digest", "cde_opportunity"):
        digest_section = "\n<DIGEST>\n" + _digest_block(category, top_item_id) + "\n</DIGEST>"

    # ── Is first touch? → template-style instruction ──
    is_first_touch = conv_state in ("NEW", "PITCHING", "")

    # ── Assemble system instruction ──
    system = (
        _MASTER_SYSTEM
        + "\n\n<CATEGORY_VOICE>\n" + _voice_block(category) + "\n</CATEGORY_VOICE>"
        + "\n\n<MERCHANT>\n" + _merchant_block(merchant) + "\n</MERCHANT>"
        + "\n\n<TRIGGER>\n" + _trigger_block(trigger) + "\n</TRIGGER>"
        + "\n\n<CUSTOMER>\n" + _customer_block(customer) + "\n</CUSTOMER>"
        + "\n\n<CONVERSATION>\n" + _conv_block(conv_state, sent_history, intent)
        + "\n</CONVERSATION>"
        + digest_section
    )

    # ── Kind-specific task instruction ──
    task = _KIND_INSTRUCTIONS.get(trigger_kind, _DEFAULT_KIND_INSTRUCTION)

    # ── First-touch addendum ──
    if is_first_touch:
        task += (
            "\n\nThis is a FIRST-TOUCH message. Use an approved-template style: "
            "introduce yourself briefly (you are Vera, the merchant's business "
            "assistant on magicpin), then deliver the core message. "
            "Keep to 100-200 characters for the opening line."
        )
    else:
        task += (
            "\n\nThis is a FOLLOW-UP message in an active conversation. "
            "Skip re-introduction. Continue naturally from the prior exchange."
        )

    return system, task
