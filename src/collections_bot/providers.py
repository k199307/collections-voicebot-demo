from __future__ import annotations

import base64
from functools import lru_cache
import json
import re
from datetime import date, timedelta
from time import perf_counter
from urllib.parse import urlencode

import httpx
from openai import AsyncOpenAI
from websockets.legacy.client import connect as websocket_connect

from .config import settings

_BROWSER_TTS_MODEL = "flux-naveen-en"
CLASSIFIER_PROMPT_VERSION = "state-aware-context-v4-loop-recovery"


def _dialogue_exchanges(messages: list[dict[str, str]]) -> list[dict[str, str | None]]:
    """Represent prior turns as explicit customer/agent exchanges."""
    exchanges: list[dict[str, str | None]] = []
    customer_text: str | None = None
    for item in messages:
        role = item.get("role")
        content = str(item.get("content") or "")[:500]
        if role == "user":
            # Defensive handling for older history with two consecutive user
            # messages: preserve the earlier one as an incomplete exchange.
            if customer_text is not None:
                exchanges.append({"customer_said": customer_text, "agent_replied": None})
            customer_text = content
        elif role == "assistant":
            exchanges.append({"customer_said": customer_text, "agent_replied": content})
            customer_text = None
    if customer_text is not None:
        exchanges.append({"customer_said": customer_text, "agent_replied": None})
    return exchanges


def _phase_guidance(phase: str) -> str:
    """Give the classifier only the slot-specific instruction needed now."""
    guidance = {
        "identity_confirmation": "Task: answer the named identity question. A direct yes or 'you are' confirms it; do not restart the greeting.",
        "ptp": "Task: capture the expected payment date. Do not ask for an amount until the customer confirms the date. For a broad window such as next week, ask for the exact calendar date within that window; never guess a day.",
        "ptp_far_future_choice": "Task: a far-future date is already saved. If the caller cannot pay earlier, says this is the earliest date, repeats it, or requests a colleague, resolve to human follow-up; never ask for that date again. Otherwise extract only a clearly stated earlier date.",
        "ptp_confirmation": "Task: interpret whether the caller confirms or corrects the proposed payment date. On confirmation, policy asks for an optional amount next.",
        "ptp_amount": "Task: extract a numeric amount only if the caller provides one. Requests for the due/balance and a yes to checking it mean they want the OTP-protected bank-recorded balance/minimum due check. Recognize when the caller needs more time and wants a colleague callback. Never invent an amount or suggest skipping it.",
        "ptp_amount_confirmation": "Task: clarify whether the caller means the verified minimum due shown in context; accept yes, no, a corrected numeric amount, or a request for more time.",
        "paid_date": "Task: collect the date of an already-made payment. For a broad window such as last week, ask for the exact calendar date within it; never guess a day.",
        "paid_mode": "Task: collect the payment method for the already-made payment.",
        "paid_most_recent_confirmation": "Task: interpret yes, no, or uncertainty about whether the reported payment is the most recent one.",
        "paid_most_recent_date": "Task: collect the date of the most recent payment, without replacing earlier saved details unless clearly corrected.",
        "paid_most_recent_mode": "Task: collect the method used for the most recent payment.",
        "refusal_reason": "Task: interpret the reason for declining payment; a short answer belongs to this question, not an unrelated topic.",
        "callback_time": "Task: collect a preferred callback day or time, or recognize that none was given.",
        "balance_check_consent": "Task: interpret consent to an OTP-protected bank-recorded balance check.",
    }
    return guidance.get(phase, "Task: classify the customer's latest request in the overdue-card conversation.")


def voice_provider_name() -> str:
    return settings.voice_provider if settings.voice_provider in {"deepgram", "sarvam"} else "deepgram"


def voice_provider_configured() -> bool:
    if voice_provider_name() == "sarvam":
        return bool(settings.sarvam_api_key)
    return bool(settings.deepgram_api_key)


def llm_provider_name() -> str:
    return settings.llm_provider if settings.llm_provider in {"openai", "gemini"} else "openai"


def classifier_configured() -> bool:
    if llm_provider_name() == "gemini":
        return bool(settings.gemini_api_key)
    return bool(settings.openai_api_key)


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["greeting", "already_paid", "payment_not_made", "payment_refusal", "promise_to_pay", "payment_commitment_interest", "payment_link_request", "defer_payment_question", "payment_method_question", "payment_policy_question", "related_question", "offer_request", "waiver", "dispute", "callback", "distress", "abuse", "opt_out", "balance_question", "payment_question", "account_identification_question", "otp_request", "interest_question", "fee_question", "fee_applicability", "credit_score_question", "legal_question", "other_product", "unclear"],
        },
        "intent_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "amount_inr": {"type": ["string", "null"]},
        "date_iso": {"type": ["string", "null"]},
        "payment_mode": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "dialogue_act": {
            "type": "string",
            "enum": ["answers_pending", "cannot_provide", "asks_question", "corrects_previous", "new_request", "no_clear_act"],
        },
        "pending_slot_status": {
            "type": "string",
            "enum": ["provided", "cannot_provide", "question", "not_applicable", "unclear"],
        },
        "date_precision": {"type": "string", "enum": ["exact", "approximate", "none"]},
        "date_phrase": {"type": ["string", "null"]},
        "identity_status": {"type": "string", "enum": ["confirmed", "not_confirmed", "unclear"]},
        "acknowledgment": {"type": "string"},
    },
    "required": ["intent", "intent_confidence", "amount_inr", "date_iso", "payment_mode", "summary", "dialogue_act",
                 "pending_slot_status", "date_precision", "date_phrase", "identity_status", "acknowledgment"],
    "additionalProperties": False,
}

INTENT_CANONICAL = {
    "already_paid": "already paid",
    "payment_not_made": "payment has not been made",
    "payment_refusal": "caller does not want to pay",
    "promise_to_pay": "i will pay",
    "payment_commitment_interest": "tentative payment willingness",
    "payment_link_request": "payment link request",
    "defer_payment_question": "question about paying later",
    "payment_method_question": "accepted payment method question",
    "payment_policy_question": "payment policy question needing a colleague",
    "related_question": "related question about the overdue card payment",
    "offer_request": "offer request",
    "waiver": "waiver",
    "dispute": "dispute",
    "callback": "call me later",
    "distress": "medical emergency",
    "abuse": "abusive",
    "opt_out": "stop calling",
    "balance_question": "what is my balance",
    "interest_question": "interest rate",
    "fee_question": "late fee",
    "fee_applicability": "whether the late fee applies",
    "credit_score_question": "credit score",
    "legal_question": "legal advice",
    "other_product": "another product",
    "payment_question": "pending payment question",
    "account_identification_question": "which card",
    "otp_request": "otp request",
}

_FAST_INTENT_PHRASES = {
    "already_paid": ("already paid", "i paid", "payment done", "paid yesterday", "payment kar diya", "bhar diya"),
    "callback": ("call me later", "call back", "callback", "busy right now", "later please"),
}
_DETAIL_MARKERS = re.compile(
    r"\d|\b(today|tomorrow|yesterday|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"upi|imps|neft|cheque|check|cash|card|net banking|evening|morning|afternoon|after|before)\b",
    re.IGNORECASE,
)


def fast_classify_utterance(
    transcript: str,
    pending_state: str | None = None,
    reference_date: str | None = None,
) -> dict[str, str | None] | None:
    """Skip the network round trip for simple, high-confidence turns with no details to extract."""
    text = transcript.casefold().strip()
    normalized_greeting = re.sub(r"[^a-z\u0900-\u097f]+", " ", text).strip()
    if normalized_greeting in {
        "hi", "hello", "hey", "hi there", "hello there", "hey there",
        "good morning", "good afternoon", "good evening", "namaste",
        "नमस्ते", "हाय", "हेलो", "हेलो जी",
    }:
        return {
            "intent": "greeting", "intent_confidence": "high", "amount_inr": None,
            "date_iso": None, "payment_mode": None, "summary": "The caller greeted the assistant.",
            "dialogue_act": "answers_pending", "pending_slot_status": "not_applicable",
            "date_precision": "none", "date_phrase": None, "identity_status": "unclear",
        "acknowledgment": "Hello.",
        }
    if pending_state == "ptp_amount":
        number = r"[0-9,]+(?:\.[0-9]{1,2})?"
        amount_match = re.search(rf"(?:₹\s*|rs\.?\s*|inr\s*|pay(?:\s+only)?\s+)({number})", text, re.IGNORECASE)
        if not amount_match:
            amount_match = re.search(rf"\b({number})\s*(?:rupees?|inr)\b", text, re.IGNORECASE)
        if not amount_match:
            amount_match = re.fullmatch(rf"\s*({number})\s*", text)
        if amount_match:
            return {
                "intent": "unclear", "intent_confidence": "high",
                "amount_inr": amount_match.group(1).replace(",", ""),
                "date_iso": None, "payment_mode": None,
                "summary": "The caller supplied a payment amount in response to the optional amount question.",
                "dialogue_act": "answers_pending", "pending_slot_status": "provided",
                "date_precision": "none", "date_phrase": None,
                "identity_status": "unclear", "acknowledgment": "",
            }
        if re.fullmatch(r"\s*(?:skip|no|nope|nah|not sure|don't know|do not know)\s*[.!]?\s*", text):
            return {
                "intent": "unclear", "intent_confidence": "high", "amount_inr": None,
                "date_iso": None, "payment_mode": None,
                "summary": "The caller declined to provide a payment amount.",
                "dialogue_act": "answers_pending", "pending_slot_status": "provided",
                "date_precision": "none", "date_phrase": None,
                "identity_status": "unclear", "acknowledgment": "",
            }
    if any(phrase in text for phrase in (
        "discount regarding the late fee", "discount regarding late fee", "discount on the late fee",
        "discount on late fee", "discount for the late fee", "late fee discount", "late-fee discount",
        "reduce the late fee", "reduce my late fee",
    )):
        return {
            "intent": "waiver", "intent_confidence": "high", "amount_inr": None,
            "date_iso": None, "payment_mode": None, "summary": "The caller requested a discount on the late fee.",
            "dialogue_act": "new_request", "pending_slot_status": "not_applicable",
            "date_precision": "none", "date_phrase": None, "identity_status": "unclear",
            "acknowledgment": "You’re asking for a discount on the late fee.",
        }
    if any(phrase in text for phrase in (
        "not paid yet", "have not paid", "haven't paid", "havent paid", "not made the payment",
        "have not made the payment", "haven't made the payment", "havent made the payment",
        "did not pay", "didn't pay", "didnt pay", "payment is still pending",
        "abhi tak payment nahi", "payment nahi kiya",
    )):
        return {
            "intent": "payment_not_made", "intent_confidence": "high", "amount_inr": None,
            "date_iso": None, "payment_mode": None, "summary": "The caller has not made the payment yet.",
            "dialogue_act": "answers_pending", "pending_slot_status": "provided",
            "date_precision": "none", "date_phrase": None, "identity_status": "unclear",
            "acknowledgment": "You haven’t made the payment yet.",
        }
    cash_question = "cash" in text and any(
        cue in text for cue in ("can i", "could i", "is it", "would", "will you", "accepted", "okay", "allowed", "possible")
    )
    if cash_question:
        return {"intent": "payment_method_question", "intent_confidence": "high", "amount_inr": None, "date_iso": None, "payment_mode": "cash", "summary": "The caller asked whether cash is an accepted payment method."}
    defer_question = any(cue in text for cue in ("is it okay if i pay", "is it okay to pay", "can i pay", "could i pay", "would it be okay if i pay", "would you allow me to pay")) and any(
        cue in text for cue in ("next month", "next week", "later", "after a month", "after one month", "next year")
    )
    if defer_question:
        return {"intent": "defer_payment_question", "intent_confidence": "high", "amount_inr": None, "date_iso": None, "payment_mode": None, "summary": "The caller asked whether they can delay payment."}
    if any(phrase in text for phrase in ("payment link", "pay link", "link to pay", "link for payment", "send me a link", "payment ka link")):
        return {"intent": "payment_link_request", "intent_confidence": "high", "amount_inr": None, "date_iso": None, "payment_mode": None, "summary": "The caller requested a payment link."}
    if any(phrase in text for phrase in (
        "latest offer", "latest offers", "give me an offer", "give me the offer",
        "any offer", "any offers", "discount", "settlement offer", "offer before", "offer first",
    )) or ("offer" in text and any(cue in text for cue in ("only then", "before i pay", "before paying", "only if"))):
        return {"intent": "offer_request", "amount_inr": None, "date_iso": None, "payment_mode": None, "summary": text[:160]}
    identity_affirmative = normalized_greeting in {"you are", "you are speaking with me", "you are speaking to me"} or bool(re.match(
        r"^(?:yes|yeah|yep|yup|correct|right|haan|han|ji)\s*(?:,\s*)?"
        r"(?:you are(?:\s+speaking(?:\s+(?:with|to)\s+(?:me|[a-z]+(?:\s+[a-z]+)?))?)?"
        r"|i am(?:\s+speaking)?(?:\s+with\s+(?:you|[a-z]+(?:\s+[a-z]+)?))?"
        r"|this is me|speaking(?:\s+with\s+you)?)?[.!? ]*$",
        normalized_greeting,
    ))
    if pending_state == "identity_confirmation" and identity_affirmative:
        return {
            "intent": "unclear", "intent_confidence": "high", "amount_inr": None,
            "date_iso": None, "payment_mode": None, "summary": "Identity confirmation.",
            "dialogue_act": "answers_pending", "pending_slot_status": "provided",
            "date_precision": "none", "date_phrase": None, "identity_status": "confirmed",
            "acknowledgment": "Thanks for confirming.",
        }
    if pending_state == "ptp_confirmation" and text in {"yes", "yes that's right", "correct", "haan", "han", "ji", "right"}:
        return {"intent": "unclear", "amount_inr": None, "date_iso": None, "payment_mode": None, "summary": "Commitment confirmed."}
    for intent, phrases in _FAST_INTENT_PHRASES.items():
        if not any(phrase in text for phrase in phrases):
            continue
        number = r"[0-9,]+(?:\.[0-9]{1,2})?"
        amount_match = re.search(rf"(?:₹\s*|rs\.?\s*|inr\s*|pay(?:\s+only)?\s+)({number})", text, re.IGNORECASE)
        if not amount_match:
            amount_match = re.search(rf"\b({number})\s*(?:rupees?|inr)\b", text, re.IGNORECASE)
        amount = amount_match.group(1).replace(",", "") if amount_match else None
        date_value = None
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        if date_match:
            try:
                date_value = date.fromisoformat(date_match.group(1)).isoformat()
            except ValueError:
                return None
        else:
            relative = {"today": 0, "tomorrow": 1, "yesterday": -1,
                        "day after tomorrow": 2}
            matched_relative = next((days for phrase, days in relative.items() if phrase in text), None)
            if matched_relative is not None:
                try:
                    reference = date.fromisoformat(reference_date) if reference_date else date.today()
                    date_value = (reference + timedelta(days=matched_relative)).isoformat()
                except ValueError:
                    return None
        mode_match = re.search(r"\b(upi|net banking|imps|neft|cheque|check|cash|card|autopay)\b", text)
        mode = mode_match.group(1).replace(" ", "_") if mode_match else None
        if _DETAIL_MARKERS.search(text) and not any((amount, date_value, mode)):
            return None
        if _DETAIL_MARKERS.search(text) and any(word in text for word in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "morning", "afternoon", "evening", "after", "before")):
            return None
        return {"intent": intent, "amount_inr": amount, "date_iso": date_value, "payment_mode": mode, "summary": text[:160]}
    return None


@lru_cache(maxsize=1)
def _openai_client() -> AsyncOpenAI:
    # A retry can double the wait in a live voice turn. The application has a
    # deterministic policy fallback when a single model request times out.
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=5.0, max_retries=0)


@lru_cache(maxsize=1)
def _gemini_client():
    # Import lazily so existing OpenAI installations do not need to initialize Gemini.
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=10000),
    )


async def classify_utterance(
    transcript: str,
    pending_state: str | None = None,
    known_fields: dict[str, object] | None = None,
    reference_date: str | None = None,
    conversation_history: list[dict[str, str]] | None = None,
) -> tuple[dict[str, str | None], dict[str, object]]:
    """Interpret the caller's turn and return a brief acknowledgment for policy-approved composition."""
    classifier_started = perf_counter()
    provider = llm_provider_name()
    if provider == "gemini" and not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if provider == "openai" and not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    prompt_started = perf_counter()
    phase = pending_state or "payment_resolution"
    recovery_instruction = ""
    if (known_fields or {}).get("loop_recovery"):
        recovery_instruction = (
            "RECOVERY MODE: Review all recent_exchanges and saved_facts before classifying. "
            "Identify the exact answer or constraint the caller already gave and how they responded to the agent's follow-up. "
            "Treat a repeated date, refusal of an earlier date, or correction as an answer to the active question; do not classify it as a fresh request or missing detail. "
            "Preserve the original answer and set dialogue_act and pending_slot_status to reflect the conversation as a whole. "
            "If the answer is already present, do not ask for it again.\n"
        )
    instructions = (
        "You classify one customer turn in an Indian credit-card collections call. Return only the required JSON; never choose actions or compose the bot's answer.\n"
        "Use state.active_question and recent_exchanges to interpret latest_utterance. Each exchange is the customer's words and the agent's reply. The latest_utterance is new and is not yet in those exchanges. Resolve it against the last agent question first, including short, negative, uncertain, corrective, Hindi, transliterated Hindi, or code-switched replies. Preserve saved facts; do not restart a completed step, invent facts, or ask for facts already supplied.\n"
        f"{_phase_guidance(phase)}\n"
        "Choose the most specific intent from the schema. A promise_to_pay requires clear willingness and a future date; never infer it from a question, amount, condition, or negation. After the date is confirmed, policy may ask for an optional customer-provided amount; an amount is never required and must never be invented. already_paid means a completed payment. Keep approximate dates approximate and date_iso null. During the amount step, a request for the due or balance, or a yes to checking it, means the caller wants the OTP-protected bank lookup; a clear request for more time means arrange a colleague callback.\n"
        "Short/noisy speech is unclear, not automatically unrelated. Opt-out, identity protection, dispute, hardship, abuse, and human-review safeguards remain policy-controlled. Never disclose balance before verified OTP; never invent rates/fees, give legal advice, threaten, mention CIBIL, or ask for a spoken OTP.\n"
        f"{recovery_instruction}"
        "Return a short calm, neutral English summary and a grounded English acknowledgment of at most 15 words; use an empty acknowledgment if unclear. Keep the demeanor steady, respectful, and nonjudgmental even when the caller is upset. Do not sound impatient, stern, emphatic, or mirror the caller's anger. The acknowledgment must not answer a policy question or claim an action was completed."
    )
    known = known_fields or {}
    fact_keys = (
        "ptp_date", "reported_payment_date", "reported_payment_date_text", "reported_payment_mode",
        "ptp_proposed_date_text", "ptp_far_future_date_iso", "ptp_earlier_date_requested",
        "ptp_broad_date_window", "reported_payment_broad_window",
    )
    state = {
        "phase": phase,
        "active_question": known.get("pending_question") or {},
        "saved_facts": {key: known[key] for key in fact_keys if key in known and known[key] not in (None, "")},
    }
    for source_key, output_key in (
        ("greeting_completed", "greeting_completed"),
        ("right_party_confirmed", "identity_verified"),
        ("due_information_disclosed", "due_information_disclosed"),
        ("target_name", "target_name"),
    ):
        value = known.get(source_key)
        if value:
            state[output_key] = value
    if known.get("loop_recovery"):
        state["recovery"] = known["loop_recovery"]
    # Preserve full customer/agent pairs. Normal turns use two exchanges;
    # recovery uses six to include the original answer and failed recovery turns.
    recent_exchange_limit = 6 if known.get("loop_recovery") else 2
    exchanges = _dialogue_exchanges(conversation_history or [])[-recent_exchange_limit:]
    input_context = {
        "state": state,
        "reference_date_local": reference_date,
        "recent_exchanges": exchanges,
        "latest_utterance": transcript,
    }
    llm_input = json.dumps(input_context, ensure_ascii=False)
    response_format = {"type": "json_schema", "name": "collection_intent", "strict": True, "schema": INTENT_SCHEMA}
    prompt_build_ms = round((perf_counter() - prompt_started) * 1000, 1)
    request_started = perf_counter()
    try:
        if provider == "gemini":
            from google.genai import types

            response = await _gemini_client().aio.models.generate_content(
                model=settings.gemini_model,
                contents=llm_input,
                config=types.GenerateContentConfig(
                    system_instruction=instructions,
                    response_mime_type="application/json",
                    response_json_schema=INTENT_SCHEMA,
                    max_output_tokens=600,
                    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                ),
            )
        else:
            response = await _openai_client().responses.create(
                model=settings.openai_model,
                reasoning={"effort": settings.openai_reasoning_effort},
                service_tier=settings.openai_service_tier,
                store=False,
                # The schema is compact; keep generated output bounded to reduce latency.
                max_output_tokens=600,
                instructions=instructions,
                input=llm_input,
                text={"format": response_format},
            )
    except Exception as exc:
        timing = {
            "prompt_build_ms": prompt_build_ms,
            "model_request_ms": round((perf_counter() - request_started) * 1000, 1),
            "response_parse_ms": 0.0,
            "total_ms": round((perf_counter() - classifier_started) * 1000, 1),
            "instructions_chars": len(instructions),
            "input_chars": len(llm_input),
            "recent_exchange_count": len(exchanges),
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
        }
        try:
            setattr(exc, "classifier_timing_ms", timing)
            setattr(exc, "classifier_prompt_trace", {
                "status": "error", "provider": provider,
                "model": settings.gemini_model if provider == "gemini" else settings.openai_model,
                "timings_ms": timing, "instructions": instructions, "input": input_context,
                "prompt_version": CLASSIFIER_PROMPT_VERSION, "response_format": response_format,
                "reasoning_effort": settings.openai_reasoning_effort if provider == "openai" else None,
                "error_type": type(exc).__name__, "error_detail": str(exc)[:300],
            })
        except Exception:
            pass
        raise
    model_request_ms = round((perf_counter() - request_started) * 1000, 1)
    parse_started = perf_counter()
    try:
        response_status = "completed" if provider == "gemini" else response.status
        if response_status != "completed":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            raise RuntimeError(f"LLM response status={response_status}; incomplete_reason={reason or 'unknown'}")
        output_text = response.text if provider == "gemini" else response.output_text
        if not output_text or not output_text.strip():
            raise RuntimeError("LLM completed without structured output")
        parsed = json.loads(output_text)
    except Exception as exc:
        timing = {
            "prompt_build_ms": prompt_build_ms,
            "model_request_ms": model_request_ms,
            "response_parse_ms": round((perf_counter() - parse_started) * 1000, 1),
            "total_ms": round((perf_counter() - classifier_started) * 1000, 1),
            "instructions_chars": len(instructions),
            "input_chars": len(llm_input),
            "recent_exchange_count": len(exchanges),
            "input_tokens": None,
            "output_tokens": None,
            "cached_input_tokens": None,
        }
        try:
            setattr(exc, "classifier_timing_ms", timing)
            setattr(exc, "classifier_prompt_trace", {
                "status": "error", "provider": provider,
                "model": settings.gemini_model if provider == "gemini" else settings.openai_model,
                "timings_ms": timing, "instructions": instructions, "input": input_context,
                "prompt_version": CLASSIFIER_PROMPT_VERSION, "response_format": response_format,
                "reasoning_effort": settings.openai_reasoning_effort if provider == "openai" else None,
                "error_type": type(exc).__name__, "error_detail": str(exc)[:300],
            })
        except Exception:
            pass
        raise
    response_parse_ms = round((perf_counter() - parse_started) * 1000, 1)
    if provider == "gemini":
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        cached_input_tokens = getattr(usage, "cached_content_token_count", None)
        model_name = settings.gemini_model
        service_tier = "standard"
        response_status = "completed"
    else:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        input_token_details = getattr(usage, "input_tokens_details", None)
        cached_input_tokens = getattr(input_token_details, "cached_tokens", None)
        model_name = settings.openai_model
        service_tier = getattr(response, "service_tier", settings.openai_service_tier)
        response_status = response.status
    classifier_timings = {
        "prompt_build_ms": prompt_build_ms,
        "model_request_ms": model_request_ms,
        "response_parse_ms": response_parse_ms,
        "total_ms": round((perf_counter() - classifier_started) * 1000, 1),
        "instructions_chars": len(instructions),
        "input_chars": len(llm_input),
        "recent_exchange_count": len(exchanges),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
    }
    return parsed, {
        "status": response_status,
        "provider": provider,
        "model": model_name,
        "service_tier": service_tier,
        "reasoning_effort": settings.openai_reasoning_effort if provider == "openai" else None,
        "timings_ms": classifier_timings,
        "instructions": instructions,
        "input": input_context,
        "prompt_version": CLASSIFIER_PROMPT_VERSION,
        "response_format": response_format,
        "output_raw": output_text,
        "output_parsed": parsed,
    }


async def transcribe_browser_audio(audio: bytes, content_type: str = "audio/webm") -> str:
    """Transcribe a browser-recorded turn with the configured speech provider."""
    if voice_provider_name() == "sarvam":
        if not settings.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.sarvam.ai/speech-to-text",
                headers={"api-subscription-key": settings.sarvam_api_key},
                data={"model": settings.sarvam_stt_model, "mode": settings.sarvam_stt_mode},
                files={"file": ("customer-turn.webm", audio, content_type)},
            )
            response.raise_for_status()
        return response.json().get("transcript", "").strip()
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured")
    query = urlencode([
        ("model", settings.deepgram_stt_model), ("language", "multi"),
        ("language_hint", "en-IN"), ("language_hint", "hi"), ("smart_format", "true"),
    ])
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.post(
            f"{settings.deepgram_api_base_url}/v1/listen?{query}",
            headers={"Authorization": f"Token {settings.deepgram_api_key}", "Content-Type": content_type},
            content=audio,
        )
        response.raise_for_status()
    result = response.json()
    return result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "").strip()


async def stream_browser_audio(text: str):
    """Yield configured-provider audio chunks and timing for progressive playback."""
    if voice_provider_name() == "sarvam":
        if not settings.sarvam_api_key:
            raise RuntimeError("SARVAM_API_KEY is not configured")
        started = perf_counter()
        query = urlencode({"model": settings.sarvam_tts_model, "send_completion_event": "true"})
        url = f"wss://api.sarvam.ai/text-to-speech/ws?{query}"
        first_audio_ms = None
        async with websocket_connect(
            url,
            extra_headers={"api-subscription-key": settings.sarvam_api_key},
            open_timeout=15,
            close_timeout=3,
            ping_interval=20,
            max_size=2_000_000,
        ) as socket:
            await socket.send(json.dumps({
                "type": "config",
                "data": {
                    "language_code": "en-IN",
                    "speaker": settings.sarvam_tts_speaker,
                    "speech_sample_rate": 24000,
                    "output_audio_codec": "mp3",
                    # Keep delivery even and slightly measured for a calm
                    # collections conversation. Bulbul v4 supports these
                    # prosody controls; the speaker remains fixed by config.
                    "pace": 1.0,
                    "pitch": 0.0,
                    "loudness": 0.9,
                    "enable_preprocessing": True,
                },
            }))
            await socket.send(json.dumps({"type": "text", "data": {"text": text}}))
            await socket.send(json.dumps({"type": "flush"}))
            yield ("format", "audio/mpeg", None, None)
            async for message in socket:
                if isinstance(message, bytes):
                    chunk = message
                    event = None
                else:
                    try:
                        event = json.loads(message)
                    except (TypeError, ValueError):
                        continue
                    if event.get("type") == "error":
                        raise RuntimeError("Sarvam TTS streaming failed")
                    if event.get("type") == "audio":
                        audio_data = event.get("data", {}).get("audio")
                        if not audio_data:
                            continue
                        chunk = base64.b64decode(audio_data)
                    else:
                        chunk = None
                if chunk:
                    if first_audio_ms is None:
                        first_audio_ms = round((perf_counter() - started) * 1000, 1)
                        yield ("first_audio", chunk, first_audio_ms, None)
                    else:
                        yield ("audio", chunk, None, None)
                    continue
                if event and event.get("type") == "event" and event.get("data", {}).get("event_type") == "final":
                    total_ms = round((perf_counter() - started) * 1000, 1)
                    yield ("done", None, first_audio_ms, total_ms)
                    break
        return
    if not settings.deepgram_api_key:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured")
    started = perf_counter()
    query = urlencode({
        "model": _BROWSER_TTS_MODEL,
        "encoding": "linear16",
        "sample_rate": 24000,
        "mip_opt_out": "true",
    })
    url = f"{settings.deepgram_api_base_url.replace('https://', 'wss://').replace('http://', 'ws://')}/v2/speak?{query}"
    first_audio_ms = None
    async with websocket_connect(
        url,
        extra_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        open_timeout=15,
        close_timeout=3,
        ping_interval=20,
        max_size=2_000_000,
    ) as socket:
        await socket.send(json.dumps({"type": "Speak", "text": text}))
        await socket.send(json.dumps({"type": "Flush"}))
        async for message in socket:
            if isinstance(message, bytes):
                if first_audio_ms is None:
                    first_audio_ms = round((perf_counter() - started) * 1000, 1)
                    yield ("first_audio", message, first_audio_ms, None)
                else:
                    yield ("audio", message, None, None)
                continue
            try:
                event = json.loads(message)
            except (TypeError, ValueError):
                continue
            if event.get("type") == "Error":
                raise RuntimeError("Deepgram streaming TTS failed")
            if event.get("type") == "SpeechMetadata":
                total_ms = round((perf_counter() - started) * 1000, 1)
                yield ("done", None, first_audio_ms, total_ms)
                break
