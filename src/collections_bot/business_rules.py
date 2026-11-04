"""Versioned, editable business rules for the collections voicebot.

Edit ``business_rules.json`` for policy facts, thresholds and phrase cues. Keep
the rule evaluator here small and deterministic; conversation orchestration and
external side effects remain in their own modules.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BusinessRules:
    version: str
    facts: dict[str, Any]
    thresholds: dict[str, int]
    calling_frequency: dict[str, int]
    phrases: dict[str, tuple[str, ...]]
    patterns: dict[str, re.Pattern[str]]
    pending_question_contracts: dict[str, tuple[str, tuple[str, ...]]]
    pending_slot_intents: frozenset[str]

    def phrase(self, name: str) -> tuple[str, ...]:
        try:
            return self.phrases[name]
        except KeyError as exc:
            raise KeyError(f"Unknown business-rule phrase group: {name}") from exc

    def has(self, text: str, name: str) -> bool:
        normalized = text.casefold()
        return any(phrase in normalized for phrase in self.phrase(name))

    def pattern_search(self, name: str, text: str) -> re.Match[str] | None:
        try:
            return self.patterns[name].search(text)
        except KeyError as exc:
            raise KeyError(f"Unknown business-rule pattern: {name}") from exc


def _load_rules(path: Path) -> BusinessRules:
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("version", "facts", "thresholds", "calling_frequency", "phrases", "patterns", "pending_question_contracts", "pending_slot_intents"):
        if key not in raw:
            raise ValueError(f"Business rules file is missing required section: {key}")
    if not isinstance(raw["version"], str) or not raw["version"].strip():
        raise ValueError("Business rules version must be a non-empty string")
    required_facts = {
        "currency", "monthly_interest_rate_percent", "late_fee_inr",
        "late_fee_balance_threshold_inr", "payment_reflection_working_days",
    }
    required_thresholds = {
        "recent_payment_days", "old_payment_review_days", "far_future_commitment_days",
        "maximum_call_seconds", "maximum_turns", "identity_confirmation_attempts",
        "payment_date_wait_attempts", "low_signal_word_count", "low_stt_confidence_percent",
    }
    required_frequency = {
        "allowed_start_hour", "allowed_end_hour", "max_attempts_per_local_day",
        "max_attempts_per_rolling_7_days", "min_interval_minutes",
    }
    required_phrases = {
        "abuse", "distress", "paid", "late_fee_discount", "waiver", "not_paid", "payment_refusal",
        "balance", "balance_check", "defer_payment", "defer_period", "payment_method_question",
        "payment_terms", "question", "card_reference_question", "otp_question", "payment_purpose_question",
        "products", "dispute", "callback", "payment_link", "commitment", "negated_commitment",
        "offer_request", "offer_reference", "conditional_offer", "interest", "interest_reference",
        "interest_concern", "fee", "credit_score", "legal", "identity_info_question", "frustration",
        "hurry", "you_called", "greeting", "affirm", "negative", "uncertain_confirmation",
        "needs_time_to_check", "not_available", "opt_out", "refusal_reason", "payment_mode_upi",
        "payment_mode_net_banking", "payment_mode_imps", "payment_mode_neft", "payment_mode_cheque",
        "payment_mode_cash", "payment_mode_card", "payment_mode_autopay",
    }
    required_patterns = {
        "balance_info_request", "interest_concern", "clear_yes", "clear_no",
        "customer_balance_estimate", "approximate_payment_date", "identity_self_identification",
    }
    for section, required in (("facts", required_facts), ("thresholds", required_thresholds),
                              ("calling_frequency", required_frequency), ("phrases", required_phrases),
                              ("patterns", required_patterns)):
        missing = required - set(raw[section])
        if missing:
            raise ValueError(f"Business rules section {section!r} is missing: {', '.join(sorted(missing))}")
    thresholds = {str(key): int(value) for key, value in raw["thresholds"].items()}
    frequency = {str(key): int(value) for key, value in raw["calling_frequency"].items()}
    if any(value < 0 for value in thresholds.values()):
        raise ValueError("Business rule thresholds cannot be negative")
    if not 0 <= frequency.get("allowed_start_hour", -1) <= 23:
        raise ValueError("calling_frequency.allowed_start_hour must be between 0 and 23")
    if not 1 <= frequency.get("allowed_end_hour", -1) <= 24:
        raise ValueError("calling_frequency.allowed_end_hour must be between 1 and 24")
    phrases = {
        str(key): tuple(str(phrase).casefold() for phrase in values if str(phrase).strip())
        for key, values in raw["phrases"].items()
        if isinstance(values, list)
    }
    if len(phrases) != len(raw["phrases"]):
        raise ValueError("Every business-rule phrase group must be a list of phrases")
    if any(not values for values in phrases.values()):
        raise ValueError("Business rule phrase groups cannot be empty")
    patterns = {str(key): re.compile(str(value), re.IGNORECASE) for key, value in raw["patterns"].items()}
    contracts = {
        str(key): (str(value[0]), tuple(str(item) for item in value[1]))
        for key, value in raw["pending_question_contracts"].items()
    }
    return BusinessRules(
        version=raw["version"],
        facts=dict(raw["facts"]),
        thresholds=thresholds,
        calling_frequency=frequency,
        phrases=phrases,
        patterns=patterns,
        pending_question_contracts=contracts,
        pending_slot_intents=frozenset(str(value) for value in raw["pending_slot_intents"]),
    )


def load_business_rules(path: str | None = None) -> BusinessRules:
    """Load configured rules; an explicit path enables alternate campaign rulesets."""
    configured_path = path or os.getenv("COLLECTIONS_BUSINESS_RULES_PATH")
    rules_path = Path(configured_path) if configured_path else Path(__file__).with_name("business_rules.json")
    return _load_rules(rules_path)


business_rules = load_business_rules()


class BusinessRuleEngine:
    """Deterministic access/evaluation facade over the active rule version."""

    def __init__(self, rules: BusinessRules = business_rules):
        self.rules = rules

    @property
    def version(self) -> str:
        return self.rules.version

    def matches(self, text: str, phrase_group: str) -> bool:
        return self.rules.has(text, phrase_group)

    def pattern_matches(self, text: str, pattern_name: str) -> bool:
        return self.rules.pattern_search(pattern_name, text) is not None

    def payment_age_band(self, age_days: int | None) -> str:
        """Return the configured operational band for a reported payment date."""
        if age_days is None:
            return "unknown"
        if age_days < 0:
            return "future_date"
        if age_days <= self.rules.thresholds["recent_payment_days"]:
            return "recent"
        if age_days > self.rules.thresholds["old_payment_review_days"]:
            return "old_review"
        return "reconciliation_review"

    def late_fee_threshold_applies(self, outstanding_inr: int | float) -> bool:
        """The approved fee condition is strictly greater than the configured threshold."""
        return outstanding_inr > float(self.rules.facts["late_fee_balance_threshold_inr"])

    def commitment_is_too_far(self, days_from_today: int) -> bool:
        return days_from_today > self.rules.thresholds["far_future_commitment_days"]

    def identity_limit_reached(self, attempts: int) -> bool:
        return attempts >= self.rules.thresholds["identity_confirmation_attempts"]

    def call_time_limit_reached(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds >= self.rules.thresholds["maximum_call_seconds"]

    def turn_limit_reached(self, turns: int) -> bool:
        return turns >= self.rules.thresholds["maximum_turns"]


business_rule_engine = BusinessRuleEngine()
