# Vera Bot — Manual Test Requests for /docs (Swagger UI)

Base URL: `https://magicpin-vera-bot-nvk2.onrender.com`
Open `https://magicpin-vera-bot-nvk2.onrender.com/docs`, expand each endpoint, click **Try it out**, paste the body, **Execute**.

Run these **in order** — later steps depend on context pushed in earlier steps.

---

## PHASE 0 — Warmup (GET, no body)

### 0.1 `GET /v1/healthz`
Expect: `200`, `contexts_loaded` all zero (or whatever was pushed before, if you've already run this).

### 0.2 `GET /v1/metadata`
Expect: `200`, your team info.

---

## PHASE 1 — Context push: idempotency, versioning, validation

### 1.1 Push category `dentists` v1 — `POST /v1/context`
```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 1,
  "delivered_at": "2026-09-26T09:45:00Z",
  "payload": {
    "slug": "dentists",
    "display_name": "Dentists",
    "voice": {
      "tone": "peer_clinical",
      "register": "respectful_collegial",
      "code_mix": "hindi_english_natural",
      "vocab_allowed": ["fluoride varnish", "scaling", "caries", "occlusion", "bruxism", "endodontic", "periodontal", "implant", "aligner", "veneer", "OPG", "IOPA", "RCT", "CAD/CAM", "zirconia", "PFM"],
      "vocab_taboo": ["guaranteed", "100% safe", "completely cure", "miracle", "best in city", "doctor approved"],
      "salutation_examples": ["Dr. {first_name}", "Doc"],
      "tone_examples": ["Worth a look — JIDA Oct 2026 p.14", "This one likely affects your high-risk adult cohort"]
    },
    "offer_catalog": [
      {"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "audience": "new_user", "type": "service_at_price"},
      {"id": "den_003", "title": "Teeth Whitening @ ₹1,499", "value": "1499", "audience": "new_user", "type": "service_at_price"}
    ],
    "peer_stats": {"scope": "metro_solo_practices_2026", "avg_rating": 4.4, "avg_review_count": 62, "avg_ctr": 0.030, "retention_6mo_pct": 0.42},
    "digest": [
      {
        "id": "d_2026W17_jida_fluoride",
        "kind": "research",
        "title": "3-month fluoride varnish recall outperforms 6-month for high-risk adult caries",
        "source": "JIDA Oct 2026, p.14",
        "trial_n": 2100,
        "patient_segment": "high_risk_adults",
        "summary": "Multi-center Indian trial shows 38% lower caries recurrence with 3-month vs 6-month recall in adults with active decay history.",
        "actionable": "Reassess recall interval for adults flagged high-risk in your charting"
      }
    ],
    "patient_content_library": [],
    "seasonal_beats": [{"month_range": "Nov-Feb", "note": "exam-stress bruxism spike"}],
    "trend_signals": [{"query": "clear aligners delhi", "delta_yoy": 0.62, "segment_age": "28-45", "skew": "female"}],
    "regulatory_authorities": ["Dental Council of India (DCI)"],
    "professional_journals": ["JIDA"]
  }
}
```
Expect: `200`, `{"accepted": true, "ack_id": "ack_dentists_v1", ...}`

### 1.2 Repost SAME version 1 (idempotency check) — `POST /v1/context`
Send the **exact same body as 1.1**.
Expect: `200`, `accepted: true` (no-op, must NOT error).

### 1.3 Push category v2 (version bump) — `POST /v1/context`
Same body as 1.1 but change `"version": 2` and add a new digest item:
```json
{
  "scope": "category",
  "context_id": "dentists",
  "version": 2,
  "delivered_at": "2026-09-26T10:50:00Z",
  "payload": {
    "slug": "dentists",
    "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed", "100% safe"]},
    "digest": [
      {"id": "d_2026W17_jida_fluoride", "kind": "research", "title": "3-month fluoride varnish recall outperforms 6-month for high-risk adult caries", "source": "JIDA Oct 2026, p.14", "trial_n": 2100, "patient_segment": "high_risk_adults", "summary": "38% lower caries recurrence.", "actionable": "Reassess recall interval."},
      {"id": "d_2026W17_dci_radiograph_NEW", "kind": "compliance", "title": "DCI revised radiograph dose limits effective 2026-12-15", "source": "DCI circular 2026-11-04", "summary": "Max dose drops 1.5→1.0 mSv per IOPA. E-speed film passes; D-speed does not.", "actionable": "Audit X-ray setup before Dec 15."}
    ],
    "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299", "audience": "new_user", "type": "service_at_price"}],
    "peer_stats": {"avg_ctr": 0.030}
  }
}
```
Expect: `200`, `accepted: true`.

### 1.4 Repost v1 AFTER v2 (stale version) — `POST /v1/context`
Send **body from 1.1** (version 1) again.
Expect: **`409`**, `{"accepted": false, "reason": "stale_version", "current_version": 2}`

### 1.5 Invalid scope — `POST /v1/context`
```json
{
  "scope": "banana",
  "context_id": "x",
  "version": 1,
  "payload": {}
}
```
Expect: **`400`**, `accepted: false`, `reason` mentions invalid scope.

### 1.6 Malformed / missing fields — `POST /v1/context`
```json
{
  "scope": "category"
}
```
Expect: **`400`** (or `422` — check which your app returns; brief wants 400).

---

## PHASE 2 — Push merchant, customer, triggers (real dataset)

### 2.1 Push merchant `m_001_drmeera_dentist_delhi` v1 — `POST /v1/context`
```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 1,
  "delivered_at": "2026-09-26T09:45:30Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {"name": "Dr. Meera's Dental Clinic", "city": "Delhi", "locality": "Lajpat Nagar", "place_id": "ChIJ_LAJPATNAGAR_DENTIST_001", "verified": true, "languages": ["en", "hi"], "owner_first_name": "Meera", "established_year": 2018},
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 82},
    "performance": {"window_days": 30, "views": 2410, "calls": 18, "directions": 45, "ctr": 0.021, "leads": 9, "delta_7d": {"views_pct": 0.18, "calls_pct": -0.05}},
    "offers": [{"id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active"}],
    "conversation_history": [],
    "customer_aggregate": {"total_unique_ytd": 540, "lapsed_180d_plus": 78, "retention_6mo_pct": 0.38, "high_risk_adult_count": 124},
    "signals": ["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort", "engaged_in_last_48h"],
    "review_themes": []
  }
}
```
Expect: `200`, `accepted: true`.

### 2.2 Push customer `c_001_priya_for_m001` v1 — `POST /v1/context`
```json
{
  "scope": "customer",
  "context_id": "c_001_priya_for_m001",
  "version": 1,
  "delivered_at": "2026-09-26T09:46:00Z",
  "payload": {
    "customer_id": "c_001_priya_for_m001",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "identity": {"name": "Priya", "phone_redacted": "<phone>", "language_pref": "hi-en mix", "age_band": "25-35"},
    "relationship": {"first_visit": "2025-11-04", "last_visit": "2026-05-12", "visits_total": 4, "services_received": ["cleaning", "cleaning", "whitening", "cleaning"], "lifetime_value": 1696},
    "state": "lapsed_soft",
    "preferences": {"preferred_slots": "weekday_evening", "channel": "whatsapp", "reminder_opt_in": true},
    "consent": {"opted_in_at": "2025-11-04", "scope": ["recall_reminders", "appointment_reminders"]}
  }
}
```
Expect: `200`, `accepted: true`.

### 2.3 Push trigger `trg_001_research_digest_dentists` (merchant-scope) — `POST /v1/context`
```json
{
  "scope": "trigger",
  "context_id": "trg_001_research_digest_dentists",
  "version": 1,
  "delivered_at": "2026-09-26T10:32:00Z",
  "payload": {
    "id": "trg_001_research_digest_dentists",
    "scope": "merchant",
    "kind": "research_digest",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
    "urgency": 2,
    "suppression_key": "research:dentists:2026-W17",
    "expires_at": "2026-12-03T00:00:00Z"
  }
}
```
Expect: `200`, `accepted: true`.

### 2.4 Push trigger `trg_003_recall_due_priya` (customer-scope) — `POST /v1/context`
```json
{
  "scope": "trigger",
  "context_id": "trg_003_recall_due_priya",
  "version": 1,
  "delivered_at": "2026-09-26T11:00:00Z",
  "payload": {
    "id": "trg_003_recall_due_priya",
    "scope": "customer",
    "kind": "recall_due",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": "c_001_priya_for_m001",
    "payload": {
      "service_due": "6_month_cleaning",
      "last_service_date": "2026-05-12",
      "due_date": "2026-11-12",
      "available_slots": [
        {"iso": "2026-11-05T18:00:00+05:30", "label": "Wed 5 Nov, 6pm"},
        {"iso": "2026-11-06T17:00:00+05:30", "label": "Thu 6 Nov, 5pm"}
      ]
    },
    "urgency": 3,
    "suppression_key": "recall:c_001_priya_for_m001:6mo",
    "expires_at": "2026-11-30T00:00:00Z"
  }
}
```
Expect: `200`, `accepted: true`.

### 2.5 Push trigger `trg_022_cde_webinar_dentists` (for auto-reply-hell test later) — `POST /v1/context`
```json
{
  "scope": "trigger",
  "context_id": "trg_022_cde_webinar_dentists",
  "version": 1,
  "delivered_at": "2026-09-26T11:05:00Z",
  "payload": {
    "id": "trg_022_cde_webinar_dentists",
    "scope": "merchant",
    "kind": "cde_opportunity",
    "source": "external",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {"digest_item_id": "d_2026W17_ida_webinar", "credits": 2, "fee": "free_for_members"},
    "urgency": 1,
    "suppression_key": "cde:dentists:2026-11-02",
    "expires_at": "2026-11-02T19:00:00+05:30"
  }
}
```
Expect: `200`, `accepted: true`.

### 2.6 `GET /v1/healthz` — check counts
Expect: `contexts_loaded` = `{"category": 1, "merchant": 1, "customer": 1, "trigger": 3}`

---

## PHASE 3 — Tick: does the bot actually compose grounded messages?

### 3.1 Tick with the research-digest trigger — `POST /v1/tick`
```json
{
  "now": "2026-09-26T10:35:00Z",
  "available_triggers": ["trg_001_research_digest_dentists"]
}
```
**This is the most important check.** Expect `200` with `actions: [...]` containing ONE action whose `body`:
- mentions Dr. Meera / the clinic by name
- cites JIDA / fluoride / 2,100 / 38% (real digest facts — NOT invented)
- has a `conversation_id`, `cta`, `suppression_key` matching `research:dentists:2026-W17`, and a `rationale`

⚠️ **If the body is generic** (e.g. *"Hi, this is Vera. I have an update regarding your magicpin profile. Please reply when you have a moment."*) — that's the deterministic **fallback** firing, meaning `GEMINI_API_KEY` is missing/invalid on Render. This is the #1 thing to check. **Note the exact `conversation_id` returned — you need it for Phase 4.**

### 3.2 Tick with the customer-scoped recall trigger — `POST /v1/tick`
```json
{
  "now": "2026-09-26T11:05:00Z",
  "available_triggers": ["trg_003_recall_due_priya"]
}
```
Expect: action with `customer_id: "c_001_priya_for_m001"`, `send_as: "merchant_on_behalf"`, body mentioning Priya, the real slot times (Wed 5 Nov 6pm / Thu 6 Nov 5pm), ₹299 cleaning, hi-en mix language. **Note this `conversation_id` too.**

### 3.3 Tick with an unknown trigger id — `POST /v1/tick`
```json
{
  "now": "2026-09-26T11:10:00Z",
  "available_triggers": ["trg_does_not_exist"]
}
```
Expect: `200`, `actions: []` (must not error/crash).

### 3.4 Tick with empty triggers — `POST /v1/tick`
```json
{
  "now": "2026-09-26T11:11:00Z",
  "available_triggers": []
}
```
Expect: `200`, `actions: []`.

### 3.5 Re-tick the SAME trigger again (suppression check) — `POST /v1/tick`
Same body as 3.1.
Expect: `actions: []` — should be suppressed (already sent, same `suppression_key`), unless your router intentionally allows resend. If it sends again with the identical body, that's a repetition bug the judge penalizes (-2).

---

## PHASE 4 — Reply: conversation behavior (use the `conversation_id` from 3.1)

Replace `<CONV_ID_FROM_3.1>` below with the actual ID returned.

### 4.1 Engaged reply — `POST /v1/reply`
```json
{
  "conversation_id": "<CONV_ID_FROM_3.1>",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Yes please send the abstract. Also draft the patient WhatsApp.",
  "received_at": "2026-09-26T10:42:00Z",
  "turn_number": 2
}
```
Expect: `action: "send"`, body honors the ask, no repetition of the first message.

### 4.2 Off-topic curveball — `POST /v1/reply` (new conversation_id)
```json
{
  "conversation_id": "conv_test_offtopic_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Btw can you also help me file my GST return this month?",
  "received_at": "2026-09-26T10:43:00Z",
  "turn_number": 2
}
```
Expect: `action: "send"`, politely declines GST help, redirects to the actual topic (does NOT hallucinate capability).

### 4.3 Hostile / not-interested — `POST /v1/reply` (new conversation_id)
```json
{
  "conversation_id": "conv_test_hostile_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Stop messaging me. This is useless spam.",
  "received_at": "2026-09-26T10:44:00Z",
  "turn_number": 2
}
```
Expect: `action: "end"` (or a one-line polite apology + end). Must NOT keep pitching.

### 4.4 Intent transition (commitment) — `POST /v1/reply` (new conversation_id)
```json
{
  "conversation_id": "conv_test_intent_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Ok lets do it. Whats next?",
  "received_at": "2026-09-26T10:45:00Z",
  "turn_number": 2
}
```
Expect: `action: "send"`, body uses action words ("done", "sending", "draft", "confirm", "next") — must NOT ask another qualifying question like "Would you be interested in...".

### 4.5 Auto-reply hell — turn 1 — `POST /v1/reply`
```json
{
  "conversation_id": "conv_test_autoreply_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
  "received_at": "2026-09-26T10:46:00Z",
  "turn_number": 2
}
```
Expect: `action: "send"` (one gentle nudge) OR `"wait"` — must NOT `"end"` yet on the first canned reply.

### 4.6 Auto-reply hell — turn 2 (SAME canned text again) — `POST /v1/reply`
```json
{
  "conversation_id": "conv_test_autoreply_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
  "received_at": "2026-09-26T10:47:00Z",
  "turn_number": 3
}
```
Expect: `action: "wait"` (streak=2, per your `routing/auto_reply.py` logic) with a `wait_seconds` value.

### 4.7 Auto-reply hell — turn 3 (SAME canned text again) — `POST /v1/reply`
```json
{
  "conversation_id": "conv_test_autoreply_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
  "received_at": "2026-09-26T10:48:00Z",
  "turn_number": 4
}
```
Expect: `action: "end"` — bot must stop burning turns on the same auto-reply.

### 4.8 Unknown conversation_id (judge references a conv the bot "forgot") — `POST /v1/reply`
```json
{
  "conversation_id": "conv_never_seen_before_xyz",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Hello?",
  "received_at": "2026-09-26T10:49:00Z",
  "turn_number": 1
}
```
Expect: `200` with a valid action — must not 500.

### 4.9 Malformed reply (missing `from_role`) — `POST /v1/reply`
```json
{
  "conversation_id": "conv_bad_001",
  "merchant_id": "m_001_drmeera_dentist_delhi",
  "message": "Hello"
}
```
Expect: `400`/`422`, not a `500`.

---

## PHASE 5 — Adaptive context injection (mid-test updates)

### 5.1 Push updated merchant performance (v2) — `POST /v1/context`
```json
{
  "scope": "merchant",
  "context_id": "m_001_drmeera_dentist_delhi",
  "version": 2,
  "delivered_at": "2026-09-26T11:15:00Z",
  "payload": {
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "category_slug": "dentists",
    "identity": {"name": "Dr. Meera's Dental Clinic", "city": "Delhi", "locality": "Lajpat Nagar", "verified": true, "languages": ["en", "hi"], "owner_first_name": "Meera"},
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 78},
    "performance": {"window_days": 30, "views": 3100, "calls": 25, "directions": 52, "ctr": 0.035, "leads": 14, "delta_7d": {"views_pct": 0.28, "calls_pct": 0.15}},
    "offers": [{"id": "o_meera_001", "title": "Dental Cleaning @ ₹299", "status": "active"}],
    "customer_aggregate": {"total_unique_ytd": 540},
    "signals": ["ctr_above_peer_median_now", "engaged_in_last_48h"]
  }
}
```
Expect: `200`, `accepted: true`.

### 5.2 New trigger reflecting the updated perf (`perf_spike`) — `POST /v1/context`
```json
{
  "scope": "trigger",
  "context_id": "trg_test_perf_spike_meera",
  "version": 1,
  "delivered_at": "2026-09-26T11:16:00Z",
  "payload": {
    "id": "trg_test_perf_spike_meera",
    "scope": "merchant",
    "kind": "perf_spike",
    "source": "internal",
    "merchant_id": "m_001_drmeera_dentist_delhi",
    "customer_id": null,
    "payload": {"metric": "views", "delta_pct": 0.28, "window": "7d", "vs_baseline": 2410},
    "urgency": 1,
    "suppression_key": "perf_spike:m_001:views:test",
    "expires_at": "2026-10-03T00:00:00Z"
  }
}
```

### 5.3 Tick again — bot should use the NEW numbers (3,100 views / 3.5% CTR), not the old ones — `POST /v1/tick`
```json
{
  "now": "2026-09-26T11:17:00Z",
  "available_triggers": ["trg_test_perf_spike_meera"]
}
```
Expect: body cites the updated performance figures (3,100 / 25 / 0.035 / +28%), proving version-bump adoption. If it still cites the old 2,410/18/0.021, that's a stale-context bug.

---

## PHASE 6 — Teardown

### 6.1 `POST /v1/teardown` (if exposed — check `/docs`; it's `include_in_schema=False` in your code so it may not show in Swagger UI — call it directly via curl if needed)
```
curl -X POST https://magicpin-vera-bot-nvk2.onrender.com/v1/teardown
```
Expect: `{"status": "wiped"}`, then `GET /v1/healthz` shows all-zero counts again.

---

## Quick pass/fail checklist

- [ ] 1.2 idempotent repost → `200`, not `409`
- [ ] 1.4 stale version → `409` with `current_version: 2`
- [ ] 1.5 / 1.6 invalid input → `400`
- [ ] 3.1 tick body is **grounded** (real JIDA facts), not generic fallback text
- [ ] 3.1 `suppression_key` present and matches trigger's key
- [ ] 3.5 same trigger doesn't re-fire (or if it does, body isn't verbatim repeated)
- [ ] 4.3 hostile → `action: "end"`, no more selling
- [ ] 4.4 committed → action words, no re-qualifying question
- [ ] 4.6–4.7 auto-reply streak → `wait` then `end`, not endless `send`
- [ ] 4.9 malformed body → `400`/`422`, never `500`
- [ ] 5.3 tick after version bump uses **new** performance numbers
- [ ] every `/v1/tick` and `/v1/reply` response arrives well under 30s
