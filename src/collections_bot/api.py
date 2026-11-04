from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import re
from time import perf_counter
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from websockets.legacy.client import connect as websocket_connect

from .config import settings
from .business_rules import business_rules
from .bank_services import bank_services
from .browser_demo import BROWSER_DEMO_HTML
from .conversation import create_followup_task, fallback_interpretation, pending_question_context, process_otp_code, process_turn
from .mock_bank_api import router as mock_bank_router
from .policy import configured_frequency_policy
from .repository import CallBlocked, Repository
from .schemas import (
    AttemptDisposition,
    CallSession,
    CallStarted,
    CompleteCallRequest,
    CompletionResponse,
    CustomerOutcomeEvent,
    Outcome,
    OutcomeType,
    OtpCodeRequest,
    StartCallRequest,
    TurnRequest,
    TurnResponse,
)
from .webhook import deliver_event
from .providers import (
    CLASSIFIER_PROMPT_VERSION,
    classifier_configured,
    classify_utterance,
    fast_classify_utterance,
    llm_provider_name,
    stream_browser_audio,
    transcribe_browser_audio,
    voice_provider_configured,
    voice_provider_name,
)
from .security import authorize
from .storage import close_pools


if settings.app_env == "production":
    if settings.auth_mode != "oidc" or not all((settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url)):
        raise RuntimeError("Production requires AUTH_MODE=oidc and issuer, audience, and JWKS configuration")
    if settings.mock_bank_enabled:
        raise RuntimeError("Production must disable mock bank services and connect approved bank adapters")

if settings.app_env == "demo":
    if len(settings.demo_access_token) < 32:
        raise RuntimeError("Demo mode requires a high-entropy DEMO_ACCESS_TOKEN of at least 32 characters")
    if not settings.mock_bank_enabled:
        raise RuntimeError("Demo mode requires mock bank services for synthetic demo accounts")
    if settings.auth_mode != "static" or not settings.collections_api_token or not settings.mock_bank_admin_token:
        raise RuntimeError("Demo mode requires distinct static service and mock-admin tokens")
    if hmac.compare_digest(settings.collections_api_token, settings.mock_bank_admin_token):
        raise RuntimeError("Demo service and mock-admin tokens must differ")
    if not settings.database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("Demo mode requires PostgreSQL persistence")

app = FastAPI(
    title="Collections Voicebot",
    version="0.2.0",
    docs_url=None if settings.app_env == "demo" else "/docs",
    redoc_url=None if settings.app_env == "demo" else "/redoc",
    openapi_url=None if settings.app_env == "demo" else "/openapi.json",
)
repository = Repository(settings.database_url or settings.db_path)
app.include_router(mock_bank_router)
logger = logging.getLogger("collections_bot.api")


def _question_fingerprint(text: str) -> str | None:
    """Return the final question in a bot utterance as a stable loop key."""
    questions = re.findall(r"[^?]*\?", text or "")
    if not questions:
        return None
    return re.sub(r"[^a-z0-9]+", " ", questions[-1].casefold()).strip() or None


def _question_family_for_state(state: str | None) -> str | None:
    """Group wording variants under the conversational slot they are asking about."""
    return {
        # Treat the earlier-date choice and date collection as one recovery
        # family. If date extraction falls back between these states, the
        # loop detector must still see the repeated payment-date conversation.
        "ptp": "payment_commitment_resolution",
        "ptp_far_future_choice": "payment_commitment_resolution",
        "ptp_confirmation": "payment_commitment_confirmation",
        "ptp_amount": "payment_commitment_amount",
        "ptp_amount_confirmation": "payment_commitment_amount_confirmation",
        "paid_date": "reported_payment_date",
        "paid_mode": "reported_payment_mode",
        "paid_most_recent_confirmation": "most_recent_payment_confirmation",
        "paid_most_recent_date": "most_recent_payment_date",
        "paid_most_recent_mode": "most_recent_payment_mode",
        "identity_confirmation": "identity_confirmation",
        "callback_time": "callback_preference",
        "refusal_reason": "payment_refusal_reason",
        "balance_check_consent": "balance_check_consent",
        "interest_follow_up_consent": "interest_follow_up_consent",
    }.get(state or "")


def _repeated_bot_question(
    history: list[dict[str, str]], active_state: str | None
) -> tuple[str | None, int]:
    """Count repeated asks by active answer slot, even when the wording changes."""
    family = _question_family_for_state(active_state)
    if family:
        repeats = sum(
            1 for item in history
            if item.get("role") == "assistant"
            and item.get("question_family") == family
            and _question_fingerprint(item.get("content", ""))
        )
        if repeats:
            return family, repeats
    # Read older sessions created before question-family metadata was added.
    latest_assistant = next((item for item in reversed(history) if item.get("role") == "assistant"), None)
    last_question = _question_fingerprint((latest_assistant or {}).get("content", ""))
    if not last_question:
        return family, 0
    repeats = sum(
        1 for item in history
        if item.get("role") == "assistant"
        and _question_fingerprint(item.get("content", "")) == last_question
    )
    return family or last_question, repeats


def _relevant_dialogue_context(
    history: list[dict[str, str]], active_family: str | None, loop_recovery: bool,
) -> list[dict[str, str]]:
    """Select a small context window anchored to the active question family."""
    # Recovery needs enough turns to include the original answer, the agent's
    # proposed next step, and the customer's rejection/correction of it.
    limit = 12 if loop_recovery else 4
    if not history:
        return []
    if active_family:
        matching_assistant_indexes = [
            index for index, item in enumerate(history)
            if item.get("role") == "assistant" and item.get("question_family") == active_family
        ]
        if matching_assistant_indexes:
            asks_to_keep = 6 if loop_recovery else 2
            first_kept_ask = matching_assistant_indexes[-min(asks_to_keep, len(matching_assistant_indexes))]
            # Keep the customer turn that led into the first retained prompt.
            start = first_kept_ask - 1 if first_kept_ask > 0 and history[first_kept_ask - 1].get("role") == "user" else first_kept_ask
            selected = history[start:]
            # A tangential exchange may be useful, but unrelated earlier
            # opening/identity turns are not. Keep the bounded tail only.
            return selected[-limit:]
    return history[-limit:]


def _contracted_reply_rejection_reason(
    candidate: str,
    policy_text: str,
    conversation_state: str,
    grounded_utterance: str = "",
) -> str | None:
    candidate = candidate.strip()
    if not candidate:
        return "The generated response was empty."
    if len(candidate) > 500:
        return "The generated response exceeded the 500-character limit."
    if any("\u0900" <= char <= "\u097f" for char in candidate):
        return "The response included Devanagari text, but the configured bot language is English."
    lowered = candidate.casefold()
    generic_questions = (
        "what would you like me to help with", "what would you like help with",
        "what would you like to discuss", "how can i help you", "what can i help you with",
    )
    if any(phrase in lowered for phrase in generic_questions):
        return "The response ended with a generic help question instead of the policy-selected next step."
    policy = policy_text.casefold()
    if "payment" in policy or "paid" in policy or "pay" in policy:
        if not any(term in lowered for term in ("payment", "paid", "pay", "settled")):
            return "The response did not preserve the payment topic selected by policy."
    if "minimum payment" in policy and ("minimum payment" not in lowered or "overdue" not in lowered):
        return "The response omitted that the minimum payment is overdue."
    policy_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", policy_text))
    candidate_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", candidate))
    if "late fee" in policy and "may apply" in policy:
        fee = f"{int(business_rules.facts['late_fee_inr']):,}"
        threshold = f"{int(business_rules.facts['late_fee_balance_threshold_inr']):,}"
        if "late fee" not in lowered or fee not in candidate_numbers or threshold not in candidate_numbers:
            return "The response omitted the late-fee amount or threshold selected by policy."
        if not any(term in lowered for term in ("may apply", "could apply", "might apply")) or "if" not in lowered:
            return "The response changed the conditional late-fee wording selected by policy."
    if "callback" in policy or "call back" in policy:
        if not any(term in lowered for term in ("callback", "call back", "call you back")):
            return "The response omitted the callback option required by policy."
    if "already made the payment" in policy or "already paid" in policy:
        if not any(term in lowered for term in ("already paid", "paid it", "made the payment", "made a payment", "settled")):
            return "The response omitted the already-paid option required by policy."
    if ("when" in policy and ("pay" in policy or "payment" in policy)) or "what date" in policy:
        if not (("when" in lowered or "date" in lowered) and any(term in lowered for term in ("pay", "payment", "paid"))):
            return "The response omitted the required payment timing question."
    if conversation_state == "paid_date":
        policy_requires_date = "date" in policy
        if policy_requires_date and "date" not in lowered:
            return "The response omitted the exact-date requirement."
        if "?" in policy_text and "?" not in candidate:
            return "The response omitted the policy-selected question."
    if conversation_state == "paid_mode" and not any(term in lowered for term in ("payment mode", "which mode", "how did you pay", "upi", "net banking", "cheque")):
        return "The response omitted the payment-method question."
    if conversation_state == "ptp":
        if any(term in lowered for term in ("what amount", "how much", "amount can you", "amount do you")):
            return "The response asked for a payment amount, which is not part of the assignment flow."
        if ("date" in policy or "when" in policy) and not any(term in lowered for term in ("date", "when", "by what day", "by what time")):
            return "The response omitted the payment date question."
    grounded_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", grounded_utterance))
    if not candidate_numbers.issubset(policy_numbers | grounded_numbers):
        return "The response contained a number not present in the policy text or verified caller/account context."
    return None


def _contracted_reply_is_valid(candidate: str, policy_text: str, conversation_state: str, grounded_utterance: str = "") -> bool:
    return _contracted_reply_rejection_reason(candidate, policy_text, conversation_state, grounded_utterance) is None


def _acknowledgment_is_valid(acknowledgment: str) -> bool:
    acknowledgment = acknowledgment.strip()
    if not acknowledgment or len(acknowledgment) > 180 or len(acknowledgment.split()) > 15 or "?" in acknowledgment:
        return False
    if any("\u0900" <= char <= "\u097f" for char in acknowledgment):
        return False
    # A generic courtesy alone does not demonstrate that the latest point was heard.
    generic_only = {
        "i understand", "i understand.", "thanks", "thanks.", "thank you", "thank you.",
        "okay", "okay.", "got it", "got it.", "i see", "i see.", "understood", "understood.",
    }
    return acknowledgment.casefold() not in generic_only


_ACK_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "about", "be", "been", "by", "for", "from",
    "i", "im", "i’m", "is", "it", "me", "my", "of", "on", "or", "our", "the", "this",
    "that", "to", "with", "you", "your", "do", "does", "have", "has", "had", "just",
    "understand", "hear", "see", "know", "thank", "thanks", "thankyou", "okay", "well",
    "want", "would", "like", "only", "asking", "saying", "sharing", "letting", "telling", "confirming",
}


def _acknowledgment_repeats_policy_opening(acknowledgment: str, policy_text: str) -> bool:
    """Drop an LLM preface when its content duplicates the policy's first sentence."""
    ack = re.split(r"(?<=[.!?])\s+", acknowledgment.strip(), maxsplit=1)[0]
    first_policy_sentence = re.split(r"(?<=[.!?])\s+", policy_text.strip(), maxsplit=1)[0]
    courtesy = lambda value: value.casefold().lstrip(" .,!?").startswith(("thank you", "thanks"))
    if courtesy(ack) and courtesy(first_policy_sentence):
        return True
    normalized_ack = ack.casefold()
    normalized_policy = first_policy_sentence.casefold()
    ack_numbers = {int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", ack)}
    policy_numbers = {int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", first_policy_sentence)}
    if ack_numbers & policy_numbers and any(
        marker in normalized_ack + " " + normalized_policy
        for marker in ("₹", "balance", "estimate", "outstanding", "fee", "payment")
    ):
        return True
    understood = ("understood", "got it", "i see", "okay")
    if any(normalized_ack.startswith(item) for item in understood) and any(
        normalized_policy.startswith(item) for item in understood
    ):
        return True
    if (
        any(phrase in normalized_ack for phrase in ("get to the point", "speak quickly", "be brief"))
        and any(phrase in normalized_policy for phrase in ("be brief", "keep it brief", "get to the point"))
    ):
        return True
    if (
        any(phrase in normalized_ack for phrase in ("you’re asking", "you're asking", "you are asking"))
        and any(phrase in normalized_policy for phrase in ("asking about something outside", "asking about something unrelated"))
    ):
        return True
    aliases = {
        "paid": "payment", "pay": "payment", "paying": "payment", "pays": "payment",
        "settled": "payment", "settlement": "payment", "payment": "payment",
        "discount": "offer", "waiver": "offer", "offer": "offer", "reduce": "offer",
        "willing": "willingness", "willingness": "willingness", "open": "willingness",
        "difficult": "difficulty", "difficulty": "difficulty", "problem": "difficulty",
        "problems": "difficulty", "issue": "difficulty", "concern": "concern",
        "concerns": "concern", "fees": "fee", "fee": "fee", "charges": "fee", "charge": "fee",
        "believe": "estimate", "believes": "estimate", "estimate": "estimate", "estimated": "estimate",
        "balance": "estimate", "balances": "estimate", "amount": "estimate",
        "upi": "mode", "net": "mode", "banking": "mode", "cheque": "mode", "cash": "mode",
        "imps": "mode", "neft": "mode", "mode": "mode", "method": "mode",
        "expect": "commitment", "expects": "commitment", "expected": "commitment",
        "friday": "commitment", "tomorrow": "commitment", "date": "commitment",
        "willingness": "commitment", "willing": "commitment", "open": "commitment",
    }

    def concepts(value: str) -> set[str]:
        value = value.casefold().replace("’", "'")
        value = value.replace("don't", "not").replace("doesn't", "not").replace("didn't", "not")
        words = re.findall(r"[a-z]+", value)
        return {aliases.get(word, word) for word in words if word not in _ACK_STOP_WORDS and len(word) > 2}

    ack_concepts = concepts(ack)
    policy_concepts = concepts(first_policy_sentence)
    shared = ack_concepts & policy_concepts
    if shared == {"offer"} and ack_concepts <= {"offer"}:
        return True
    if shared == {"estimate"} and ack_concepts <= {"estimate"}:
        return True
    if "mode" in shared and ack_concepts <= {"mode", "payment"}:
        return True
    if len(shared) < 2:
        return False
    return len(shared) / max(1, min(len(ack_concepts), len(policy_concepts))) >= 0.55


@app.middleware("http")
async def track_api_latency(request: Request, call_next):
    started = perf_counter()
    response = await call_next(request)
    response_ms = round((perf_counter() - started) * 1000, 1)
    response.headers["X-Response-Time-Ms"] = str(response_ms)
    response.headers["Server-Timing"] = f"app;dur={response_ms}"
    logger.info("api_timing method=%s path=%s status=%s response_ms=%s",
                request.method, request.url.path, response.status_code, response_ms)
    return response


@app.on_event("shutdown")
def close_database_pools() -> None:
    close_pools()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "collections-voicebot"}


@app.post("/v1/calls", response_model=CallStarted)
async def start_call(request: StartCallRequest, authorization: str | None = Header(default=None)) -> CallStarted:
    authorize(authorization)
    now = datetime.now(timezone.utc)
    policy = configured_frequency_policy()
    opted_out = bank_services.is_opted_out(request.customer_id, request.contact_point_id, "voice")
    if not request.eligibility_confirmed or not request.contact_allowed or opted_out:
        reason = ("account_not_eligible" if not request.eligibility_confirmed else
                  "do_not_call_preference" if opted_out else "contact_restricted")
        repository.record_blocked_evaluation(request.model_dump(), now, policy.version, reason)
        raise HTTPException(
            status_code=409,
            detail={"code": "call_blocked", "reason": reason, "ruleset_version": policy.version},
        )
    try:
        attempt = repository.reserve_attempt(request.model_dump(), policy, now)
    except CallBlocked as exc:
        repository.record_blocked_evaluation(request.model_dump(), now, exc.policy_version, exc.reason)
        raise HTTPException(
            status_code=409,
            detail={"code": "call_blocked", "reason": exc.reason, "ruleset_version": exc.policy_version},
        ) from exc

    session = CallSession(
        session_id=uuid4(),
        attempt_id=attempt.attempt_id,
        request=request,
        started_at=now,
        pending="identity_confirmation",
        bot_version=f"{llm_provider_name()}-{CLASSIFIER_PROMPT_VERSION}" if classifier_configured() else "rules-fallback-v1",
    )
    customer_name = " ".join(part.strip() for part in (request.first_name, request.last_name) if part and part.strip())
    opening = (f"Hello, I’m an automated assistant calling on behalf of Mumbai Bank. Am I speaking with {customer_name}?"
               if customer_name else
               "Hello, I’m an automated assistant calling on behalf of Mumbai Bank. Am I speaking with the account holder?")
    session.scratch["conversation_stage"] = "identity_confirmation"
    session.scratch["awaiting_identity_confirmation"] = True
    session.scratch["greeting_completed"] = True
    session.scratch["dialogue_history"] = [{"role": "assistant", "content": opening}]
    repository.create_session(session)
    return CallStarted(
        session_id=session.session_id,
        attempt_id=attempt.attempt_id,
        case_id=request.case_id,
        opening=opening,
        frequency_policy_version=policy.version,
    )


@app.post("/v1/calls/{session_id}/turn", response_model=TurnResponse)
async def turn(session_id: UUID, request: TurnRequest, authorization: str | None = Header(default=None)) -> TurnResponse:
    turn_started = perf_counter()
    authorize(authorization)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    if session.terminal:
        raise HTTPException(status_code=409, detail="call_session_is_terminal")
    started = perf_counter()
    reference_date = datetime.now(ZoneInfo(session.request.timezone)).date().isoformat()
    fast_extracted = fast_classify_utterance(request.transcript, session.pending, reference_date)
    extracted = None
    source = "rule_fallback"
    llm_ms = 0.0
    llm_error_type = None
    llm_error_detail = None
    classifier_timings: dict[str, object] = {}
    llm_trace: dict[str, object] = {}
    dialogue_history = list(session.scratch.get("dialogue_history", []))
    question_family = _question_family_for_state(session.pending)
    repeated_question, repeated_question_count = _repeated_bot_question(dialogue_history, session.pending)
    loop_recovery = bool(
        # Start contextual recovery after two same-family asks. Keep trying
        # contextual recovery before the loop breaker hands off to a colleague.
        repeated_question_count >= 2
        and session.scratch.get("right_party_confirmed")
        and session.scratch.get("due_information_given") is True
    )
    if loop_recovery:
        session.scratch["loop_recovery_active"] = {
            "question": repeated_question,
            "repetitions": repeated_question_count,
        }
    else:
        session.scratch.pop("loop_recovery_active", None)
    # Include a bounded, relevant customer/agent exchange from the beginning
    # of the call too. Identity and greeting answers depend on what the agent
    # just asked, while this history contains no due details before disclosure.
    conversation_context = _relevant_dialogue_context(
        dialogue_history, question_family, loop_recovery
    )
    deterministic_fast_intents = {"greeting", "payment_not_made", "waiver"}
    deterministic_fast = not loop_recovery and fast_extracted is not None and (
        fast_extracted.get("intent") in deterministic_fast_intents
        or (
            session.pending == "identity_confirmation"
            and fast_extracted.get("summary") == "Identity confirmation."
        )
    )
    if deterministic_fast:
        extracted = fast_extracted
        source = "local_fast_path"
        llm_trace["intent_classifier"] = {
            "status": "skipped",
            "reason": f"The explicit {fast_extracted.get('intent')} phrase matched a high-confidence deterministic fast path",
            "local_interpretation": fast_extracted,
        }
    elif classifier_configured():
        try:
            extracted, classifier_trace = await classify_utterance(
                request.transcript,
                pending_state=session.pending or session.scratch.get("conversation_stage") or "payment_resolution",
                known_fields={
                    **{
                        key: session.scratch[key]
                        for key in ("right_party_confirmed", "ptp_date", "ptp_amount", "reported_payment_date",
                                    "reported_payment_date_text", "reported_payment_mode",
                                    "ptp_proposed_date_text", "ptp_far_future_date_iso",
                                    "ptp_earlier_date_requested", "ptp_broad_date_window",
                                    "reported_payment_broad_window")
                        if key in session.scratch
                    },
                    "greeting_completed": bool(session.scratch.get("greeting_completed")),
                    "due_information_disclosed": bool(session.scratch.get("due_information_given")),
                    **({"target_name": " ".join(part for part in (session.request.first_name, session.request.last_name) if part)}
                       if not session.scratch.get("right_party_confirmed") else {}),
                    "pending_question": pending_question_context(session),
                    **({"loop_recovery": {
                        "repeated_question": repeated_question,
                        "times_asked": repeated_question_count,
                        "instruction": "Use the recent turns to understand the caller's answer or correction. Do not ask this same question again.",
                    }} if loop_recovery else {}),
                },
                reference_date=reference_date,
                # Send the bounded relevant dialogue exchange on every turn;
                # the provider pairs it and normally keeps two exchanges, or
                # four when recovering from a repeated-question loop.
                conversation_history=conversation_context,
            )
            llm_ms = round((perf_counter() - started) * 1000, 1)
            source = "llm"
            llm_trace["intent_classifier"] = classifier_trace
            classifier_timings = dict(classifier_trace.get("timings_ms", {}))
        except Exception as exc:
            # Preserve clear customer facts locally if the provider errors; policy still
            # controls every side effect and protected-data disclosure.
            llm_ms = round((perf_counter() - started) * 1000, 1)
            extracted = fallback_interpretation(
                request.transcript,
                session.pending or session.scratch.get("conversation_stage"),
                reference_date,
                fast_extracted,
            )
            source = "local_safe_fallback"
            llm_error_type = type(exc).__name__
            llm_error_detail = str(exc)[:300]
            classifier_timings = dict(getattr(exc, "classifier_timing_ms", {}) or {})
            llm_trace["intent_classifier"] = dict(getattr(exc, "classifier_prompt_trace", {}) or {})
            llm_trace["intent_classifier"].update({
                "status": "error", "error_type": llm_error_type, "error_detail": llm_error_detail,
                "timings_ms": classifier_timings, "local_interpretation": extracted,
                "prompt_version": CLASSIFIER_PROMPT_VERSION,
            })
            logger.warning("conversation_llm_failed error_type=%s error_detail=%s", llm_error_type, llm_error_detail)
    else:
        extracted = fast_extracted
        source = "local_fast_path" if fast_extracted is not None else "rule_fallback"
        llm_trace["intent_classifier"] = {
            "status": "skipped",
            "reason": f"{llm_provider_name()} classifier credentials are not configured; using local interpretation when available",
            "local_interpretation": fast_extracted,
        }
    # A speech turn may have started while OTP was pending and waited on the
    # LLM. The keypad endpoint can verify the code during that wait and clear
    # the pending state. Reload before applying/saving this turn so an older
    # in-memory session cannot restore otp_code after successful verification.
    latest_session = repository.get_session(session_id)
    if latest_session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    session = latest_session
    if session.terminal:
        raise HTTPException(status_code=409, detail="call_session_is_terminal")
    dialogue_history = list(session.scratch.get("dialogue_history", []))

    intent_ms = llm_ms
    turn_pending_state = session.pending
    policy_started = perf_counter()
    response = process_turn(
        session, request.transcript, extracted,
        heard_before_opening=request.heard_before_opening,
        stt_confidence=request.stt_confidence,
        reference_date=reference_date,
    )
    # Allow contextual recovery attempts to use the prior six exchanges. Only
    # hand off after four same-family questions were already asked, rather than
    # terminating on the first turn where recovery context is enabled.
    if (
        loop_recovery
        and repeated_question_count >= 4
        and not response.terminal
        and response.outcome is None
        and session.pending not in {"identity_confirmation", "otp_code"}
        and "?" in response.bot_text
        and _question_family_for_state(session.pending) == question_family
    ):
        recovery_summary = (
            f"Repeated question loop: {repeated_question_count} prior asks. "
            f"Recent conversation: {json.dumps(dialogue_history[-12:], ensure_ascii=False)}. "
            f"Latest customer statement: {request.transcript[:500]}"
        )
        task = create_followup_task(session, "repeated_question_recovery", recovery_summary, "normal")
        session.outcome = Outcome(
            type=OutcomeType.NO_COMMITMENT,
            fields={"reason": "repeated_question_recovery", "agent_task_id": task["task_id"]},
            follow_up_required=True,
            follow_up_reason="repeated_question_recovery",
        )
        session.pending = None
        session.terminal = True
        response = TurnResponse(
            session_id=session.session_id,
            bot_text="I may have repeated my question. I’ve noted what you’ve told me and will ask a colleague to follow up, so you don’t need to repeat it. Thank you for your time.",
            terminal=True,
            outcome=session.outcome,
            metadata={"loop_recovery": "human_follow_up_after_repeated_question"},
        )
    policy_ms = round((perf_counter() - policy_started) * 1000, 1)

    # Policy selects the allowed action and complete response before any LLM wording is used.
    right_party_confirmed = bool(session.scratch.get("right_party_confirmed"))
    suppress_acknowledgment = bool(session.scratch.pop("suppress_acknowledgment", False))
    fixed_answer_intents = {"balance_question", "interest_question", "fee_question", "related_question", "credit_score_question", "legal_question"}
    may_use_acknowledgment = (
        classifier_configured()
        and source == "llm"
        and right_party_confirmed
        and not suppress_acknowledgment
        and not response.terminal
        and response.outcome is None
        and turn_pending_state not in {"identity_confirmation", "otp_code", "ptp_confirmation"}
        and (extracted or {}).get("intent") not in fixed_answer_intents
        and (extracted or {}).get("intent") != "greeting"
    )
    acknowledgment = str((extracted or {}).get("acknowledgment") or "").strip()
    response_source = "policy"
    response_validation_reason = None
    if may_use_acknowledgment:
        response_state = session.pending or session.scratch.get("conversation_stage") or "payment_resolution"
        if acknowledgment and _acknowledgment_repeats_policy_opening(acknowledgment, response.bot_text):
            response_source = "policy_duplicate_ack_suppressed"
            response_validation_reason = "The LLM acknowledgment repeated the policy response opening; deterministic wording was kept."
            response.metadata["response_validation"] = {"status": "suppressed_duplicate", "reason": response_validation_reason}
            response.metadata["acknowledgment_skipped_reason"] = response_validation_reason
            acknowledgment = ""
        candidate = " ".join(part for part in (acknowledgment, response.bot_text) if part).strip()
        if not acknowledgment and response_source == "policy_duplicate_ack_suppressed":
            pass
        elif _acknowledgment_is_valid(acknowledgment):
            response_validation_reason = _contracted_reply_rejection_reason(
                candidate,
                response.bot_text,
                response_state,
                grounded_utterance=f"{request.transcript} {session.request.masked_account_reference or ''}",
            )
        else:
            response_validation_reason = "The acknowledgment was missing, generic, or too long."
        if response_source == "policy_duplicate_ack_suppressed":
            pass
        elif response_validation_reason is None:
            response.bot_text = candidate
            response_source = "llm_acknowledgment"
            response.metadata["acknowledgment"] = acknowledgment
            response.metadata["response_validation"] = {"status": "passed", "reason": None}
        else:
            response_source = "policy_validator_fallback"
            response.metadata["response_validation"] = {"status": "rejected", "reason": response_validation_reason}
    else:
        if source == "llm" and acknowledgment:
            response.metadata["acknowledgment_skipped_reason"] = (
                "Policy selected a protected, fixed, or terminal response path; policy wording was used as-is."
            )
    response.metadata["llm_used"] = source == "llm" and extracted is not None
    response.metadata["prompt_version"] = CLASSIFIER_PROMPT_VERSION if classifier_configured() else "rules-fallback-v1"
    response.metadata["intent_source"] = source
    response.metadata["conversation_state"] = turn_pending_state or session.scratch.get("conversation_stage") or "payment_resolution"
    response.metadata["classifier_timings_ms"] = classifier_timings
    response.metadata["heard_before_opening"] = request.heard_before_opening
    response.metadata["timings_ms"] = {
        "llm": round(intent_ms, 1),
        "intent": intent_ms,
        "response_generation": 0.0,
        "policy": policy_ms,
        "turn_api": round((perf_counter() - turn_started) * 1000, 1),
    }
    if classifier_timings:
        logger.info(
            "classifier_timing state=%s source=%s intent=%s timing_ms=%s",
            response.metadata["conversation_state"], source,
            (extracted or {}).get("intent", "unclear"), classifier_timings,
        )
    if extracted is not None and extracted.get("intent") != "unclear":
        response.metadata["intent"] = extracted.get("intent")
    if extracted is not None:
        for semantic_field in ("dialogue_act", "pending_slot_status", "date_precision", "identity_status"):
            semantic_value = extracted.get(semantic_field)
            if semantic_value and semantic_value not in {"not_applicable", "none", "no_clear_act", "unclear"}:
                response.metadata[semantic_field] = semantic_value
    response.metadata["reply_source"] = response_source
    response.metadata["llm_trace"] = {
        "intent_classifier": llm_trace.get("intent_classifier"),
        "response_generator": {
            "status": "not_called",
            "reason": "The policy response is composed with the acknowledgment from the intent call; no second LLM request is made.",
        },
    }
    if llm_error_type:
        response.metadata["llm_error_type"] = llm_error_type
        response.metadata["llm_error_detail"] = llm_error_detail
    decision_trace = list(session.scratch.get("decision_trace", []))
    if loop_recovery:
        decision_trace.append({
            "rule": "Repeated-question recovery",
            "status": "triggered",
            "explanation": (
                f"The same assistant question had already been asked {repeated_question_count} times. "
                "The classifier received the last four customer/assistant exchanges and was instructed to recover prior answers instead of repeating the question."
            ),
        })
    if response.metadata.get("loop_recovery") == "human_follow_up_after_repeated_question":
        decision_trace.append({
            "rule": "Repeated-question loop breaker",
            "status": "human follow-up",
            "explanation": "Context did not resolve the repeated prompt, so the bot stopped asking and sent the recent conversation to a colleague.",
        })
    if response_source == "llm_acknowledgment":
        decision_trace.append({
            "rule": "Customer acknowledgment",
            "status": "passed",
            "explanation": f"The reply specifically acknowledged: {response.metadata['acknowledgment']}",
        })
        decision_trace.append({
            "rule": "Response contract check",
            "status": "passed",
            "explanation": "The LLM acknowledgment passed validation and the deterministic policy response stayed intact.",
        })
    elif response_source == "policy_validator_fallback":
        decision_trace.append({
            "rule": "Response contract check",
            "status": "rejected",
            "explanation": f"{response.metadata.get('response_validation', {}).get('reason') or 'The acknowledgment failed validation.'} The policy-selected wording was kept.",
        })
    elif response_source == "policy_duplicate_ack_suppressed":
        decision_trace.append({
            "rule": "Duplicate acknowledgment suppression",
            "status": "suppressed",
            "explanation": "The LLM acknowledgment repeated the opening point of the deterministic response, so only the policy response was spoken.",
        })
    decision_trace.append({
        "rule": "Next response",
        "status": "selected",
        "explanation": response.bot_text,
    })
    response.metadata["decision_trace"] = decision_trace
    dialogue_history.extend([
        {"role": "user", "content": request.transcript[:1000]},
        {
            "role": "assistant",
            "content": response.bot_text[:1000],
            **({"question_family": _question_family_for_state(session.pending)}
               if "?" in response.bot_text and _question_family_for_state(session.pending) else {}),
        },
    ])
    session.scratch["dialogue_history"] = dialogue_history[-12:]
    repository.save_session(session)
    return response


@app.post("/v1/calls/{session_id}/otp", response_model=TurnResponse)
def verify_session_otp(session_id: UUID, request: OtpCodeRequest,
                       authorization: str | None = Header(default=None)) -> TurnResponse:
    authorize(authorization)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    if not session.scratch.get("right_party_confirmed"):
        raise HTTPException(status_code=403, detail="right_party_confirmation_required")
    response = process_otp_code(session, request.code)
    repository.save_session(session)
    return response


async def _complete_session(session: CallSession, disposition: AttemptDisposition) -> CompletionResponse:
    if repository.is_completed(session.session_id):
        raise HTTPException(status_code=409, detail="call_session_already_completed")
    if session.outcome is None:
        right_party = bool(session.scratch.get("right_party_confirmed"))
        task = None
        if right_party:
            task = create_followup_task(session, "connected_call_ended_without_outcome",
                                        "Conversation ended without a recorded customer outcome", "normal")
        session.outcome = Outcome(
            type=OutcomeType.NO_COMMITMENT,
            fields={
                "reason": "conversation_ended_without_outcome" if right_party else "account_holder_not_confirmed",
                **({"agent_task_id": task["task_id"]} if task else {}),
            },
            follow_up_required=right_party,
            follow_up_reason="outcome_review_needed" if right_party else None,
        )
    if not repository.mark_completed(session):
        raise HTTPException(status_code=409, detail="call_session_already_completed")
    repository.update_attempt_disposition(session.attempt_id, disposition)
    event_id = uuid4()
    event = CustomerOutcomeEvent(
        event_id=event_id,
        case_id=session.request.case_id,
        episode_id=session.request.episode_id,
        interaction_id=session.session_id,
        customer_id=session.request.customer_id,
        account_id=session.request.account_id,
        occurred_at=datetime.now(timezone.utc),
        contact_disposition=disposition,
        outcome=session.outcome,
        bot_version=session.bot_version,
        campaign_id=session.request.campaign_id,
    )
    payload = event.model_dump(mode="json")
    repository.save_event(event_id, session.session_id, session.request.case_id, event.occurred_at, event.model_dump_json())
    status, attempts, error = await asyncio.to_thread(deliver_event, payload)
    repository.update_delivery(event_id, status, attempts, error)
    return CompletionResponse(
        session_id=session.session_id,
        case_id=session.request.case_id,
        disposition=disposition,
        outcome=session.outcome,
        delivery_status=status,
        event_id=event_id,
    )


@app.post("/v1/calls/{session_id}/complete", response_model=CompletionResponse)
async def complete(session_id: UUID, request: CompleteCallRequest,
                   authorization: str | None = Header(default=None)) -> CompletionResponse:
    authorize(authorization)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    return await _complete_session(session, request.disposition)


_DEMO_ACCESS_COOKIE = "collections_demo_access"
_DEMO_ACCESS_HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Private voice demo</title>
<body style="font:16px system-ui;max-width:560px;margin:15vh auto;padding:24px;color:#202124">
<h1>Private voice demo</h1><p id="status">Checking your private access link…</p>
<script>
const statusEl = document.getElementById('status');
const token = location.hash ? decodeURIComponent(location.hash.slice(1)) : '';
if (!token) {
  statusEl.textContent = 'This demo is private. Open the full access link you were given.';
} else {
  fetch('/demo/unlock', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token})})
    .then(async response => ({ok:response.ok, data:await response.json()}))
    .then(result => {
      if (!result.ok) throw new Error('Access link is invalid or expired. Ask the owner for a fresh link.');
      history.replaceState(null, '', location.pathname);
      location.reload();
    })
    .catch(error => { history.replaceState(null, '', location.pathname); statusEl.textContent = error.message; });
}
</script></body></html>"""


def _demo_token_matches(presented: str | None) -> bool:
    return bool(settings.demo_access_token and presented and
                hmac.compare_digest(presented, settings.demo_access_token))


def _require_local_browser_demo(request: Request) -> None:
    if settings.app_env == "demo":
        if _demo_token_matches(request.cookies.get(_DEMO_ACCESS_COOKIE)):
            return
        raise HTTPException(status_code=404, detail="private_demo_access_required")
    if settings.app_env != "development":
        raise HTTPException(status_code=404, detail="browser_demo_only_available_in_development_or_gated_demo")
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="browser_demo_requires_loopback_access")


def _require_demo_websocket_access(websocket: WebSocket) -> None:
    host = websocket.client.host if websocket.client else ""
    if settings.app_env == "development":
        if host in {"127.0.0.1", "::1", "localhost", "testclient"}:
            return
        raise HTTPException(status_code=403, detail="browser_demo_requires_loopback_access")
    origin = urlsplit(websocket.headers.get("origin", ""))
    request_host = websocket.headers.get("host", "")
    if (settings.app_env != "demo"
            or not _demo_token_matches(websocket.cookies.get(_DEMO_ACCESS_COOKIE))
            or origin.scheme != "https"
            or origin.netloc != request_host):
        raise HTTPException(status_code=403, detail="private_demo_access_required")


def _internal_service_authorization() -> str:
    if not settings.collections_api_token:
        raise HTTPException(status_code=503, detail="COLLECTIONS_API_TOKEN_not_configured")
    return f"Bearer {settings.collections_api_token}"


@app.get("/", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
def browser_demo(request: Request) -> HTMLResponse:
    if settings.app_env == "demo" and not _demo_token_matches(request.cookies.get(_DEMO_ACCESS_COOKIE)):
        return HTMLResponse(_DEMO_ACCESS_HTML, headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
        })
    _require_local_browser_demo(request)
    return HTMLResponse(BROWSER_DEMO_HTML, headers={
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
    })


@app.post("/demo/unlock")
async def unlock_browser_demo(request: Request) -> JSONResponse:
    if settings.app_env != "demo":
        raise HTTPException(status_code=404, detail="not_found")
    origin = urlsplit(request.headers.get("origin", ""))
    request_host = request.headers.get("host", "")
    if origin.scheme != "https" or origin.netloc != request_host:
        raise HTTPException(status_code=403, detail="same_origin_https_required")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_request") from exc
    if not isinstance(payload, dict) or not _demo_token_matches(payload.get("token")):
        raise HTTPException(status_code=403, detail="invalid_demo_access_link")
    response = JSONResponse({"unlocked": True}, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    response.set_cookie(
        _DEMO_ACCESS_COOKIE,
        settings.demo_access_token,
        max_age=86400,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@app.post("/demo/session")
async def create_browser_demo_session(request: Request) -> dict:
    api_started = perf_counter()
    _require_local_browser_demo(request)
    suffix = uuid4().hex[:12]
    customer_id = f"cust-browser-{suffix}"
    account_id = f"acct-browser-{suffix}"
    contact_point_id = f"contact-browser-{suffix}"
    bank_services.create_browser_demo_account(customer_id, account_id)
    demo_request = StartCallRequest(
        case_id=f"case-browser-{suffix}",
        episode_id=f"episode-browser-{suffix}",
        customer_id=customer_id,
        account_id=account_id,
        contact_point_id=contact_point_id,
        timezone="Asia/Kolkata",
        first_name="Asha",
        last_name="Mehta",
        days_past_due=8,
        masked_account_reference="****1234",
        eligibility_confirmed=True,
        contact_allowed=True,
        contact_policy_version="browser-demo",
    )
    started = await start_call(demo_request, authorization=_internal_service_authorization())
    # Unlike a telephony adapter, the browser demo has not played the opening
    # yet. Keep identity confirmation closed until the browser acknowledges that
    # the named opening finished playing.
    session = repository.get_session(started.session_id)
    if session:
        session.scratch["awaiting_identity_confirmation"] = False
        session.scratch["identity_opening_delivered"] = False
        repository.save_session(session)
    return {
        "session_id": str(started.session_id),
        "opening": started.opening,
        "case_id": started.case_id,
        "llm_configured": classifier_configured(),
        "llm_provider": llm_provider_name(),
        "stt_tts_configured": voice_provider_configured(),
        "voice_provider": voice_provider_name(),
        "timings_ms": {"api": round((perf_counter() - api_started) * 1000, 1)},
    }


@app.post("/demo/session/{session_id}/opening-delivered")
def browser_demo_opening_delivered(request: Request, session_id: UUID) -> dict:
    _require_local_browser_demo(request)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    if session.terminal or session.pending != "identity_confirmation":
        raise HTTPException(status_code=409, detail="identity_opening_not_expected")
    session.scratch["identity_opening_delivered"] = True
    session.scratch["awaiting_identity_confirmation"] = True
    repository.save_session(session)
    return {"opening_delivered": True}


@app.post("/demo/session/{session_id}/identity-pause-check")
def browser_demo_identity_pause_check(request: Request, session_id: UUID) -> dict:
    """Repeat identity question only after the browser observes a sustained pause."""
    _require_local_browser_demo(request)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    if (session.terminal or session.pending != "identity_confirmation"
            or not session.scratch.get("identity_silent_wait")
            or session.scratch.get("right_party_confirmed")):
        return {"prompt": None}
    contact_name = " ".join(
        part.strip() for part in (session.request.first_name, session.request.last_name)
        if part and part.strip()
    ) or "the account holder"
    prompt = f"Am I speaking with {contact_name}?"
    session.scratch["identity_silent_wait"] = False
    session.scratch["awaiting_identity_confirmation"] = True
    history = list(session.scratch.get("dialogue_history", []))
    history.append({
        "role": "assistant",
        "content": prompt,
        "question_family": "identity_confirmation",
    })
    session.scratch["dialogue_history"] = history[-12:]
    repository.save_session(session)
    return {"prompt": prompt}


@app.post("/demo/session/{session_id}/turn")
async def browser_demo_turn(
    request: Request,
    session_id: UUID,
    audio: UploadFile = File(...),
    heard_before_opening: bool = Form(default=False),
    live_transcript: str = Form(default=""),
    stt_confidence: float | None = Form(default=None, ge=0.0, le=1.0),
) -> dict:
    api_started = perf_counter()
    _require_local_browser_demo(request)
    raw_audio = await audio.read(10_000_001)
    if not raw_audio or len(raw_audio) > 10_000_000:
        raise HTTPException(status_code=413, detail="audio_turn_must_be_under_10mb")
    transcript = live_transcript.strip()[:4000]
    if transcript:
        # The browser already streamed this microphone turn to the configured
        # speech provider. Reuse its finalized text instead of retranscribing.
        stt_ms = 0.0
        stt_source = "live_stream"
    else:
        stt_started = perf_counter()
        try:
            transcript = await transcribe_browser_audio(raw_audio, (audio.content_type or "audio/webm").split(";")[0])
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"speech_recognition_failed: {type(exc).__name__}") from exc
        stt_ms = round((perf_counter() - stt_started) * 1000, 1)
        stt_source = "uploaded_audio_fallback"
    if not transcript:
        raise HTTPException(status_code=422, detail="no_speech_detected_try_again")
    result = await turn(
        session_id,
        TurnRequest(
            transcript=transcript,
            heard_before_opening=heard_before_opening,
            stt_confidence=stt_confidence,
        ),
        authorization=_internal_service_authorization(),
    )
    session = repository.get_session(session_id)
    # The policy has selected an identity question, but it is not an active
    # confirmation prompt until the browser finishes playing that response.
    if (session and session.pending == "identity_confirmation"
            and not result.metadata.get("identity_pause_check")):
        session.scratch["awaiting_identity_confirmation"] = False
        repository.save_session(session)
    completion = None
    if result.terminal and session:
        disposition = (AttemptDisposition.CONNECTED_CUSTOMER if session.scratch.get("right_party_confirmed")
                       else AttemptDisposition.CONNECTED_THIRD_PARTY)
        completion = await _complete_session(session, disposition)
    timings = {
        "stt": stt_ms,
        "llm": result.metadata.get("timings_ms", {}).get("llm", 0.0),
        "policy": result.metadata.get("timings_ms", {}).get("policy", 0.0),
        "api": round((perf_counter() - api_started) * 1000, 1),
    }
    result.metadata["timings_ms"] = timings
    return {
        "transcript": transcript,
        "stt_source": stt_source,
        "response": result.model_dump(mode="json"),
        "pending": session.pending if session else None,
        "completion": completion.model_dump(mode="json") if completion else None,
        "timings_ms": timings,
    }


@app.post("/demo/session/{session_id}/otp")
async def browser_demo_otp(request: Request, session_id: UUID, otp: OtpCodeRequest) -> dict:
    api_started = perf_counter()
    _require_local_browser_demo(request)
    result = verify_session_otp(
        session_id,
        otp,
        authorization=_internal_service_authorization(),
    )
    session = repository.get_session(session_id)
    completion = None
    if result.terminal and session:
        disposition = (AttemptDisposition.CONNECTED_CUSTOMER if session.scratch.get("right_party_confirmed")
                       else AttemptDisposition.CONNECTED_THIRD_PARTY)
        completion = await _complete_session(session, disposition)
    return {
        "response": result.model_dump(mode="json"),
        "pending": session.pending if session else None,
        "completion": completion.model_dump(mode="json") if completion else None,
        "timings_ms": {"api": round((perf_counter() - api_started) * 1000, 1)},
    }


@app.websocket("/demo/tts")
async def browser_demo_tts(websocket: WebSocket) -> None:
    try:
        _require_demo_websocket_access(websocket)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        text = str(payload.get("text", "")).strip()
        if not text or len(text) > 4000:
            await websocket.send_json({"type": "error", "message": "invalid_tts_text"})
            await websocket.close(code=1008)
            return
        started = perf_counter()
        first_audio_ms = None
        total_ms = None
        async for kind, chunk, first_ms, final_ms in stream_browser_audio(text):
            if kind == "format":
                await websocket.send_json({"type": "audio_format", "mime_type": chunk})
            elif kind == "first_audio":
                first_audio_ms = first_ms
                await websocket.send_json({"type": "timing", "tts_first_audio_ms": first_ms})
                await websocket.send_bytes(chunk)
            elif kind == "audio":
                await websocket.send_bytes(chunk)
            elif kind == "done":
                total_ms = final_ms
                await websocket.send_json({"type": "timing", "tts_first_audio_ms": first_audio_ms, "tts_total_ms": total_ms})
        if total_ms is None:
            total_ms = round((perf_counter() - started) * 1000, 1)
        logger.info("tts_timing first_audio_ms=%s total_ms=%s", first_audio_ms, total_ms)
        await websocket.close(code=1000)
    except WebSocketDisconnect:
        logger.info("tts_stream_disconnected")
    except Exception as exc:
        logger.warning("tts_stream_failed error=%s", type(exc).__name__)
        try:
            await websocket.send_json({"type": "error", "message": "tts_unavailable"})
            await websocket.close(code=1011)
        except Exception:
            pass


@app.websocket("/demo/stt")
async def browser_demo_stt(websocket: WebSocket) -> None:
    """Proxy live browser PCM to the selected speech provider."""
    try:
        _require_demo_websocket_access(websocket)
    except HTTPException:
        await websocket.close(code=1008)
        return
    provider = voice_provider_name()
    if not voice_provider_configured():
        await websocket.close(code=1011)
        return
    if provider == "sarvam":
        query = urlencode({
            "model": settings.sarvam_stt_model,
            "language_code": settings.sarvam_stt_language,
            "stream_type": settings.sarvam_stt_stream_type,
            "mode": settings.sarvam_stt_mode,
            "endpointing": "manual",
            "encoding": "linear16",
            "sample_rate": "16000",
            **({"keyterms": settings.sarvam_stt_keyterms} if settings.sarvam_stt_model == "saaras:v4" and settings.sarvam_stt_keyterms else {}),
        })
        url = f"wss://api.sarvam.ai/speech-to-text-realtime/ws?{query}"
        auth_headers = {"api-subscription-key": settings.sarvam_api_key}
    else:
        query = urlencode([
            ("model", settings.deepgram_stt_model), ("language", "multi"),
            ("language_hint", "en-IN"), ("language_hint", "hi"),
            ("encoding", "linear16"), ("sample_rate", "16000"), ("channels", "1"),
            ("interim_results", "true"), ("smart_format", "true"), ("endpointing", "800"),
        ])
        base = settings.deepgram_api_base_url.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{base}/v1/listen?{query}"
        auth_headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
    await websocket.accept()
    try:
        async with websocket_connect(
            url,
            extra_headers=auth_headers,
            open_timeout=15,
            close_timeout=3,
            ping_interval=20,
            max_size=2_000_000,
        ) as deepgram:
            async def browser_to_provider() -> None:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("bytes") is not None:
                        if provider == "sarvam":
                            await deepgram.send(json.dumps({
                                "event": "audio_input",
                                "audio": base64.b64encode(message["bytes"]).decode("ascii"),
                            }))
                        else:
                            await deepgram.send(message["bytes"])
                    elif message.get("text"):
                        control = json.loads(message["text"])
                        if control.get("type") in {"KeepAlive", "Finalize", "CloseStream"}:
                            if provider == "sarvam":
                                event_type = {
                                    "KeepAlive": "ping",
                                    "Finalize": "speech_end",
                                    "CloseStream": "end",
                                }[control["type"]]
                                await deepgram.send(json.dumps({"event": event_type}))
                            else:
                                await deepgram.send(json.dumps(control))
                        elif provider == "sarvam" and control.get("type") == "SpeechStart":
                            await deepgram.send(json.dumps({"event": "speech_start"}))
                        if control.get("type") == "CloseStream":
                            return

            async def provider_to_browser() -> None:
                async for message in deepgram:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        if provider == "sarvam":
                            try:
                                event = json.loads(message)
                            except (TypeError, ValueError):
                                continue
                            event_type = event.get("event")
                            if event_type in {"transcript.partial", "transcript.final"}:
                                alternative = {"transcript": event.get("text", "")}
                                if isinstance(event.get("confidence"), (int, float)):
                                    alternative["confidence"] = event["confidence"]
                                await websocket.send_json({
                                    "channel": {"alternatives": [alternative]},
                                    "is_final": event_type == "transcript.final",
                                    "provider": "sarvam",
                                    "language": event.get("language"),
                                })
                            elif event_type == "error":
                                await websocket.send_json({"type": "Error", "message": "sarvam_transcription_unavailable"})
                                if event.get("is_fatal"):
                                    return
                        else:
                            await websocket.send_text(message)

            tasks = {asyncio.create_task(browser_to_provider()), asyncio.create_task(provider_to_browser())}
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                try:
                    task.result()
                except (WebSocketDisconnect, Exception) as exc:
                    logger.info("live_stt_stream_ended error=%s", type(exc).__name__)
    except Exception as exc:
        logger.warning("live_stt_stream_failed error=%s", type(exc).__name__)
        try:
            await websocket.send_json({"type": "Error", "message": "live_transcription_unavailable"})
            await websocket.close(code=1011)
        except Exception:
            pass


@app.get("/demo/session/{session_id}/otp-code")
def browser_demo_otp_code(request: Request, session_id: UUID) -> dict[str, str]:
    _require_local_browser_demo(request)
    session = repository.get_session(session_id)
    if session is None or not session.scratch.get("otp_challenge_id"):
        raise HTTPException(status_code=404, detail="otp_challenge_not_found")
    code = bank_services.dev_otp_code(session.scratch["otp_challenge_id"], "loopback-browser-demo")
    if code is None:
        raise HTTPException(status_code=404, detail="otp_code_not_available")
    return {"code": code}


@app.post("/demo/session/{session_id}/finish")
async def finish_browser_demo(request: Request, session_id: UUID) -> dict:
    _require_local_browser_demo(request)
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call_session_not_found")
    if not session.terminal:
        session.terminal = True
        repository.save_session(session)
    completed = await _complete_session(session, AttemptDisposition.CONNECTED_CUSTOMER)
    return completed.model_dump(mode="json")


@app.get("/v1/cases/{case_id}/history")
def case_history(case_id: str, authorization: str | None = Header(default=None)) -> dict:
    authorize(authorization)
    return repository.case_history(case_id)

