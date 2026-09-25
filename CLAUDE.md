## 1. Project mission

You are working on the **magicpin AI Challenge**.

The goal is to build an AI assistant that engages and assists merchants over WhatsApp in the style of magicpin's merchant assistant **Vera**, but with better specificity, intent handling, engagement, and multi-turn behavior.

The challenge is evaluated by an automated/LLM judge. Treat the challenge brief and testing brief as the source of truth.

### Primary objective

Build a robust, stateful bot that:

1. Receives Category, Merchant, Trigger, and optional Customer contexts.
2. Stores and updates those contexts correctly.
3. Decides when a proactive message should be sent.
4. Composes concise, category-appropriate, merchant-specific WhatsApp messages.
5. Handles replies across multiple turns.
6. Detects auto-replies and avoids wasting turns.
7. Detects explicit intent and switches from qualification to action immediately.
8. Knows when to wait or gracefully end.
9. Adapts to context updates injected after the initial dataset.
10. Never fabricates facts that are not present in the supplied context.

The bot must optimize for the judge's rubric rather than generic chatbot behavior.

---

# 2. Source-of-truth documents

The repository is accompanied by these challenge materials:

- `challenge-brief.md`
- `challenge-testing-brief.md`
- `engagement-design.md`
- `engagement-research.md`
- `judge_simulator.py`

Read these before making architectural changes.

### Important distinction

- `challenge-brief.md` = product requirements, composition framework, evaluation criteria, examples, engagement principles.
- `challenge-testing-brief.md` = HTTP contract, lifecycle, rate limits, timeouts, deployment expectations, and judge behavior.
- `engagement-design.md` = proposed 4-context engagement architecture and composer design.
- `engagement-research.md` = how existing Vera/merchant/customer data is currently obtained and what is already available.
- `judge_simulator.py` = local evaluator and practical behavioral contract.

Do not invent requirements that contradict these documents.

---

# 3. Core mental model

Every outbound message is composed from:

```text
compose(category, merchant, trigger, customer?)
```

The four contexts are:

### CategoryContext

Slow-changing knowledge about the business vertical.

Contains:

- category slug
- offer catalog
- voice
- vocabulary and taboos
- peer statistics
- research/compliance digest
- patient/customer-facing content
- seasonal beats
- trend signals

### MerchantContext

Current state of one merchant.

Contains:

- merchant identity
- subscription
- performance
- active/paused offers
- conversation history
- customer aggregates
- derived signals

### TriggerContext

Why the message should happen **right now**.

Examples:

- research digest
- recall due
- performance spike/dip
- milestone
- dormant merchant
- festival
- weather
- local event
- competitor opened
- review theme
- scheduled curiosity question

Every proactive message must have a trigger.

### CustomerContext

Only for customer-facing messages sent on behalf of a merchant.

Contains:

- customer identity
- relationship with merchant
- lifecycle state
- preferences
- consent

---

# 4. Evaluation rubric

The judge scores generated messages on five dimensions, each from 0–10:

1. **Specificity**
2. **Category fit**
3. **Merchant fit**
4. **Trigger relevance / decision quality**
5. **Engagement compulsion**

Total message score = 50 before penalties/bonuses.

## 4.1 Specificity

Prefer concrete, verifiable facts:

- numbers
- dates
- localities
- ratings
- review counts
- CTR
- views
- calls
- active offers
- research headlines
- source citations
- trigger payload facts

Avoid generic messages such as:

> Improve your profile to get more customers.

Prefer:

> Your profile had 2,410 views this month, but CTR is 2.1% versus the 3.0% peer median.

Never invent a number.

## 4.2 Category fit

The message must sound like the category.

Examples:

- Dentists: clinical, peer-to-peer, technical terms can be appropriate, avoid hype.
- Salons: warm, friendly, practical.
- Restaurants: operator-to-operator.
- Gyms: coaching/motivational.
- Pharmacies: trustworthy and precise.

Respect `voice`, allowed vocabulary, and taboos supplied in CategoryContext.

## 4.3 Merchant fit

Personalize using actual context:

- merchant name
- owner name if supplied
- locality/city
- performance
- offers
- customer aggregate
- previous conversation
- signals
- language preference

Do not fabricate merchant information.

## 4.4 Trigger relevance

The message must answer:

> Why am I messaging this merchant right now?

Use the actual trigger payload.

Do not turn every trigger into a generic promotional message.

## 4.5 Engagement compulsion

Use one or more appropriate levers:

1. Specificity/verifiability
2. Loss aversion
3. Social proof
4. Effort externalization
5. Curiosity
6. Reciprocity
7. Asking the merchant
8. Single binary commitment

Use judgment. Do not force a CTA onto purely informational messages.

---

# 5. Message-writing rules

## Always

- Be concise.
- Lead with the useful fact.
- Make the message feel written for this merchant.
- Make the reason for contacting them obvious.
- Use the merchant's preferred language where possible.
- Match category voice.
- Use actual prices/offers from context.
- Use source citations when the trigger is research/compliance related.
- Put the primary CTA at the end.
- Maintain conversation continuity.
- Avoid repeating previously sent copy.
- Be honest about uncertainty.

## Never

- Hallucinate numbers, sources, competitors, offers, dates, slots, or performance.
- Use generic discount copy when a service+price offer is available.
- Use multiple competing CTAs.
- Bury the CTA.
- Use hype for clinical/professional categories.
- Start every message with a long greeting.
- Re-introduce Vera after the first turn.
- Ignore the merchant's language preference.
- Repeat the same message verbatim.
- Continue pushing after a clear stop/not-interested signal.
- Ask another qualification question after the merchant has clearly committed to an action.

---

# 6. High-priority behavioral rules

These are especially important because the challenge explicitly tests them.

## 6.1 Auto-reply detection

Merchant WhatsApp Business accounts may send canned replies.

Signals include:

- same or nearly identical message repeated multiple times
- obvious canned wording such as:
  - "Thank you for contacting us..."
  - "Our team will respond shortly..."
  - "I am an automated assistant..."
- no meaningful response to Vera's previous question

Behavior:

1. Do not repeatedly re-qualify.
2. Optionally make one useful attempt if appropriate.
3. If the pattern continues, gracefully end/wait.
4. Do not burn four or five turns against the same auto-reply.

The local judge explicitly sends repeated canned messages and checks whether the bot exits.

## 6.2 Intent transition

If the merchant says something equivalent to:

- "Yes, let's do it"
- "Ok let's proceed"
- "I want to join"
- "Go ahead"
- "Please update it"
- "Send it"
- "Do it"

switch immediately from **qualification/pitch mode** to **action mode**.

Bad:

> Would you be interested in getting more customers?

after the merchant already said:

> Yes, let's do it.

Good:

> Done — I'll start with the profile update. Please send the missing business hours.

Or, when no action tool exists:

> Great — I'll move to the next step. Here's exactly what I need from you: ...

Do not ask redundant qualification questions.

## 6.3 Hostile / not interested

If the merchant says:

> Stop messaging me.

or:

> This is useless spam.

Respond politely and end the conversation when appropriate.

Never argue, persuade aggressively, or continue selling.

## 6.4 Off-topic requests

Stay on mission.

If the merchant asks for an unrelated service that the bot cannot actually perform, do not hallucinate capability.

Acknowledge briefly and redirect to the supported Vera task.

---

# 7. Proactive engagement strategy

`/v1/tick` is not a requirement to send a message every time.

The bot may return:

```json
{"actions": []}
```

when nothing is worth sending.

Prioritize:

1. High-value actionable triggers.
2. Time-sensitive triggers.
3. Strong merchant-specific opportunities.
4. Curiosity/knowledge triggers.
5. Customer lifecycle opportunities when consent exists.
6. Lower-value reminders only when appropriate.

Avoid notification spam.

Use `suppression_key` to deduplicate.

Never send the same trigger repeatedly unless the context/version meaningfully changed and the suppression policy allows it.

---

# 8. WhatsApp/session constraints

The challenge specifies:

- First outbound message in a session must use an approved-template style payload.
- Subsequent messages within 24 hours of a merchant reply can be free-form.
- Keep bodies concise and readable.
- A single primary CTA is preferred.
- URLs are allowed only when they add clear value.

Represent first-touch messages with:

- `template_name`
- `template_params`
- `body`

For subsequent turns, the normal `body` is sufficient.

Do not put implementation jargon into merchant-facing copy.

---

# 9. Required HTTP API

The bot must expose five endpoints.

## POST /v1/context

Purpose: receive context updates.

Request:

```json
{
  "scope": "category | merchant | customer | trigger",
  "context_id": "unique-context-id",
  "version": 3,
  "payload": {},
  "delivered_at": "2026-04-26T10:00:00Z"
}
```

Rules:

- Idempotent by `(context_id, version)`.
- Reposting the same version is a no-op.
- Higher version replaces the previous version atomically.
- Preserve context across requests.

Successful response:

```json
{
  "accepted": true,
  "ack_id": "ack_...",
  "stored_at": "..."
}
```

Stale version:

```json
{
  "accepted": false,
  "reason": "stale_version",
  "current_version": 5
}
```

Malformed request should return an appropriate 400 response.

## POST /v1/tick

Request:

```json
{
  "now": "2026-04-26T10:30:00Z",
  "available_triggers": ["trigger-id"]
}
```

Response:

```json
{
  "actions": []
}
```

or:

```json
{
  "actions": [
    {
      "conversation_id": "conv_unique",
      "merchant_id": "m_001",
      "customer_id": null,
      "send_as": "vera",
      "trigger_id": "trigger-id",
      "template_name": "vera_template_v1",
      "template_params": [],
      "body": "...",
      "cta": "open_ended",
      "suppression_key": "unique-key",
      "rationale": "..."
    }
  ]
}
```

Important:

- A new conversation must have a new `conversation_id`.
- Do not reuse an existing conversation ID to start another conversation.
- `/v1/tick` must be fast and should return within the judge's 30-second timeout.

## POST /v1/reply

Request:

```json
{
  "conversation_id": "conv_001",
  "merchant_id": "m_001",
  "customer_id": null,
  "from_role": "merchant",
  "message": "Yes, send me the abstract",
  "received_at": "2026-04-26T10:45:00Z",
  "turn_number": 2
}
```

Valid responses:

### Send

```json
{
  "action": "send",
  "body": "...",
  "cta": "open_ended",
  "rationale": "..."
}
```

### Wait

```json
{
  "action": "wait",
  "wait_seconds": 1800,
  "rationale": "..."
}
```

### End

```json
{
  "action": "end",
  "rationale": "..."
}
```

The response must be synchronous and within 30 seconds.

## GET /v1/healthz

Return HTTP 200 and a JSON health response.

Example:

```json
{
  "status": "ok",
  "uptime_seconds": 1234,
  "contexts_loaded": {
    "category": 5,
    "merchant": 50,
    "customer": 200,
    "trigger": 100
  }
}
```

Three consecutive health failures can disqualify the bot for a test slot.

## GET /v1/metadata

Return bot identity information:

```json
{
  "team_name": "...",
  "team_members": [],
  "model": "...",
  "approach": "...",
  "contact_email": "...",
  "version": "...",
  "submitted_at": "..."
}
```

Do not hardcode fake credentials or contact information.

---

# 10. Context storage architecture

Use a version-aware context store.

Recommended logical structure:

```text
contexts/
  categories[context_id] -> {version, payload}
  merchants[context_id]  -> {version, payload}
  customers[context_id]  -> {version, payload}
  triggers[context_id]   -> {version, payload}

conversations/
  conversation_id -> {
    merchant_id,
    customer_id,
    messages[],
    state,
    last_trigger_id,
    last_sent_body,
    turn_count,
    mode
  }
```

For local development, in-memory state is acceptable.

For production-like reliability, SQLite or Redis may be used if already present in the repository.

Do not add unnecessary infrastructure before confirming it is needed.

---

# 11. Conversation state

Every active conversation should track at least:

- conversation ID
- merchant ID
- customer ID if applicable
- trigger
- sent messages
- received messages
- turn number
- current intent
- whether merchant has committed to an action
- whether an auto-reply pattern was detected
- whether the merchant has asked to stop
- whether the conversation is waiting
- whether the conversation has ended

Useful intent states:

```text
NEW
PITCHING
QUALIFYING
COMMITTED
ACTIONING
WAITING
AUTO_REPLY
NOT_INTERESTED
OFF_TOPIC
ENDED
```

Do not over-engineer the state machine if simple deterministic rules are sufficient.

---

# 12. LLM composer architecture

Prefer a layered architecture:

```text
HTTP API
   |
Context Store
   |
Trigger Router
   |
Conversation State
   |
Composer
   |
Post-generation Validator
   |
Response
```

The LLM should not be responsible for everything.

Use deterministic code for:

- version checks
- context storage
- deduplication
- conversation state
- obvious intent detection
- auto-reply detection
- stop detection
- schema validation
- CTA validation
- maximum action count
- context lookup

Use the LLM for:

- natural-language composition
- category-appropriate phrasing
- language mixing
- nuanced prioritization
- conversational responses

---

# 13. Composer prompt rules

The composer must receive structured context.

Conceptually:

```text
CATEGORY
MERCHANT
TRIGGER
CUSTOMER (optional)
CONVERSATION HISTORY
CURRENT CONVERSATION STATE

TASK:
Compose the next WhatsApp message.

REQUIREMENTS:
- Use only facts present in context.
- Match category voice.
- Personalize to merchant/customer.
- Make the trigger/reason clear.
- Keep it concise.
- Use one primary CTA at most.
- Do not hallucinate.
- Do not repeat prior messages.
- If intent is already committed, take action rather than qualify.
```

Different trigger kinds may use different prompt variants.

Examples:

- `research_digest` → source-backed knowledge hook
- `recall_due` → appointment/slot framing
- `competitor_opened` → curiosity/social-proof framing
- `perf_dip` → concrete performance issue + next action
- `milestone_reached` → celebrate + useful next step
- `customer_lapsed_soft` → personalized reactivation
- `appointment_tomorrow` → concise reminder

Keep prompt versions explicit, e.g.:

```text
composer_v1
composer_v2
```

Record the version in internal logs.

---

# 14. Post-generation validation

Never blindly return raw LLM output.

Validate:

### Factual grounding

Reject or regenerate if the message introduces unsupported:

- numbers
- prices
- dates
- competitor names
- research papers
- performance metrics
- offers
- appointment slots

### CTA

Check for multiple conflicting CTAs.

Prefer one clear CTA.

### Language

If the merchant prefers `hi-en mix`, the message can naturally use Hindi-English mix.

Do not mechanically translate every English word.

### Repetition

Compare against previous messages in the conversation.

If the body is effectively identical, regenerate.

### Category safety

Check taboo vocabulary from CategoryContext.

### Length

Keep messages short enough for WhatsApp readability.

---

# 15. Dataset handling

The judge initially loads:

- 5 category contexts
- 50 merchant contexts
- 200 customer contexts
- triggers during the test

The judge can later inject new:

- digest items
- merchant performance versions
- triggers
- customer contexts

Never assume the initial dataset is complete.

The bot must use the **latest context version**.

The judge intentionally rewards adaptation to newly injected context.

---

# 16. Local testing

The repository includes `judge_simulator.py`.

Run the bot first, then run the judge.

On Windows PowerShell, prefer:

```powershell
python --version
python judge_simulator.py
```

or:

```powershell
py --version
py judge_simulator.py
```

If `python3` is not recognized on Windows, do not use it by default.

The simulator supports scenarios including:

```text
warmup
phase2_short
auto_reply_hell
intent_transition
hostile
all
full_evaluation
```

Use:

```powershell
python judge_simulator.py
```

for the default configuration.

If needed, edit the simulator configuration:

- `BOT_URL`
- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`
- `TEST_SCENARIO`

Do not commit API keys.

---

# 17. Local test priorities

Before considering the implementation complete, verify:

### API

- `/v1/healthz`
- `/v1/metadata`
- `/v1/context`
- `/v1/tick`
- `/v1/reply`

### Context behavior

- same `(context_id, version)` is idempotent
- stale versions do not overwrite newer versions
- newer versions replace old versions
- contexts survive across calls

### Proactive behavior

- active triggers can produce actions
- no-trigger situations can return zero actions
- suppression works
- each new conversation gets a unique ID

### Conversation behavior

- normal engaged reply
- auto-reply
- explicit commitment
- not interested
- hostile message
- off-topic question
- language switch
- repeated message

### Evaluation

Run:

```powershell
python judge_simulator.py
```

Then specifically test:

```powershell
# Depending on the simulator configuration:
# warmup
# phase2_short
# auto_reply_hell
# intent_transition
# hostile
# full_evaluation
```

Aim for strong scores across all five dimensions, not just one.

---

# 18. Security and privacy

The challenge dataset is synthetic.

Do not:

- send merchant/customer payloads to arbitrary external services
- add analytics that exfiltrate context
- log sensitive payloads unnecessarily
- persist challenge context after teardown

Commercial LLM APIs are allowed for composition, but external APIs must not receive merchant/customer data unless explicitly permitted by the challenge.

Never commit API keys.

Use environment variables for secrets.

---

# 19. Code-quality rules for Claude

When modifying this project:

1. Inspect the existing repository before creating new architecture.
2. Reuse existing utilities where appropriate.
3. Prefer small modules with clear responsibilities.
4. Do not rewrite working code without a concrete reason.
5. Do not introduce dependencies unnecessarily.
6. Keep API schemas stable.
7. Add tests for every behavioral bug fixed.
8. Preserve backward compatibility unless the challenge requires a breaking change.
9. Validate all external/LLM output.
10. Keep deterministic routing logic outside the LLM when possible.
11. Do not hardcode the seed dataset into the composer.
12. Do not hardcode one merchant's behavior as the general solution.
13. Do not optimize for a single visible example at the expense of generalization.
14. Never fabricate missing data to make a message sound impressive.

---

# 20. Development workflow

Before coding:

1. Inspect the repository structure.
2. Find the current entrypoint.
3. Find existing API/server code.
4. Find dataset loading/generation code.
5. Find existing LLM/client abstractions.
6. Find tests.
7. Read relevant challenge sections.
8. Identify the smallest change that satisfies the requirement.

After coding:

1. Run syntax/type checks if available.
2. Start the bot.
3. Run health check.
4. Run the local judge.
5. Run targeted scenarios.
6. Fix failures.
7. Re-run full evaluation.
8. Review generated messages manually for hallucination and repetition.
9. Confirm no secrets are committed.

---

# 21. Important anti-patterns

Avoid these implementation shortcuts:

### Hardcoded message templates only

A static list of messages will not adapt to injected context.

### One giant LLM prompt with no routing

Different trigger types require different conversational strategies.

### LLM-only state management

The LLM should not be trusted to remember versions, suppression, or exact conversation state.

### Always send something

Zero-action ticks are valid.

### Always ask a question

Some messages should inform, act, wait, or end.

### Always use discounts

Service + price is often stronger and more category-appropriate than generic percentage discounts.

### Generic personalization

Writing:

> Hi Dr. Meera, grow your business today!

is not sufficient.

Use actual context:

> Your CTR is 2.1% versus the 3.0% peer median.

### Qualification after commitment

Never make the merchant repeat a decision they already made.

### Repeated auto-reply interaction

Detect canned replies and exit gracefully.

---

# 22. Target behavior examples

## Good merchant-facing message

```text
Dr. Meera, JIDA's latest issue has one useful item for your high-risk adult patients: a 2,100-patient trial found 3-month fluoride recall performed better than 6-month recall. Want me to pull the abstract and draft a patient WhatsApp?
```

Why:

- category-specific
- source-backed
- concrete
- tied to merchant context
- clear low-friction CTA

## Good performance message

```text
Your listing got 2,410 views in the last 30 days, but CTR is 2.1% vs the 3.0% peer median in South Delhi. I can draft the profile changes that target the biggest gap — want me to?
```

## Bad

```text
Hi! We have an amazing opportunity to help you grow your business. Would you like to know more?
```

Reason: generic, low specificity, weak merchant fit.

## Bad intent handling

Merchant:

```text
Yes, let's do it.
```

Bad bot:

```text
Would you be interested in proceeding with the update?
```

Correct behavior:

```text
Great — let's do it. I’ll start with the profile update. Please send the current business hours.
```

## Auto-reply

If the same canned reply appears repeatedly:

```text
Thank you for contacting us. Our team will respond shortly.
```

Do not continue asking new qualification questions. After detecting the pattern, gracefully wait/end.

---

# 23. Architecture preference

A practical project structure is:

```text
project/
├── CLAUDE.md
├── bot.py
├── composer/
│   ├── __init__.py
│   ├── composer.py
│   ├── prompts.py
│   └── validators.py
├── state/
│   ├── context_store.py
│   └── conversation_store.py
├── routing/
│   ├── trigger_router.py
│   ├── intent.py
│   └── auto_reply.py
├── models/
│   └── contexts.py
├── dataset/
├── tests/
├── judge_simulator.py
└── README.md
```

This is a recommendation, not a requirement. Reuse the repository's existing structure if it is already sensible.

---

# 24. Definition of done

The implementation is ready only when:

- [ ] All five API endpoints work.
- [ ] Context versions are handled correctly.
- [ ] State persists between HTTP requests.
- [ ] Proactive ticks can produce zero or more actions.
- [ ] Every new proactive conversation has a unique ID.
- [ ] Reply handling supports send/wait/end.
- [ ] Auto-replies are detected.
- [ ] Explicit intent transitions to action mode.
- [ ] Not-interested/hostile messages are handled gracefully.
- [ ] Messages are category-appropriate.
- [ ] Messages use merchant-specific facts.
- [ ] Trigger relevance is obvious.
- [ ] No unsupported facts are fabricated.
- [ ] Repetition is prevented.
- [ ] New context versions are used.
- [ ] Customer-facing messages respect consent and customer context.
- [ ] `/v1/tick` and `/v1/reply` stay within the 30-second judge timeout.
- [ ] Health endpoint remains reliable.
- [ ] `judge_simulator.py` runs successfully.
- [ ] No API keys/secrets are committed.
- [ ] The README explains how to run and deploy the bot.

---

# 25. Claude operating instruction

When asked to implement, debug, or improve this project:

**First inspect the relevant code and challenge requirements. Then make the smallest robust change. Test it against the local judge and the relevant behavioral scenario. Do not optimize for a single example; optimize for the five-dimensional evaluation rubric and the adaptive, stateful test harness.**

When there is a conflict between a generic coding preference and the challenge requirements, prioritize the challenge requirements.

When information is missing, inspect the repository and supplied challenge files before guessing.

Do not claim that a feature works until it has been tested.

