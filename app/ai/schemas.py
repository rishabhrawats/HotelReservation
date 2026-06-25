from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AllowedIntent = Literal[
    "booking_request",
    "availability_check",
    "booking_enquiry",
    "booking_cancellation",
    "booking_modification",
    "policy_question",
    "amenity_question",
    "invoice_request",
    "early_checkin_request",
    "late_checkout_request",
    "room_preference_request",
    "bed_type_request",
    "parking_request",
    "taxi_transfer_request",
    "luggage_storage_request",
    "special_occasion_request",
    "accessibility_request",
    "pet_policy_question",
    "refund_cancellation_policy_question",
    "complaint",
    "unknown",
]

NextAction = Literal[
    "no_action",
    "ask_missing_details",
    "answer_policy_question",
    "acknowledge_booking_request",
    "answer_question_and_acknowledge_booking",
    "cancellation_human_review",
    "modification_human_review",
    "complaint_human_review",
    "escalate_to_human",
]

FinalStatus = Literal[
    "POLICY_ANSWERED",
    "AVAILABILITY_QUOTED",
    "BOOKING_ACKNOWLEDGED",
    "BOOKING_MISSING_DETAILS",
    "BOOKING_CREATED",
    "BOOKING_ALTERNATIVES",
    "BOOKING_UNAVAILABLE",
    "BOOKING_CANCELLED",
    "ORACLE_FAILED",
    "POLICY_ANSWERED_AND_BOOKING_ACKNOWLEDGED",
    "POLICY_ANSWERED_AND_BOOKING_MISSING_DETAILS",
    "HUMAN_REVIEW",
    "DRAFT_CREATED",
    "SENT",
    "FAILED",
]

ReplyStatus = Literal["DRAFT_ONLY", "SENT", "FAILED"]

ReplyType = Literal[
    "policy_answer",
    "availability_quote",
    "booking_acknowledgement",
    "missing_details",
    "policy_answer_plus_booking_acknowledgement",
    "policy_answer_plus_missing_details",
    "booking_created",
    "booking_alternatives",
    "booking_unavailable",
    "booking_cancelled",
    "booking_lookup",
    "human_review_acknowledgement",
    "unknown_request",
]

OracleOperation = Literal[
    "none",
    "availability_checked",
    "booking_created",
    "booking_alternatives",
    "booking_unavailable",
    "booking_cancelled",
    "booking_lookup",
    "failed",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(StrictModel):
    email_id: str
    internet_message_id: str | None
    subject: str
    sender_name: str | None
    sender_email: str
    received_datetime: str
    body_text: str
    is_read: bool | None = None


class BookingRequest(StrictModel):
    guest_name: str | None = None
    arrival_date: str | None = None
    departure_date: str | None = None
    adults: int | None = None
    children: int | None = None
    rooms: int | None = None
    room_type: str | None = None
    hotel_code: str | None = None
    property_name: str | None = None
    booking_reference: str | None = None
    ota_reference: str | None = None
    custom_reference: str | None = None
    special_requests: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class PolicyQuestion(StrictModel):
    question: str
    category: str | None = None
    needs_rag_answer: bool


class IntentResult(StrictModel):
    primary_intent: AllowedIntent
    secondary_intents: list[AllowedIntent] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_review: bool
    human_review_reason: str | None = None
    customer_message_summary: str
    booking_request: BookingRequest | None = None
    questions: list[PolicyQuestion] = Field(default_factory=list)
    next_action: NextAction


class PolicyAnswer(StrictModel):
    question: str
    answer: str
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    insufficient_policy_context: bool


class OracleAvailabilityOption(StrictModel):
    arrival_date: str
    departure_date: str
    room_type: str
    rate_plan_code: str | None = None
    number_of_units: int | None = None
    amount_before_tax: float | None = None
    currency_code: str | None = None
    is_requested_dates: bool = False


class OracleOperationResult(StrictModel):
    operation: OracleOperation
    success: bool
    message: str
    requested_arrival_date: str | None = None
    requested_departure_date: str | None = None
    options: list[OracleAvailabilityOption] = Field(default_factory=list)
    reservation_id: str | None = None
    confirmation_number: str | None = None
    cancellation_id: str | None = None
    custom_reference: str | None = None
    error: str | None = None


class ReplyResult(StrictModel):
    reply_subject: str
    reply_body: str
    reply_type: ReplyType
    should_send: bool
    requires_human_review: bool
    reason: str | None = None


class FinalProcessingResult(StrictModel):
    email: EmailInput
    intent: IntentResult
    policy_answers: list[PolicyAnswer] = Field(default_factory=list)
    oracle_result: OracleOperationResult | None = None
    reply: ReplyResult
    final_status: FinalStatus
    errors: list[str] = Field(default_factory=list)
