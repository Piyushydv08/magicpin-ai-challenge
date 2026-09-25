"""
tests/test_endpoints.py
-----------------------
HTTP-level integration tests for all 5 bot endpoints.
Uses FastAPI's TestClient (no real network, no subprocess) so the suite runs fast.

Scenarios verified:
  1.  GET /v1/healthz → 200, all-zero counts before any push
  2.  GET /v1/metadata → 200, expected keys
  3.  POST /v1/context (category, v1) → 200 accepted=True
  4.  POST /v1/context (category, v1) AGAIN → 200 accepted=True (idempotent)
  5.  GET /v1/healthz after push → category count = 1
  6.  POST /v1/context (category, v2) → 200 accepted=True  (version bump)
  7.  POST /v1/context (category, v1) AFTER v2 → 409 stale_version
  8.  POST /v1/context invalid scope → 400
  9.  POST /v1/context missing required field → 400
  10. POST /v1/tick → 200, actions=[]
  11. POST /v1/reply (unknown conv) → 200, action=send
  12. POST /v1/reply (known conv, adds to history) → 200
  13. Merchant + trigger context push → healthz counts reflect both
  14. Customer context push with null phone → accepted
  15. Version gap jump (v1 → v10) → accepted
"""

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# The TestClient patches the app singleton — each test module gets a fresh
# bot.py import so store state is isolated between test functions via the
# teardown endpoint.
# ---------------------------------------------------------------------------
from bot import app, context_store, conversation_store

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _push(scope: str, context_id: str, version: int, payload: dict):
    return client.post("/v1/context", json={
        "scope": scope,
        "context_id": context_id,
        "version": version,
        "payload": payload,
    })


def _reset():
    """Wipe stores between tests via the teardown endpoint."""
    client.post("/v1/teardown")


# ---------------------------------------------------------------------------
# GET /v1/healthz
# ---------------------------------------------------------------------------

class TestHealthz:

    def setup_method(self):
        _reset()

    def test_returns_200(self):
        r = client.get("/v1/healthz")
        assert r.status_code == 200

    def test_all_zero_counts_before_push(self):
        r = client.get("/v1/healthz")
        body = r.json()
        assert body["status"] == "ok"
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], int)
        counts = body["contexts_loaded"]
        assert counts == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}

    def test_counts_after_context_push(self):
        _push("category", "dentists", 1, {"slug": "dentists"})
        _push("merchant", "m_001", 1, {"merchant_id": "m_001"})
        _push("merchant", "m_002", 1, {"merchant_id": "m_002"})
        r = client.get("/v1/healthz")
        counts = r.json()["contexts_loaded"]
        assert counts["category"] == 1
        assert counts["merchant"] == 2
        assert counts["customer"] == 0
        assert counts["trigger"] == 0

    def test_version_bump_does_not_change_count(self):
        _push("category", "dentists", 1, {"slug": "dentists"})
        _push("category", "dentists", 2, {"slug": "dentists", "updated": True})
        counts = client.get("/v1/healthz").json()["contexts_loaded"]
        assert counts["category"] == 1   # still only 1 category entry


# ---------------------------------------------------------------------------
# GET /v1/metadata
# ---------------------------------------------------------------------------

class TestMetadata:

    def test_returns_200(self):
        r = client.get("/v1/metadata")
        assert r.status_code == 200

    def test_required_keys_present(self):
        body = client.get("/v1/metadata").json()
        for key in ("team_name", "team_members", "model", "approach",
                    "contact_email", "version", "submitted_at"):
            assert key in body, f"Missing key: {key}"

    def test_team_members_is_list(self):
        body = client.get("/v1/metadata").json()
        assert isinstance(body["team_members"], list)


# ---------------------------------------------------------------------------
# POST /v1/context — the four scenarios the user explicitly asked for
# ---------------------------------------------------------------------------

class TestContextPush:

    def setup_method(self):
        _reset()

    # ── Scenario 3: first push accepted ────────────────────────────────────

    def test_first_push_accepted(self):
        r = _push("category", "dentists", 1, {"slug": "dentists"})
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert "ack_id" in body
        assert "stored_at" in body

    # ── Scenario 4: same version idempotent ────────────────────────────────

    def test_same_version_idempotent_returns_200(self):
        _push("category", "dentists", 1, {"slug": "dentists", "round": 1})
        r = _push("category", "dentists", 1, {"slug": "dentists", "round": 2})
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    def test_idempotent_push_does_not_change_payload(self):
        """Idempotent push must not overwrite stored payload."""
        _push("category", "dentists", 1, {"slug": "dentists", "original": True})
        _push("category", "dentists", 1, {"slug": "dentists", "original": False})
        stored = context_store.get("category", "dentists")
        assert stored["original"] is True

    # ── Scenario 6: higher version replaces ───────────────────────────────

    def test_higher_version_accepted(self):
        _push("category", "dentists", 1, {"ctr": 0.021})
        r = _push("category", "dentists", 2, {"ctr": 0.035})
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    def test_higher_version_replaces_payload(self):
        _push("category", "dentists", 1, {"ctr": 0.021, "views": 2410})
        _push("category", "dentists", 2, {"ctr": 0.035, "views": 3100})
        stored = context_store.get("category", "dentists")
        assert stored["ctr"] == pytest.approx(0.035)
        assert stored["views"] == 3100

    # ── Scenario 7: stale version after bump → 409 ─────────────────────────

    def test_stale_version_returns_409(self):
        _push("category", "dentists", 2, {"ctr": 0.035})
        r = _push("category", "dentists", 1, {"ctr": 0.021})
        assert r.status_code == 409

    def test_stale_version_body_shape(self):
        _push("category", "dentists", 2, {"ctr": 0.035})
        r = _push("category", "dentists", 1, {"ctr": 0.021})
        body = r.json()
        assert body["accepted"] is False
        assert body["reason"] == "stale_version"
        assert body["current_version"] == 2

    def test_stale_version_does_not_overwrite_payload(self):
        _push("category", "dentists", 5, {"name": "v5"})
        _push("category", "dentists", 3, {"name": "v3"})
        stored = context_store.get("category", "dentists")
        assert stored["name"] == "v5"

    # ── Scope validation → 400 ─────────────────────────────────────────────

    def test_invalid_scope_returns_400(self):
        r = client.post("/v1/context", json={
            "scope": "banana",
            "context_id": "x",
            "version": 1,
            "payload": {},
        })
        assert r.status_code == 400
        body = r.json()
        assert body["accepted"] is False

    def test_invalid_scope_reason(self):
        r = client.post("/v1/context", json={
            "scope": "invalid_scope_xyz",
            "context_id": "x",
            "version": 1,
            "payload": {},
        })
        assert r.json()["reason"] in ("invalid_scope", "invalid_request")

    # ── Malformed / missing fields → 400 ──────────────────────────────────

    def test_missing_required_field_returns_400(self):
        r = client.post("/v1/context", json={"scope": "category"})
        assert r.status_code == 400

    def test_empty_body_returns_400(self):
        r = client.post(
            "/v1/context",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        # Our global handler converts 422 → 400; either is acceptable per the brief
        assert r.status_code in (400, 422)

    def test_non_json_body_returns_error(self):
        r = client.post(
            "/v1/context",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 422)

    # ── All four valid scopes ─────────────────────────────────────────────

    def test_all_four_scopes_accepted(self):
        payloads = {
            "category": ("dentists", {"slug": "dentists"}),
            "merchant": ("m_001",    {"merchant_id": "m_001"}),
            "customer": ("c_001",    {"customer_id": "c_001"}),
            "trigger":  ("trg_001",  {"id": "trg_001"}),
        }
        for scope, (cid, payload) in payloads.items():
            r = _push(scope, cid, 1, payload)
            assert r.status_code == 200, f"Scope {scope} failed: {r.json()}"
            assert r.json()["accepted"] is True

    # ── Version gap jump ──────────────────────────────────────────────────

    def test_version_gap_jump_accepted(self):
        _push("trigger", "trg_001", 1, {"urgency": 1})
        r = _push("trigger", "trg_001", 10, {"urgency": 5})
        assert r.status_code == 200
        assert r.json()["accepted"] is True
        assert context_store.get("trigger", "trg_001")["urgency"] == 5

    # ── Customer with null phone (real dataset shape) ─────────────────────

    def test_customer_with_null_phone_accepted(self):
        r = _push("customer", "c_anon", 1, {
            "customer_id": "c_anon",
            "identity": {"name": "(walk-in)", "phone_redacted": None},
            "consent": {"opted_in_at": None, "scope": []},
        })
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    # ── Ack ID format ─────────────────────────────────────────────────────

    def test_ack_id_contains_context_id_and_version(self):
        r = _push("merchant", "m_007", 3, {"merchant_id": "m_007"})
        ack = r.json()["ack_id"]
        assert "m_007" in ack
        assert "3" in ack


# ---------------------------------------------------------------------------
# POST /v1/tick
# ---------------------------------------------------------------------------

class TestTick:

    def setup_method(self):
        _reset()

    def test_returns_200(self):
        r = client.post("/v1/tick", json={
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": [],
        })
        assert r.status_code == 200

    def test_returns_actions_list(self):
        body = client.post("/v1/tick", json={
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": [],
        }).json()
        assert "actions" in body
        assert isinstance(body["actions"], list)

    def test_empty_triggers_returns_empty_actions(self):
        body = client.post("/v1/tick", json={
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": [],
        }).json()
        assert body["actions"] == []

    def test_with_trigger_ids_returns_actions_list(self):
        """Even with trigger IDs, stub returns [] — real logic wired in Part 3."""
        body = client.post("/v1/tick", json={
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": ["trg_001", "trg_002"],
        }).json()
        assert isinstance(body["actions"], list)

    def test_missing_now_field_returns_400(self):
        r = client.post("/v1/tick", json={"available_triggers": []})
        assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# POST /v1/reply
# ---------------------------------------------------------------------------

class TestReply:

    def setup_method(self):
        _reset()

    def test_returns_200(self):
        r = client.post("/v1/reply", json={
            "conversation_id": "conv_001",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": "Yes, send me the abstract",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 2,
        })
        assert r.status_code == 200

    def test_returns_valid_action(self):
        body = client.post("/v1/reply", json={
            "conversation_id": "conv_002",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": "Ok let's do it",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 2,
        }).json()
        assert body["action"] in ("send", "wait", "end")

    def test_send_response_has_body(self):
        body = client.post("/v1/reply", json={
            "conversation_id": "conv_003",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": "Tell me more",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 2,
        }).json()
        if body["action"] == "send":
            assert body.get("body")  # non-empty body

    def test_unknown_conversation_still_responds(self):
        """Bot must always respond within 30 s, even for unknown conv IDs."""
        r = client.post("/v1/reply", json={
            "conversation_id": "conv_unknown_xyz",
            "merchant_id": "m_999",
            "from_role": "merchant",
            "message": "Hello?",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 1,
        })
        assert r.status_code == 200

    def test_known_conversation_message_logged(self):
        """After a /v1/reply call, the message should be in conversation history."""
        conversation_store.create("conv_log_test", "m_001")
        client.post("/v1/reply", json={
            "conversation_id": "conv_log_test",
            "merchant_id": "m_001",
            "from_role": "merchant",
            "message": "I want to join",
            "received_at": "2026-04-26T10:45:00Z",
            "turn_number": 2,
        })
        conv = conversation_store.get("conv_log_test")
        assert conv is not None
        assert any(m.body == "I want to join" for m in conv.messages)

    def test_missing_from_role_returns_error(self):
        r = client.post("/v1/reply", json={
            "conversation_id": "conv_001",
            "merchant_id": "m_001",
            "message": "Hello",
        })
        assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# POST /v1/teardown  (sanity check)
# ---------------------------------------------------------------------------

class TestTeardown:

    def test_teardown_clears_contexts(self):
        _push("category", "dentists", 1, {"slug": "dentists"})
        client.post("/v1/teardown")
        counts = client.get("/v1/healthz").json()["contexts_loaded"]
        assert all(v == 0 for v in counts.values())

    def test_teardown_clears_conversations(self):
        conversation_store.create("conv_pre_teardown", "m_001")
        client.post("/v1/teardown")
        assert conversation_store.get("conv_pre_teardown") is None
