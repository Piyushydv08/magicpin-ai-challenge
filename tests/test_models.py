"""
tests/test_models.py
--------------------
Unit tests for Pydantic models in models/schemas.py.
Verifies that the real dataset JSON parses cleanly, required fields are enforced,
extra fields are allowed (judge can inject arbitrary data), and alias handling works.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.schemas import (
    CategoryContext,
    MerchantContext,
    CustomerContext,
    TriggerContext,
    ContextPushRequest,
    VALID_SCOPES,
)

DATASET = Path(__file__).parent.parent / "dataset"


# ---------------------------------------------------------------------------
# CategoryContext
# ---------------------------------------------------------------------------

class TestCategoryContext:

    def test_parse_dentists_json(self):
        raw = json.loads((DATASET / "categories" / "dentists.json").read_text())
        ctx = CategoryContext.model_validate(raw)
        assert ctx.slug == "dentists"
        assert len(ctx.offer_catalog) > 0
        assert ctx.peer_stats.avg_ctr == pytest.approx(0.030)
        assert len(ctx.digest) >= 4
        assert ctx.voice.tone == "peer_clinical"
        assert "guaranteed" in ctx.voice.vocab_taboo

    def test_parse_all_category_files(self):
        for cat_file in (DATASET / "categories").glob("*.json"):
            raw = json.loads(cat_file.read_text())
            ctx = CategoryContext.model_validate(raw)
            assert ctx.slug  # non-empty slug

    def test_extra_fields_allowed(self):
        """Judge may inject extra keys — must not raise."""
        ctx = CategoryContext.model_validate({
            "slug": "dentists",
            "new_future_field": "some_value",
        })
        assert ctx.slug == "dentists"

    def test_slug_required(self):
        with pytest.raises(ValidationError):
            CategoryContext.model_validate({})


# ---------------------------------------------------------------------------
# MerchantContext
# ---------------------------------------------------------------------------

class TestMerchantContext:

    def _load_merchants(self):
        raw = json.loads((DATASET / "merchants_seed.json").read_text())
        return raw["merchants"]

    def test_parse_all_merchants(self):
        merchants = self._load_merchants()
        for m_raw in merchants:
            ctx = MerchantContext.model_validate(m_raw)
            assert ctx.merchant_id

    def test_drmeera_fields(self):
        merchants = self._load_merchants()
        drmeera = next(m for m in merchants if m["merchant_id"] == "m_001_drmeera_dentist_delhi")
        ctx = MerchantContext.model_validate(drmeera)
        assert ctx.identity.name == "Dr. Meera's Dental Clinic"
        assert ctx.identity.city == "Delhi"
        assert ctx.performance.views == 2410
        assert ctx.performance.ctr == pytest.approx(0.021)
        assert any(o.status == "active" for o in ctx.offers)
        assert "ctr_below_peer_median" in ctx.signals
        assert ctx.customer_aggregate.total_unique_ytd == 540

    def test_conversation_history_alias(self):
        """ConversationTurn uses alias 'from' → 'from_' internally."""
        merchants = self._load_merchants()
        drmeera = next(m for m in merchants if m["merchant_id"] == "m_001_drmeera_dentist_delhi")
        ctx = MerchantContext.model_validate(drmeera)
        turns = ctx.conversation_history
        assert len(turns) == 2
        # The 'from' alias should parse correctly
        assert turns[0].from_ == "vera"
        assert turns[1].from_ == "merchant"

    def test_merchant_id_required(self):
        with pytest.raises(ValidationError):
            MerchantContext.model_validate({"category_slug": "dentists"})

    def test_extra_fields_allowed(self):
        ctx = MerchantContext.model_validate({
            "merchant_id": "m_test",
            "experimental_field": 99,
        })
        assert ctx.merchant_id == "m_test"


# ---------------------------------------------------------------------------
# CustomerContext
# ---------------------------------------------------------------------------

class TestCustomerContext:

    def _load_customers(self):
        raw = json.loads((DATASET / "customers_seed.json").read_text())
        return raw["customers"]

    def test_parse_all_customers(self):
        customers = self._load_customers()
        for c_raw in customers:
            ctx = CustomerContext.model_validate(c_raw)
            assert ctx.customer_id

    def test_priya_fields(self):
        customers = self._load_customers()
        priya = next(c for c in customers if c["customer_id"] == "c_001_priya_for_m001")
        ctx = CustomerContext.model_validate(priya)
        assert ctx.identity.name == "Priya"
        assert ctx.identity.language_pref == "hi-en mix"
        assert ctx.state == "lapsed_soft"
        assert ctx.relationship.visits_total == 4
        assert ctx.preferences.reminder_opt_in is True
        assert "recall_reminders" in ctx.consent.scope

    def test_anonymous_customer_no_phone(self):
        customers = self._load_customers()
        anon = next(c for c in customers if c["customer_id"] == "c_015_anonymous_for_m010")
        ctx = CustomerContext.model_validate(anon)
        assert ctx.identity.phone_redacted is None
        assert ctx.consent.opted_in_at is None

    def test_customer_id_required(self):
        with pytest.raises(ValidationError):
            CustomerContext.model_validate({"merchant_id": "m_001"})


# ---------------------------------------------------------------------------
# TriggerContext
# ---------------------------------------------------------------------------

class TestTriggerContext:

    def _load_triggers(self):
        raw = json.loads((DATASET / "triggers_seed.json").read_text())
        return raw["triggers"]

    def test_parse_all_triggers(self):
        triggers = self._load_triggers()
        for t_raw in triggers:
            ctx = TriggerContext.model_validate(t_raw)
            assert ctx.id

    def test_research_digest_trigger(self):
        triggers = self._load_triggers()
        t = next(t for t in triggers if t["id"] == "trg_001_research_digest_dentists")
        ctx = TriggerContext.model_validate(t)
        assert ctx.kind == "research_digest"
        assert ctx.scope == "merchant"
        assert ctx.source == "external"
        assert ctx.merchant_id == "m_001_drmeera_dentist_delhi"
        assert ctx.customer_id is None
        assert ctx.urgency == 2
        assert ctx.suppression_key == "research:dentists:2026-W17"
        assert ctx.payload["category"] == "dentists"

    def test_customer_scoped_trigger(self):
        triggers = self._load_triggers()
        t = next(t for t in triggers if t["id"] == "trg_003_recall_due_priya")
        ctx = TriggerContext.model_validate(t)
        assert ctx.scope == "customer"
        assert ctx.customer_id == "c_001_priya_for_m001"

    def test_trigger_id_required(self):
        with pytest.raises(ValidationError):
            TriggerContext.model_validate({"kind": "research_digest"})


# ---------------------------------------------------------------------------
# ContextPushRequest
# ---------------------------------------------------------------------------

class TestContextPushRequest:

    def test_valid_request(self):
        req = ContextPushRequest.model_validate({
            "scope": "category",
            "context_id": "dentists",
            "version": 1,
            "payload": {"slug": "dentists"},
            "delivered_at": "2026-04-26T10:00:00Z",
        })
        assert req.scope == "category"
        assert req.version == 1

    def test_all_valid_scopes(self):
        for scope in VALID_SCOPES:
            req = ContextPushRequest.model_validate({
                "scope": scope,
                "context_id": "x",
                "version": 1,
                "payload": {},
            })
            assert req.scope == scope

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            # Missing scope, context_id, version, payload
            ContextPushRequest.model_validate({"delivered_at": "2026-04-26T10:00:00Z"})

    def test_extra_fields_forbidden(self):
        """ContextPushRequest uses extra='forbid' to catch judge bugs early."""
        with pytest.raises(ValidationError):
            ContextPushRequest.model_validate({
                "scope": "category",
                "context_id": "dentists",
                "version": 1,
                "payload": {},
                "unexpected_field": "oops",
            })
