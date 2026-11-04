from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .bank_services import bank_services
from .schemas import CallSession, Outcome, OutcomeType, TurnResponse


from .business_rules import business_rules, business_rule_engine

RULES = business_rules

# Compatibility names keep the flow readable while every adjustable phrase,
# cue, regex, threshold and fact is sourced from the active versioned ruleset.
_ABUSE = RULES.phrase("abuse")
_DISTRESS = RULES.phrase("distress")
_PAID = RULES.phrase("paid")
_LATE_FEE_DISCOUNT = RULES.phrase("late_fee_discount")
_WAIVER = RULES.phrase("waiver")
_NOT_PAID = RULES.phrase("not_paid")
_PAYMENT_REFUSAL = RULES.phrase("payment_refusal")
_BALANCE = RULES.phrase("balance")
_BALANCE_INFO_REQUEST = RULES.patterns["balance_info_request"]
_BALANCE_CHECK_CUES = RULES.phrase("balance_check")
_DEFER_PAYMENT_CUES = RULES.phrase("defer_payment")
_DEFER_PERIOD_CUES = RULES.phrase("defer_period")
_PAYMENT_METHOD_QUESTION_CUES = RULES.phrase("payment_method_question")
_PAYMENT_TERMS = RULES.phrase("payment_terms")
_QUESTION_CUES = RULES.phrase("question")
_CARD_REFERENCE_QUESTION = RULES.phrase("card_reference_question")
_OTP_QUESTION = RULES.phrase("otp_question")
_PAYMENT_PURPOSE_QUESTION = RULES.phrase("payment_purpose_question")
_PRODUCTS = RULES.phrase("products")
_DISPUTE = RULES.phrase("dispute")
_CALLBACK = RULES.phrase("callback")
_PAYMENT_LINK = RULES.phrase("payment_link")
_COMMITMENT_CUES = RULES.phrase("commitment")
_NEGATED_COMMITMENT = RULES.phrase("negated_commitment")
_OFFER_REQUEST = RULES.phrase("offer_request")
_INTEREST = RULES.phrase("interest")
_INTEREST_CONCERN = RULES.phrase("interest_concern")
_INTEREST_CONCERN_CUE = RULES.patterns["interest_concern"]
_FEE = RULES.phrase("fee")
_CREDIT_SCORE = RULES.phrase("credit_score")
_LEGAL = RULES.phrase("legal")
_IDENTITY_INFO_QUESTION = RULES.phrase("identity_info_question")
_FRUSTRATION = RULES.phrase("frustration")
_HURRY = RULES.phrase("hurry")
_YOU_CALLED = RULES.phrase("you_called")
_GREETING = RULES.phrase("greeting")
_AFFIRM = RULES.phrase("affirm")
_NEGATIVE = RULES.phrase("negative")
_UNCERTAIN_CONFIRMATION = RULES.phrase("uncertain_confirmation")
_NEEDS_TIME_TO_CHECK = RULES.phrase("needs_time_to_check")
_NOT_AVAILABLE = RULES.phrase("not_available")
_OPT_OUT = RULES.phrase("opt_out")
_REFUSAL_REASON_CUES = RULES.phrase("refusal_reason")
_PENDING_QUESTION_CONTRACTS = RULES.pending_question_contracts
_PENDING_SLOT_INTENTS = RULES.pending_slot_intents

INTEREST_RATE = float(RULES.facts["monthly_interest_rate_percent"])
LATE_FEE = int(RULES.facts["late_fee_inr"])
LATE_FEE_THRESHOLD = int(RULES.facts["late_fee_balance_threshold_inr"])
REFLECTION_WORKING_DAYS = int(RULES.facts["payment_reflection_working_days"])
RECENT_PAYMENT_DAYS = RULES.thresholds["recent_payment_days"]
OLD_PAYMENT_REVIEW_DAYS = RULES.thresholds["old_payment_review_days"]
FAR_FUTURE_COMMITMENT_DAYS = RULES.thresholds["far_future_commitment_days"]
LOW_SIGNAL_WORD_COUNT = RULES.thresholds["low_signal_word_count"]
LOW_STT_CONFIDENCE_PERCENT = RULES.thresholds["low_stt_confidence_percent"]
MAXIMUM_CALL_SECONDS = RULES.thresholds["maximum_call_seconds"]
MAXIMUM_TURNS = RULES.thresholds["maximum_turns"]
IDENTITY_CONFIRMATION_ATTEMPTS = RULES.thresholds["identity_confirmation_attempts"]
PAYMENT_DATE_WAIT_ATTEMPTS = RULES.thresholds["payment_date_wait_attempts"]


def _is_customer_balance_request(text: str) -> bool:
    """Return true only when the caller asks about their bank/card balance.

    The configured balance-question regex can match the word "balance" before
    the rest of a sentence is considered (for example, "balance of the Indian
    cricket team"). Treat an explicit "balance of ..." object as an additional
    scope check so unrelated subjects cannot trigger OTP verification.
    """
    normalized = re.sub(r"\s+", " ", (text or "").casefold()).strip()
    object_match = re.search(r"\bbalance\s+of\s+([^?.!,;]+)", normalized)
    if object_match:
        target = object_match.group(1).strip()
        if not re.match(
            r"(?:(?:my|our|the|this|your)\s+)?(?:(?:mumbai\s+bank|the\s+bank|bank)\s+)?"
            r"(?:account|credit\s*card|card|loan|minimum\s+due|amount\s+due|outstanding)\b",
            target,
        ):
            return False
    return bool(_BALANCE_INFO_REQUEST.search(normalized) or _has(normalized, _BALANCE))


def _monthly_interest_text() -> str:
    return f"{INTEREST_RATE:g}% per month"


def _late_fee_text() -> str:
    return f"₹{LATE_FEE:,}"


def _threshold_text() -> str:
    return f"₹{LATE_FEE_THRESHOLD:,}"


def _approximate_payment_date_reply() -> str:
    return ("I understand it was around that time. To check the payment, I need the specific calendar day. "
            "Do you remember the date? Take a moment to check; if you can’t find it, I can ask our team to review it.")


def _broad_date_window(text: str) -> str | None:
    """Find a relative date window that still needs a calendar day."""
    patterns = (
        r"\b(?:early|mid|middle|late|end of)\s+(?:next|this|last)\s+week\b",
        r"\b(?:next|this|last|coming|following|previous)\s+week\b",
        r"\b(?:early|mid|middle|late|end of)\s+(?:next|this|last)\s+month\b",
        r"\b(?:next|this|last|coming|following|previous)\s+month\b",
        r"\b(?:within|in)\s+(?:the\s+)?next\s+(?:one|two|\d+)\s+weeks?\b",
        r"\b(?:within|in)\s+(?:a|one|two|\d+)\s+weeks?\b",
        r"\b(?:by|at)\s+the\s+end\s+of\s+(?:this|next|the)\s+month\b",
        r"\b(?:in|within)\s+(?:the\s+)?next\s+few\s+days\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text.casefold())
        if match:
            return match.group(0)
    return None


def _weekday_date_in_window(text: str, window: str, reference_date: str | None = None) -> str | None:
    """Resolve a weekday-only answer when the previous question named a week."""
    weekday_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    match = re.search(r"\b(" + "|".join(weekday_names) + r")\b", text.casefold())
    if (not match or "week" not in window
            or any(term in window for term in ("two weeks", "few days", "within", "in "))):
        return None
    try:
        today = date.fromisoformat(reference_date) if reference_date else datetime.now(timezone.utc).date()
    except ValueError:
        today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    normalized_window = window.casefold()
    if "last" in normalized_window or "previous" in normalized_window:
        week_start = monday - timedelta(days=7)
    elif "this" in normalized_window:
        week_start = monday
    else:
        week_start = monday + timedelta(days=7)
    return (week_start + timedelta(days=weekday_names[match.group(1)])).isoformat()


def _date_window_bounds(window: str, reference_date: str | None = None) -> tuple[date, date] | None:
    """Resolve a supported broad date phrase to inclusive calendar boundaries."""
    try:
        today = date.fromisoformat(reference_date) if reference_date else datetime.now(timezone.utc).date()
    except ValueError:
        today = datetime.now(timezone.utc).date()
    phrase = window.casefold().strip()

    if "week" in phrase:
        monday = today - timedelta(days=today.weekday())
        if "last" in phrase or "previous" in phrase:
            start = monday - timedelta(days=7)
        elif "this" in phrase:
            start = monday
        else:
            start = monday + timedelta(days=7)
        if "early" in phrase:
            return start, start + timedelta(days=1)
        if "mid" in phrase or "middle" in phrase:
            return start + timedelta(days=2), start + timedelta(days=3)
        if "late" in phrase:
            return start + timedelta(days=4), start + timedelta(days=6)
        if "end of" in phrase:
            return start + timedelta(days=6), start + timedelta(days=6)
        return start, start + timedelta(days=6)

    if "month" in phrase:
        if "next" in phrase:
            year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        elif "last" in phrase or "previous" in phrase:
            year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        else:
            year, month = today.year, today.month
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        if "early" in phrase:
            return start, min(end, start + timedelta(days=9))
        if "mid" in phrase or "middle" in phrase:
            return min(end, start + timedelta(days=10)), min(end, start + timedelta(days=19))
        if "late" in phrase:
            return min(end, start + timedelta(days=20)), end
        if "by the end" in phrase or phrase.startswith("by ") or phrase.startswith("at "):
            return today + timedelta(days=1), end
        if "end of" in phrase:
            return max(start, end - timedelta(days=6)), end
        return start, end

    weeks_match = re.search(r"\b(?:within|in)\s+(?:the\s+)?(?:next\s+)?(one|two|\d+)\s+weeks?\b", phrase)
    if weeks_match:
        count = {"one": 1, "two": 2}.get(weeks_match.group(1)) or int(weeks_match.group(1))
        return today + timedelta(days=1), today + timedelta(days=7 * count)
    if "few days" in phrase or "a week" in phrase:
        return today + timedelta(days=1), today + timedelta(days=7)
    return None


def _date_window_violation(
    date_iso: str,
    *,
    window: str | None,
    reference_date: str | None,
    payment_already_made: bool,
) -> str | None:
    """Return a clarification when date direction or its stated window conflicts."""
    try:
        candidate = date.fromisoformat(date_iso)
    except ValueError:
        target = f" within {window}" if window else ""
        if payment_already_made:
            return "I couldn’t confirm that calendar date. What exact past date did you make the payment?"
        return f"I couldn’t confirm that calendar date. What exact future date{target} should I note for your payment?"
    try:
        today = date.fromisoformat(reference_date) if reference_date else datetime.now(timezone.utc).date()
    except ValueError:
        today = datetime.now(timezone.utc).date()
    label = candidate.strftime("%d %B").lstrip("0")
    if payment_already_made and candidate > today:
        return f"{label} is in the future. Since you said you already paid, what past date did you make the payment?"
    if not payment_already_made and candidate <= today:
        suffix = f" and falls outside {window}" if window else ""
        target = f" within {window}" if window else ""
        return f"{label} has already passed{suffix}. Which future date{target} should I note for your payment?"
    if window:
        bounds = _date_window_bounds(window, reference_date)
        if bounds and not bounds[0] <= candidate <= bounds[1]:
            if payment_already_made:
                return f"{label} falls outside the period you mentioned ({window}). What exact date within that period did you make the payment?"
            return f"{label} falls outside the period you mentioned ({window}). Which exact date {window} should I note for your payment?"
    return None


def _broad_date_follow_up(window: str, *, payment_already_made: bool) -> str:
    simple_week = window in {"next week", "this week", "last week", "coming week", "previous week", "following week"}
    if payment_already_made:
        if simple_week:
            return f"Which exact date {window} did you make the payment?"
        return f"What specific calendar date within the period you mentioned ({window}) did you make the payment?"
    if simple_week:
        return f"Which exact date {window} should I note for your payment?"
    return f"What specific calendar date within the period you mentioned ({window}) should I note for your payment?"

def _has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _is_low_signal_utterance(
    transcript: str, extracted: dict | None, stt_confidence: float | None = None
) -> bool:
    """Keep short or weakly understood speech in clarification, not scope rejection."""
    normalized = transcript.casefold().strip()
    words = re.findall(r"[a-z]+|[\u0900-\u097f]+", normalized)
    confidence = (extracted or {}).get("intent_confidence")
    intent = (extracted or {}).get("intent")
    # Short utterances are often acknowledgements, fragments, or speech cut off
    # by VAD. A low-confidence transcript can also be poor audio even when longer.
    weak_stt = stt_confidence is not None and stt_confidence < LOW_STT_CONFIDENCE_PERCENT / 100
    return (len(words) <= LOW_SIGNAL_WORD_COUNT or weak_stt
            or (confidence == "low" and intent in {None, "unclear", "other_product"}))


def _has_explicit_out_of_scope_topic(text: str) -> bool:
    """Only route to an out-of-scope response when a clear topic was recognized."""
    return _has(text, _PRODUCTS + _CREDIT_SCORE + _LEGAL)


def _low_signal_clarification(session: CallSession) -> str:
    """Ask for the missing point in the context of the active step."""
    pending = session.pending
    if pending in {"paid_date", "paid_most_recent_date"}:
        return "I didn’t quite catch the date. What specific day did you make the payment? Take a moment if you need to check."
    if pending in {"paid_mode", "paid_most_recent_mode"}:
        return "I didn’t quite catch the payment method. Was it UPI, net banking, cheque, or another method?"
    if pending == "ptp":
        return "I didn’t quite catch the date. When do you expect to make the payment?"
    if pending == "ptp_amount":
        return "I didn’t catch the amount. What amount would you like me to note? If you need the bank-recorded minimum due, I can check it using OTP verification."
    if pending == "ptp_amount_confirmation":
        due = session.scratch.get("verified_minimum_due")
        return f"I didn’t catch that. Do you mean the verified minimum due of {_format_inr_amount(due)}?"
    if pending == "ptp_far_future_choice":
        return "I didn’t quite catch that. Can you pay earlier, or should I ask a colleague to call you?"
    if pending == "callback_time":
        return "I didn’t quite catch the preferred time. What day or time would be convenient for our team to call?"
    if pending == "paid_most_recent_confirmation":
        return "I didn’t quite catch that. Is this your most recent payment, or was there a later one?"
    if pending == "balance_check_consent":
        return "I didn’t quite catch your answer. Would you like me to check the bank-recorded balance using OTP verification?"
    if pending == "refusal_reason":
        return "I’m listening. Could you say a little more about what’s making the payment difficult?"
    return "I didn’t quite catch that. Have you already paid, or would you like to tell me when you expect to pay?"


def _is_clear_yes(text: str) -> bool:
    value = text.casefold().strip()
    return bool(RULES.pattern_search("clear_yes", value))


def _is_clear_no(text: str) -> bool:
    value = text.casefold().strip()
    return bool(RULES.pattern_search("clear_no", value))


def _is_defer_payment_question(text: str) -> bool:
    return _has(text, _DEFER_PAYMENT_CUES) and _has(text, _DEFER_PERIOD_CUES)


def _is_cash_payment_question(text: str) -> bool:
    return RULES.has(text, "payment_mode_cash") and _has(text, _PAYMENT_METHOD_QUESTION_CUES)


def _is_unmapped_payment_question(text: str) -> bool:
    return _has(text, _PAYMENT_TERMS) and _has(text, _QUESTION_CUES)


def _cannot_pay_earlier(text: str) -> bool:
    normalized = text.casefold().replace("’", "'")
    return bool(re.search(
        r"\b(?:i\s+)?(?:cannot|can't|won't|will not|am not able|not able|unable|"
        r"not going to be able|will be unable)\b"
        r"(?:\s+[a-z']+){0,10}\s+\b(?:pay|payment|make it)\b"
        r"(?:\s+[a-z']+){0,5}\s+\b(?:earlier|early|sooner)\b",
        normalized,
    )) or bool(re.search(
        r"\b(?:earlier|early|sooner)\b[^.!?]{0,50}\b(?:cannot|can't|won't|will not|not able|unable)\b",
        normalized,
    ))


def _can_pay_earlier(text: str) -> bool:
    normalized = text.casefold().replace("’", "'")
    if _cannot_pay_earlier(normalized):
        return False
    return bool(re.search(
        r"\b(?:i can|i could|yes,? i can|able to)\b[^.!?]{0,45}\b(?:pay|payment|make it)\b"
        r"[^.!?]{0,35}\b(?:earlier|sooner)\b",
        normalized,
    )) or bool(re.search(r"\b(?:yes|yeah|yep)\b[^.!?]{0,25}\b(?:earlier|sooner)\b", normalized))


def _is_payment_purpose_question(text: str) -> bool:
    return _has(text, _PAYMENT_PURPOSE_QUESTION)


def _is_interest_concern(text: str) -> bool:
    return _has(text.casefold(), _INTEREST_CONCERN) or bool(_INTEREST_CONCERN_CUE.search(text))


def _trace_policy(session: CallSession, rule: str, status: str, explanation: str) -> None:
    """Attach a plain-language audit trail for the rule actually evaluated or selected."""
    trace = session.scratch.setdefault("decision_trace", [])
    trace.append({"rule": rule, "status": status, "explanation": explanation,
                  "ruleset_version": business_rule_engine.version})


def _sync_pending_question(session: CallSession) -> None:
    """Persist the active question and the answer classes accepted for that slot."""
    state = session.pending
    if not state:
        session.scratch.pop("pending_question", None)
        return
    question_type, accepted = _PENDING_QUESTION_CONTRACTS.get(
        state, (state, ["answer", "question", "unclear"])
    )
    current = session.scratch.get("pending_question")
    if not isinstance(current, dict) or current.get("state") != state:
        session.scratch["pending_question"] = {
            "state": state,
            "question_type": question_type,
            "accepted_response_classes": list(accepted),
        }


def pending_question_context(session: CallSession) -> dict[str, object]:
    _sync_pending_question(session)
    return dict(session.scratch.get("pending_question") or {})


def _last_agent_asked_expected_payment_date(session: CallSession) -> bool:
    history = session.scratch.get("dialogue_history", [])
    latest_agent = next((item for item in reversed(history) if item.get("role") == "assistant"), None)
    content = str((latest_agent or {}).get("content") or "").casefold()
    return any(phrase in content for phrase in (
        "when do you expect to pay", "when do you expect to make the payment",
        "by when will you pay", "when can you make the payment",
    ))


def contextualize_pending_answer(session: CallSession, transcript: str, extracted: dict | None) -> dict | None:
    """Use the active question to disambiguate short answers before scope fallback."""
    _sync_pending_question(session)
    if session.pending != "refusal_reason" or not extracted:
        return extracted
    text = transcript.casefold().strip().strip(".!?, ")
    words = re.findall(r"[a-z]+|[\u0900-\u097f]+", text)
    intent = extracted.get("intent")
    if intent in _PENDING_SLOT_INTENTS and not (
        len(words) <= 3 and _has(text, _REFUSAL_REASON_CUES)
        and intent in {"other_product", "greeting", "unclear"}
    ):
        return extracted
    if len(words) <= 5 and (_has(text, _REFUSAL_REASON_CUES) or extracted.get("dialogue_act") == "answers_pending"):
        updated = dict(extracted)
        updated.update({
            "intent": "unclear",
            "dialogue_act": "answers_pending",
            "pending_slot_status": "provided",
            "summary": "The caller is answering the question about why they do not want to pay.",
            "acknowledgment": "I understand there is a concern.",
        })
        return updated
    return extracted


def _customer_balance_estimate(text: str) -> int | None:
    """Extract an explicitly customer-stated balance estimate, never bank data."""
    match = RULES.pattern_search("customer_balance_estimate", text.casefold())
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def fallback_interpretation(
    transcript: str,
    pending_state: str | None = None,
    reference_date: str | None = None,
    fast_extracted: dict | None = None,
) -> dict:
    """Conservative local interpretation used after an LLM parse or network error.

    It preserves explicit safety requests and payment facts without inventing an
    intent from ambiguous speech. The policy still decides all actions.
    """
    text = transcript.casefold().strip()
    normalized = re.sub(r"[^a-z\u0900-\u097f]+", " ", text).strip()
    result = {
        "intent": "unclear", "intent_confidence": "low", "amount_inr": None,
        "date_iso": None, "payment_mode": None, "summary": "The caller’s meaning could not be confirmed locally.",
        "dialogue_act": "no_clear_act", "pending_slot_status": "unclear",
        "date_precision": "none", "date_phrase": None, "identity_status": "unclear",
        "acknowledgment": "",
    }
    if fast_extracted:
        result.update(fast_extracted)

    explicit_date = _date(text)
    relative_days = {
        "day before yesterday": -2, "yesterday": -1, "today": 0,
        "tomorrow": 1, "day after tomorrow": 2,
    }
    relative_phrase = next((phrase for phrase in relative_days if phrase in text), None)
    if explicit_date:
        result.update(date_iso=explicit_date, date_precision="exact", date_phrase=transcript.strip()[:80])
    elif relative_phrase:
        try:
            ref = date.fromisoformat(reference_date) if reference_date else datetime.now(timezone.utc).date()
            result.update(date_iso=(ref + timedelta(days=relative_days[relative_phrase])).isoformat(),
                          date_precision="exact", date_phrase=relative_phrase)
        except ValueError:
            pass
    elif RULES.pattern_search("approximate_payment_date", text):
        result.update(date_iso=None, date_precision="approximate", date_phrase=transcript.strip()[:80])

    mode = _mode(text)
    if mode:
        result["payment_mode"] = mode

    # Highest-priority caller instructions are locally recognizable and should
    # survive a broken model response.
    if _has(text, _OPT_OUT):
        intent, summary = "opt_out", "The caller requested no further collection calls."
    elif _has(text, _DISTRESS):
        intent, summary = "distress", "The caller reported hardship or a medical emergency."
    elif _has(text, _ABUSE):
        intent, summary = "abuse", "The caller used abusive language."
    elif _has(text, _DISPUTE):
        intent, summary = "dispute", "The caller disputed the account or debt."
    elif _has(text, _PAYMENT_REFUSAL):
        intent, summary = "payment_refusal", "The caller does not want to pay."
    elif _has(text, _NOT_PAID):
        intent, summary = "payment_not_made", "The caller has not made the payment yet."
    elif _has(text, _WAIVER):
        intent, summary = "waiver", "The caller requested a fee waiver or discount."
    elif _has(text, _PAYMENT_LINK):
        intent, summary = "payment_link_request", "The caller requested a payment link."
    elif _has(text, _PAID) or (pending_state in {"paid_date", "paid_mode", "paid_most_recent_date", "paid_most_recent_mode"} and (explicit_date or relative_phrase or mode)):
        intent, summary = "already_paid", "The caller reports a payment and supplied locally recognized details."
    elif pending_state == "identity_confirmation" and (_is_clear_yes(text) or normalized in {"you are", "yes you are", "yeah you are", "haan", "han", "हाँ", "हां", "जी"}):
        intent, summary = "unclear", "The caller affirmed the named identity question."
        result["identity_status"] = "confirmed"
    elif pending_state == "identity_confirmation" and _is_clear_no(text):
        intent, summary = "unclear", "The caller declined the named identity question."
        result["identity_status"] = "not_confirmed"
    elif pending_state == "paid_most_recent_confirmation" and _is_clear_yes(text):
        intent, summary = "already_paid", "The caller confirmed this was the most recent payment."
    elif pending_state == "paid_most_recent_confirmation" and _is_clear_no(text):
        intent, summary = "already_paid", "The caller said there was a more recent payment."
    elif pending_state == "paid_most_recent_confirmation" and _has(text, _UNCERTAIN_CONFIRMATION):
        intent, summary = "already_paid", "The caller is unsure whether this was the most recent payment."
    elif _has(text, _OTP_QUESTION):
        intent, summary = "otp_request", "The caller asked about an OTP."
    elif _is_customer_balance_request(text):
        intent, summary = "balance_question", "The caller explicitly asked about their balance."
    elif pending_state == "refusal_reason" and (len(normalized.split()) <= 5 or _has(text, _REFUSAL_REASON_CUES)):
        intent, summary = "unclear", "The caller is answering why they do not want to pay."
        result["dialogue_act"] = "answers_pending"
        result["pending_slot_status"] = "provided"
    else:
        intent, summary = result["intent"], result["summary"]

    result["intent"] = intent
    result["summary"] = summary
    if intent != "unclear":
        result["intent_confidence"] = "high"
        result["dialogue_act"] = "answers_pending" if pending_state else "new_request"
        result["pending_slot_status"] = "provided" if pending_state else "not_applicable"
    if intent == "already_paid" and result["date_precision"] == "none" and re.search(r"\b(?:about|around|roughly|a few|several|six or seven|one week|a week)\b.{0,35}\b(?:day|days|week|weeks|ago)\b", text):
        result["date_precision"] = "approximate"
        result["date_phrase"] = transcript.strip()[:80]
    if pending_state == "callback_time" and (explicit_date or relative_phrase or re.search(r"\b(?:morning|afternoon|evening|at \d)\b", text)):
        result["intent"] = "callback"
        result["intent_confidence"] = "high"
        result["dialogue_act"] = "answers_pending"
        result["pending_slot_status"] = "provided"
    return result


def _record_waiver_request(session: CallSession, transcript: str) -> TurnResponse:
    task = create_followup_task(session, "waiver_request", transcript, "normal")
    session.outcome = Outcome(
        type=OutcomeType.WAIVER_REQUEST,
        fields={"reason": transcript[:500], "agent_task_id": task["task_id"]},
        follow_up_required=True,
        follow_up_reason="human_review_waiver_request",
    )
    session.pending = None
    session.terminal = True
    return TurnResponse(session_id=session.session_id,
                        bot_text="I can’t approve late-fee discounts or waivers. I’ll note your request, and a human agent will call you back.",
                        terminal=True, outcome=session.outcome)


def _record_dispute(session: CallSession, transcript: str) -> TurnResponse:
    task = create_followup_task(session, "customer_disputes_debt", transcript, "high")
    session.outcome = Outcome(
        type=OutcomeType.DISPUTE_TRANSFER,
        fields={"reason": "customer_disputes_debt", "summary": transcript[:500], "agent_task_id": task["task_id"]},
        follow_up_required=True,
        follow_up_reason="human_review_dispute",
    )
    session.terminal = True
    return TurnResponse(session_id=session.session_id,
                        bot_text="I’m sorry this is causing concern. I’ve noted what you’ve told me, and the team will look into it. I’ll pause the payment discussion and ask a human colleague to follow up.",
                        terminal=True, outcome=session.outcome)


def _record_callback_request(session: CallSession, transcript: str, normalized_text: str | None = None) -> TurnResponse:
    callback_date = _date(normalized_text or transcript)
    task = create_followup_task(session, "customer_requested_callback", transcript, "normal", transcript[:200])
    session.outcome = Outcome(
        type=OutcomeType.CALLBACK_REQUEST,
        fields={"requested_time_text": transcript[:200], "requested_date": callback_date, "agent_task_id": task["task_id"]},
        follow_up_required=True,
        follow_up_reason="customer_requested_callback",
    )
    session.pending = None
    session.terminal = True
    return TurnResponse(session_id=session.session_id,
                        bot_text="Thanks. I’ve passed your preferred callback time to our team.",
                        terminal=True, outcome=session.outcome)


def _record_far_future_follow_up(
    session: CallSession, transcript: str, reason: str | None = None
) -> TurnResponse:
    date_phrase = str(session.scratch.get("ptp_proposed_date_text") or "an upcoming date")
    cannot_pay_earlier = _cannot_pay_earlier(transcript)
    reason = reason or ("cannot pay earlier" if cannot_pay_earlier else "human review requested")
    details = (
        f"Customer expects to pay by {date_phrase}; reason for human follow-up: {reason}. "
        f"Latest statement: {transcript[:300]}"
    )
    task = create_followup_task(session, "far_future_payment_commitment", details, "normal")
    session.outcome = Outcome(
        type=OutcomeType.NO_COMMITMENT,
        fields={
            "reason": "far_future_payment_needs_human_discussion",
            "expected_payment_date_text": date_phrase,
            "agent_task_id": task["task_id"],
        },
        follow_up_required=True,
        follow_up_reason="far_future_payment_needs_human_discussion",
    )
    session.pending = None
    session.terminal = True
    session.scratch["ptp_far_future_active"] = False
    _trace_policy(
        session,
        "Far-future payment follow-up",
        "human follow-up recorded",
            f"The original date was preserved and the bot stopped asking for it. Follow-up reason: {reason}.",
    )
    return TurnResponse(
        session_id=session.session_id,
        bot_text=(f"I’ve noted that you expect to pay by {date_phrase}. "
                  f"{'I understand you can’t pay earlier. ' if cannot_pay_earlier else ''}"
                  "I’ll ask a colleague to call and discuss the options, so you don’t need to repeat the date. "
                  "That’s all I need for now. Thank you for your time."),
        terminal=True,
        outcome=session.outcome,
    )


def _resolve_far_future_payment(
    session: CallSession,
    transcript: str,
    original_text: str,
    extracted: dict | None,
) -> TurnResponse | None:
    """Resolve the entire far-future PTP branch before generic intent handling.

    The saved proposed date is the anchor for this scenario. A classifier label
    or a stale pending slot must not erase it and send the customer back to a
    generic date question.
    """
    saved_iso = session.scratch.get("ptp_far_future_date_iso")
    active = bool(session.scratch.get("ptp_far_future_active")) or (
        bool(saved_iso) and session.pending in {"ptp", "ptp_far_future_choice"}
    )
    if not active or not saved_iso or not session.scratch.get("right_party_confirmed"):
        return None

    # Let separate servicing intents run without losing this context.
    intent = (extracted or {}).get("intent")
    if (
        (intent == "balance_question" and _is_customer_balance_request(original_text))
        or intent in {"interest_question", "fee_question", "fee_applicability",
                   "payment_link_request", "waiver", "dispute", "abuse", "distress", "opt_out"}
        or _is_customer_balance_request(original_text)
        or _has(original_text, _INTEREST + _FEE + _PAYMENT_LINK + _WAIVER + _DISPUTE)
    ):
        return None

    saved_date = datetime.fromisoformat(saved_iso).date()
    proposed_date = (
        _date(original_text) or _month_year_date(original_text)
        or _exact_iso_calendar_date((extracted or {}).get("date_iso"))
    )
    same_saved_date = proposed_date == saved_iso
    normalized = original_text.casefold()
    callback_request = _has(original_text, _CALLBACK) or (
        intent == "callback" or ("colleague" in normalized
        and any(word in normalized for word in ("call", "speak", "talk")))
    )

    if _cannot_pay_earlier(original_text) or callback_request or same_saved_date:
        session.scratch["ptp_far_future_active"] = False
        _trace_policy(
            session,
            "Far-future payment resolution",
            "human follow-up recorded",
            "The saved date was retained. The caller cannot pay sooner, requested a colleague, or reaffirmed the far-future date, so the bot records follow-up instead of asking for the date again.",
        )
        reason = (
            "cannot pay earlier" if _cannot_pay_earlier(original_text)
            else "customer requested a colleague" if callback_request
            else "customer reaffirmed the far-future date"
        )
        return _record_far_future_follow_up(session, transcript, reason)

    if proposed_date:
        proposed_day = datetime.fromisoformat(proposed_date).date()
        if proposed_day < date.today():
            session.pending = "ptp_far_future_choice"
            return _reply(session, "That date has already passed. Is there a future date you could pay earlier, or should I ask a colleague to call you?")
        too_far = business_rule_engine.commitment_is_too_far((proposed_day - date.today()).days)
        if proposed_day < saved_date and not too_far:
            session.scratch["ptp_date"] = proposed_date
            session.scratch["ptp_date_text"] = str((extracted or {}).get("date_phrase") or transcript[:100])
            session.scratch["ptp_far_future_active"] = False
            session.scratch.pop("ptp_earlier_date_requested", None)
            session.pending = "ptp_confirmation"
            date_label = proposed_day.strftime("%d %B").lstrip("0")
            return _reply(session, f"You expect to make the payment by {date_label}. Have I got that right?")
        if proposed_day >= saved_date or too_far:
            session.scratch["ptp_far_future_active"] = False
            return _record_far_future_follow_up(session, transcript, "no earlier date could be confirmed")

    if _can_pay_earlier(original_text) or _is_clear_yes(original_text):
        session.pending = "ptp_far_future_choice"
        session.scratch["ptp_earlier_date_requested"] = True
        session.scratch["ptp_far_future_clarification_attempts"] = 0
        return _reply(session, "Okay. What earlier date should I note for your payment?")

    if _is_clear_no(original_text):
        session.scratch["ptp_far_future_active"] = False
        return _record_far_future_follow_up(session, transcript)

    if (extracted or {}).get("dialogue_act") == "asks_question":
        return _reply(session, "I’m asking whether you can pay before the date you gave. If you can’t, I can ask a colleague to call and discuss options.")

    attempts = int(session.scratch.get("ptp_far_future_clarification_attempts", 0)) + 1
    session.scratch["ptp_far_future_clarification_attempts"] = attempts
    session.pending = "ptp_far_future_choice"
    if attempts >= 2:
        session.scratch["ptp_far_future_active"] = False
        return _record_far_future_follow_up(session, transcript)
    session.scratch["suppress_acknowledgment"] = True
    return _reply(session, "I’ve noted the date you gave. Can you pay earlier, or should I ask a colleague to call you?")


def _record_payment_link_request(session: CallSession, transcript: str) -> TurnResponse:
    task = create_followup_task(session, "payment_link_request", transcript, "normal")
    session.outcome = Outcome(
        type=OutcomeType.PAYMENT_LINK_REQUEST,
        fields={"reason": "customer_requested_payment_link", "agent_task_id": task["task_id"]},
        follow_up_required=True,
        follow_up_reason="payment_link_request",
    )
    session.pending = None
    session.terminal = True
    return TurnResponse(
        session_id=session.session_id,
        bot_text="I’ve noted your request for a payment link. A colleague will call you back about it.",
        terminal=True,
        outcome=session.outcome,
    )


def _normalize_customer_amount(value: object) -> str | None:
    """Normalize an amount explicitly supplied in the active PTP amount step."""
    if value is None:
        return None
    raw = str(value).strip().replace(",", "")
    raw = re.sub(r"^(?:₹|INR|Rs\.?|rupees?)\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*(?:INR|Rs\.?|rupees?)$", "", raw, flags=re.IGNORECASE)
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return format(amount.normalize(), "f")


def _amount_json_number(value: str | None) -> int | float | None:
    """Keep collected payment amounts numeric in structured outcomes."""
    if value is None:
        return None
    amount = Decimal(value)
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _format_inr_amount(value: object) -> str:
    amount = _normalize_customer_amount(value)
    if amount is None:
        return "the verified minimum due"
    decimal_amount = Decimal(amount)
    if decimal_amount == decimal_amount.to_integral_value():
        return f"₹{int(decimal_amount):,}"
    return f"₹{decimal_amount:,.2f}"


def _finish_ptp_amount(session: CallSession, amount: str | None) -> TurnResponse:
    pay_date = session.scratch.get("ptp_date")
    fields: dict[str, object] = {
        "date": pay_date,
        "amount": _amount_json_number(amount),
        "currency": "INR",
        "amount_status": "customer_provided" if amount is not None else "not_provided",
    }
    session.outcome = Outcome(type=OutcomeType.PROMISE_TO_PAY, fields=fields)
    session.scratch.pop("ptp_amount_after_otp", None)
    session.pending = None
    session.terminal = True
    amount_note = (
        f" I’ve noted ₹{amount} as the amount you plan to pay."
        if amount is not None
        else ""
    )
    date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date you gave"
    return TurnResponse(
        session_id=session.session_id,
        bot_text=(f"Thank you. I’ve recorded your payment commitment for {date_label}."
                  f"{amount_note} That’s all the information I needed, so I’ll end the call now. Goodbye."),
        terminal=True,
        outcome=session.outcome,
    )


def _record_ptp_amount_callback(session: CallSession, transcript: str) -> TurnResponse:
    """Save the confirmed payment date and arrange human follow-up on amount."""
    pay_date = session.scratch.get("ptp_date")
    date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date you confirmed"
    task = create_followup_task(
        session,
        "ptp_amount_follow_up",
        f"Customer confirmed a payment date of {pay_date or 'not recorded'} but needs more time to confirm the amount. Caller said: {transcript[:300]}",
        "normal",
    )
    session.outcome = Outcome(
        type=OutcomeType.CALLBACK_REQUEST,
        fields={
            "commitment_date": pay_date,
            "amount": None,
            "currency": "INR",
            "reason": "customer_needs_more_time_to_confirm_amount",
            "requested_time_text": None,
            "agent_task_id": task["task_id"],
        },
        follow_up_required=True,
        follow_up_reason="ptp_amount_follow_up",
    )
    session.pending = None
    session.terminal = True
    return TurnResponse(
        session_id=session.session_id,
        bot_text=(f"That’s okay. I’ve recorded your expected payment date as {date_label}. "
                  "I’ll arrange for a colleague to call you about the amount. Thank you for confirming the date. Goodbye."),
        terminal=True,
        outcome=session.outcome,
    )


def _record_payment_question_follow_up(session: CallSession, transcript: str, question_type: str) -> TurnResponse:
    task = create_followup_task(
        session,
        "payment_policy_question",
        f"Customer asked about {question_type}. Caller’s question: {transcript[:400]}",
        "normal",
    )
    session.outcome = Outcome(
        type=OutcomeType.NO_COMMITMENT,
        fields={"reason": "payment_policy_not_available_to_bot", "question_type": question_type, "agent_task_id": task["task_id"]},
        follow_up_required=True,
        follow_up_reason="payment_policy_question",
    )
    session.pending = None
    session.terminal = True
    reply = (
        "Thanks. I’ve noted your concern about the interest rate, and a human colleague will call you back."
        if question_type == "interest rate concern"
        else "I don’t want to give you incorrect information. I’ve noted your question, and a colleague will look into it and call you back."
    )
    return TurnResponse(
        session_id=session.session_id,
        bot_text=reply,
        terminal=True,
        outcome=session.outcome,
    )


def _start_balance_verification(session: CallSession, transcript: str) -> TurnResponse:
    """Start OTP verification as the direct next step for an explicit balance request."""
    _trace_policy(session, "Account-information verification", "triggered", "The customer explicitly asked for the bank-recorded balance; OTP verification is the next action before disclosure.")
    if session.scratch.get("balance_verified"):
        if session.scratch.get("ptp_amount_after_otp"):
            session.scratch.pop("ptp_amount_after_otp", None)
            session.pending = "ptp_amount"
            due = session.scratch.get("verified_minimum_due")
            pay_date = session.scratch.get("ptp_date")
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date you gave"
            due_text = f"Your verified minimum due is {_format_inr_amount(due)}. " if due else "I’ve already checked the bank-recorded minimum due. "
            return _reply(session, f"{due_text}What amount would you like me to note for your payment on {date_label}?")
        return _reply(session, "Your balance was already checked earlier in this call. Is there anything about the balance or minimum due you’d like me to clarify?")
    try:
        challenge = bank_services.issue_otp(session.request.customer_id, session.request.account_id,
                                            session.request.contact_point_id)
    except ValueError:
        task = create_followup_task(session, "balance_verification_unavailable", transcript, "normal")
        session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT,
                                 fields={"reason": "balance_verification_unavailable", "agent_task_id": task["task_id"]},
                                 follow_up_required=True, follow_up_reason="human_follow_up_needed")
        session.terminal = True
        return TurnResponse(session_id=session.session_id,
                            bot_text="I’m unable to verify the account through the bank service. I’ve noted your request, and the team will look into it and call you back.",
                            terminal=True, outcome=session.outcome)
    session.pending = "otp_code"
    session.scratch["otp_challenge_id"] = challenge["challenge_id"]
    return TurnResponse(session_id=session.session_id,
                        bot_text="I can check that for you. I’ve sent a six-digit verification code to your registered contact. Please enter it in the verification field on the screen; don’t say the code aloud.",
                        metadata={"otp_challenge_id": challenge["challenge_id"], "expires_at": challenge["expires_at"]})
def _date(text: str) -> str | None:
    weekday_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    previous_weekday = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.IGNORECASE)
    if previous_weekday:
        today = datetime.now(timezone.utc).date()
        target = weekday_names[previous_weekday.group(1).lower()]
        days_back = (today.weekday() - target) % 7 or 7
        return (today - timedelta(days=days_back)).isoformat()
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        try:
            return datetime.fromisoformat(iso.group(1)).date().isoformat()
        except ValueError:
            return None
    numeric = re.search(r"\b([0-3]?\d)[/-]([01]?\d)(?:[/-](20\d{2}))?\b", text)
    if numeric:
        year = int(numeric.group(3) or datetime.now(timezone.utc).year)
        try:
            return datetime(year, int(numeric.group(2)), int(numeric.group(1))).date().isoformat()
        except ValueError:
            return None
    month_numbers = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    ordinals = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
        "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
        "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
        "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
        "twentieth": 20, "twenty-first": 21, "twenty second": 22, "twenty-second": 22,
        "twenty-third": 23, "twenty third": 23, "twenty-fourth": 24, "twenty fourth": 24,
        "twenty-fifth": 25, "twenty fifth": 25, "twenty-sixth": 26, "twenty sixth": 26,
        "twenty-seventh": 27, "twenty seventh": 27, "twenty-eighth": 28, "twenty eighth": 28,
        "twenty-ninth": 29, "twenty ninth": 29, "thirtieth": 30, "thirty-first": 31,
        "thirty first": 31,
    }
    day_token = r"(?P<day>\d{1,2}(?:st|nd|rd|th)?|[a-z]+(?:[- ][a-z]+)?)"
    month_pattern = "|".join(month_numbers)
    named = re.search(rf"\b(?P<month>{month_pattern})\s+{day_token}(?:,?\s+(?P<year>20\d{{2}}))?\b", text, re.IGNORECASE)
    if named:
        month, day_text, year_text = named.group("month").lower(), named.group("day").lower(), named.group("year")
        day = int(re.match(r"\d+", day_text).group()) if re.match(r"\d+", day_text) else ordinals.get(day_text)
        if day is None:
            return None
        year = int(year_text) if year_text else datetime.now(timezone.utc).year
        try:
            return datetime(year, month_numbers[month], day).date().isoformat()
        except ValueError:
            return None
    named = re.search(rf"\b{day_token}\s+(?P<month>{month_pattern})(?:,?\s+(?P<year>20\d{{2}}))?\b", text, re.IGNORECASE)
    if named:
        day_text, month, year_text = named.group("day").lower(), named.group("month").lower(), named.group("year")
        day = int(re.match(r"\d+", day_text).group()) if re.match(r"\d+", day_text) else ordinals.get(day_text)
        if day is None:
            return None
        year = int(year_text) if year_text else datetime.now(timezone.utc).year
        try:
            return datetime(year, month_numbers[month], day).date().isoformat()
        except ValueError:
            return None
    return None


def _month_year_date(text: str) -> str | None:
    """Return a month anchor for horizon checks, never as an exact commitment date."""
    months = {
        "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
        "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
        "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    }
    month_pattern = "|".join(sorted(months, key=len, reverse=True))
    match = re.search(rf"\b(?P<month>{month_pattern})\.?\s+(?P<year>20\d{{2}})\b", text, re.IGNORECASE)
    if not match:
        return None
    month = months[match.group("month").casefold()]
    return datetime(int(match.group("year")), month, 1).date().isoformat()


def _exact_iso_calendar_date(value: object) -> str | None:
    """Accept only a complete, valid YYYY-MM-DD date from model extraction.

    Some model responses encode a month-only answer as ``YYYY-MM``. That is a
    useful timing hint, but it must never reach ``fromisoformat`` as if it were
    an exact calendar date.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _month_year_phrase(text: str) -> str | None:
    match = re.search(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+20\d{2}\b",
        text,
        re.IGNORECASE,
    )
    return match.group(0).replace(".", "").title() if match else None


def _mode(text: str) -> str | None:
    for group, mode in (("payment_mode_upi", "UPI"), ("payment_mode_net_banking", "net_banking"),
                        ("payment_mode_imps", "IMPS"), ("payment_mode_neft", "NEFT"),
                        ("payment_mode_cheque", "cheque"), ("payment_mode_cash", "cash"),
                        ("payment_mode_card", "card"), ("payment_mode_autopay", "autopay")):
        if RULES.has(text, group):
            return mode
    return None


def _record_paid_for_manual_reconciliation(session: CallSession, transcript: str) -> TurnResponse:
    timing = session.scratch.get("reported_payment_date_text")
    mode = session.scratch.get("reported_payment_mode")
    details = "Customer reports a payment but could not provide an exact calendar date"
    if timing:
        details += f"; approximate timing reported: {timing}"
    if not mode:
        details += " and payment mode was not confirmed"
    details += f"; latest response: {transcript[:120]}"
    task = create_followup_task(session, "payment_reconciliation_review", details, "normal")
    fields = {
        "verification_status": "customer_reported",
        "exact_date_provided": False,
        "agent_task_id": task["task_id"],
    }
    if timing:
        fields["reported_payment_date_text"] = timing
    if mode:
        fields["reported_payment_mode"] = mode
    session.outcome = Outcome(
        type=OutcomeType.ALREADY_PAID_REPORTED,
        fields=fields,
        follow_up_required=True,
        follow_up_reason="payment_reconciliation_review",
    )
    session.pending = None
    session.terminal = True
    return TurnResponse(
        session_id=session.session_id,
        bot_text="No problem. I’ve noted that you made a payment, and I’ve asked our team to check the payment records and get back to you. That’s all the information I needed, so I’ll end the call now. Goodbye.",
        terminal=True,
        outcome=session.outcome,
    )


def _payment_age_days(paid_date: str) -> int | None:
    try:
        return (datetime.now(timezone.utc).date() - date.fromisoformat(paid_date)).days
    except (TypeError, ValueError):
        return None


def _is_uncertain_confirmation(text: str, extracted: dict | None) -> bool:
    confidence = (extracted or {}).get("intent_confidence")
    dialogue_act = (extracted or {}).get("dialogue_act")
    return (
        _has(text, _UNCERTAIN_CONFIRMATION)
        or confidence in {"medium", "low"}
        or dialogue_act == "cannot_provide"
        or (extracted or {}).get("pending_slot_status") == "cannot_provide"
    )


def _record_old_payment_for_review(session: CallSession, most_recent_status: str) -> TurnResponse:
    paid_date = session.scratch.get("reported_payment_date") or session.scratch.get("older_payment_date")
    mode = session.scratch.get("reported_payment_mode")
    date_detail = f"dated {paid_date}" if paid_date else "with no date provided"
    summary = f"Customer reported a payment {date_detail}; most-recent status: {most_recent_status}"
    summary += f"; payment mode: {mode}." if mode else "; payment mode was not confirmed."
    task = create_followup_task(session, "payment_reconciliation_review", summary, "normal")
    fields = {
        "verification_status": "customer_reported",
        "most_recent_payment_status": most_recent_status,
        "agent_task_id": task["task_id"],
    }
    if paid_date:
        fields["reported_payment_date"] = paid_date
    if mode:
        fields["reported_payment_mode"] = mode
    session.outcome = Outcome(
        type=OutcomeType.ALREADY_PAID_REPORTED,
        fields=fields,
        follow_up_required=True,
        follow_up_reason="payment_reconciliation_review",
    )
    session.pending = None
    session.terminal = True
    mode_text = f" via {mode.replace('_', ' ')}" if mode else ""
    return TurnResponse(
        session_id=session.session_id,
        bot_text=(f"Thank you. I’ve noted the payment details{mode_text}. "
                  "I’ll share this with a human colleague to check and get back to you. "
                  "That’s all the information I needed, so I’ll end the call now. Goodbye."),
        terminal=True,
        outcome=session.outcome,
    )


def _continue_reported_payment(session: CallSession, paid_date: str, mode: str | None, *, most_recent_confirmed: bool = False) -> TurnResponse:
    age_days = _payment_age_days(paid_date)
    if age_days is not None and age_days < 0:
        session.pending = "paid_date"
        return _reply(session, "That date appears to be in the future. What date did you make the payment?")

    session.scratch["reported_payment_date"] = paid_date
    if mode:
        session.scratch["reported_payment_mode"] = mode
    if business_rule_engine.rules and business_rule_engine.rules.thresholds and business_rule_engine.payment_age_band(age_days) == "old_review":
        if most_recent_confirmed:
            if mode:
                _trace_policy(session, "Old most-recent payment review", "triggered", f"The caller supplied the most recent payment date and mode, but the date is more than {OLD_PAYMENT_REVIEW_DAYS} days old; a human colleague will review it.")
                return _record_old_payment_for_review(session, "confirmed")
            session.pending = "paid_most_recent_mode"
            return _reply(session, "Which payment mode did you use for that most recent payment?")
        session.pending = "paid_most_recent_confirmation"
        _trace_policy(session, "Most-recent payment check", "triggered", f"The reported payment is more than {OLD_PAYMENT_REVIEW_DAYS} days old; the bot asks whether it is the most recent payment.")
        return _reply(session, f"That payment was more than {OLD_PAYMENT_REVIEW_DAYS} days ago. Is it the most recent payment you made?")
    if business_rule_engine.payment_age_band(age_days) == "recent":
        _trace_policy(session, "Recent payment processing window", "selected", f"The reported payment is within {RECENT_PAYMENT_DAYS} days; if the ledger has not updated, the bot explains the {REFLECTION_WORKING_DAYS}-working-day posting window without raising an immediate reconciliation task.")
    elif age_days is not None:
        _trace_policy(session, "Payment reconciliation window", "selected", f"The reported payment is more than {RECENT_PAYMENT_DAYS} and no more than {OLD_PAYMENT_REVIEW_DAYS} days old; an unconfirmed ledger entry is referred to a human agent.")
    if not mode:
        session.pending = "paid_mode"
        return _reply(session, "Thank you. Which payment mode did you use—UPI, net banking, cheque, or another method?")
    return _finish_paid(session, paid_date, mode)


def process_turn(
    session: CallSession,
    transcript: str,
    extracted: dict | None = None,
    *,
    heard_before_opening: bool = False,
    stt_confidence: float | None = None,
    speech_evidence: bool | None = None,
    reference_date: str | None = None,
) -> TurnResponse:
    """Conservative rule-based starter. Critical actions are policy-ordered."""
    session.scratch["decision_trace"] = []
    session.scratch.pop("suppress_acknowledgment", None)
    _sync_pending_question(session)
    extracted = contextualize_pending_answer(session, transcript, extracted)
    text = transcript.casefold().strip()
    original_text = text
    broad_date_window = _broad_date_window(original_text)
    acoustic_utterance_untrusted = speech_evidence is False
    # A one-word identity confirmation can be genuine speech even when the
    # browser's pitch-periodicity gate is uncertain. Require one independent
    # repeat before accepting it in that case: a single transient/noise
    # hallucination must not unlock account details, but repeated clear “yes”
    # answers should not be trapped in the same clarification loop.
    weak_identity_yes = (
        session.pending == "identity_confirmation"
        and _is_clear_yes(original_text)
    )
    if session.scratch.get("weak_identity_yes_retry") and not weak_identity_yes:
        session.scratch.pop("weak_identity_yes_retry", None)
    if (acoustic_utterance_untrusted and weak_identity_yes
            and session.scratch.get("weak_identity_yes_retry") is True):
        acoustic_utterance_untrusted = False
    if acoustic_utterance_untrusted:
        session.turn_count += 1
        session.scratch["suppress_acknowledgment"] = True
        _trace_policy(
            session,
            "Acoustic speech check",
            "uncertain; clarification required",
            "The browser detected little voiced-speech evidence in this audio, so its transcript is not used to change identity or payment state.",
        )
        if session.pending == "identity_confirmation":
            session.scratch["awaiting_identity_confirmation"] = True
            session.scratch["identity_wait_prompt_given"] = True
            contact_name = " ".join(part.strip() for part in (session.request.first_name, session.request.last_name) if part and part.strip()) or "the account holder"
            if weak_identity_yes:
                session.scratch["weak_identity_yes_retry"] = True
                return _reply(
                    session,
                    f"I heard you say yes, but the audio was unclear. For security, please say ‘Yes, I am {contact_name}’ once more.",
                )
            return _reply(session, f"I couldn’t make out a clear spoken answer. Are you {contact_name}?")
        return _reply(session, _low_signal_clarification(session))
    if (
        broad_date_window
        and session.pending is None
        and session.scratch.get("right_party_confirmed")
        and _last_agent_asked_expected_payment_date(session)
        and not _has(original_text, _PAID + _NOT_PAID + _PAYMENT_REFUSAL)
        and not _is_defer_payment_question(original_text)
    ):
        # The opening payment menu asks when the customer expects to pay but
        # does not create a named pending slot. Reconstruct that slot from the
        # last agent question so an answer such as “next week” stays in context.
        session.pending = "ptp"
        _sync_pending_question(session)
    approximate_payment_date = bool(extracted and extracted.get("date_precision") == "approximate")
    commitment_intent_uncertain = False
    balance_check_consented = False
    explicit_balance_info_request = _is_customer_balance_request(original_text)
    if explicit_balance_info_request and session.scratch.get("right_party_confirmed"):
        extracted = dict(extracted or {})
        extracted.update({
            "intent": "balance_question",
            "intent_confidence": "high",
            "dialogue_act": "asks_question",
            "summary": "The caller explicitly requested their account balance.",
            "acknowledgment": "You’re asking for your account balance.",
        })
        text += " what is my balance"
    elif _customer_balance_estimate(original_text) is not None and session.scratch.get("right_party_confirmed"):
        # A stated estimate in response to the fee threshold is not a request
        # to disclose the bank-recorded balance and must not trigger OTP alone.
        extracted = dict(extracted or {})
        extracted.update({
            "intent": "fee_applicability",
            "intent_confidence": "high",
            "dialogue_act": "corrects_previous",
            "summary": "The caller supplied an unverified estimate of their balance in response to the late-fee threshold.",
        })
    # A requested identity explanation takes precedence over a generic positive
    # classifier label (for example, “Haan, but tell me first who you are”).
    if session.pending == "identity_confirmation" and _has(original_text, _IDENTITY_INFO_QUESTION):
        extracted = dict(extracted or {})
        extracted.update({
            "intent": "unclear", "intent_confidence": "high",
            "dialogue_act": "asks_question", "identity_status": "unclear",
            "summary": "The caller asked who is calling before confirming identity.",
        })
    # Treat a past weekday offered as a future commitment as a date error even
    # if the classifier is uncertain about the mixed tense.
    if session.pending in {None, "ptp"} and _has(original_text, _COMMITMENT_CUES):
        past_weekday_date = _date(original_text)
        if past_weekday_date and re.search(r"\blast\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", original_text):
            extracted = dict(extracted or {})
            extracted.update({
                "intent": "promise_to_pay", "intent_confidence": "high",
                "date_iso": past_weekday_date, "date_precision": "exact",
                "dialogue_act": "answers_pending", "pending_slot_status": "provided",
                "summary": "The caller named a past weekday while discussing a future payment.",
            })
    # In the payment-date question, a broad future window is still a usable
    # answer to the timing question even though it is not yet an exact date.
    # Keep it in the commitment flow and ask for the calendar day within it.
    if (broad_date_window and not _date(original_text)
            and session.pending == "ptp"
            and not _has(original_text, _NEGATED_COMMITMENT)):
        extracted = dict(extracted or {})
        extracted.update({
            "intent": "promise_to_pay", "intent_confidence": "high",
            "date_iso": None, "date_precision": "approximate", "date_phrase": broad_date_window,
            "dialogue_act": "answers_pending", "pending_slot_status": "provided",
            "summary": f"The caller gave a broad expected payment window: {broad_date_window}.",
        })
    elif (broad_date_window and not _date(original_text)
            and session.scratch.get("right_party_confirmed")
            and _has(original_text, _COMMITMENT_CUES)
            and not _has(original_text, _NEGATED_COMMITMENT)
            and not _has(original_text, _OFFER_REQUEST)):
        extracted = dict(extracted or {})
        extracted.update({
            "intent": "promise_to_pay", "intent_confidence": "high",
            "date_iso": None, "date_precision": "approximate", "date_phrase": broad_date_window,
            "dialogue_act": "answers_pending", "pending_slot_status": "provided",
            "summary": f"The caller gave a broad expected payment window: {broad_date_window}.",
        })
    if extracted:
        intent = extracted.get("intent")
        # Explicit unwillingness is a distinct caller intent, even if the model
        # loosely labels the utterance as a payment question or unclear.
        if _has(original_text, _PAYMENT_REFUSAL):
            intent = "payment_refusal"
            extracted["intent"] = intent
        # Conditional offer requests are not commitments, even when the utterance
        # also contains wording like “then I will pay”.
        late_fee_discount = _has(original_text, _LATE_FEE_DISCOUNT)
        conditional_offer = not late_fee_discount and (_has(original_text, _OFFER_REQUEST) or (
            RULES.has(original_text, "offer_reference") and RULES.has(original_text, "conditional_offer")
        ))
        if late_fee_discount:
            intent = "waiver"
            extracted["intent"] = intent
        elif conditional_offer:
            intent = "offer_request"
            extracted["intent"] = intent
        if _has(original_text, _PAYMENT_LINK):
            intent = "payment_link_request"
            extracted["intent"] = intent
        elif _is_defer_payment_question(original_text):
            intent = "defer_payment_question"
            extracted["intent"] = intent
        elif _is_cash_payment_question(original_text):
            intent = "payment_method_question"
            extracted["intent"] = intent
        confidence = extracted.get("intent_confidence")
        negated_commitment = (
            not conditional_offer
            and intent in {"promise_to_pay", "unclear"}
            and _has(original_text, _NEGATED_COMMITMENT)
        )
        commitment_language_uncertain = (
            intent == "promise_to_pay" and confidence != "high"
        ) or (
            intent == "unclear" and confidence in {"medium", "low"} and _has(original_text, _COMMITMENT_CUES)
        )
        if intent == "promise_to_pay" or commitment_language_uncertain or negated_commitment:
            if confidence != "high" or negated_commitment:
                commitment_intent_uncertain = True
                intent = "unclear"
                extracted["intent"] = intent
            _trace_policy(
                session,
                "Commitment-intent confidence gate",
                "clarification required" if commitment_intent_uncertain else "passed",
                ("The utterance includes negated payment intent; commitment capture is blocked pending clarification." if negated_commitment
                 else f"The LLM classified payment intent with {confidence or 'missing'} confidence; commitment capture is allowed only for high-confidence intent."),
            )
        dialogue_act = extracted.get("dialogue_act")
        summary = str(extracted.get("summary") or "").casefold()
        # Keep a false-positive balance classification from issuing an OTP. An OTP
        # challenge is allowed only when the caller clearly asks for balance/due data.
        # The model's label/summary cannot by itself authorize OTP; the caller's
        # actual words must ask for their balance or amount due.
        explicit_balance_request = explicit_balance_info_request
        if dialogue_act in {"asks_question", "new_request"} and _has(original_text, _OTP_QUESTION):
            intent = "otp_request"
            extracted["intent"] = intent
        elif dialogue_act == "asks_question" and _has(original_text, _CARD_REFERENCE_QUESTION):
            intent = "account_identification_question"
            extracted["intent"] = intent
        elif dialogue_act == "asks_question" and _is_payment_purpose_question(original_text):
            intent = "payment_question"
            extracted["intent"] = intent
        elif intent == "payment_question" and _is_unmapped_payment_question(original_text):
            intent = "payment_policy_question"
            extracted["intent"] = intent
        elif intent == "balance_question" and not explicit_balance_request:
            if _has(original_text, _CARD_REFERENCE_QUESTION) or "which card" in summary or "which account" in summary:
                intent = "account_identification_question"
            elif _is_payment_purpose_question(original_text) or "asks what this payment is about" in summary:
                intent = "payment_question"
            else:
                intent = "unclear"
            extracted["intent"] = intent
            _trace_policy(
                session,
                "Explicit balance request required for OTP",
                "blocked",
                "The classifier suggested a balance question, but the caller did not explicitly request balance or amount-due information; no OTP was issued.",
            )
        if intent == "other_product" and (_has(text, _HURRY) or _has(text, _YOU_CALLED)):
            intent = "unclear"
            extracted["intent"] = intent
        canonical = {
            "already_paid": "already paid", "payment_not_made": "payment has not been made",
            "payment_refusal": "caller does not want to pay",
            "promise_to_pay": "i will pay",
            "payment_commitment_interest": "tentative payment willingness",
            "payment_link_request": "payment link request",
            "defer_payment_question": "question about paying later",
            "payment_method_question": "accepted payment method question",
            "payment_policy_question": "payment policy question needing a colleague",
            "related_question": "related question about the overdue card payment",
            "waiver": "waiver", "dispute": "dispute", "callback": "call me later",
            "distress": "medical emergency", "abuse": "abusive",
            "opt_out": "stop calling",
            "balance_question": "what is my balance", "interest_question": "interest rate",
            "fee_question": "late fee", "fee_applicability": "whether the late fee applies", "credit_score_question": "credit score",
            "legal_question": "legal advice", "other_product": "another product",
            "otp_request": "otp request", "account_identification_question": "which card",
            "payment_question": "pending payment question",
            "offer_request": "offer request",
        }.get(intent)
        if canonical:
            text += " " + canonical
        date_iso = extracted.get("date_iso")
        mode = extracted.get("payment_mode")
        # A model must not turn an explicitly approximate range into a guessed date.
        if date_iso and not approximate_payment_date:
            text += f" {date_iso}"
        if mode:
            text += f" {mode}"
    session.turn_count += 1

    # Abuse/distress handling takes precedence over ordinary opt-out parsing in that turn:
    # record the issue, apologize, and route to a human rather than treating abusive language
    # as a request to suppress the contact point. Plain opt-out requests remain handled below.
    distress_detected = _has(text, _DISTRESS)
    abuse_detected = _has(text, _ABUSE)
    safety_triggered = distress_detected or abuse_detected
    _trace_policy(
        session,
        "Safety and human-escalation check",
        "triggered" if safety_triggered else "passed",
        "A distress or abuse signal was detected; the bot is escalating." if safety_triggered
        else "No distress or abuse signal was detected.",
    )
    if explicit_balance_info_request and session.scratch.get("right_party_confirmed"):
        _trace_policy(session, "Explicit balance request", "recognized", "The caller explicitly asked for the account balance; the existing OTP verification safeguard will run before any balance is disclosed.")
    if safety_triggered:
        reason = "customer_distress" if distress_detected else "abusive_interaction"
        task = create_followup_task(session, reason, transcript, "urgent" if reason == "customer_distress" else "high")
        transfer = bank_services.request_human_transfer(
            idempotency_key=f"{session.session_id}:{reason}", agent_task_id=task["task_id"],
            case_id=session.request.case_id, episode_id=session.request.episode_id,
            customer_id=session.request.customer_id, account_id=session.request.account_id,
            interaction_id=str(session.session_id), reason=reason,
            priority="urgent" if reason == "customer_distress" else "high",
        )
        session.outcome = Outcome(
            type=OutcomeType.DISPUTE_TRANSFER,
            fields={"reason": reason, "agent_task_id": task["task_id"],
                    "agent_transfer_id": transfer["transfer_id"], "transfer_status": transfer["status"]},
            follow_up_required=True,
            follow_up_reason=reason,
        )
        session.terminal = True
        if distress_detected:
            safety_reply = ("I’m sorry you’re dealing with this. I’ve noted what you shared, and the team will look into it. "
                            "I’ll pause the payment discussion and request a human colleague now. If no one can join, the team will call you back.")
        else:
            safety_reply = ("I’m sorry this call has been frustrating. I’ve noted the issue and will hand this to a human colleague to follow up. "
                            "I’ll stop the payment discussion now.")
        return TurnResponse(
            session_id=session.session_id,
            bot_text=safety_reply,
            terminal=True,
            outcome=session.outcome,
        )

    opt_out_detected = _has(text, _OPT_OUT)
    _trace_policy(
        session,
        "Contact opt-out check",
        "triggered" if opt_out_detected else "passed",
        "The caller requested no further contact; the opt-out action is being recorded." if opt_out_detected
        else "No opt-out request was detected.",
    )
    if opt_out_detected:
        return record_contact_opt_out(session, "voice_customer_request", transcript[:200])

    if business_rule_engine.call_time_limit_reached((datetime.now(timezone.utc) - session.started_at).total_seconds()):
        if session.scratch.get("right_party_confirmed"):
            task = create_followup_task(session, "conversation_time_limit", transcript, "normal")
            session.outcome = Outcome(
                type=OutcomeType.NO_COMMITMENT,
                fields={"reason": "conversation_time_limit", "agent_task_id": task["task_id"]},
                follow_up_required=True,
                follow_up_reason="conversation_time_limit",
            )
            closing = "We’ve reached the end of this call. I’ll ask our team to follow up about your payment. Thank you for your time."
        else:
            session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT, fields={"reason": "identity_confirmation_timeout"})
            closing = "I couldn’t confirm I’m speaking with the right person, so I’ll end this call. Goodbye."
        session.pending = None
        session.terminal = True
        _trace_policy(session, "Three-minute call limit", "triggered", "The conversation reached its three-minute limit; the bot closes with a clear follow-up outcome.")
        return TurnResponse(session_id=session.session_id, bot_text=closing, terminal=True, outcome=session.outcome)

    far_future_response = _resolve_far_future_payment(session, transcript, original_text, extracted)
    if far_future_response is not None:
        return far_future_response

    current_step = session.pending or session.scratch.get("conversation_stage") or "payment_resolution"
    _trace_policy(
        session,
        "Conversation-state check",
        "selected",
        f"The active step is {current_step.replace('_', ' ')}.",
    )

    normalized_greeting = re.sub(r"[^a-z\u0900-\u097f]+", " ", original_text.casefold()).strip()
    # Treat a greeting as a greeting only when the transcript itself is a short
    # greeting. The classifier can label identity answers such as “Yeah, this is
    # Asha Mehta” as `greeting`; allowing that label to take precedence here
    # loops the identity prompt and prevents the identity policy below from
    # seeing the customer's actual answer.
    if normalized_greeting in _GREETING:
        _trace_policy(session, "Greeting handling", "triggered", "A brief greeting was acknowledged while preserving the active identity or payment step.")
        if session.pending == "identity_confirmation":
            _trace_policy(session, "Identity confirmation breathing room", "silent wait", "A greeting is not treated as a request for help or as identity confirmation. The bot listens without speaking, then the browser may repeat the identity question after a sustained pause.")
            return _identity_silent_wait(session)
        if session.pending == "paid_date":
            return _reply(session, "Hi. I’m here to help check the payment you mentioned. What date did you make it? If you don’t remember, I can ask our team to check.")
        if session.pending == "paid_mode":
            return _reply(session, "Hi. I’m checking the payment you mentioned. Which method did you use—UPI, net banking, or cheque?")
        if session.pending == "ptp":
            return _reply(session, "Hi. I’m here to help with your overdue minimum payment. When do you expect to pay it?")
        if session.pending == "ptp_confirmation":
            pay_date = session.scratch.get("ptp_date")
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date we discussed"
            return _reply(session, f"Hi. I have your expected payment date as {date_label}. Is that correct, or would you like to change it?")
        if session.pending == "callback_time":
            return _reply(session, "Hi. What day or time would be convenient for our team to call you?")
        if session.pending == "balance_check_consent":
            return _reply(session, "Hi. Would you like me to check the bank-recorded balance using OTP verification, or continue with the overdue payment?")
        if session.pending == "otp_code":
            return _reply(session, "Hi. For your security, please enter the six-digit code using the verification field. I can’t accept a spoken code.")
        return _reply(session, f"Hi. Your minimum payment on your Mumbai Bank credit card is overdue. Interest is charged at {_monthly_interest_text()}, and a late fee of {_late_fee_text()} may apply if your outstanding balance is over {_threshold_text()}. Have you already paid, or when do you expect to pay the minimum amount due?")

    if session.scratch.get("right_party_confirmed"):
        if session.pending == "interest_follow_up_consent":
            if _is_clear_yes(original_text):
                _trace_policy(session, "Interest-rate complaint follow-up", "accepted", "The customer accepted a human callback about the interest-rate concern.")
                concern = session.scratch.pop("interest_concern_transcript", transcript)
                session.pending = None
                return _record_payment_question_follow_up(session, concern, "interest rate concern")
            if _is_clear_no(original_text):
                _trace_policy(session, "Interest-charge human review", "declined", "The customer declined colleague follow-up; the bot gives the approved rate information and returns to the payment menu.")
                session.pending = None
                return _reply(session, f"Understood. The rate provided for this call is {_monthly_interest_text()}. I can’t calculate the exact charge here. Have you already paid, or when do you expect to pay the minimum due?")
            if _is_interest_concern(original_text):
                session.scratch["interest_concern_transcript"] = transcript
                _trace_policy(session, "Interest concern repeated", "callback offered", "The caller reiterated that the interest rate feels too high. The bot clarifies it cannot modify the rate and offers an optional human follow-up.")
                return _reply(session, "I understand you still feel the interest rate is too high. I can’t change the rate, but I can note your concern and arrange for a human colleague to call you. Would you like me to arrange that?")
            if (extracted or {}).get("dialogue_act") in {"asks_question", "new_request"}:
                session.pending = None
                session.scratch.pop("interest_concern_transcript", None)
            else:
                _trace_policy(session, "Interest-charge human review", "clarification required", "The customer has not clearly accepted or declined a colleague review.")
                return _reply(session, "Would you like me to ask a colleague to look into the interest charge and call you?")
        if session.pending == "balance_check_consent":
            if (
                _has(original_text, _AFFIRM)
                or _has(original_text, _BALANCE_CHECK_CUES)
                or (_is_customer_balance_request(original_text) and (extracted or {}).get("intent") == "balance_question")
            ):
                balance_check_consented = True
                session.pending = None
                _trace_policy(session, "Balance-verification consent", "confirmed", "The caller agreed to check the bank-recorded balance; the OTP safeguard is now required before disclosure.")
            elif _has(text, _NEGATIVE):
                session.pending = None
                _trace_policy(session, "Balance-verification consent", "declined", "The caller declined the optional balance check; no OTP was issued.")
                if session.scratch.pop("ptp_amount_after_otp", False):
                    session.pending = "ptp_amount"
                    pay_date = session.scratch.get("ptp_date")
                    date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the confirmed date"
                    return _reply(session, f"Understood. What amount would you like me to note for your payment on {date_label}?")
            elif (
                (extracted or {}).get("intent") not in {None, "unclear", "balance_question"}
                or (extracted or {}).get("dialogue_act") in {"asks_question", "new_request"}
                or _is_defer_payment_question(text)
                or _is_cash_payment_question(text)
                or _has(text, _PAID + _CALLBACK + _PAYMENT_LINK + _WAIVER + _DISPUTE)
            ):
                session.pending = None
                _trace_policy(session, "Balance-verification consent", "cancelled for new request", "The caller changed topic instead of accepting or declining the optional balance check. The pending consent prompt was cleared so the new intent can be handled.")
            else:
                _trace_policy(session, "Balance-verification consent", "clarification required", "The caller’s response did not clearly accept or decline the optional OTP-protected balance check.")
                return _reply(session, "Would you like me to check the bank-recorded balance using OTP verification, or should we continue with the overdue payment?")
        if _has(text, _HURRY) or _has(text, _YOU_CALLED):
            _trace_policy(session, "Keep collections conversation on task", "triggered", "The caller asked for brevity or pointed out that the bank initiated the call; the bot acknowledges this and returns to the payment choices.")
            return _reply(session, f"You’re right—I’ll be brief. Your minimum payment is overdue. Interest is charged at {_monthly_interest_text()}, and a late fee of {_late_fee_text()} may apply if your outstanding balance is over {_threshold_text()}. Have you already paid, or when do you expect to pay the minimum amount due?")
        if _has(text, _DISPUTE):
            _trace_policy(session, "Debt-dispute handling", "triggered", "The caller disputed the debt; the bot pauses collections and requests human review.")
            return _record_dispute(session, transcript)
        if _has(text, _PAYMENT_LINK) or (extracted or {}).get("intent") == "payment_link_request":
            _trace_policy(session, "Payment-link request", "triggered", "The verified customer requested a payment link. The bot records a colleague follow-up and does not claim to send or trigger the link itself.")
            return _record_payment_link_request(session, transcript)
        if _has(text, _WAIVER):
            _trace_policy(session, "Fee-waiver handling", "triggered", "The caller requested a fee waiver; the bot records a human follow-up task.")
            return _record_waiver_request(session, transcript)
        if _has(text, _CALLBACK) and session.pending != "callback_time":
            has_preferred_time = _date(text) is not None or any(
                marker in text for marker in (" at ", "morning", "afternoon", "evening", " after ", " before ", "between")
            )
            if has_preferred_time:
                _trace_policy(session, "Callback scheduling", "triggered", "The caller requested a callback and supplied a preferred time.")
                return _record_callback_request(session, transcript, text)
            session.pending = "callback_time"
            _trace_policy(session, "Callback scheduling", "triggered", "The caller requested a callback; the bot is collecting a preferred time.")
            return _reply(session, "Of course. What day or time would be convenient for our team to call you?")

        if session.pending == "refusal_reason":
            pending_intent = (extracted or {}).get("intent")
            if pending_intent in _PENDING_SLOT_INTENTS and pending_intent != "payment_refusal":
                # A new, explicit topic takes precedence over the reason question.
                session.pending = None
                _sync_pending_question(session)
            elif ((extracted or {}).get("dialogue_act") == "answers_pending"
                  or _has(text, _REFUSAL_REASON_CUES)
                  or len(re.findall(r"[a-z]+|[\u0900-\u097f]+", original_text)) <= 5):
                _trace_policy(session, "Payment refusal reason follow-up", "answered", "The caller’s short reply is interpreted against the pending question about why payment is difficult; the generic unrelated-topic fallback is skipped.")
                return _reply(session, "Could you tell me more about that concern—is it the interest or fee, the payment process, or something else?")

        if _has(original_text, _PAYMENT_REFUSAL) or (extracted or {}).get("intent") == "payment_refusal":
            session.pending = "refusal_reason"
            _trace_policy(session, "Payment refusal handling", "triggered", "The caller explicitly does not want to pay. The bot asks for the reason; disputes and hardship cases remain governed by their higher-priority escalation rules.")
            return _reply(session, "I understand you don’t want to pay. Is there a concern about the payment, or is something making it difficult to pay?")

    if session.pending == "identity_confirmation":
        _trace_policy(session, "Right-party identity safeguard", "active", "Account details remain protected until the caller confirms they are the account holder.")
        awaiting_full_name = session.scratch.get("awaiting_full_name") is True
        opening_was_delivered = session.scratch.get("identity_opening_delivered") is True
        identity_prompt_was_active = (
            session.scratch.get("awaiting_identity_confirmation") is True
            and opening_was_delivered
            and not heard_before_opening
            and not awaiting_full_name
        )
        # Consume the active prompt. Any clarification response below must
        # explicitly ask the identity question again before a later answer can confirm it.
        session.scratch["awaiting_identity_confirmation"] = False
        _trace_policy(
            session,
            "Identity confirmation prompt state",
            "awaiting response" if identity_prompt_was_active else "no active identity question",
            "A positive answer can confirm identity only when the bot's immediately preceding response asked who it was speaking with.",
        )
        identity_status = (extracted or {}).get("identity_status")
        normalized_identity_reply = re.sub(r"[^a-z\u0900-\u097f]+", " ", text).strip()
        bare_no = normalized_identity_reply in {"no", "nope", "नहीं", "नही", "नहि", "nahi", "nahin"}
        if _has(text, _NOT_AVAILABLE):
            _trace_policy(session, "Identity result", "triggered", "The caller indicated the account holder is unavailable or this is not the account holder.")
            session.pending = None
            session.scratch["right_party_confirmed"] = False
            session.terminal = True
            return TurnResponse(session_id=session.session_id, bot_text="Thank you. I’ll try to reach them another time. Goodbye.", terminal=True)
        contact_name = " ".join(part.strip() for part in (session.request.first_name, session.request.last_name) if part and part.strip()) or "the account holder"
        first_name = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", (session.request.first_name or "").casefold()).strip()
        last_name = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", (session.request.last_name or "").casefold()).strip()
        first_present = bool(first_name and re.search(rf"(?<!\w){re.escape(first_name)}(?!\w)", normalized_identity_reply))
        last_present = bool(last_name and re.search(rf"(?<!\w){re.escape(last_name)}(?!\w)", normalized_identity_reply))
        full_name_present = first_present and (last_present or not last_name)
        partial_name_present = (first_present or last_present) and not full_name_present
        self_identification = bool(RULES.pattern_search("identity_self_identification", normalized_identity_reply)) or bool(re.match(r"^(?:yes|yeah|yep|haan|han|ji)\b", normalized_identity_reply))
        exact_full_name = bool(normalized_identity_reply == re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", contact_name.casefold()).strip())
        partial_name_response = partial_name_present and (
            self_identification
            or normalized_identity_reply in {first_name, last_name}
        )

        if partial_name_response:
            attempts = int(session.scratch.get("full_name_clarification_attempts", 0)) + 1
            session.scratch["full_name_clarification_attempts"] = attempts
            if business_rule_engine.identity_limit_reached(attempts):
                session.pending = None
                session.terminal = True
                _trace_policy(session, "Full-name verification limit", "triggered", "The caller did not provide the full name after repeated clarification; the call ended without discussing the account.")
                return TurnResponse(session_id=session.session_id, bot_text="I’m unable to confirm I’m speaking with the right person, so I’ll end the call without discussing the account. Goodbye.", terminal=True)
            session.scratch["awaiting_full_name"] = True
            session.scratch["awaiting_identity_confirmation"] = False
            _trace_policy(session, "Partial-name verification", "clarification required", "The caller supplied only part of the named customer’s name; full name is required before discussing the account.")
            return _reply(session, "For security, please confirm your full name, including your first and last name.")

        if awaiting_full_name:
            if full_name_present or exact_full_name:
                identity_prompt_was_active = True
                session.scratch["awaiting_full_name"] = False
                session.scratch["full_name_clarification_attempts"] = 0
            else:
                attempts = int(session.scratch.get("full_name_clarification_attempts", 0)) + 1
                session.scratch["full_name_clarification_attempts"] = attempts
                if business_rule_engine.identity_limit_reached(attempts):
                    session.pending = None
                    session.terminal = True
                    _trace_policy(session, "Full-name verification limit", "triggered", "The caller did not provide the full name after repeated clarification; the call ended without discussing the account.")
                    return TurnResponse(session_id=session.session_id, bot_text="I’m unable to confirm I’m speaking with the right person, so I’ll end the call without discussing the account. Goodbye.", terminal=True)
                session.scratch["awaiting_identity_confirmation"] = False
                session.scratch["awaiting_full_name"] = True
                _trace_policy(session, "Full-name verification", "still required", "The caller has not provided both parts of the name needed to complete identity verification.")
                return _reply(session, "I still need your full name, including your first and last name, before I can discuss the account.")

        # A name volunteered before the bot asks the named identity question
        # is not confirmation. The browser-delivered marker is authoritative;
        # the client timing flag is an additional safeguard, not the source of
        # truth.
        unprompted_full_name_confirmation = False
        if (heard_before_opening or not opening_was_delivered) and not awaiting_full_name:
            session.scratch["awaiting_identity_confirmation"] = True
            _trace_policy(session, "Identity opening delivery check", "not delivered", "The server has not recorded that the named identity question was played before this caller response.")
            _trace_policy(session, "Pre-opening caller response", "identity clarification required", "The caller spoke before hearing the named identity prompt; the bot introduces itself and explains that it must confirm the recipient before sharing the specific call reason.")
            return _reply(session, f"Thanks. I’m an automated assistant calling on behalf of Mumbai Bank. Am I speaking with {contact_name}?")

        direct_identity_affirmative = identity_prompt_was_active and (
            normalized_identity_reply in {"you are", "you are speaking with me", "you are speaking to me"}
            or bool(re.match(
            r"^(?:yes|yeah|yep|yup|correct|right)\s*(?:,\s*)?"
            r"you are(?:\s+speaking(?:\s+(?:with|to)\s+(?:me|[a-z]+(?:\s+[a-z]+)?))?)?[.!? ]*$",
            normalized_identity_reply,
            ))
        )
        if (identity_status == "not_confirmed" or bare_no) and not direct_identity_affirmative:
            _trace_policy(session, "Identity result", "triggered", "The caller clearly declined or indicated the named person is unavailable after the identity question was asked.")
            session.pending = None
            session.scratch["right_party_confirmed"] = False
            session.terminal = True
            return TurnResponse(session_id=session.session_id, bot_text="Thank you. I’ll try to reach them another time. Goodbye.", terminal=True)

        if _has(text, _FRUSTRATION):
            attempts = int(session.scratch.get("identity_clarification_attempts", 0)) + 1
            session.scratch["identity_clarification_attempts"] = attempts
            if business_rule_engine.identity_limit_reached(attempts):
                session.pending = None
                session.terminal = True
                _trace_policy(session, "Identity clarification limit", "triggered", "The caller remained unconfirmed after three turns; the call ended without disclosing account information.")
                return TurnResponse(session_id=session.session_id, bot_text="Sorry, I still can’t confirm I’m speaking with the right person, so I’ll end the call without discussing the account. Goodbye.", terminal=True)
            session.scratch["awaiting_identity_confirmation"] = not awaiting_full_name
            session.scratch["awaiting_full_name"] = False
            return _reply(session, f"I’m sorry this feels frustrating. I’m an automated assistant calling on behalf of Mumbai Bank. Am I speaking with {contact_name}?")
        if _has(text, _IDENTITY_INFO_QUESTION) or (extracted or {}).get("dialogue_act") == "asks_question":
            _trace_policy(session, "Identity question clarification", "brief answer and silent wait", "The caller asked a question before confirming identity. The bot identifies itself, listens without adding a time-pressure phrase, and may repeat the identity question after a sustained pause.")
            if awaiting_full_name:
                session.scratch["awaiting_full_name"] = True
                session.scratch["awaiting_identity_confirmation"] = False
                return _reply(session, "For your privacy, I need your full name to confirm I’m speaking with the right person. Could you tell me your first and last name?")
            return _identity_silent_wait(session, "I’m an automated assistant calling on behalf of Mumbai Bank.")
        llm_confirmed_answer = (
            identity_status == "confirmed"
            and (extracted or {}).get("intent_confidence") == "high"
            and (extracted or {}).get("dialogue_act") == "answers_pending"
        )
        prompted_full_name_answer = full_name_present and (self_identification or exact_full_name)
        if (
            identity_prompt_was_active
            and (_has(text, _AFFIRM) or direct_identity_affirmative or llm_confirmed_answer or prompted_full_name_answer)
        ) or unprompted_full_name_confirmation:
            _trace_policy(session, "Identity result", "confirmed", "The current turn was accepted as confirmation from the account holder.")
            session.pending = None
            session.scratch["right_party_confirmed"] = True
            session.scratch["awaiting_full_name"] = False
            session.scratch["full_name_clarification_attempts"] = 0
            session.scratch["identity_clarification_attempts"] = 0
            session.scratch["identity_wait_prompt_given"] = False
            session.scratch.pop("weak_identity_yes_retry", None)
            session.scratch["conversation_stage"] = "payment_resolution"
            session.scratch["due_information_given"] = True
            return _reply(session, f"Thank you for confirming. Your minimum payment on your Mumbai Bank credit card is overdue. Interest is charged at {_monthly_interest_text()}, and a late fee of {_late_fee_text()} may apply if your outstanding balance is over {_threshold_text()}. Have you already paid, or when do you expect to pay the minimum amount due?")
        _trace_policy(session, "Identity result", "not established", "The current turn did not establish that the account holder is speaking; no account details were disclosed.")
        if not session.scratch.get("identity_wait_prompt_given"):
            _trace_policy(session, "Identity confirmation breathing room", "silent wait", "The answer did not clearly confirm or decline identity. The bot listens without speaking, then may repeat the question after a sustained pause.")
            return _identity_silent_wait(session)
        attempts = int(session.scratch.get("identity_clarification_attempts", 0)) + 1
        session.scratch["identity_clarification_attempts"] = attempts
        _trace_policy(session, "Identity clarification limit", "triggered" if business_rule_engine.identity_limit_reached(attempts) else "active", f"Unconfirmed identity turn {attempts} of {IDENTITY_CONFIRMATION_ATTEMPTS}; the bot will clarify or end without disclosing account information.")
        if business_rule_engine.identity_limit_reached(attempts):
            session.pending = None
            session.terminal = True
            return TurnResponse(session_id=session.session_id, bot_text="Sorry, I still can’t confirm I’m speaking with the right person, so I’ll end the call without discussing the account. Goodbye.", terminal=True)
        if session.request.first_name or session.request.last_name:
            session.scratch["awaiting_identity_confirmation"] = True
            return _reply(session, f"Sorry, I didn’t catch that. I’m trying to reach {contact_name}. Are you {contact_name}?")
        session.scratch["awaiting_identity_confirmation"] = True
        return _reply(session, "Sorry, I didn’t catch that. Are you the account holder?")

    # Handle offer requests before pending payment slots. Otherwise a customer
    # asking about an offer while the bot is collecting PTP details gets pushed
    # back into the amount/date question loop.
    late_fee_discount = _has(original_text, _LATE_FEE_DISCOUNT)
    conditional_offer = not late_fee_discount and (_has(original_text, _OFFER_REQUEST) or (
        RULES.has(original_text, "offer_reference") and RULES.has(original_text, "conditional_offer")
    ) or (extracted or {}).get("intent") == "offer_request")
    if session.scratch.get("right_party_confirmed") and conditional_offer:
        _trace_policy(session, "Offer request boundary", "triggered", "A conditional request for an offer is not a payment commitment; no payment amount or date is collected.")
        session.pending = None
        return _reply(session, "I understand you’d like to know the current offer before deciding about payment. I don’t have the offer details available in this call. I can ask our team to contact you about it, or we can continue with the payment options. Which would you prefer?")

    if session.pending == "otp_code":
        # Spoken OTPs are ignored. The voice path also stops forwarding audio to STT in this state.
        return _reply(session, "For your security, please enter the six-digit code using your phone keypad. I can’t accept a spoken code.")

    # An explicit balance question takes priority over whichever conversational
    # prompt was active (for example, payment date or callback timing). Do not
    # send the customer back to the payment menu before starting OTP verification.
    balance_requested_now = (
        explicit_balance_info_request
        or _is_customer_balance_request(original_text)
    )
    if session.scratch.get("right_party_confirmed") and balance_requested_now:
        if session.pending == "ptp_amount":
            session.scratch["ptp_amount_after_otp"] = True
        session.pending = None
        return _start_balance_verification(session, transcript)

    if session.pending == "ptp_amount":
        normalized = original_text.casefold().strip()
        if RULES.has(normalized, "ptp_amount_check"):
            session.scratch["ptp_amount_after_otp"] = True
            session.pending = None
            return _start_balance_verification(session, transcript)
        if RULES.has(normalized, "ptp_amount_delay") or (extracted or {}).get("pending_slot_status") == "cannot_provide":
            return _record_ptp_amount_callback(session, transcript)
        if RULES.has(normalized, "ptp_amount_decline") or _is_clear_no(normalized):
            return _finish_ptp_amount(session, None)
        if RULES.has(normalized, "ptp_amount_min_due_reference") and session.scratch.get("verified_minimum_due") is not None:
            session.pending = "ptp_amount_confirmation"
            due = _format_inr_amount(session.scratch.get("verified_minimum_due"))
            return _reply(session, f"Just to confirm, do you mean the verified minimum due of {due}?")
        amount = _normalize_customer_amount((extracted or {}).get("amount_inr"))
        # In this dedicated slot, a bare numeric answer is an amount, but a
        # calendar date must not be mistaken for one.
        if amount is None and not _date(original_text):
            bare_number = re.search(r"(?<!\w)(\d[\d,]*(?:\.\d{1,2})?)(?!\w)", original_text)
            amount = _normalize_customer_amount(bare_number.group(1)) if bare_number else None
        if amount is not None:
            return _finish_ptp_amount(session, amount)
        if RULES.has(normalized, "ptp_amount_otp_accept") or _is_clear_yes(normalized):
            session.scratch["ptp_amount_after_otp"] = True
            session.pending = None
            return _start_balance_verification(session, transcript)
        if RULES.has(normalized, "ptp_amount_min_due_reference") or any(phrase in normalized for phrase in ("otp", "check the amount", "tell me the amount", "exact amount", "amount due")):
            session.scratch["ptp_amount_after_otp"] = True
            session.pending = None
            return _start_balance_verification(session, transcript)
        if (extracted or {}).get("dialogue_act") == "asks_question" or (extracted or {}).get("intent") in {"other_product", "other_question"}:
            return _reply(session, "I can’t help with that on this call. What amount would you like me to note for your payment?")
        return _reply(session, "What amount would you like me to note? If you need the bank-recorded minimum due, I can check it using OTP verification.")

    if session.pending == "ptp_amount_confirmation":
        normalized = original_text.casefold().strip()
        if RULES.has(normalized, "ptp_amount_delay") or (extracted or {}).get("pending_slot_status") == "cannot_provide":
            return _record_ptp_amount_callback(session, transcript)
        amount = _normalize_customer_amount((extracted or {}).get("amount_inr"))
        if amount is None and not _date(original_text):
            bare_number = re.search(r"(?<!\w)(\d[\d,]*(?:\.\d{1,2})?)(?!\w)", original_text)
            amount = _normalize_customer_amount(bare_number.group(1)) if bare_number else None
        if amount is not None:
            return _finish_ptp_amount(session, amount)
        if _is_clear_yes(normalized):
            return _finish_ptp_amount(session, _normalize_customer_amount(session.scratch.get("verified_minimum_due")))
        if _is_clear_no(normalized):
            session.pending = "ptp_amount"
            pay_date = session.scratch.get("ptp_date")
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the confirmed date"
            return _reply(session, f"Understood. What amount would you like me to note for your payment on {date_label}?")
        due = _format_inr_amount(session.scratch.get("verified_minimum_due"))
        return _reply(session, f"Just to confirm, do you mean the verified minimum due of {due}?")

    if session.pending == "ptp_confirmation":
        if _has(text, _AFFIRM):
            _trace_policy(session, "Payment-commitment confirmation", "confirmed", "The caller confirmed the expected payment date; the amount step follows if they have not already volunteered an amount.")
            pay_date = session.scratch.get("ptp_date", "")
            amount = _normalize_customer_amount(session.scratch.get("ptp_amount"))
            if amount is not None:
                return _finish_ptp_amount(session, amount)
            session.pending = "ptp_amount"
            _sync_pending_question(session)
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date you gave"
            return _reply(
                session,
                f"Thank you for confirming {date_label}. What amount do you plan to pay? "
                    "If you need to check the bank-recorded minimum due, I can do that after OTP verification.",
            )
        if _has(text, _NEGATIVE):
            _trace_policy(session, "Payment-commitment correction", "triggered", "The caller rejected the proposed date; the bot asks for a replacement date.")
            session.pending = "ptp"
            session.scratch.pop("ptp_date", None)
            return _reply(session, "No problem. What date should I note instead?")
        return _reply(session, "I have your expected payment date as stated. Is that correct, or would you like to change the date?")

    if session.pending == "callback_time":
        _trace_policy(session, "Callback scheduling", "selected", "The bot is recording the requested callback preference for the team.")
        return _record_callback_request(session, transcript, text)

    if session.pending == "paid_most_recent_confirmation":
        supplied_mode = _mode(original_text)
        if supplied_mode:
            session.scratch["reported_payment_mode"] = supplied_mode
        if _has(original_text, _UNCERTAIN_CONFIRMATION):
            _trace_policy(session, "Most-recent payment check", "uncertain", "The caller was unsure whether this was the most recent payment; the bot records the uncertainty and routes it to a human colleague instead of repeating the question.")
            return _record_old_payment_for_review(session, "uncertain")
        if _is_clear_no(original_text):
            _trace_policy(session, "Most-recent payment check", "answered-no", "The caller said the reported old payment was not the most recent; the bot asks for the most recent payment date.")
            session.scratch["older_payment_date"] = session.scratch.pop("reported_payment_date", None)
            session.scratch["older_payment_mode"] = session.scratch.pop("reported_payment_mode", None)
            session.pending = "paid_most_recent_date"
            return _reply(session, "Understood. What date did you make your most recent payment?")
        if _is_clear_yes(original_text):
            _trace_policy(session, "Most-recent payment check", "answered-yes", "The caller confirmed that the reported old payment is their most recent; a human colleague will review it.")
            return _record_old_payment_for_review(session, "confirmed")
        if supplied_mode:
            return _reply(session, "I’ve noted the payment mode. Is that your most recent payment, or was there a later one?")
        if _is_uncertain_confirmation(original_text, extracted):
            _trace_policy(session, "Most-recent payment check", "uncertain", "The caller was unsure whether this was the most recent payment; the bot records the uncertainty and routes it to a human colleague instead of repeating the question.")
            return _record_old_payment_for_review(session, "uncertain")
        return _reply(session, "I’ve noted the payment. Is it your most recent payment, or was there a later one?")

    if session.pending == "paid_most_recent_date":
        if (extracted or {}).get("dialogue_act") == "cannot_provide" or (extracted or {}).get("pending_slot_status") == "cannot_provide":
            return _record_old_payment_for_review(session, "newer_payment_date_not_provided")
        saved_window = session.scratch.get("reported_payment_broad_window")
        weekday_date = _weekday_date_in_window(original_text, str(saved_window), reference_date) if saved_window else None
        explicit_date = _date(text) or weekday_date
        if broad_date_window and not explicit_date:
            session.scratch["reported_payment_broad_window"] = broad_date_window
            session.scratch["reported_payment_date_text"] = transcript[:120]
            _trace_policy(session, "Broad most-recent payment date", "exact calendar date requested", f"The caller gave the broad time window ‘{broad_date_window}’; the bot asks for a specific day within that window.")
            return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=True))
        paid_date = explicit_date or (None if broad_date_window else (extracted or {}).get("date_iso"))
        if not paid_date:
            return _reply(session, "What calendar date did you make your most recent payment?")
        date_issue = _date_window_violation(
            paid_date, window=str(saved_window) if saved_window else None,
            reference_date=reference_date, payment_already_made=True,
        )
        if date_issue:
            _trace_policy(session, "Most-recent payment date validation", "clarification required", "The proposed date is future-dated or outside the caller's stated window, so it cannot be accepted as a completed payment date.")
            return _reply(session, date_issue)
        session.scratch.pop("reported_payment_broad_window", None)
        session.scratch["reported_payment_date"] = paid_date
        mode = _mode(text)
        if mode:
            session.scratch["reported_payment_mode"] = mode
            return _continue_reported_payment(session, paid_date, mode, most_recent_confirmed=True)
        session.pending = "paid_most_recent_mode"
        return _reply(session, "Thank you. Which payment mode did you use for that most recent payment?")

    if session.pending == "paid_most_recent_mode":
        mode = _mode(text)
        if mode:
            session.scratch["reported_payment_mode"] = mode
            return _continue_reported_payment(session, session.scratch["reported_payment_date"], mode, most_recent_confirmed=True)
        if (extracted or {}).get("dialogue_act") == "cannot_provide" or (extracted or {}).get("pending_slot_status") == "cannot_provide":
            return _record_old_payment_for_review(session, "confirmed_latest_date_mode_unavailable")
        return _reply(session, "Which payment mode did you use for that most recent payment—UPI, net banking, cheque, cash, or another method?")

    if session.pending in {"paid_date", "paid_mode"}:
        # A customer may correct an earlier "already paid" answer while we
        # are collecting reconciliation details. A clear future commitment is
        # a change of outcome, not another attempted past-payment date. Switch
        # the active state before the paid-date validator can reject it.
        explicit_future_commitment = bool(re.search(
            r"\b(?:i(?:'|’)ll|i will|i shall|i am going to|i'm going to|i plan to|i intend to)\s+(?:be\s+)?(?:making|make|pay|paying)\b",
            original_text,
        ))
        classified_future_commitment = (
            (extracted or {}).get("intent") == "promise_to_pay"
            and (extracted or {}).get("intent_confidence") == "high"
        )
        if (explicit_future_commitment or classified_future_commitment) and not _has(original_text, _NEGATED_COMMITMENT):
            _trace_policy(
                session,
                "Correction from already-paid to payment commitment",
                "disposition changed",
                "The caller clarified that payment has not yet been made and stated a future commitment; stale reconciliation fields are cleared and the commitment flow becomes active.",
            )
            for key in (
                "reported_payment_date", "reported_payment_date_text", "reported_payment_mode",
                "reported_payment_broad_window", "payment_date_clarification_attempts",
                "payment_date_wait_attempts", "older_payment_date", "older_payment_mode",
            ):
                session.scratch.pop(key, None)
            session.pending = "ptp"
            _sync_pending_question(session)

            future_window = broad_date_window
            proposed_date = _date(original_text) or _month_year_date(original_text)
            if proposed_date is None:
                proposed_date = _exact_iso_calendar_date((extracted or {}).get("date_iso"))
            if future_window and not _date(original_text):
                session.scratch["ptp_broad_date_window"] = future_window
                session.scratch["ptp_proposed_date_text"] = transcript[:100]
                return _reply(session, _broad_date_follow_up(future_window, payment_already_made=False))
            if proposed_date:
                date_issue = _date_window_violation(
                    proposed_date, window=None, reference_date=reference_date,
                    payment_already_made=False,
                )
                if date_issue:
                    return _reply(session, date_issue)
                if business_rule_engine.commitment_is_too_far(
                    (date.fromisoformat(proposed_date) - (date.fromisoformat(reference_date) if reference_date else datetime.now(timezone.utc).date())).days
                ):
                    session.scratch["ptp_far_future_date_iso"] = proposed_date
                    session.scratch["ptp_proposed_date_text"] = transcript[:100]
                    session.scratch["ptp_far_future_active"] = True
                    session.scratch["ptp_far_future_clarification_attempts"] = 0
                    session.pending = "ptp_far_future_choice"
                    _sync_pending_question(session)
                    return _reply(session, "That date is quite some time away. Are you able to make the payment earlier, or would you like a colleague to call and discuss options?")
                if _month_year_date(original_text) and not _date(original_text):
                    session.scratch["ptp_month_year_text"] = _month_year_phrase(original_text) or "that month"
                    return _reply(session, f"I’ve noted {session.scratch['ptp_month_year_text']} as the timing. What specific day in that month should I note for your payment?")
                session.scratch["ptp_date"] = proposed_date
                session.pending = "ptp_confirmation"
                _sync_pending_question(session)
                date_label = datetime.fromisoformat(proposed_date).strftime("%d %B").lstrip("0")
                return _reply(session, f"Thanks for clarifying—you plan to make the payment on {date_label}. Have I got that right?")
            return _reply(session, "Thanks for clarifying that you haven’t made this payment yet. What future date should I note for your payment?")

        dialogue_act = (extracted or {}).get("dialogue_act")
        pending_slot_status = (extracted or {}).get("pending_slot_status")
        _trace_policy(session, "Payment reconciliation information check", "evaluated", "The bot is checking whether the caller supplied a usable payment date or payment method.")
        # Use facts in the utterance before trusting the classifier's dialogue-act label.
        # In live speech, a date can arrive as a separate short utterance after a fragment
        # such as “I made it on”; the classifier may otherwise call that fragment missing.
        saved_window = session.scratch.get("reported_payment_broad_window")
        weekday_date = _weekday_date_in_window(original_text, str(saved_window), reference_date) if saved_window else None
        explicit_date = _date(text) or weekday_date
        paid_date = (
            explicit_date
            or (None if broad_date_window else (extracted or {}).get("date_iso"))
            or (None if broad_date_window else session.scratch.get("reported_payment_date"))
        )
        mode = _mode(text) or (extracted or {}).get("payment_mode") or session.scratch.get("reported_payment_mode")
        if broad_date_window and not explicit_date and session.pending == "paid_date":
            _trace_policy(session, "Broad payment-date handling", "exact calendar date requested", f"The caller gave the broad time window ‘{broad_date_window}’; do not turn it into a guessed date. Ask for a specific calendar day within that window.")
            session.scratch["reported_payment_date_text"] = transcript[:120]
            session.scratch["reported_payment_broad_window"] = broad_date_window
            if mode:
                session.scratch["reported_payment_mode"] = mode
            attempts = int(session.scratch.get("payment_date_clarification_attempts", 0)) + 1
            session.scratch["payment_date_clarification_attempts"] = attempts
            if attempts >= PAYMENT_DATE_WAIT_ATTEMPTS:
                return _record_paid_for_manual_reconciliation(session, transcript)
            return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=True))
        if paid_date:
            date_issue = _date_window_violation(
                paid_date, window=str(saved_window) if saved_window else None,
                reference_date=reference_date, payment_already_made=True,
            )
            if date_issue:
                _trace_policy(session, "Reported payment date validation", "clarification required", "The proposed date is future-dated or outside the caller's stated window, so it cannot be accepted as a completed payment date.")
                return _reply(session, date_issue)
            session.scratch.pop("reported_payment_broad_window", None)
            _trace_policy(session, "Payment date and age handling", "selected", "A specific payment date was supplied; date extraction takes precedence over a conflicting missing-detail label.")
            return _continue_reported_payment(session, paid_date, mode)
        if mode:
            session.scratch["reported_payment_mode"] = mode
        if approximate_payment_date:
            _trace_policy(session, "Approximate-date handling", "triggered", "The caller gave an approximate time, so the bot will not treat it as an exact date or run a reconciliation lookup.")
            session.scratch["reported_payment_date_text"] = transcript[:120]
            mode = _mode(text)
            if mode:
                session.scratch["reported_payment_mode"] = mode
            attempts = int(session.scratch.get("payment_date_clarification_attempts", 0)) + 1
            session.scratch["payment_date_clarification_attempts"] = attempts
            if attempts >= PAYMENT_DATE_WAIT_ATTEMPTS:
                return _record_paid_for_manual_reconciliation(session, transcript)
            return _reply(session, _approximate_payment_date_reply())
        if dialogue_act == "asks_question" or pending_slot_status == "question":
            _trace_policy(session, "Question-during-information-collection", "triggered", "The caller asked a question while a payment detail is pending; the reply explains why that detail is needed.")
            return _reply(session, "I can’t calculate that without a payment date. If you remember the exact date or roughly when you paid, tell me; if not, I can ask our team to check.")
        if _has(text, _NEEDS_TIME_TO_CHECK) or dialogue_act == "cannot_provide" or pending_slot_status == "cannot_provide":
            attempts = int(session.scratch.get("payment_date_wait_attempts", 0)) + 1
            session.scratch["payment_date_wait_attempts"] = attempts
            if attempts < PAYMENT_DATE_WAIT_ATTEMPTS or _has(text, _NEEDS_TIME_TO_CHECK):
                _trace_policy(session, "Give customer time to check payment date", "triggered", "The customer needs time or the classifier marked a fragmented response as missing; the date question stays open and no follow-up call is created yet.")
                return _reply(session, "No problem—take a moment to check your message or statement. I can wait; tell me the date when you’re ready. If you can’t find it, I can ask a colleague to check.")
            _trace_policy(session, "Payment date unavailable after time to check", "triggered", "The caller still cannot provide a date after being given time; the bot records a human reconciliation follow-up.")
            return _record_paid_for_manual_reconciliation(session, transcript)
        if mode:
            session.pending = "paid_date"
            return _reply(session, "Got it. Take a moment if you need to check—what date did you make the payment?")
        return _reply(session, "Okay, I can check that for you. What date did you pay, and was it through UPI, net banking, or cheque?")

    if session.pending == "paid_mode":
        mode = _mode(text)
        if mode:
            return _finish_paid(session, session.scratch["reported_payment_date"], mode)
        return _reply(session, "And how did you make the payment—through UPI, net banking, or cheque?")

    if _has(original_text, _NOT_PAID) or (extracted or {}).get("intent") == "payment_not_made":
        _trace_policy(session, "Unpaid-status handling", "triggered", "The caller said the payment has not been made; the bot asks about the reason or expected date without treating this as a commitment.")
        session.pending = None
        return _reply(session, "I understand you haven’t paid yet. Is something making it difficult to pay, or do you know when you can make the payment?")

    if session.pending == "ptp":
        saved_window = session.scratch.get("ptp_broad_date_window")
        if saved_window:
            exact_or_weekday_date = _date(original_text) or _weekday_date_in_window(original_text, str(saved_window), reference_date)
            if exact_or_weekday_date:
                date_issue = _date_window_violation(
                    exact_or_weekday_date, window=str(saved_window),
                    reference_date=reference_date, payment_already_made=False,
                )
                if date_issue:
                    _trace_policy(session, "Broad commitment-date validation", "clarification required", "The proposed date is not a future date within the broad window the caller supplied; preserve the window and ask for a matching day.")
                    return _reply(session, date_issue)
                session.scratch.pop("ptp_broad_date_window", None)
                session.scratch["ptp_date"] = exact_or_weekday_date
                session.pending = "ptp_confirmation"
                date_label = datetime.fromisoformat(exact_or_weekday_date).strftime("%d %B").lstrip("0")
                _trace_policy(session, "Broad commitment-date answer", "date captured", f"The caller supplied a specific date within the previously stated window ‘{saved_window}’.")
                return _reply(session, f"You expect to make the payment on {date_label}. Have I got that right?")
            if broad_date_window:
                _trace_policy(session, "Broad commitment-date repeat", "exact calendar date still required", f"The caller repeated a broad window ‘{broad_date_window}’; do not normalize it to a guessed date.")
                return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=False))
        elif broad_date_window and not _date(original_text):
            session.scratch["ptp_broad_date_window"] = broad_date_window
            session.scratch["ptp_proposed_date_text"] = transcript[:100]
            _trace_policy(session, "Broad commitment-date handling", "exact calendar date requested", f"The caller gave the broad time window ‘{broad_date_window}’; the bot asks for a specific date within that window without guessing.")
            return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=False))
        if commitment_intent_uncertain:
            _trace_policy(session, "Pending commitment clarification", "triggered", "The LLM did not confirm willingness to pay with high confidence; the bot clarifies instead of collecting or confirming a date.")
            return _reply(session, "I want to make sure I understood. Are you willing to make a payment, or are you unable to commit right now?")
        _trace_policy(session, "Payment-commitment capture", "evaluated", "The bot first confirms a future payment date; after confirmation it asks for an optional amount and offers OTP verification for the bank-recorded minimum due.")
        exact_date = _date(original_text)
        month_year_date = _month_year_date(original_text)
        pay_date = (
            exact_date or month_year_date
            or _exact_iso_calendar_date((extracted or {}).get("date_iso"))
            or session.scratch.get("ptp_date")
        )
        if pay_date and datetime.fromisoformat(pay_date).date() < datetime.now(timezone.utc).date():
            session.scratch["ptp_date_clarification_attempts"] = int(session.scratch.get("ptp_date_clarification_attempts", 0)) + 1
            if session.scratch["ptp_date_clarification_attempts"] >= PAYMENT_DATE_WAIT_ATTEMPTS:
                task = create_followup_task(session, "payment_commitment_date_unclear", transcript, "normal")
                session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT, fields={"reason": "past_or_unclear_payment_date", "agent_task_id": task["task_id"]}, follow_up_required=True, follow_up_reason="payment_commitment_date_unclear")
                session.pending = None
                session.terminal = True
                return TurnResponse(session_id=session.session_id, bot_text="I’m unable to confirm a future payment date, so I’ll ask our team to follow up with you. Thank you for your time.", terminal=True, outcome=session.outcome)
            session.pending = "ptp"
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0")
            return _reply(session, f"{date_label} has already passed. What future date should I note for your payment?")
        if pay_date and business_rule_engine.commitment_is_too_far((datetime.fromisoformat(pay_date).date() - datetime.now(timezone.utc).date()).days):
            session.scratch["ptp_far_future_date_iso"] = pay_date
            session.scratch["ptp_proposed_date_text"] = str((extracted or {}).get("date_phrase") or transcript[:100])
            session.scratch["ptp_far_future_active"] = True
            session.scratch["ptp_far_future_clarification_attempts"] = 0
            session.pending = "ptp_far_future_choice"
            _trace_policy(session, "Far-future commitment date", "clarification required", f"The proposed payment date is more than {FAR_FUTURE_COMMITMENT_DAYS} days away, so it is not recorded as a near-term commitment; ask for a sooner date or human discussion.")
            return _reply(session, "That date is quite some time away. Are you able to make the payment earlier, or would you like a colleague to call and discuss options?")
        if month_year_date and not exact_date:
            session.pending = "ptp"
            month_phrase = _month_year_phrase(original_text) or "that month"
            session.scratch["ptp_month_year_text"] = month_phrase
            _trace_policy(session, "Month-only payment timing", "exact day required", "The caller gave a month and year but no calendar day; the month anchor is used only to identify a far-future date, never to record an exact commitment.")
            return _reply(session, f"I’ve noted {month_phrase} as the timing. To record a payment commitment, what specific day in that month should I note?")
        if pay_date:
            session.scratch["ptp_date"] = pay_date
            volunteered_amount = _normalize_customer_amount((extracted or {}).get("amount_inr"))
            if volunteered_amount is not None:
                session.scratch["ptp_amount"] = volunteered_amount
            session.pending = "ptp_confirmation"
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0")
            return _reply(session, f"You expect to make the payment by {date_label}. Have I got that right?")
        session.pending = "ptp"
        return _reply(session, "When do you expect to make the payment?")

    if _has(text, _PAID):
        _trace_policy(session, "Already-paid handling", "triggered", "The caller reports that payment was made; the bot gathers details needed for reconciliation.")
        if broad_date_window:
            exact_window_weekday = _weekday_date_in_window(original_text, broad_date_window, reference_date)
            explicit_date = _date(original_text) or exact_window_weekday
            if not explicit_date:
                session.scratch["reported_payment_date_text"] = transcript[:120]
                session.scratch["reported_payment_broad_window"] = broad_date_window
                session.scratch["payment_date_clarification_attempts"] = 1
                mode = _mode(text)
                if mode:
                    session.scratch["reported_payment_mode"] = mode
                session.pending = "paid_date"
                _trace_policy(session, "Broad payment-date handling", "exact calendar date requested", f"The caller said the payment was in ‘{broad_date_window}’; the bot asks for a specific day within that window and does not guess.")
                return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=True))
            date_issue = _date_window_violation(
                explicit_date, window=broad_date_window, reference_date=reference_date,
                payment_already_made=True,
            )
            if date_issue:
                _trace_policy(session, "Reported payment date validation", "clarification required", "The date does not describe a past payment within the caller's stated window.")
                session.pending = "paid_date"
                session.scratch["reported_payment_broad_window"] = broad_date_window
                return _reply(session, date_issue)
            return _continue_reported_payment(session, explicit_date, _mode(text))
        if approximate_payment_date:
            session.scratch["reported_payment_date_text"] = transcript[:120]
            session.scratch["payment_date_clarification_attempts"] = 1
            mode = _mode(text)
            if mode:
                session.scratch["reported_payment_mode"] = mode
            session.pending = "paid_date"
            return _reply(session, _approximate_payment_date_reply())
        paid_date, mode = _date(text), _mode(text)
        if paid_date:
            _trace_policy(session, "Payment date and age handling", "selected", "An exact reported payment date is available; the policy checks its age before reconciliation or follow-up.")
            return _continue_reported_payment(session, paid_date, mode)
        if mode:
            session.scratch["reported_payment_mode"] = mode
            session.pending = "paid_date"
            return _reply(session, "Thank you. On what date did you make the payment?")
        session.pending = "paid_date"
        return _reply(session, "When did you make the payment, and through which mode?")

    if _has(text, _WAIVER):
        _trace_policy(session, "Fee-waiver handling", "triggered", "The caller requested a late-fee discount or waiver; the bot records a human follow-up and does not approve it.")
        return _record_waiver_request(session, transcript)

    if _has(text, _DISPUTE):
        _trace_policy(session, "Debt-dispute handling", "triggered", "The caller disputed the debt; the bot pauses collections and requests human review.")
        return _record_dispute(session, transcript)

    if _has(text, _CALLBACK):
        _trace_policy(session, "Callback scheduling", "triggered", "The caller requested a callback; the bot is collecting a preferred time.")
        session.pending = "callback_time"
        return _reply(session, "Of course. What day or time would be convenient for our team to call you?")

    classified_intent = (extracted or {}).get("intent")
    if classified_intent == "fee_applicability":
        _trace_policy(session, "Late-fee threshold clarification", "triggered", "The caller asked whether the late fee applies or corrected a balance in response to the fee threshold. The bot acknowledges the point, gives the approved rule, and offers OTP verification without treating a caller-stated amount as verified bank data.")
        session.pending = "balance_check_consent"
        estimate = _customer_balance_estimate(original_text)
        if estimate is not None and not business_rule_engine.late_fee_threshold_applies(estimate):
            reply = (f"Thanks for sharing your estimate of ₹{estimate:,}. If that estimate is accurate, it is not over {_threshold_text()}, "
                     f"so the stated threshold for the {_late_fee_text()} late fee is not met. The bank-recorded balance may differ. "
                     "Would you like me to check the bank-recorded balance using OTP verification?")
        elif estimate is not None:
            reply = (f"Thanks for sharing your estimate of ₹{estimate:,}. If the bank-recorded outstanding is over {_threshold_text()}, "
                     f"the {_late_fee_text()} late fee rule may apply; your estimate alone does not verify the bank balance or fee. "
                     "Would you like me to check the bank-recorded balance using OTP verification?")
        elif (extracted or {}).get("dialogue_act") == "corrects_previous":
            reply = f"Thanks for clarifying. If your estimate is accurate and the outstanding is not over {_threshold_text()}, the stated threshold for the {_late_fee_text()} late fee is not met. The bank-recorded balance may differ. Would you like me to check it using OTP verification?"
        else:
            reply = f"The {_late_fee_text()} late fee applies only if the bank-recorded outstanding is over {_threshold_text()}. I can check the bank-recorded balance using OTP verification if you’d like. Would you like me to check it now?"
        return _reply(session, reply)
    if classified_intent == "payment_commitment_interest":
        _trace_policy(session, "Tentative payment-willingness clarification", "triggered", "The caller sounds open to paying but has not made a definite commitment; the bot asks whether they can agree on a date or want to explain a difficulty, without collecting an amount or recording a commitment.")
        return _reply(session, "I hear you may be open to paying. Would you be comfortable agreeing on a date, or would you like to tell me what’s making payment difficult?")
    if classified_intent == "defer_payment_question" or _is_defer_payment_question(original_text):
        _trace_policy(session, "Unconfirmed payment deferral policy", "triggered", "The caller asked whether payment can be postponed. The assignment context does not define an extension policy, so the bot records a colleague follow-up rather than approving or rejecting the request.")
        return _record_payment_question_follow_up(session, transcript, "whether payment can be postponed")
    if classified_intent == "payment_method_question" or _is_cash_payment_question(original_text):
        _trace_policy(session, "Unconfirmed payment-method policy", "triggered", "The caller asked about an unsupported payment method. The bot does not guess bank policy and records a colleague follow-up.")
        return _record_payment_question_follow_up(session, transcript, "whether cash is accepted")
    if classified_intent == "payment_policy_question":
        _trace_policy(session, "Unsupported payment-policy question", "triggered", "The caller asked a payment-process question that is not covered by approved information; the bot records a colleague follow-up instead of improvising.")
        return _record_payment_question_follow_up(session, transcript, "an unsupported payment policy or process")
    if (
        classified_intent in {None, "unclear"}
        and (
            _is_unmapped_payment_question(original_text)
            or (
                _has(original_text, _PAYMENT_TERMS)
                and (extracted or {}).get("dialogue_act") in {"asks_question", "new_request"}
            )
        )
    ):
        _trace_policy(session, "Unmapped payment question", "triggered", "The caller asked a payment-related question that did not match an approved answer. The bot records a colleague follow-up rather than guessing.")
        return _record_payment_question_follow_up(session, transcript, "an unsupported payment policy or process")
    if commitment_intent_uncertain and session.scratch.get("right_party_confirmed"):
        _trace_policy(session, "Ambiguous payment-intent clarification", "triggered", "The LLM did not classify the customer's payment intent with high confidence, so the bot asks what they mean instead of entering commitment capture.")
        return _reply(session, "Just to check I understood: are you willing to make a payment, or are you unable to commit right now?")
    if classified_intent == "offer_request":
        _trace_policy(session, "Offer request boundary", "triggered", "A conditional request for an offer is not a payment commitment; no payment amount or date is collected.")
        return _reply(session, "I understand you’d like to know the current offer before deciding about payment. I don’t have the offer details available in this call. I can ask our team to contact you about it, or we can continue with the payment options. Which would you prefer?")
    if (extracted or {}).get("dialogue_act") == "corrects_previous" and session.scratch.get("right_party_confirmed"):
        _trace_policy(session, "Contextual correction clarification", "triggered", "The caller is correcting or qualifying an earlier point, but the specific correction did not map to an approved topic. The bot acknowledges the correction and asks a focused clarification instead of repeating the generic payment menu.")
        return _reply(session, "Thanks for clarifying. I want to make sure I respond to the right point—what would you like me to correct or explain?")
    if classified_intent == "account_identification_question":
        _trace_policy(session, "Card-reference clarification", "triggered", "The caller asked which card this call concerns; the bot uses only the masked account reference attached to this call.")
        account_reference = session.request.masked_account_reference or ""
        last_four = re.search(r"(\d{4})\D*$", account_reference)
        if last_four:
            reply = (f"I’m referring to the Mumbai Bank card ending in {last_four.group(1)}, which is the account linked to this call. "
                     "I can’t see your other cards here. Have you already paid this card, would you like to tell me when you can pay, or would you prefer a callback?")
        else:
            reply = ("I can only see the Mumbai Bank account linked to this call, and I don’t have its card reference available here. "
                     "Would you prefer a callback to confirm the card, or should we continue with the pending payment?")
        return _reply(session, reply)

    if classified_intent == "payment_question":
        _trace_policy(session, "Pending-payment explanation", "triggered", "The caller asked what payment this call concerns; the bot explains the call purpose without treating it as a balance request.")
        return _reply(session, f"This call is about the overdue minimum payment on your Mumbai Bank credit card. Interest is charged at {_monthly_interest_text()}, and a late fee of {_late_fee_text()} may apply if the outstanding balance is over {_threshold_text()}. What would you like me to clarify about the payment?")

    if classified_intent == "otp_request":
        _trace_policy(session, "OTP request without protected-data request", "blocked", "The caller asked for an OTP but did not request protected account data; no OTP challenge was created.")
        return _reply(session, "You don’t need an OTP to discuss this payment. I only request one before sharing protected information such as a balance. Are you asking for your balance, or would you like to discuss the pending payment?")

    if explicit_balance_info_request or balance_check_consented:
        session.pending = None
        return _start_balance_verification(session, transcript)

    if RULES.has(text, "interest_reference") or _has(text, _INTEREST) or classified_intent == "interest_question":
        if _is_interest_concern(original_text):
            session.pending = "interest_follow_up_consent"
            session.scratch["interest_concern_transcript"] = transcript
            _trace_policy(session, "Interest concern acknowledgment", "callback offered", "The customer expressed concern about the high interest rate. The bot acknowledges the concern, states it cannot change the rate, and asks whether the customer wants a human callback.")
            return _reply(session, "I understand you feel the interest rate is high. I can’t change the rate, but I can note your concern and arrange for a human colleague to call you. Would you like me to arrange that?")
        _trace_policy(session, "Related question: interest explanation", "triggered", "The caller asked a tangential but relevant question about card interest. The bot gives the approved rate and a plain-language explanation, avoids calculating an account-specific charge, then returns to the payment menu.")
        session.pending = None
        return _reply(session, f"Interest is charged on an unpaid credit-card balance and may accrue when it remains unpaid past the due date. The rate provided for this call is {_monthly_interest_text()}; I can’t calculate the exact charge here. Have you already paid, or when do you expect to pay the minimum due?")

    if _has(text, _FEE):
        _trace_policy(session, "Fee disclosure safeguard", "triggered", "The bot gives only the configured fee information and does not claim the fee applies to this account without verification.")
        session.pending = "balance_check_consent"
        return _reply(session, f"The late fee is {_late_fee_text()} when the outstanding balance is over {_threshold_text()}. I can’t confirm whether it applies to your account without secure OTP verification. Would you like me to check the bank-recorded balance now?")

    if classified_intent == "related_question":
        _trace_policy(session, "Related question: approved-context boundary", "triggered", "The caller asked a tangential question connected to the overdue card payment. No approved answer matched, so the bot records a colleague follow-up rather than guessing or dismissing it as unrelated.")
        return _record_payment_question_follow_up(session, transcript, "a related card-payment question not covered by the approved information")

    if (_has(original_text, _PRODUCTS + _CREDIT_SCORE + _LEGAL)
            and _is_low_signal_utterance(transcript, extracted, stt_confidence)):
        session.scratch["suppress_acknowledgment"] = True
        _trace_policy(session, "Weakly recognized topic clarification", "triggered", "A potentially out-of-scope phrase was very short or had low speech-recognition confidence. The bot asks what the caller meant before routing it away from the payment conversation.")
        return _reply(session, _low_signal_clarification(session))

    if _has(text, _CREDIT_SCORE):
        _trace_policy(session, "Collections scope control", "triggered", "Credit-score advice is outside this bot’s scope; the caller is directed to the bank helpline.")
        return _reply(session, "I can’t help with credit-score questions. Please contact the bank helpline for that query. I’m here to help with your pending payment.")

    if _has(text, _LEGAL):
        _trace_policy(session, "Legal-advice boundary", "triggered", "The bot does not provide legal advice and directs the caller to the bank helpline.")
        return _reply(session, "I can’t provide legal advice. Please contact the bank helpline for guidance. I’m here to help with your pending payment.")

    # Only direct customer mentions of another bank product should be sent to
    # a branch/helpline. ``text`` may also contain the classifier's canonical
    # label "another product" for an unrelated question (for example, cricket),
    # which must return to the collections conversation instead.
    if _has(original_text, _PRODUCTS):
        _trace_policy(session, "Collections scope control", "triggered", "The requested product is outside this collections conversation.")
        return _reply(session, "I’m only here for your pending payment. For other queries, please visit a branch or call the helpline.")

    if extracted and (
        extracted.get("intent") == "unclear"
        or extracted.get("dialogue_act") in {"asks_question", "new_request"}
        or (extracted.get("intent") == "other_product" and _is_low_signal_utterance(transcript, extracted, stt_confidence)
            and not _has_explicit_out_of_scope_topic(original_text))
    ) or (session.scratch.get("right_party_confirmed") and _is_low_signal_utterance(transcript, extracted, stt_confidence)
          and not _has_explicit_out_of_scope_topic(original_text)):
        if _is_low_signal_utterance(transcript, extracted, stt_confidence):
            session.scratch["suppress_acknowledgment"] = True
        payment_adjacent = _has(original_text, _PAYMENT_TERMS + _FEE + _INTEREST) or explicit_balance_info_request
        if payment_adjacent:
            _trace_policy(session, "Payment-adjacent clarification", "triggered", "The caller raised an unclear topic related to the payment; the bot offers a focused clarification and approved next steps.")
            return _reply(session, "I’m not sure which payment detail you mean. Are you asking whether a payment has been received, or would you like me to check the bank-recorded balance after OTP verification?")
        if _is_low_signal_utterance(transcript, extracted, stt_confidence) and not _has_explicit_out_of_scope_topic(original_text):
            session.scratch["suppress_acknowledgment"] = True
            _trace_policy(session, "Low-signal speech clarification", "triggered", "The utterance was very short or classified with low confidence. It is treated as potentially incomplete or weakly heard speech, not as an unrelated topic; the active question remains open.")
            return _reply(session, _low_signal_clarification(session))
        _trace_policy(session, "Unrelated-topic boundary", "triggered", "The caller asked about a topic outside this collections call; the bot declines briefly and returns to the overdue-payment outcome choices.")
        return _reply(session, "I can’t help with that question on this call, but I can help with your overdue payment. Have you already paid, or when do you expect to pay the minimum due?")

    if classified_intent == "promise_to_pay" and (extracted or {}).get("intent_confidence") == "high" and not _has(original_text, _NEGATED_COMMITMENT):
        _trace_policy(session, "Payment-commitment capture", "triggered", "The caller is discussing a future payment; the bot records the expected date without requiring an amount.")
        session.pending = "ptp"
        exact_date = _date(original_text)
        if broad_date_window and not exact_date:
            session.scratch["ptp_broad_date_window"] = broad_date_window
            session.scratch["ptp_proposed_date_text"] = transcript[:100]
            _trace_policy(session, "Broad commitment-date handling", "exact calendar date requested", f"The caller gave the broad time window ‘{broad_date_window}’; the bot asks for a specific date within that window without guessing.")
            return _reply(session, _broad_date_follow_up(broad_date_window, payment_already_made=False))
        month_year_date = _month_year_date(original_text)
        pay_date = (
            exact_date or month_year_date
            or _exact_iso_calendar_date((extracted or {}).get("date_iso"))
            or _date(text)
        )
        if pay_date and datetime.fromisoformat(pay_date).date() < datetime.now(timezone.utc).date():
            session.scratch["ptp_date_clarification_attempts"] = int(session.scratch.get("ptp_date_clarification_attempts", 0)) + 1
            if session.scratch["ptp_date_clarification_attempts"] >= PAYMENT_DATE_WAIT_ATTEMPTS:
                task = create_followup_task(session, "payment_commitment_date_unclear", transcript, "normal")
                session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT, fields={"reason": "past_or_unclear_payment_date", "agent_task_id": task["task_id"]}, follow_up_required=True, follow_up_reason="payment_commitment_date_unclear")
                session.pending = None
                session.terminal = True
                return TurnResponse(session_id=session.session_id, bot_text="I’m unable to confirm a future payment date, so I’ll ask our team to follow up with you. Thank you for your time.", terminal=True, outcome=session.outcome)
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0")
            return _reply(session, f"{date_label} has already passed. What future date should I note for your payment?")
        if pay_date and business_rule_engine.commitment_is_too_far((datetime.fromisoformat(pay_date).date() - datetime.now(timezone.utc).date()).days):
            session.scratch["ptp_far_future_date_iso"] = pay_date
            session.scratch["ptp_proposed_date_text"] = str((extracted or {}).get("date_phrase") or original_text[:100])
            session.scratch["ptp_far_future_active"] = True
            session.scratch["ptp_far_future_clarification_attempts"] = 0
            session.pending = "ptp_far_future_choice"
            _trace_policy(session, "Far-future commitment date", "clarification required", f"The proposed payment date is more than {FAR_FUTURE_COMMITMENT_DAYS} days away, so it is not recorded as a near-term commitment; ask for a sooner date or human discussion.")
            return _reply(session, "That date is quite some time away. Are you able to make the payment earlier, or would you like a colleague to call and discuss options?")
        if month_year_date and not exact_date:
            session.pending = "ptp"
            month_phrase = _month_year_phrase(original_text) or "that month"
            session.scratch["ptp_month_year_text"] = month_phrase
            _trace_policy(session, "Month-only payment timing", "exact day required", "The caller gave a month and year but no calendar day; the month anchor is used only to identify a far-future date, never to record an exact commitment.")
            return _reply(session, f"I’ve noted {month_phrase} as the timing. To record a payment commitment, what specific day in that month should I note?")
        if pay_date:
            session.scratch["ptp_date"] = pay_date
            session.pending = "ptp_confirmation"
            date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0")
            return _reply(session, f"You expect to make the payment by {date_label}. Have I got that right?")
        return _reply(session, "When do you expect to make the payment?")

    if business_rule_engine.turn_limit_reached(session.turn_count):
        task = create_followup_task(session, "conversation_limit_reached", transcript, "normal")
        session.outcome = Outcome(
            type=OutcomeType.NO_COMMITMENT,
            fields={"reason": "conversation_limit_reached", "agent_task_id": task["task_id"]},
            follow_up_required=True,
            follow_up_reason="human_follow_up_needed",
        )
        session.terminal = True
        return TurnResponse(session_id=session.session_id, bot_text="I’ll arrange for a human agent to follow up. Thank you for your time.", terminal=True, outcome=session.outcome)

    _trace_policy(session, "Payment-resolution prompt", "selected", "No higher-priority intent was selected; the bot offers the supported payment, commitment, and callback paths.")
    return _reply(session, "I can help with the pending payment. Have you already paid, when do you expect to pay, or would you prefer a callback?")


def record_contact_opt_out(session: CallSession, source: str, reason: str = "customer_requested_no_contact") -> TurnResponse:
    bank_services.set_contact_preference(
        session.request.customer_id, session.request.contact_point_id, "voice", True,
        reason[:200], source, "collections-bot",
    )
    session.outcome = Outcome(type=OutcomeType.OPT_OUT, fields={"channel": "voice", "source": source})
    session.pending = None
    session.terminal = True
    return TurnResponse(session_id=session.session_id,
                        bot_text="Understood. I’ve recorded your request not to receive collection calls at this contact point.",
                        terminal=True, outcome=session.outcome)


def process_otp_code(session: CallSession, code: str) -> TurnResponse:
    if session.pending != "otp_code":
        return TurnResponse(session_id=session.session_id, bot_text="There is no active verification request.", terminal=session.terminal, outcome=session.outcome)
    challenge_id = session.scratch.get("otp_challenge_id")
    if not challenge_id or len(code) != 6 or not code.isdigit():
        return _reply(session, "Please enter the six-digit code using your phone keypad.")
    result = bank_services.verify_otp(challenge_id, code)
    if not result["verified"]:
        if result["reason"] == "attempt_limit":
            task = create_followup_task(session, "otp_verification_failed", "OTP verification attempt limit reached", "high")
            session.pending = None
            session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT,
                                     fields={"reason": "otp_verification_failed", "agent_task_id": task["task_id"]},
                                     follow_up_required=True, follow_up_reason="human_follow_up_needed")
            session.terminal = True
            return TurnResponse(session_id=session.session_id,
                                bot_text="I couldn’t complete verification. I’ll arrange for a human agent to help you.",
                                terminal=True, outcome=session.outcome)
        return _reply(session, "That code couldn’t be verified. Please try again using your phone keypad, or say ‘callback’ for help.")
    try:
        balance = bank_services.get_balance(session.request.account_id, result["verification_token"])
    except (PermissionError, LookupError):
        task = create_followup_task(session, "verified_balance_lookup_failed", "Verified balance lookup failed", "high")
        session.pending = None
        session.outcome = Outcome(type=OutcomeType.NO_COMMITMENT,
                                 fields={"reason": "verified_balance_lookup_failed", "agent_task_id": task["task_id"]},
                                 follow_up_required=True, follow_up_reason="human_follow_up_needed")
        session.terminal = True
        return TurnResponse(session_id=session.session_id,
                            bot_text="Verification succeeded, but I couldn’t retrieve the account details. I’ll arrange a human callback.",
                            terminal=True, outcome=session.outcome)
    session.pending = None
    session.scratch["balance_verified"] = True
    session.scratch["verified_minimum_due"] = str(balance["minimum_due"])
    session.scratch["otp_challenge_id"] = None
    session.outcome = None
    if session.scratch.pop("ptp_amount_after_otp", False):
        session.pending = "ptp_amount"
        session.scratch["verified_minimum_due"] = str(balance["minimum_due"])
        pay_date = session.scratch.get("ptp_date")
        date_label = datetime.fromisoformat(pay_date).strftime("%d %B").lstrip("0") if pay_date else "the date you gave"
        return TurnResponse(
            session_id=session.session_id,
            bot_text=(f"Your verified minimum due is {balance['currency']} {balance['minimum_due']}, "
                      f"due by {balance['due_date']}. For your payment on {date_label}, "
                      "what amount would you like me to note?"),
        )
    return TurnResponse(
        session_id=session.session_id,
        bot_text=(f"Your verified current balance is {balance['currency']} {balance['balance']}. "
                  f"The minimum due is {balance['currency']} {balance['minimum_due']}, due by {balance['due_date']}. "
                  "Would you like me to clarify any of those details?"),
    )


def create_followup_task(session: CallSession, reason: str, summary: str, priority: str,
                         callback_time: str | None = None) -> dict:
    return bank_services.create_agent_task(
        idempotency_key=f"{session.session_id}:{reason}",
        case_id=session.request.case_id,
        episode_id=session.request.episode_id,
        customer_id=session.request.customer_id,
        account_id=session.request.account_id,
        reason=reason,
        priority=priority,
        summary=summary,
        callback_time=callback_time,
    )


def _finish_paid(session: CallSession, paid_date: str, mode: str) -> TurnResponse:
    reconciliation = bank_services.reconcile_payment(session.request.account_id, paid_date, mode)
    age_days = _payment_age_days(paid_date)
    recent_payment = age_days is not None and 0 <= age_days <= RECENT_PAYMENT_DAYS
    ledger_confirmed = reconciliation["status"] == "confirmed"
    needs_follow_up = not ledger_confirmed and not recent_payment
    fields = {
        "reported_payment_date": paid_date,
        "reported_payment_mode": mode,
        "verification_status": "customer_reported",
        "reconciliation_status": reconciliation["status"],
    }
    task_id = None
    if reconciliation.get("payment_id"):
        fields["payment_id"] = reconciliation["payment_id"]
        fields["payment_reference"] = reconciliation.get("reference")
    if needs_follow_up:
        task = create_followup_task(session, "payment_reconciliation_review",
                                     f"Customer reported payment on {paid_date} via {mode}; ledger status: {reconciliation['status']}", "normal")
        task_id = task["task_id"]
        fields["agent_task_id"] = task_id
    session.outcome = Outcome(
        type=OutcomeType.ALREADY_PAID_REPORTED,
        fields=fields,
        follow_up_required=needs_follow_up,
        follow_up_reason="payment_reconciliation_review" if task_id else None,
    )
    session.pending = None
    session.terminal = True
    if ledger_confirmed:
        reply = "Thank you. The bank ledger confirms this payment."
        if recent_payment:
            reply += f" It can take up to {REFLECTION_WORKING_DAYS} working days to appear in the account view."
    elif recent_payment:
        reply = f"Thank you. I’ve recorded your payment details. It can take up to {REFLECTION_WORKING_DAYS} working days to reflect, so it should appear soon."
    else:
        reply = "Thank you. I’ve recorded the payment details, but the bank ledger hasn’t confirmed the payment yet. I’ve asked a human agent to check the records and get back to you."
    reply += " That’s all the information I needed, so I’ll end the call now. Goodbye."
    return TurnResponse(
        session_id=session.session_id,
        bot_text=reply,
        terminal=True,
        outcome=session.outcome,
    )


def _reply(session: CallSession, text: str) -> TurnResponse:
    _sync_pending_question(session)
    return TurnResponse(session_id=session.session_id, bot_text=text, terminal=False, outcome=None)


def _identity_silent_wait(session: CallSession, spoken_text: str = "") -> TurnResponse:
    """Keep listening during identity confirmation; defer a repeat until silence."""
    session.scratch["awaiting_identity_confirmation"] = True
    session.scratch["identity_wait_prompt_given"] = True
    session.scratch["identity_silent_wait"] = True
    response = _reply(session, spoken_text)
    response.metadata["identity_pause_check"] = True
    response.metadata["identity_pause_ms"] = 3000
    return response

