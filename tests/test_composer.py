"""
tests/test_composer.py
----------------------
Comprehensive tests for the Gemini composer module.

Covers:
1. Gemini client initialization
2. Missing GEMINI_API_KEY
3. Gemini API success
4. Gemini API timeout/error
5. Malformed Gemini response
6. Structured JSON parsing
7. First-touch message generation (prompts)
8. Free-form follow-up generation (prompts)
9. Customer consent handling (prompts)
10. Merchant-context grounding (prompts)
11. Category-context grounding (prompts)
12. Trigger-context grounding (prompts)
13. Single CTA enforcement (validators)
14. Deterministic fallback when Gemini fails
"""

import json
from unittest.mock import MagicMock

import pytest

from composer.composer import EngagementComposer, _fallback_message
from composer.gemini import GeminiClient
from composer.prompts import build_prompt
from composer.validators import validate
from google.genai.errors import APIError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_category():
    return {
        "slug": "dentists",
        "voice": {
            "tone": "clinical",
            "vocab_taboo": ["deal", "discount", "cheap"],
            "salutation_examples": ["Dr. {name}"],
        }
    }

@pytest.fixture
def mock_merchant():
    return {
        "merchant_id": "m_001",
        "identity": {"name": "Smile Clinic", "owner_first_name": "Meera"},
        "performance": {"views": 1200, "calls": 45, "ctr": 0.035},
        "subscription": {"status": "active"},
    }

@pytest.fixture
def mock_trigger():
    return {
        "id": "trg_001",
        "kind": "perf_dip",
        "payload": {"metric": "calls", "delta_pct": -0.2},
    }

@pytest.fixture
def mock_customer():
    return {
        "customer_id": "c_001",
        "identity": {"name": "Arjun"},
        "consent": {"scope": ["recall_reminders"]},
    }

# ---------------------------------------------------------------------------
# 1 & 2. Client init & Missing API Key
# ---------------------------------------------------------------------------

def test_client_init_with_key():
    client = GeminiClient(api_key="fake-key")
    assert client.is_configured()

def test_client_init_missing_key():
    # Force api_key to None (ignoring environment vars for the test)
    client = GeminiClient(api_key=None)
    # If os.environ["GEMINI_API_KEY"] is set locally, clear it for this test
    # but to be safe, just inject a fake client wrapper
    client.api_key = None
    client.client = None
    assert not client.is_configured()
    assert client.generate("sys", "user") is None

# ---------------------------------------------------------------------------
# 3. Gemini API success & JSON parsing
# ---------------------------------------------------------------------------

def test_generate_success(mocker):
    client = GeminiClient(api_key="fake-key")
    
    mock_response = MagicMock()
    mock_response.text = '{"body": "Hello", "cta": "none", "send_as": "vera", "rationale": "Test"}'
    
    mocker.patch.object(client.client.models, 'generate_content', return_value=mock_response)
    
    result = client.generate("system", "user")
    
    assert result == {
        "body": "Hello",
        "cta": "none",
        "send_as": "vera",
        "rationale": "Test"
    }

# ---------------------------------------------------------------------------
# 4 & 5. Gemini Errors / Timeouts / Malformed JSON
# ---------------------------------------------------------------------------

def test_generate_api_error(mocker):
    client = GeminiClient(api_key="fake-key")
    mocker.patch.object(
        client.client.models, 
        'generate_content', 
        side_effect=Exception("Rate limit")
    )
    assert client.generate("sys", "user") is None

def test_generate_timeout_or_generic_exception(mocker):
    client = GeminiClient(api_key="fake-key")
    mocker.patch.object(
        client.client.models, 
        'generate_content', 
        side_effect=TimeoutError("Connection timed out")
    )
    assert client.generate("sys", "user") is None

def test_generate_malformed_json(mocker):
    client = GeminiClient(api_key="fake-key")
    mock_response = MagicMock()
    mock_response.text = '{"body": "Oops missing closing brace'
    mocker.patch.object(client.client.models, 'generate_content', return_value=mock_response)
    assert client.generate("sys", "user") is None

def test_generate_empty_text(mocker):
    client = GeminiClient(api_key="fake-key")
    mock_response = MagicMock()
    mock_response.text = ''
    mocker.patch.object(client.client.models, 'generate_content', return_value=mock_response)
    assert client.generate("sys", "user") is None

# ---------------------------------------------------------------------------
# 7. First-touch vs 8. Free-form follow-up
# ---------------------------------------------------------------------------

def test_prompt_first_touch(mock_category, mock_merchant, mock_trigger):
    # NEW conversation state -> first touch
    sys, usr = build_prompt(mock_category, mock_merchant, mock_trigger, conv_state="NEW")
    assert "FIRST-TOUCH" in usr
    assert "template style" in usr

def test_prompt_free_form(mock_category, mock_merchant, mock_trigger):
    # ACTIVE conversation state -> follow up
    sys, usr = build_prompt(mock_category, mock_merchant, mock_trigger, conv_state="ACTIONING")
    assert "FOLLOW-UP" in usr
    assert "Skip re-introduction" in usr

# ---------------------------------------------------------------------------
# 9-12. Context Grounding
# ---------------------------------------------------------------------------

def test_prompt_customer_consent(mock_category, mock_merchant, mock_trigger, mock_customer):
    sys, usr = build_prompt(mock_category, mock_merchant, mock_trigger, customer=mock_customer)
    assert "Customer ID: c_001" in sys
    assert "Consent scope: recall_reminders" in sys

def test_prompt_no_customer(mock_category, mock_merchant, mock_trigger):
    sys, usr = build_prompt(mock_category, mock_merchant, mock_trigger, customer=None)
    assert "No customer context available" in sys

def test_prompt_merchant_category_trigger_grounding(mock_category, mock_merchant, mock_trigger):
    sys, usr = build_prompt(mock_category, mock_merchant, mock_trigger)
    assert "Smile Clinic" in sys
    assert "Dr. {name}" in sys
    assert "trg_001" in sys
    assert "perf_dip" in sys

# ---------------------------------------------------------------------------
# 13. Single CTA & Validation Rules
# ---------------------------------------------------------------------------

def test_validator_success(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "Your CTR is 0.035, which is great.",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert result.ok

def test_validator_taboo_word(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "Here is a cheap discount deal for your customers. Your CTR is 0.035.",
        "cta": "open_ended",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert not result.ok
    assert any("taboo word" in err for err in result.errors)
    assert any("cheap" in err or "discount" in err or "deal" in err for err in result.errors)

def test_validator_internal_jargon(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "I am sending this because your trigger_id matched. CTR is 0.035.",
        "cta": "open_ended",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert not result.ok
    assert any("internal term" in err for err in result.errors)

def test_validator_multi_cta(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "Would you like me to update your hours? Reply YES to proceed, or NO to cancel. CTR is 0.035.",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert not result.ok
    assert any("Multiple CTAs detected" in err for err in result.errors)

def test_validator_duplicate_message(mock_category, mock_merchant, mock_trigger):
    msg = "This is the exact same message body as before, don't send it again. 0.035"
    data = {
        "body": msg,
        "cta": "open_ended",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger, sent_history=[msg])
    assert not result.ok
    assert any("similar to a prior message" in err for err in result.errors)

def test_validator_factual_grounding_numbers(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "Your CTR is 0.999 which is impossible.",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Test"
    }
    # 0.999 is fabricated (not in context)
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert not result.ok
    assert any("Fabrication detected: The number '0.999' is not present" in err for err in result.errors)

def test_validator_factual_grounding_url(mock_category, mock_merchant, mock_trigger):
    data = {
        "body": "Check out https://scam-site.com/login for details. CTR is 0.035.",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert not result.ok
    assert any("Fabrication detected: The URL 'https://scam-site.com/login' is not present" in err for err in result.errors)

def test_validator_length_warning(mock_category, mock_merchant, mock_trigger):
    long_body = "A" * 301 + " 0.035"
    data = {
        "body": long_body,
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Test"
    }
    result = validate(data, mock_category, mock_merchant, mock_trigger)
    assert result.ok  # Length is a warning, not an error
    assert any("unusually long" in w for w in result.warnings)

# ---------------------------------------------------------------------------
# 14. Deterministic Fallback & Retry via Composer
# ---------------------------------------------------------------------------

def test_composer_uses_fallback_on_llm_failure(mocker, mock_category, mock_merchant, mock_trigger):
    mock_client = MagicMock(spec=GeminiClient)
    mock_client.generate.return_value = None  # Simulate LLM failure
    
    composer = EngagementComposer(gemini_client=mock_client)
    
    result = composer.compose(mock_category, mock_merchant, mock_trigger)
    
    assert result.is_fallback is True
    assert result.cta == "open_ended"
    assert "update regarding your magicpin profile" in result.body

def test_composer_uses_fallback_on_validation_failure(mocker, mock_category, mock_merchant, mock_trigger):
    mock_client = MagicMock(spec=GeminiClient)
    # LLM returns something that fails validation (missing fields, too short) consistently
    mock_client.generate.return_value = {"body": "short"} 
    
    composer = EngagementComposer(gemini_client=mock_client)
    
    result = composer.compose(mock_category, mock_merchant, mock_trigger)
    
    assert result.is_fallback is True
    assert mock_client.generate.call_count == 2  # Attempted retry

def test_composer_retry_succeeds(mocker, mock_category, mock_merchant, mock_trigger):
    mock_client = MagicMock(spec=GeminiClient)
    
    # First call returns bad output, second call returns good output
    bad_output = {"body": "short"}
    good_output = {
        "body": "Dr. Meera, your calls are down 20%. Would you like me to activate a promo?",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Address perf_dip"
    }
    mock_client.generate.side_effect = [bad_output, good_output]
    
    composer = EngagementComposer(gemini_client=mock_client)
    
    result = composer.compose(mock_category, mock_merchant, mock_trigger)
    
    assert result.is_fallback is False
    assert mock_client.generate.call_count == 2
    assert result.body.startswith("Dr. Meera")

def test_composer_success(mocker, mock_category, mock_merchant, mock_trigger):
    mock_client = MagicMock(spec=GeminiClient)
    # The output MUST contain valid numbers present in the context, like 0.2 (from -0.2 delta_pct) or 20 (we'll just use 0.2 to match context exact)
    mock_client.generate.return_value = {
        "body": "Dr. Meera, your calls dipped. The delta is 0.2%. Do you want a promo?",
        "cta": "binary_yes_stop",
        "send_as": "vera",
        "rationale": "Address perf_dip"
    }
    
    composer = EngagementComposer(gemini_client=mock_client)
    
    result = composer.compose(mock_category, mock_merchant, mock_trigger)
    
    assert result.is_fallback is False
    assert result.body.startswith("Dr. Meera")
    assert result.cta == "binary_yes_stop"
