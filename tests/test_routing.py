"""
tests/test_routing.py
---------------------
Deterministic unit tests for all three routing modules.

Test scenario sources:
  - challenge-brief.md §6.1-6.4 (behavioral contract)
  - challenge-brief.md §9 Patterns B (auto-reply hell), C (intent transition),
    D (hostile), plus off-topic (Pattern E implied)
  - challenge-testing-brief.md §4.1 (auto_reply_hell), §4.2 (intent_transition),
    §4.3 (hostile)
  - routing/auto_reply.py canned phrase list
  - routing/intent.py commitment / hostility / off-topic pattern sets

ALL tests use only deterministic logic — no LLM calls.
"""

import pytest
from routing.auto_reply import (
    AutoReplyLabel,
    detect as ar_detect,
    is_auto_reply,
    should_exit,
    CONFIRMED_STREAK_THRESHOLD,
    REPETITION_SIMILARITY_THRESHOLD,
)
from routing.intent import (
    Intent,
    IntentResult,
    detect as intent_detect,
    is_committed,
    is_hostile,
    is_off_topic,
)
from routing.trigger_router import (
    TriggerRouter,
    SelectedTrigger,
    _composite_score,
    _is_expired,
    _parse_iso,
    MAX_ACTIONS_PER_TICK,
)
from state.context_store import ContextStore
from state.conversation_store import ConversationStore


# =============================================================================
# AutoReplyDetector tests
# =============================================================================

class TestAutoReplyPhraseDetection:
    """Pattern B: judge sends the same canned reply 4× in a row."""

    # ── Canonical canned phrases from CLAUDE.md §6.1 ──────────────────────

    def test_thank_you_for_contacting(self):
        r = ar_detect("Thank you for contacting us! Our team will respond shortly.", [], 0)
        assert r.label != AutoReplyLabel.NORMAL
        assert is_auto_reply(r)

    def test_our_team_will_respond(self):
        r = ar_detect("Our team will respond shortly to your query.", [], 0)
        assert is_auto_reply(r)

    def test_automated_assistant(self):
        r = ar_detect("I am an automated assistant. Please wait.", [], 0)
        assert is_auto_reply(r)

    def test_received_your_message(self):
        r = ar_detect("We have received your message and will get back to you.", [], 0)
        assert is_auto_reply(r)

    # ── Exact testing-brief.md §4.1 canned text ───────────────────────────

    def test_exact_testing_brief_canned_text(self):
        """Verbatim auto-reply from testing-brief.md §4.1 example."""
        msg = "Thank you for contacting us! Our team will respond shortly."
        r = ar_detect(msg, [], 0)
        assert is_auto_reply(r), f"Should be auto-reply, got {r.label}"

    # ── More auto-reply variants ───────────────────────────────────────────

    def test_will_reply_within(self):
        r = ar_detect("We will reply within 24 hours.", [], 0)
        assert is_auto_reply(r)

    def test_out_of_office(self):
        r = ar_detect("Currently out of office. Will get back to you soon.", [], 0)
        assert is_auto_reply(r)

    def test_business_hours(self):
        r = ar_detect("Business hours are 9am to 6pm Monday to Saturday.", [], 0)
        assert is_auto_reply(r)

    def test_this_is_automated_message(self):
        r = ar_detect("This is an automated message. Please do not reply.", [], 0)
        assert is_auto_reply(r)

    def test_currently_unavailable(self):
        r = ar_detect("I am currently unavailable. Will respond soon.", [], 0)
        assert is_auto_reply(r)

    def test_thanks_for_reaching_out(self):
        r = ar_detect("Thanks for reaching out! We'll be in touch.", [], 0)
        assert is_auto_reply(r)

    # ── Genuine replies that must NOT fire ────────────────────────────────

    def test_genuine_yes_reply_normal(self):
        r = ar_detect("Yes let's do it!", [], 0)
        assert r.label == AutoReplyLabel.NORMAL

    def test_genuine_question_normal(self):
        r = ar_detect("What kind of offer do you suggest?", [], 0)
        assert r.label == AutoReplyLabel.NORMAL

    def test_genuine_complaint_normal(self):
        r = ar_detect("I need help with my profile photo.", [], 0)
        assert r.label == AutoReplyLabel.NORMAL

    def test_short_ok_normal(self):
        r = ar_detect("Ok", [], 0)
        assert r.label == AutoReplyLabel.NORMAL

    def test_emoji_only_normal(self):
        r = ar_detect("👍", [], 0)
        assert r.label == AutoReplyLabel.NORMAL


class TestAutoReplyRepetitionDetection:
    """Near-identical message to prior merchant messages → auto-reply signal."""

    def test_exact_repetition_fires(self):
        prior = ["Yes, send me the details please."]
        r = ar_detect("Yes, send me the details please.", prior, 0)
        assert is_auto_reply(r)
        assert r.similarity is not None and r.similarity >= REPETITION_SIMILARITY_THRESHOLD

    def test_near_identical_repetition_fires(self):
        prior = ["Thank you! Our team will be in touch."]
        r = ar_detect("Thank you. Our team will be in touch.", prior, 0)
        assert is_auto_reply(r)

    def test_different_message_no_repetition(self):
        prior = ["Yes, let's do it."]
        r = ar_detect("What are the pricing options?", prior, 0)
        # May still fire if phrase match, but NOT due to repetition
        if r.label != AutoReplyLabel.NORMAL:
            # Should be phrase match, not repetition
            assert r.similarity is None or r.similarity < REPETITION_SIMILARITY_THRESHOLD

    def test_high_similarity_threshold_respected(self):
        """90% overlap required — "Send me the info" vs "I need more info" is not enough."""
        prior = ["Send me the detailed information"]
        r = ar_detect("I need more info", prior, 0)
        # Jaccard on {"send","me","the","detailed","information"} vs {"i","need","more","info"} ≈ 0.11
        # Should NOT fire for repetition
        if r.label != AutoReplyLabel.NORMAL:
            assert r.matched_phrase is not None  # must be a phrase match, not repetition


class TestAutoReplyStreakAndEscalation:
    """Streak counter escalates NORMAL → LIKELY → CONFIRMED."""

    def test_first_auto_reply_likely(self):
        r = ar_detect("Thank you for contacting us!", [], 0)
        assert r.label == AutoReplyLabel.LIKELY_AUTO_REPLY
        assert r.new_streak == 1

    def test_second_auto_reply_confirmed(self):
        r = ar_detect("Our team will respond shortly.", [], 1)
        assert r.label == AutoReplyLabel.CONFIRMED_AUTO_REPLY
        assert r.new_streak == 2
        assert should_exit(r)

    def test_third_auto_reply_still_confirmed(self):
        r = ar_detect("I am an automated assistant.", [], 2)
        assert r.label == AutoReplyLabel.CONFIRMED_AUTO_REPLY
        assert r.new_streak == 3

    def test_normal_message_resets_streak(self):
        r = ar_detect("Great, what should I do next?", [], 2)
        assert r.label == AutoReplyLabel.NORMAL
        assert r.new_streak == 0

    def test_should_exit_false_for_likely(self):
        r = ar_detect("Thank you for contacting us!", [], 0)
        assert r.label == AutoReplyLabel.LIKELY_AUTO_REPLY
        assert not should_exit(r)

    def test_should_exit_true_for_confirmed(self):
        r = ar_detect("Our team will respond shortly.", [], 1)
        assert should_exit(r)

    def test_full_pattern_b_sequence(self):
        """
        Simulate testing-brief.md §4.1 auto_reply_hell:
        Judge sends the same canned reply 4 times in a row.
        Bot must reach CONFIRMED by turn 2 (streak >= 2).
        """
        canned = "Thank you for contacting us! Our team will respond shortly."
        streak = 0
        prior: list = []

        for turn in range(4):
            r = ar_detect(canned, prior, streak)
            prior.append(canned)
            streak = r.new_streak
            if turn == 0:
                assert r.label == AutoReplyLabel.LIKELY_AUTO_REPLY
            if turn >= 1:
                assert r.label == AutoReplyLabel.CONFIRMED_AUTO_REPLY
                assert should_exit(r)


# =============================================================================
# IntentDetector tests
# =============================================================================

class TestIntentCommitted:
    """Pattern C / testing-brief.md §4.2 intent_transition."""

    # ── Exact test-brief sentence ─────────────────────────────────────────

    def test_ok_lets_do_it(self):
        """Exact sentence from testing-brief.md §4.2."""
        r = intent_detect("Ok lets do it. Whats next?")
        assert r.intent == Intent.COMMITTED
        assert r.confidence == "high"

    # ── CLAUDE.md §6.2 canonical examples ────────────────────────────────

    def test_yes_lets_do_it(self):
        r = intent_detect("Yes, let's do it!")
        assert r.intent == Intent.COMMITTED

    def test_ok_lets_proceed(self):
        r = intent_detect("Ok let's proceed")
        assert r.intent == Intent.COMMITTED

    def test_go_ahead(self):
        r = intent_detect("Go ahead")
        assert r.intent == Intent.COMMITTED

    def test_go_ahead_with_please(self):
        r = intent_detect("Please go ahead with the update.")
        assert r.intent == Intent.COMMITTED

    def test_please_update_it(self):
        r = intent_detect("Please update it.")
        assert r.intent == Intent.COMMITTED

    def test_send_it(self):
        r = intent_detect("Send it!")
        assert r.intent == Intent.COMMITTED

    def test_do_it(self):
        r = intent_detect("Do it.")
        assert r.intent == Intent.COMMITTED

    def test_i_want_to_join(self):
        r = intent_detect("I want to join")
        assert r.intent == Intent.COMMITTED

    # ── Other common commitment phrases ──────────────────────────────────

    def test_yes_please_focus_on(self):
        """From the merchants_seed.json conversation history."""
        r = intent_detect("Yes please, focus on whitening and aligners")
        assert r.intent == Intent.COMMITTED

    def test_send_me_the_abstract(self):
        """From merchants_seed.json / the auto-reply test flow."""
        r = intent_detect("Yes, send me the abstract")
        assert r.intent == Intent.COMMITTED

    def test_yes_good_idea(self):
        r = intent_detect("Yes good idea, what would it look like")
        assert r.intent == Intent.COMMITTED

    def test_confirm_lowercase(self):
        r = intent_detect("confirmed, please proceed")
        assert r.intent == Intent.COMMITTED

    def test_sure_go(self):
        r = intent_detect("Sure, go ahead!")
        assert r.intent == Intent.COMMITTED

    def test_send_me_the_list(self):
        """From merchants_seed.json — pharmacy merchant."""
        r = intent_detect("Yes send me the list please")
        assert r.intent == Intent.COMMITTED

    # ── Negation should NOT commit ────────────────────────────────────────

    def test_go_ahead_but_first_tell_me(self):
        """Has negator context — should NOT be COMMITTED."""
        r = intent_detect("Go ahead, but first tell me the price")
        # With negation the fast path is bypassed — could be QUESTION or NORMAL
        assert r.intent in (Intent.QUESTION, Intent.NORMAL)

    def test_do_not_proceed_yet(self):
        r = intent_detect("Please do not proceed yet")
        assert r.intent != Intent.COMMITTED


class TestIntentHostile:
    """Pattern D / testing-brief.md §4.3 hostile test."""

    # ── Exact test-brief sentence ─────────────────────────────────────────

    def test_stop_messaging_me_this_is_useless_spam(self):
        """Exact sentences from testing-brief.md §4.3."""
        r = intent_detect("Stop messaging me. This is useless spam.")
        assert r.intent == Intent.NOT_INTERESTED
        assert r.confidence == "high"

    # ── CLAUDE.md §6.3 variants ───────────────────────────────────────────

    def test_stop_messaging_me(self):
        r = intent_detect("Stop messaging me.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_this_is_useless(self):
        r = intent_detect("This is useless.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_not_interested(self):
        r = intent_detect("Not interested.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_spam(self):
        r = intent_detect("This is spam, stop it.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_unsubscribe(self):
        r = intent_detect("Unsubscribe me from this.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_opt_out(self):
        r = intent_detect("I want to opt out of these messages.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_dont_contact_again(self):
        r = intent_detect("Don't contact me again please.")
        assert r.intent == Intent.NOT_INTERESTED

    def test_leave_me_alone(self):
        r = intent_detect("Leave us alone.")
        assert r.intent == Intent.NOT_INTERESTED

    # ── Convenience predicates ────────────────────────────────────────────

    def test_is_hostile_predicate(self):
        r = intent_detect("Stop messaging me.")
        assert is_hostile(r)

    def test_is_committed_predicate_false(self):
        r = intent_detect("Stop messaging me.")
        assert not is_committed(r)


class TestIntentOffTopic:
    """Off-topic requests outside Vera's scope (CLAUDE.md §6.4)."""

    def test_gst_filing(self):
        r = intent_detect("Can you help me file my GST return?")
        assert r.intent == Intent.OFF_TOPIC

    def test_legal_advice(self):
        r = intent_detect("I need legal advice about my lease agreement.")
        assert r.intent == Intent.OFF_TOPIC

    def test_tax_return(self):
        r = intent_detect("How do I file my income tax return?")
        assert r.intent == Intent.OFF_TOPIC

    def test_write_code(self):
        r = intent_detect("Can you write me a Python script for my inventory?")
        assert r.intent == Intent.OFF_TOPIC

    def test_is_off_topic_predicate(self):
        r = intent_detect("Help me with my GST filing please")
        assert is_off_topic(r)


class TestIntentQuestion:
    """Clarifying or informational questions — should be classified as QUESTION."""

    def test_what_would_it_look_like(self):
        r = intent_detect("What would it look like?")
        assert r.intent == Intent.QUESTION

    def test_how_does_it_work(self):
        r = intent_detect("How does this work?")
        assert r.intent == Intent.QUESTION

    def test_what_is_the_price(self):
        r = intent_detect("What is the price?")
        assert r.intent == Intent.QUESTION

    def test_when_will_it_start(self):
        r = intent_detect("When will it start?")
        assert r.intent == Intent.QUESTION

    def test_can_you_tell_me_more(self):
        r = intent_detect("Can you tell me more about this?")
        assert r.intent == Intent.QUESTION


class TestIntentLLMFallback:
    """LLM fallback mechanics — injectable mock, no real network call."""

    def test_llm_fn_called_for_ambiguous(self):
        """Ambiguous message with no deterministic match → LLM fallback invoked."""
        calls = []

        def mock_llm(msg: str, context: str) -> str:
            calls.append(msg)
            return "COMMITTED"

        # "Sounds good" matches no deterministic pattern
        r = intent_detect("Sounds good!", llm_fn=mock_llm)
        # LLM is called
        assert len(calls) == 1
        assert r.intent == Intent.COMMITTED
        assert r.via_llm is True

    def test_llm_fn_not_called_for_hostile(self):
        """Hostile message handled deterministically — LLM must NOT be called."""
        calls = []

        def mock_llm(msg: str, context: str) -> str:
            calls.append(msg)
            return "NORMAL"

        r = intent_detect("Stop messaging me!", llm_fn=mock_llm)
        assert len(calls) == 0
        assert r.intent == Intent.NOT_INTERESTED

    def test_llm_fn_not_called_for_committed(self):
        """Clear commitment — LLM must NOT be called."""
        calls = []

        def mock_llm(msg: str, context: str) -> str:
            calls.append(msg)
            return "NORMAL"

        r = intent_detect("Go ahead", llm_fn=mock_llm)
        assert len(calls) == 0
        assert r.intent == Intent.COMMITTED

    def test_llm_fn_exception_returns_normal(self):
        """If LLM call raises, gracefully fall through to NORMAL."""
        def bad_llm(msg: str, context: str) -> str:
            raise RuntimeError("LLM unavailable")

        r = intent_detect("Sounds good!", llm_fn=bad_llm)
        assert r.intent == Intent.NORMAL
        assert r.via_llm is False

    def test_llm_fn_none_returns_normal_for_ambiguous(self):
        """No LLM provided → ambiguous message returns NORMAL."""
        r = intent_detect("Sounds good!", llm_fn=None)
        assert r.intent == Intent.NORMAL

    def test_llm_fn_returns_unknown_label_falls_through(self):
        """If LLM response doesn't contain a valid label → NORMAL."""
        def broken_llm(msg: str, context: str) -> str:
            return "I don't know what this means"

        r = intent_detect("Sounds good!", llm_fn=broken_llm)
        assert r.intent == Intent.NORMAL


# =============================================================================
# TriggerRouter tests
# =============================================================================

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_stores():
    """Fresh isolated stores for each test."""
    ctx = ContextStore()
    conv = ConversationStore()
    return ctx, conv


def _push_category(ctx: ContextStore, slug: str):
    ctx.upsert("category", slug, 1, {
        "slug": slug,
        "display_name": slug.capitalize(),
        "voice": {"tone": "peer_clinical", "vocab_taboo": []},
        "peer_stats": {"avg_ctr": 0.03},
    })


def _push_merchant(ctx: ContextStore, merchant_id: str, category: str,
                   subscription_status="active"):
    ctx.upsert("merchant", merchant_id, 1, {
        "merchant_id": merchant_id,
        "category_slug": category,
        "identity": {"name": f"Test Merchant {merchant_id}", "owner_first_name": "Test"},
        "subscription": {"status": subscription_status, "plan": "Pro", "days_remaining": 90},
        "performance": {"views": 1000, "ctr": 0.025},
        "signals": [],
        "offers": [],
    })


def _push_trigger(ctx: ContextStore, trigger_id: str, merchant_id: str,
                  kind="perf_dip", urgency=3, suppression_key=None,
                  expires_at="2099-12-31T00:00:00Z", customer_id=None):
    ctx.upsert("trigger", trigger_id, 1, {
        "id": trigger_id,
        "scope": "customer" if customer_id else "merchant",
        "kind": kind,
        "source": "internal",
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "payload": {"metric": "calls", "delta_pct": -0.3},
        "urgency": urgency,
        "suppression_key": suppression_key or f"key:{trigger_id}",
        "expires_at": expires_at,
    })


def _push_customer(ctx: ContextStore, customer_id: str, merchant_id: str):
    ctx.upsert("customer", customer_id, 1, {
        "customer_id": customer_id,
        "merchant_id": merchant_id,
        "identity": {"name": "Test Customer", "language_pref": "en"},
        "state": "active",
        "consent": {"scope": ["recall_reminders"]},
    })


class TestTriggerRouterFilters:

    def test_empty_input_returns_empty(self):
        ctx, conv = _make_stores()
        router = TriggerRouter(ctx, conv)
        result = router.route([], "2026-04-26T10:00:00Z")
        assert result == []

    def test_unknown_trigger_id_skipped(self):
        ctx, conv = _make_stores()
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_nonexistent"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_trigger_without_merchant_context_skipped(self):
        ctx, conv = _make_stores()
        # Push trigger but NOT its merchant context
        _push_trigger(ctx, "trg_001", "m_missing_merchant")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_expired_trigger_skipped(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_001", "m_001",
                      expires_at="2020-01-01T00:00:00Z")  # past
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_future_expires_at_not_skipped(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_001", "m_001",
                      expires_at="2099-12-31T00:00:00Z")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert len(result) == 1

    def test_suppressed_trigger_skipped(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_001", "m_001", suppression_key="my:suppression:key")
        # Mark as suppressed
        conv.suppress("my:suppression:key", "conv_existing")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_unsuppressed_trigger_included(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_001", "m_001", suppression_key="unique:key:001")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert len(result) == 1

    def test_expired_subscription_non_winback_skipped(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "salons")
        _push_merchant(ctx, "m_exp", "salons", subscription_status="expired")
        _push_trigger(ctx, "trg_exp_1", "m_exp", kind="perf_dip", urgency=4)
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_exp_1"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_expired_subscription_winback_included(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "salons")
        _push_merchant(ctx, "m_exp", "salons", subscription_status="expired")
        _push_trigger(ctx, "trg_winback", "m_exp", kind="winback_eligible", urgency=3)
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_winback"], "2026-04-26T10:00:00Z")
        assert len(result) == 1

    def test_customer_trigger_without_customer_context_skipped(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        # Push a customer-scope trigger but NO customer context
        _push_trigger(ctx, "trg_recall", "m_001", kind="recall_due", customer_id="c_001_missing")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_recall"], "2026-04-26T10:00:00Z")
        assert result == []

    def test_customer_trigger_with_customer_context_included(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_customer(ctx, "c_001", "m_001")
        _push_trigger(ctx, "trg_recall", "m_001", kind="recall_due",
                      customer_id="c_001")
        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_recall"], "2026-04-26T10:00:00Z")
        assert len(result) == 1
        assert result[0].customer_id == "c_001"
        assert result[0].customer is not None


class TestTriggerRouterRanking:

    def test_higher_urgency_ranked_first(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_low",  "m_001", urgency=1, kind="curious_ask_due")
        _push_trigger(ctx, "trg_high", "m_001", urgency=5, kind="supply_alert")
        router = TriggerRouter(ctx, conv)
        # Only one per merchant per tick (spam cap), so both won't appear
        # but we can test directly through score
        trg_high_payload = ctx.get("trigger", "trg_high")
        trg_low_payload  = ctx.get("trigger", "trg_low")
        assert _composite_score(trg_high_payload) > _composite_score(trg_low_payload)

    def test_supply_alert_beats_research_digest_same_urgency(self):
        """Kind priority dominates when urgency is equal."""
        supply = {"kind": "supply_alert", "urgency": 3}
        research = {"kind": "research_digest", "urgency": 3}
        assert _composite_score(supply) > _composite_score(research)

    def test_renewal_due_ranked_higher_than_festival(self):
        renewal = {"kind": "renewal_due", "urgency": 3}
        festival = {"kind": "festival_upcoming", "urgency": 3}
        assert _composite_score(renewal) > _composite_score(festival)

    def test_active_planning_intent_high_priority(self):
        planning = {"kind": "active_planning_intent", "urgency": 4}
        seasonal  = {"kind": "category_seasonal", "urgency": 4}
        assert _composite_score(planning) > _composite_score(seasonal)

    def test_multiple_triggers_ordered_by_score(self):
        ctx, conv = _make_stores()
        for i, cat in enumerate(["dentists", "salons", "restaurants", "gyms", "pharmacies"]):
            _push_category(ctx, cat)

        merchants = [
            ("m_a", "dentists"), ("m_b", "salons"), ("m_c", "restaurants"),
        ]
        for mid, cat in merchants:
            _push_merchant(ctx, mid, cat)

        _push_trigger(ctx, "trg_a", "m_a", kind="curious_ask_due", urgency=1)
        _push_trigger(ctx, "trg_b", "m_b", kind="perf_dip",         urgency=4)
        _push_trigger(ctx, "trg_c", "m_c", kind="renewal_due",      urgency=5)

        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_a", "trg_b", "trg_c"], "2026-04-26T10:00:00Z")

        assert len(result) == 3
        # Highest scoring first
        assert result[0].trigger_id == "trg_c"  # urgency=5, kind=renewal_due
        assert result[1].trigger_id == "trg_b"  # urgency=4, kind=perf_dip
        assert result[2].trigger_id == "trg_a"  # urgency=1, kind=curious_ask


class TestTriggerRouterSpamCap:

    def test_per_merchant_cap_one_per_tick(self):
        """Only one trigger per merchant per tick unless urgency=5 bypass."""
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_a", "m_001", kind="perf_dip", urgency=3)
        _push_trigger(ctx, "trg_b", "m_001", kind="research_digest", urgency=2)

        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_a", "trg_b"], "2026-04-26T10:00:00Z")
        # Both belong to m_001 → only 1 should pass (higher score wins)
        assert len(result) == 1

    def test_different_merchants_not_capped(self):
        """Two triggers from different merchants — both should pass."""
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_category(ctx, "salons")
        _push_merchant(ctx, "m_001", "dentists")
        _push_merchant(ctx, "m_002", "salons")
        _push_trigger(ctx, "trg_a", "m_001", kind="perf_dip", urgency=3)
        _push_trigger(ctx, "trg_b", "m_002", kind="perf_dip", urgency=3)

        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_a", "trg_b"], "2026-04-26T10:00:00Z")
        assert len(result) == 2

    def test_global_cap_at_20(self):
        """More than 20 eligible triggers → only 20 returned."""
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        ids = []
        for i in range(25):
            mid = f"m_{i:03d}"
            tid = f"trg_{i:03d}"
            _push_merchant(ctx, mid, "dentists")
            _push_trigger(ctx, tid, mid, urgency=3)
            ids.append(tid)

        router = TriggerRouter(ctx, conv)
        result = router.route(ids, "2026-04-26T10:00:00Z")
        assert len(result) <= MAX_ACTIONS_PER_TICK
        assert len(result) == 20


class TestTriggerRouterEnrichment:

    def test_selected_trigger_has_all_fields(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "restaurants")
        _push_merchant(ctx, "m_005", "restaurants")
        _push_trigger(ctx, "trg_ipl", "m_005", kind="ipl_match_today", urgency=3)

        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_ipl"], "2026-04-26T10:00:00Z")
        assert len(result) == 1
        sel = result[0]

        assert sel.trigger_id == "trg_ipl"
        assert sel.merchant_id == "m_005"
        assert sel.category_slug == "restaurants"
        assert sel.merchant is not None
        assert sel.trigger is not None
        assert sel.category is not None
        assert sel.customer is None   # merchant-scope trigger
        assert sel.score > 0

    def test_suppression_key_propagated(self):
        ctx, conv = _make_stores()
        _push_category(ctx, "dentists")
        _push_merchant(ctx, "m_001", "dentists")
        _push_trigger(ctx, "trg_001", "m_001", suppression_key="custom:sup:key")

        router = TriggerRouter(ctx, conv)
        result = router.route(["trg_001"], "2026-04-26T10:00:00Z")
        assert result[0].suppression_key == "custom:sup:key"


class TestTriggerRouterHelpers:

    def test_parse_iso_with_z(self):
        dt = _parse_iso("2026-04-26T10:00:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_parse_iso_with_offset(self):
        dt = _parse_iso("2026-04-26T10:00:00+05:30")
        assert dt is not None

    def test_parse_iso_none_input(self):
        assert _parse_iso(None) is None

    def test_parse_iso_invalid_returns_none(self):
        assert _parse_iso("not-a-date") is None

    def test_is_expired_past(self):
        now = _parse_iso("2026-04-26T10:00:00Z")
        trigger = {"expires_at": "2026-01-01T00:00:00Z"}
        assert _is_expired(trigger, now) is True

    def test_is_expired_future(self):
        now = _parse_iso("2026-04-26T10:00:00Z")
        trigger = {"expires_at": "2099-12-31T00:00:00Z"}
        assert _is_expired(trigger, now) is False

    def test_is_expired_no_expiry(self):
        now = _parse_iso("2026-04-26T10:00:00Z")
        trigger = {}
        assert _is_expired(trigger, now) is False

    def test_composite_score_urgency5_supply_alert(self):
        score = _composite_score({"kind": "supply_alert", "urgency": 5})
        # 2*5 + 10 = 20
        assert score == 20.0

    def test_composite_score_urgency1_festival(self):
        score = _composite_score({"kind": "festival_upcoming", "urgency": 1})
        # 2*1 + 3 = 5
        assert score == 5.0

    def test_composite_score_unknown_kind(self):
        score = _composite_score({"kind": "totally_new_kind", "urgency": 2})
        # 2*2 + 4 (default) = 8
        assert score == 8.0


# =============================================================================
# Integration scenario: full Pattern B/C/D sequences
# =============================================================================

class TestFullScenarios:
    """
    End-to-end routing pipeline scenarios from the challenge brief.
    No HTTP layer — pure routing logic only.
    """

    def test_pattern_b_auto_reply_sequence(self):
        """
        Pattern B: merchant is sending auto-replies.
        After streak >= 2, bot should exit.
        Reproduces testing-brief.md §4.1.
        """
        canned = "Thank you for contacting us! Our team will respond shortly."
        streak = 0
        prior_merchant_msgs: list = []

        for turn in range(4):
            r = ar_detect(canned, prior_merchant_msgs, streak)
            prior_merchant_msgs.append(canned)
            streak = r.new_streak

            if turn == 0:
                assert not should_exit(r), f"Turn 0 should not exit yet, got {r.label}"
            else:
                assert should_exit(r), f"Turn {turn} should exit, got {r.label}"

    def test_pattern_c_intent_transition(self):
        """
        Pattern C / testing-brief.md §4.2:
        Bot asks qualifying question → merchant commits → must NOT re-qualify.
        """
        commitment_msg = "Ok lets do it. Whats next?"
        r = intent_detect(commitment_msg)
        assert r.intent == Intent.COMMITTED
        # Response body must contain action words (checked separately — that's the composer's job)
        assert is_committed(r)

    def test_pattern_d_hostile_handling(self):
        """
        Pattern D / testing-brief.md §4.3:
        Merchant hostile → bot must end, not argue.
        """
        hostile_msg = "Stop messaging me. This is useless spam."
        r = intent_detect(hostile_msg)
        assert r.intent == Intent.NOT_INTERESTED
        assert is_hostile(r)
        assert not is_committed(r)

    def test_auto_reply_then_genuine_message_resets_streak(self):
        """
        Edge case: merchant sends one auto-reply, then a genuine message.
        Streak must reset to 0 on the genuine message.
        """
        canned = "Thank you for contacting us!"
        r1 = ar_detect(canned, [], 0)
        assert r1.label == AutoReplyLabel.LIKELY_AUTO_REPLY
        assert r1.new_streak == 1

        genuine = "What kind of offer do you suggest for whitening?"
        r2 = ar_detect(genuine, [canned], r1.new_streak)
        assert r2.label == AutoReplyLabel.NORMAL
        assert r2.new_streak == 0

    def test_hostile_takes_priority_over_commitment(self):
        """
        Pathological message: sounds committed but is actually hostile.
        "Go ahead and stop messaging me" → NOT_INTERESTED wins.
        """
        r = intent_detect("Go ahead and stop messaging me please.")
        # NOT_INTERESTED should win (checked first in detect())
        assert r.intent == Intent.NOT_INTERESTED
