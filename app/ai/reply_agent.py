from __future__ import annotations

import json
import logging
import re

from app.ai.prompts import REPLY_SYSTEM_PROMPT
from app.ai.schemas import (
    EmailInput,
    IntentResult,
    OracleAvailabilityOption,
    OracleOperationResult,
    PolicyAnswer,
    ReplyResult,
    ReplyType,
)
from app.config import Settings, load_settings
from app.email.reply_templates import (
    booking_details_sentence,
    reply_subject,
    user_friendly_missing_fields,
)

logger = logging.getLogger(__name__)


def generate_reply(
    email: EmailInput,
    intent: IntentResult,
    policy_answers: list[PolicyAnswer],
    settings: Settings | None = None,
    oracle_result: OracleOperationResult | None = None,
) -> ReplyResult:
    settings = settings or load_settings()
    if oracle_result:
        return build_oracle_reply(email, intent, policy_answers, oracle_result, settings)
    if settings.strict_real_mode:
        settings.require_openai_credentials()
    if settings.openai_api_key:
        try:
            reply = _generate_with_openai(email, intent, policy_answers, settings)
            return _enforce_reply_safety(reply, settings, intent, policy_answers)
        except Exception as exc:
            if not settings.can_use_local_ai_fallback:
                raise RuntimeError(f"OpenAI reply generation failed in real mode: {exc}") from exc
            logger.warning("OpenAI reply generation failed; using safe local fallback: %s", exc)
    if not settings.can_use_local_ai_fallback:
        settings.require_openai_credentials()
    return build_safe_reply(email, intent, policy_answers, settings)


def _generate_with_openai(
    email: EmailInput,
    intent: IntentResult,
    policy_answers: list[PolicyAnswer],
    settings: Settings,
) -> ReplyResult:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "subject": email.subject,
        "customer_message": email.body_text,
        "intent": intent.model_dump(mode="json"),
        "policy_answers": [answer.model_dump(mode="json") for answer in policy_answers],
        "auto_send_emails": settings.auto_send_emails,
        "oracle_enabled": settings.enable_oracle_api,
        "hard_rules": [
            "Never say booked, confirmed, or finalized.",
            "Never promise or imply a guarantee.",
            "Never invent a confirmation number or price.",
            "For booking requests, acknowledge receipt only.",
            "For missing booking fields, ask only for missing details.",
            "Do not include internal policy source labels in the customer body.",
        ],
    }
    response = client.responses.parse(
        model=settings.openai_model,
        instructions=REPLY_SYSTEM_PROMPT,
        input=json.dumps(payload, ensure_ascii=False),
        text_format=ReplyResult,
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed
    return ReplyResult.model_validate_json(response.output_text)


def build_oracle_reply(
    email: EmailInput,
    intent: IntentResult,
    policy_answers: list[PolicyAnswer],
    oracle_result: OracleOperationResult,
    settings: Settings,
) -> ReplyResult:
    subject = reply_subject(email.subject)
    policy_text = _policy_answer_text(policy_answers)
    prefix = f"{policy_text}\n\n" if policy_text else ""
    should_send = settings.auto_send_emails and not intent.requires_human_review
    if oracle_result.operation == "availability_checked":
        body = (
            f"{prefix}Thank you for your request. The requested dates "
            f"{oracle_result.requested_arrival_date} to {oracle_result.requested_departure_date} are available. "
            "Please find the quotation details below:\n\n"
            f"{_quote_options_text(oracle_result.options)}\n\n"
            "Rates are subject to availability and final confirmation at the time of reservation."
        )
        return ReplyResult(
            reply_subject=subject,
            reply_body=body,
            reply_type="availability_quote",
            should_send=should_send,
            requires_human_review=False,
            reason=None,
        )
    if oracle_result.operation == "booking_created":
        body = (
            f"{prefix}Thank you for your request. We have created the reservation for the requested dates "
            f"{oracle_result.requested_arrival_date} to {oracle_result.requested_departure_date}."
        )
        if oracle_result.confirmation_number:
            body += f"\n\nConfirmation number: {oracle_result.confirmation_number}"
        if oracle_result.reservation_id:
            body += f"\nReservation ID: {oracle_result.reservation_id}"
        body += "\n\nBest regards,\nReservations Team"
        return ReplyResult(
            reply_subject=subject,
            reply_body=body,
            reply_type="booking_created",
            should_send=should_send,
            requires_human_review=False,
            reason=None,
        )
    if oracle_result.operation == "booking_alternatives":
        body = (
            f"{prefix}Thank you for your request. The requested dates "
            f"{oracle_result.requested_arrival_date} to {oracle_result.requested_departure_date} "
            "are not available for the configured room type. We found these nearby quotation options:\n\n"
            f"{_quote_options_text(oracle_result.options)}\n\n"
            "Rates are subject to availability and final confirmation at the time of reservation. "
            "Please let us know which option you would like to proceed with."
        )
        return ReplyResult(
            reply_subject=subject,
            reply_body=body,
            reply_type="booking_alternatives",
            should_send=should_send,
            requires_human_review=False,
            reason=None,
        )
    if oracle_result.operation == "booking_unavailable":
        body = (
            f"{prefix}Thank you for your request. The requested dates "
            f"{oracle_result.requested_arrival_date} to {oracle_result.requested_departure_date} "
            "are not available, and we could not find nearby availability within 7 days."
        )
        return ReplyResult(
            reply_subject=subject,
            reply_body=body,
            reply_type="booking_unavailable",
            should_send=should_send,
            requires_human_review=False,
            reason=None,
        )
    if oracle_result.operation == "booking_cancelled":
        body = (
            "Thank you for your message. Your reservation has been cancelled."
        )
        if oracle_result.confirmation_number:
            body += f"\n\nConfirmation number: {oracle_result.confirmation_number}"
        if oracle_result.cancellation_id:
            body += f"\nCancellation ID: {oracle_result.cancellation_id}"
        body += "\n\nBest regards,\nReservations Team"
        return ReplyResult(
            reply_subject=subject,
            reply_body=body,
            reply_type="booking_cancelled",
            should_send=should_send,
            requires_human_review=False,
            reason=None,
        )
    body = (
        "Thank you for your message. We could not complete the Oracle operation automatically. "
        "Our reservations team will review and follow up."
    )
    return ReplyResult(
        reply_subject=subject,
        reply_body=body,
        reply_type="human_review_acknowledgement",
        should_send=False,
        requires_human_review=True,
        reason=oracle_result.error or oracle_result.message,
    )


def build_safe_reply(
    email: EmailInput,
    intent: IntentResult,
    policy_answers: list[PolicyAnswer],
    settings: Settings,
) -> ReplyResult:
    subject = reply_subject(email.subject)
    has_policy = bool(policy_answers)
    booking = intent.booking_request
    missing = booking.missing_fields if booking else []
    should_send = settings.auto_send_emails and not intent.requires_human_review

    if intent.requires_human_review and intent.primary_intent in {
        "booking_cancellation",
        "booking_modification",
        "complaint",
        "refund_cancellation_policy_question",
    }:
        return ReplyResult(
            reply_subject=subject,
            reply_body=(
                "Thank you for contacting us. Your request has been received and will be "
                "reviewed by our reservations team."
            ),
            reply_type="human_review_acknowledgement",
            should_send=False,
            requires_human_review=True,
            reason=intent.human_review_reason,
        )

    if intent.primary_intent == "unknown":
        return ReplyResult(
            reply_subject=subject,
            reply_body=(
                "Thank you for contacting us. Could you please share a few more details "
                "so our reservations team can assist you?"
            ),
            reply_type="unknown_request",
            should_send=False,
            requires_human_review=True,
            reason=intent.human_review_reason or "Unclear customer request.",
        )

    if has_policy and booking and missing:
        body = f"{_policy_answer_text(policy_answers)}\n\n{_missing_details_text(missing)}"
        return ReplyResult(
            reply_subject=subject,
            reply_body=_sanitize_forbidden_booking_words(body),
            reply_type="policy_answer_plus_missing_details",
            should_send=should_send,
            requires_human_review=intent.requires_human_review,
            reason=intent.human_review_reason,
        )

    if has_policy and booking:
        body = f"{_policy_answer_text(policy_answers)}\n\n{_booking_acknowledgement_text(booking)}"
        return ReplyResult(
            reply_subject=subject,
            reply_body=_sanitize_forbidden_booking_words(body),
            reply_type="policy_answer_plus_booking_acknowledgement",
            should_send=should_send,
            requires_human_review=intent.requires_human_review,
            reason=intent.human_review_reason,
        )

    if booking and missing:
        return ReplyResult(
            reply_subject=subject,
            reply_body=_missing_details_text(missing),
            reply_type="missing_details",
            should_send=should_send,
            requires_human_review=intent.requires_human_review,
            reason=intent.human_review_reason,
        )

    if booking:
        return ReplyResult(
            reply_subject=subject,
            reply_body=_booking_acknowledgement_text(booking),
            reply_type="booking_acknowledgement",
            should_send=should_send,
            requires_human_review=intent.requires_human_review,
            reason=intent.human_review_reason,
        )

    if has_policy:
        return ReplyResult(
            reply_subject=subject,
            reply_body=_policy_answer_text(policy_answers),
            reply_type="policy_answer",
            should_send=should_send,
            requires_human_review=intent.requires_human_review,
            reason=intent.human_review_reason,
        )

    return ReplyResult(
        reply_subject=subject,
        reply_body=(
            "Thank you for contacting us. Could you please clarify how our reservations "
            "team can assist you?"
        ),
        reply_type="unknown_request",
        should_send=False,
        requires_human_review=True,
        reason="No supported intent or policy answer was available.",
    )


def _policy_answer_text(policy_answers: list[PolicyAnswer]) -> str:
    parts = list(
        dict.fromkeys(answer.answer.strip() for answer in policy_answers if answer.answer.strip())
    )
    return "\n\n".join(parts)


def _booking_acknowledgement_text(booking) -> str:
    details = booking_details_sentence(booking)
    return (
        f"Thank you for sharing the reservation details. We have received your request "
        f"for {details}. Our reservations team will check availability and proceed accordingly."
    )


def _missing_details_text(missing_fields: list[str]) -> str:
    labels = user_friendly_missing_fields(missing_fields)
    joined = ", ".join(labels)
    return f"To proceed with your reservation request, please share the following details: {joined}."


def _option_price(option: OracleAvailabilityOption) -> str:
    if option.amount_before_tax is None or not option.currency_code:
        return "available"
    amount = int(option.amount_before_tax) if option.amount_before_tax.is_integer() else option.amount_before_tax
    return f"{amount} {option.currency_code} before tax"


def _quote_options_text(options: list[OracleAvailabilityOption]) -> str:
    if not options:
        return "- No priced options were returned."
    lines = []
    for index, option in enumerate(options, start=1):
        lines.append(
            f"{index}. {option.arrival_date} to {option.departure_date}\n"
            f"   Room type: {option.room_type}\n"
            f"   Rate plan: {option.rate_plan_code or 'Not returned'}\n"
            f"   Available units: {option.number_of_units if option.number_of_units is not None else 'Not returned'}\n"
            f"   Quoted amount: {_option_price(option)}"
        )
    return "\n".join(lines)


def _enforce_reply_safety(
    reply: ReplyResult,
    settings: Settings,
    intent: IntentResult,
    policy_answers: list[PolicyAnswer],
) -> ReplyResult:
    body = _sanitize_forbidden_booking_words(reply.reply_body)
    body = _strip_markdown_emphasis(body)
    body = _complete_bare_signoff(body, intent)
    requires_human_review = bool(reply.requires_human_review or intent.requires_human_review)
    return reply.model_copy(
        update={
            "reply_body": body,
            "reply_type": _expected_reply_type(intent, policy_answers, reply.reply_type),
            "should_send": bool(settings.auto_send_emails and reply.should_send and not requires_human_review),
            "requires_human_review": requires_human_review,
        }
    )


def _sanitize_forbidden_booking_words(body: str) -> str:
    replacements = {
        r"\bbooked\b": "received",
        r"\bconfirmed\b": "received",
        r"\bconfirmation number\b": "reference",
        r"\bfinalized\b": "received",
    }
    sanitized = body
    for pattern, replacement in replacements.items():
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    return sanitized


def _strip_markdown_emphasis(body: str) -> str:
    return re.sub(r"\*\*([^*\n]+)\*\*", r"\1", body)


def _complete_bare_signoff(body: str, intent: IntentResult) -> str:
    lines = body.rstrip().splitlines()
    if not lines:
        return body
    last = lines[-1].strip()
    if not re.fullmatch(r"(?:kind|best|warm)\s+regards,?", last, flags=re.IGNORECASE):
        return body
    team_name = "Reservations Team"
    booking = intent.booking_request
    if booking and booking.property_name:
        team_name = f"{booking.property_name} Reservations Team"
    return "\n".join(lines + [team_name])


def _expected_reply_type(
    intent: IntentResult, policy_answers: list[PolicyAnswer], fallback: ReplyType
) -> ReplyType:
    booking = intent.booking_request
    has_policy = bool(policy_answers)
    if intent.requires_human_review and intent.primary_intent in {
        "booking_cancellation",
        "booking_modification",
        "complaint",
        "refund_cancellation_policy_question",
    }:
        return "human_review_acknowledgement"
    if intent.primary_intent == "unknown":
        return "unknown_request"
    if has_policy and booking and booking.missing_fields:
        return "policy_answer_plus_missing_details"
    if has_policy and booking:
        return "policy_answer_plus_booking_acknowledgement"
    if booking and booking.missing_fields:
        return "missing_details"
    if booking:
        return "booking_acknowledgement"
    if has_policy:
        return "policy_answer"
    return fallback
