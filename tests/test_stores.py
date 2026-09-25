"""
tests/test_stores.py
--------------------
Unit tests for ContextStore and ConversationStore.

Run with:  python -m pytest tests/ -v
"""

import pytest
from state.context_store import ContextStore, UpsertResult
from state.conversation_store import (
    ConversationStore,
    ConversationState,
    Conversation,
    Message,
)


# =============================================================================
# ContextStore tests
# =============================================================================

class TestContextStoreIdempotency:
    """Same (context_id, version) must be a no-op that returns accepted=True."""

    def test_first_insert_accepted(self):
        store = ContextStore()
        result = store.upsert("category", "dentists", 1, {"slug": "dentists"})
        assert result.accepted is True
        assert result.current_version == 1

    def test_same_version_idempotent_accepted(self):
        store = ContextStore()
        store.upsert("category", "dentists", 1, {"slug": "dentists", "v": "first"})
        # Re-posting the exact same version is a no-op — must still be accepted=True
        result = store.upsert("category", "dentists", 1, {"slug": "dentists", "v": "second"})
        assert result.accepted is True
        assert result.current_version == 1

    def test_same_version_payload_unchanged(self):
        """Idempotent re-post must NOT overwrite the stored payload."""
        store = ContextStore()
        store.upsert("category", "dentists", 1, {"slug": "dentists", "original": True})
        store.upsert("category", "dentists", 1, {"slug": "dentists", "original": False})
        payload = store.get("category", "dentists")
        # Still the original payload
        assert payload["original"] is True

    def test_multiple_scopes_independent(self):
        """Same context_id in different scopes must be independent."""
        store = ContextStore()
        store.upsert("category", "dentists", 1, {"scope": "category"})
        store.upsert("merchant", "dentists", 1, {"scope": "merchant"})
        cat = store.get("category", "dentists")
        merch = store.get("merchant", "dentists")
        assert cat["scope"] == "category"
        assert merch["scope"] == "merchant"


class TestContextStoreStaleVersion:
    """Lower version than stored → accepted=False, reason=stale_version."""

    def test_lower_version_rejected(self):
        store = ContextStore()
        store.upsert("merchant", "m_001", 5, {"name": "v5"})
        result = store.upsert("merchant", "m_001", 3, {"name": "v3"})
        assert result.accepted is False
        assert result.reason == "stale_version"
        assert result.current_version == 5

    def test_lower_version_payload_unchanged(self):
        store = ContextStore()
        store.upsert("merchant", "m_001", 5, {"name": "v5"})
        store.upsert("merchant", "m_001", 2, {"name": "v2"})
        payload = store.get("merchant", "m_001")
        assert payload["name"] == "v5"

    def test_version_1_after_version_5_rejected(self):
        store = ContextStore()
        store.upsert("trigger", "trg_abc", 5, {"urgency": 3})
        result = store.upsert("trigger", "trg_abc", 1, {"urgency": 1})
        assert result.accepted is False
        assert result.current_version == 5


class TestContextStoreVersionBump:
    """Higher version atomically replaces the stored payload."""

    def test_higher_version_accepted(self):
        store = ContextStore()
        store.upsert("merchant", "m_001", 1, {"ctr": 0.021})
        result = store.upsert("merchant", "m_001", 2, {"ctr": 0.035})
        assert result.accepted is True
        assert result.current_version == 2

    def test_higher_version_replaces_payload(self):
        store = ContextStore()
        store.upsert("merchant", "m_001", 1, {"ctr": 0.021, "views": 2410})
        store.upsert("merchant", "m_001", 2, {"ctr": 0.035, "views": 3100})
        payload = store.get("merchant", "m_001")
        assert payload["ctr"] == 0.035
        assert payload["views"] == 3100

    def test_skip_version_gap(self):
        """Version can jump from 1 to 10 — still accepted."""
        store = ContextStore()
        store.upsert("customer", "c_001", 1, {"state": "active"})
        result = store.upsert("customer", "c_001", 10, {"state": "lapsed_soft"})
        assert result.accepted is True
        payload = store.get("customer", "c_001")
        assert payload["state"] == "lapsed_soft"

    def test_sequential_version_bumps(self):
        """Three consecutive version bumps — each must replace."""
        store = ContextStore()
        for v in range(1, 6):
            result = store.upsert("trigger", "trg_seq", v, {"urgency": v})
            assert result.accepted is True
        payload = store.get("trigger", "trg_seq")
        assert payload["urgency"] == 5

    def test_get_version(self):
        store = ContextStore()
        store.upsert("merchant", "m_001", 3, {"x": 1})
        assert store.get_version("merchant", "m_001") == 3


class TestContextStoreGetCounts:
    """counts() returns correct per-scope counts for /v1/healthz."""

    def test_empty_store_all_zeros(self):
        store = ContextStore()
        counts = store.counts()
        assert counts == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}

    def test_counts_after_inserts(self):
        store = ContextStore()
        store.upsert("category", "dentists", 1, {})
        store.upsert("category", "salons", 1, {})
        store.upsert("merchant", "m_001", 1, {})
        store.upsert("trigger", "trg_001", 1, {})
        store.upsert("trigger", "trg_002", 1, {})
        counts = store.counts()
        assert counts["category"] == 2
        assert counts["merchant"] == 1
        assert counts["customer"] == 0
        assert counts["trigger"] == 2

    def test_version_bump_does_not_increment_count(self):
        """Updating a version must not add a new count entry."""
        store = ContextStore()
        store.upsert("merchant", "m_001", 1, {})
        store.upsert("merchant", "m_001", 2, {})
        store.upsert("merchant", "m_001", 3, {})
        assert store.counts()["merchant"] == 1

    def test_invalid_scope_rejected(self):
        store = ContextStore()
        result = store.upsert("banana", "x_001", 1, {})
        assert result.accepted is False
        assert result.reason == "invalid_scope"


class TestContextStoreMissing:
    """get() returns None for unknown entries."""

    def test_get_missing_returns_none(self):
        store = ContextStore()
        assert store.get("category", "unknown") is None

    def test_get_version_missing_returns_none(self):
        store = ContextStore()
        assert store.get_version("merchant", "m_999") is None

    def test_get_all_empty_scope(self):
        store = ContextStore()
        assert store.get_all("customer") == {}

    def test_get_all_populated(self):
        store = ContextStore()
        store.upsert("trigger", "t1", 1, {"urgency": 3})
        store.upsert("trigger", "t2", 1, {"urgency": 5})
        all_triggers = store.get_all("trigger")
        assert set(all_triggers.keys()) == {"t1", "t2"}


class TestContextStoreClear:
    def test_clear_empties_store(self):
        store = ContextStore()
        store.upsert("category", "dentists", 1, {})
        store.upsert("merchant", "m_001", 1, {})
        store.clear()
        assert len(store) == 0
        assert store.get("category", "dentists") is None


# =============================================================================
# ConversationStore tests
# =============================================================================

class TestConversationCreation:

    def test_create_returns_conversation(self):
        store = ConversationStore()
        conv = store.create("conv_001", "m_001")
        assert conv.conversation_id == "conv_001"
        assert conv.merchant_id == "m_001"
        assert conv.state == ConversationState.NEW
        assert conv.turn_number == 0
        assert conv.messages == []

    def test_create_with_all_fields(self):
        store = ConversationStore()
        conv = store.create(
            "conv_002",
            "m_001",
            customer_id="c_001",
            trigger_id="trg_abc",
            suppression_key="research:dentists:2026-W17",
        )
        assert conv.customer_id == "c_001"
        assert conv.trigger_id == "trg_abc"
        assert conv.suppression_key == "research:dentists:2026-W17"

    def test_duplicate_conversation_id_raises(self):
        store = ConversationStore()
        store.create("conv_001", "m_001")
        with pytest.raises(ValueError, match="already exists"):
            store.create("conv_001", "m_002")

    def test_different_ids_independent(self):
        store = ConversationStore()
        store.create("conv_001", "m_001")
        store.create("conv_002", "m_002")
        assert store.count() == 2


class TestConversationLookup:

    def test_get_existing(self):
        store = ConversationStore()
        store.create("conv_001", "m_001")
        conv = store.get("conv_001")
        assert conv is not None
        assert conv.merchant_id == "m_001"

    def test_get_missing_returns_none(self):
        store = ConversationStore()
        assert store.get("conv_nonexistent") is None

    def test_all_active_filters_ended(self):
        store = ConversationStore()
        c1 = store.create("conv_001", "m_001")
        c2 = store.create("conv_002", "m_002")
        c3 = store.create("conv_003", "m_003")

        # End one conversation
        c2.state = ConversationState.ENDED
        store.update(c2)

        active = store.all_active()
        ids = {c.conversation_id for c in active}
        assert "conv_001" in ids
        assert "conv_002" not in ids   # ENDED
        assert "conv_003" in ids

    def test_all_for_merchant(self):
        store = ConversationStore()
        store.create("conv_001", "m_001")
        store.create("conv_002", "m_001")
        store.create("conv_003", "m_002")
        result = store.all_for_merchant("m_001")
        assert len(result) == 2
        assert all(c.merchant_id == "m_001" for c in result)


class TestConversationMessages:

    def test_add_message_increments_turn(self):
        store = ConversationStore()
        conv = store.create("conv_001", "m_001")
        conv.add_message("vera", "Hello Dr. Meera!", received_at="2026-04-26T10:00:00Z")
        assert conv.turn_number == 1
        assert len(conv.messages) == 1
        msg = conv.messages[0]
        assert msg.role == "vera"
        assert msg.body == "Hello Dr. Meera!"
        assert msg.turn_number == 1

    def test_multiple_messages_sequential_turns(self):
        store = ConversationStore()
        conv = store.create("conv_001", "m_001")
        conv.add_message("vera", "First message")
        conv.add_message("merchant", "Reply from merchant")
        conv.add_message("vera", "Second Vera message")
        assert conv.turn_number == 3
        assert [m.role for m in conv.messages] == ["vera", "merchant", "vera"]

    def test_record_sent_and_cap(self):
        conv = Conversation("conv_001", "m_001")
        for i in range(15):
            conv.record_sent(f"body_{i}")
        # Capped at 10
        assert len(conv.last_sent_bodies) == 10
        assert conv.last_sent_bodies[-1] == "body_14"

    def test_is_active_states(self):
        conv = Conversation("conv_001", "m_001")
        for state in [
            ConversationState.NEW,
            ConversationState.PITCHING,
            ConversationState.QUALIFYING,
            ConversationState.COMMITTED,
            ConversationState.ACTIONING,
            ConversationState.WAITING,
            ConversationState.AUTO_REPLY,
        ]:
            conv.state = state
            assert conv.is_active() is True, f"{state} should be active"

        for state in [ConversationState.ENDED, ConversationState.NOT_INTERESTED]:
            conv.state = state
            assert conv.is_active() is False, f"{state} should not be active"


class TestConversationStateTransitions:

    def test_state_transitions(self):
        store = ConversationStore()
        conv = store.create("conv_001", "m_001")

        # Walk through the happy path
        for new_state in [
            ConversationState.PITCHING,
            ConversationState.QUALIFYING,
            ConversationState.COMMITTED,
            ConversationState.ACTIONING,
            ConversationState.ENDED,
        ]:
            conv.state = new_state
            store.update(conv)
            assert store.get("conv_001").state == new_state

    def test_auto_reply_streak(self):
        store = ConversationStore()
        conv = store.create("conv_001", "m_001")
        auto_body = "Thank you for contacting us!"
        for i in range(3):
            conv.last_merchant_message = auto_body
            conv.auto_reply_streak += 1
        assert conv.auto_reply_streak == 3
        store.update(conv)
        fetched = store.get("conv_001")
        assert fetched.auto_reply_streak == 3


class TestSuppressionDedup:

    def test_suppression_registered_on_create(self):
        store = ConversationStore()
        store.create(
            "conv_001", "m_001",
            suppression_key="research:dentists:2026-W17"
        )
        assert store.is_suppressed("research:dentists:2026-W17") is True

    def test_different_key_not_suppressed(self):
        store = ConversationStore()
        store.create("conv_001", "m_001", suppression_key="key_A")
        assert store.is_suppressed("key_B") is False

    def test_manual_suppress(self):
        store = ConversationStore()
        store.suppress("my_key", "conv_001")
        assert store.is_suppressed("my_key") is True

    def test_release_suppression(self):
        store = ConversationStore()
        store.suppress("my_key", "conv_001")
        store.release_suppression("my_key")
        assert store.is_suppressed("my_key") is False

    def test_clear_wipes_suppression(self):
        store = ConversationStore()
        store.create("conv_001", "m_001", suppression_key="key_A")
        store.clear()
        assert store.is_suppressed("key_A") is False
        assert store.count() == 0
