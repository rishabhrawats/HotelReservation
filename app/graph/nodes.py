from __future__ import annotations

from datetime import datetime, timezone

from app.ai.intent_agent import classify_email, missing_booking_fields
from app.ai.reply_agent import generate_reply
from app.ai.schemas import EmailInput, FinalProcessingResult, IntentResult
from app.config import Settings
from app.db.models import insert_processing_log
from app.email.email_cleaner import clean_email_body
from app.email.file_source import load_email_from_file
from app.email.outlook_client import OutlookClient
from app.graph.state import HotelAgentState
from app.rag.answer_policy import answer_policy_question
from app.rag.retriever import retrieve_policy_contexts
from app.tools.email_reply import send_or_create_draft
from app.tools.oracle_booking_flow import run_oracle_booking_flow


def load_newest_email(state: HotelAgentState) -> dict:
    if state.get("email"):
        return {}
    settings = state["settings"]
    if settings.use_sample_email:
        return {"email": sample_email()}
    if settings.email_source == "file":
        return {"email": load_email_from_file(settings.email_file_path)}
    return {"email": OutlookClient(settings).get_newest_email()}


def clean_email(state: HotelAgentState) -> dict:
    email = state["email"]
    clean_body = clean_email_body(email.body_text)
    return {"email": email.model_copy(update={"body_text": clean_body})}


def classify_and_extract(state: HotelAgentState) -> dict:
    intent = classify_email(state["email"], state["settings"])
    return {"intent": intent}


def validate_booking_readiness(state: HotelAgentState) -> dict:
    intent = state["intent"]
    booking = intent.booking_request
    if not booking:
        return {}
    settings = state["settings"]
    booking = booking.model_copy(
        update={
            "room_type": settings.oracle_room_type,
            "hotel_code": settings.oracle_hotel_code,
        }
    )
    missing = missing_booking_fields(booking)
    booking = booking.model_copy(update={"missing_fields": missing})
    updates: dict = {"booking_request": booking}
    if missing and intent.next_action in {
        "acknowledge_booking_request",
        "answer_question_and_acknowledge_booking",
    }:
        updates["next_action"] = "ask_missing_details"
    return {"intent": intent.model_copy(update=updates)}


def retrieve_policy_context_node(state: HotelAgentState) -> dict:
    settings = state["settings"]
    intent = state["intent"]
    contexts = retrieve_policy_contexts(intent.questions, settings=settings, top_k=5)
    return {"policy_contexts": contexts}


def answer_policy_questions_node(state: HotelAgentState) -> dict:
    settings = state["settings"]
    intent = state["intent"]
    contexts = state.get("policy_contexts", {})
    answers = [
        answer_policy_question(question, contexts.get(question.question, []), settings=settings)
        for question in intent.questions
        if question.needs_rag_answer
    ]
    return {"policy_answers": answers}


def oracle_booking_node(state: HotelAgentState) -> dict:
    result = run_oracle_booking_flow(state["email"], state["intent"], state["settings"])
    return {"oracle_result": result} if result else {}


def generate_reply_node(state: HotelAgentState) -> dict:
    reply = generate_reply(
        state["email"],
        state["intent"],
        state.get("policy_answers", []),
        state["settings"],
        state.get("oracle_result"),
    )
    return {"reply": reply}


def send_or_draft_reply_node(state: HotelAgentState) -> dict:
    errors = list(state.get("errors", []))
    try:
        reply_status = send_or_create_draft(state["email"], state["reply"], state["settings"])
    except Exception as exc:
        reply_status = "FAILED"
        errors.append(str(exc))
    return {"reply_status": reply_status, "errors": errors}


def log_processing_result_node(state: HotelAgentState) -> dict:
    errors = list(state.get("errors", []))
    reply_status = state.get("reply_status", "DRAFT_ONLY")
    final_status = _final_status(
        state["intent"],
        bool(state.get("policy_answers")),
        reply_status,
        errors,
        state.get("oracle_result"),
    )
    result = FinalProcessingResult(
        email=state["email"],
        intent=state["intent"],
        policy_answers=state.get("policy_answers", []),
        oracle_result=state.get("oracle_result"),
        reply=state["reply"],
        final_status=final_status,
        errors=errors,
    )
    log_id = insert_processing_log(
        result=result,
        reply_status=reply_status,  # type: ignore[arg-type]
        settings=state["settings"],
        error_message="; ".join(errors) if errors else None,
    )
    return {"final_result": result, "final_status": final_status, "log_id": log_id}


def final_output(state: HotelAgentState) -> dict:
    return {}


def sample_email() -> EmailInput:
    return EmailInput(
        email_id="sample-email",
        internet_message_id="<sample-email@local>",
        subject="Hotel Booking and Early Check-in Request",
        sender_name="Sample Customer",
        sender_email="sample.customer@example.com",
        received_datetime=datetime.now(timezone.utc).isoformat(),
        body_text=(
            "Hello, please book one double room for John Smith, 2 adults, from 10 July "
            "to 12 July at Travelodge City Road. Also, can I check in early and leave "
            "my luggage before check-in?"
        ),
        is_read=False,
    )


def _final_status(
    intent: IntentResult,
    has_policy_answers: bool,
    reply_status: str,
    errors: list[str],
    oracle_result=None,
) -> str:
    if errors or reply_status == "FAILED":
        return "FAILED"
    if reply_status == "SENT":
        return "SENT"
    if oracle_result:
        if not oracle_result.success:
            return "ORACLE_FAILED"
        if oracle_result.operation == "availability_checked":
            return "AVAILABILITY_QUOTED"
        if oracle_result.operation == "booking_created":
            return "BOOKING_CREATED"
        if oracle_result.operation == "booking_alternatives":
            return "BOOKING_ALTERNATIVES"
        if oracle_result.operation == "booking_unavailable":
            return "BOOKING_UNAVAILABLE"
        if oracle_result.operation == "booking_cancelled":
            return "BOOKING_CANCELLED"
    if intent.requires_human_review:
        return "HUMAN_REVIEW"
    booking = intent.booking_request
    booking_missing = bool(booking and booking.missing_fields)
    booking_present = booking is not None
    if has_policy_answers and booking_present and booking_missing:
        return "POLICY_ANSWERED_AND_BOOKING_MISSING_DETAILS"
    if has_policy_answers and booking_present:
        return "POLICY_ANSWERED_AND_BOOKING_ACKNOWLEDGED"
    if booking_present and booking_missing:
        return "BOOKING_MISSING_DETAILS"
    if booking_present:
        return "BOOKING_ACKNOWLEDGED"
    if has_policy_answers:
        return "POLICY_ANSWERED"
    return "HUMAN_REVIEW"
