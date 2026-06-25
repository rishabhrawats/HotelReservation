from app.ai.schemas import (
    EmailInput,
    FinalProcessingResult,
    IntentResult,
    PolicyAnswer,
    ReplyResult,
)


def test_final_processing_result_validates_with_pydantic():
    email = EmailInput(
        email_id="email-final",
        internet_message_id=None,
        subject="Question",
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text="Can I check in early?",
    )
    intent = IntentResult(
        primary_intent="early_checkin_request",
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Customer asks about early check-in.",
        booking_request=None,
        questions=[],
        next_action="answer_policy_question",
    )
    answer = PolicyAnswer(
        question="Can I check in early?",
        answer="Early check-in is subject to availability.",
        sources=["Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf page=2"],
        confidence=0.8,
        insufficient_policy_context=False,
    )
    reply = ReplyResult(
        reply_subject="Re: Question",
        reply_body="Early check-in is subject to availability.",
        reply_type="policy_answer",
        should_send=False,
        requires_human_review=False,
    )

    result = FinalProcessingResult(
        email=email,
        intent=intent,
        policy_answers=[answer],
        reply=reply,
        final_status="POLICY_ANSWERED",
        errors=[],
    )

    assert result.model_dump()["final_status"] == "POLICY_ANSWERED"
