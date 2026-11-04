from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttemptDisposition(StrEnum):
    RESERVED = "reserved"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    VOICEMAIL = "voicemail"
    CONNECTED_CUSTOMER = "connected_customer"
    CONNECTED_THIRD_PARTY = "connected_third_party"
    INVALID_NUMBER = "invalid_number"
    NETWORK_FAILURE = "network_failure"
    CUSTOMER_DISCONNECTED = "customer_disconnected"
    TRANSFER_COMPLETED = "transfer_completed"
    BLOCKED_BY_POLICY = "blocked_by_policy"


class OutcomeType(StrEnum):
    PROMISE_TO_PAY = "promise_to_pay"
    ALREADY_PAID_REPORTED = "already_paid_reported"
    CALLBACK_REQUEST = "callback_request"
    PAYMENT_LINK_REQUEST = "payment_link_request"
    DISPUTE_TRANSFER = "dispute_transfer"
    WAIVER_REQUEST = "waiver_request"
    NO_COMMITMENT = "no_commitment"
    OPT_OUT = "opt_out"


class FrequencyPolicy(BaseModel):
    version: str
    allowed_start_hour: int = Field(ge=0, le=23)
    allowed_end_hour: int = Field(ge=1, le=24)
    max_attempts_per_local_day: int = Field(gt=0)
    max_attempts_per_rolling_7_days: int = Field(gt=0)
    min_interval_minutes: int = Field(ge=0)


class StartCallRequest(BaseModel):
    case_id: str
    episode_id: str
    customer_id: str
    account_id: str
    contact_point_id: str
    timezone: str = "Asia/Kolkata"
    first_name: str | None = None
    last_name: str | None = None
    days_past_due: int = Field(ge=1, le=30)
    masked_account_reference: str | None = None
    campaign_id: str | None = None
    eligibility_confirmed: bool = False
    contact_allowed: bool = False
    contact_policy_version: str | None = None


class CallStarted(BaseModel):
    session_id: UUID
    attempt_id: UUID
    case_id: str
    opening: str
    frequency_policy_version: str


class TurnRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    heard_before_opening: bool = False
    stt_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OtpCodeRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class Outcome(BaseModel):
    type: OutcomeType
    fields: dict[str, Any] = Field(default_factory=dict)
    follow_up_required: bool = False
    follow_up_reason: str | None = None


class TurnResponse(BaseModel):
    session_id: UUID
    bot_text: str
    terminal: bool = False
    outcome: Outcome | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompleteCallRequest(BaseModel):
    disposition: AttemptDisposition = AttemptDisposition.CONNECTED_CUSTOMER


class CompletionResponse(BaseModel):
    session_id: UUID
    case_id: str
    disposition: AttemptDisposition
    outcome: Outcome | None
    delivery_status: str
    event_id: UUID | None = None


class CallSession(BaseModel):
    session_id: UUID
    attempt_id: UUID
    request: StartCallRequest
    started_at: datetime
    turn_count: int = 0
    pending: str | None = None
    scratch: dict[str, Any] = Field(default_factory=dict)
    outcome: Outcome | None = None
    terminal: bool = False
    bot_version: str = "rules-v0"


class AttemptRecord(BaseModel):
    attempt_id: UUID
    case_id: str
    episode_id: str
    customer_id: str
    account_id: str
    contact_point_id: str
    campaign_id: str | None = None
    attempted_at: datetime
    timezone: str
    disposition: AttemptDisposition
    ruleset_version: str
    contact_policy_version: str | None = None
    policy_reason: str = "allowed"


class CustomerOutcomeEvent(BaseModel):
    event_id: UUID
    case_id: str
    episode_id: str
    interaction_id: UUID
    customer_id: str
    account_id: str
    occurred_at: datetime
    contact_disposition: AttemptDisposition
    outcome: Outcome | None
    bot_version: str
    campaign_id: str | None = None

