from app.ai.intent_agent import heuristic_intent
from app.ai.reply_agent import _enforce_reply_safety, generate_reply
from app.ai.schemas import (
    BookingRequest,
    EmailInput,
    IntentResult,
    OracleAvailabilityOption,
    OracleOperationResult,
    PolicyAnswer,
    ReplyResult,
)


def make_email(body: str, subject: str = "Hotel request") -> EmailInput:
    return EmailInput(
        email_id="email-reply",
        internet_message_id=None,
        subject=subject,
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text=body,
    )


def test_booking_plus_early_checkin_answers_policy_and_acknowledges(test_settings):
    email = make_email(
        "Please book a twin room for John Smith, 2 adults, from 5 August to 7 August at Travelodge City Road. "
        "Also, is parking available?"
    )
    intent = heuristic_intent(email)
    answer = PolicyAnswer(
        question=intent.questions[0].question,
        answer="Parking is subject to availability and may incur additional charges.",
        sources=["Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf page=7"],
        confidence=0.8,
        insufficient_policy_context=False,
    )

    reply = generate_reply(email, intent, [answer], test_settings)

    assert reply.reply_type == "policy_answer_plus_booking_acknowledgement"
    assert "Parking is subject to availability" in reply.reply_body
    assert "received your request" in reply.reply_body
    assert "confirmed" not in reply.reply_body.lower()
    assert "booked" not in reply.reply_body.lower()


def test_unknown_email_asks_clarification(test_settings):
    email = make_email("Hi, please help with my stay.")
    intent = heuristic_intent(email)

    reply = generate_reply(email, intent, [], test_settings)

    assert reply.reply_type == "unknown_request"
    assert "clarify" in reply.reply_body.lower() or "more details" in reply.reply_body.lower()


def test_human_review_acknowledgement_for_cancellation(test_settings):
    email = make_email("Please cancel my booking reference ABC123.")
    intent = heuristic_intent(email)

    reply = generate_reply(email, intent, [], test_settings)

    assert reply.reply_type == "human_review_acknowledgement"
    assert reply.requires_human_review is True
    assert reply.should_send is False


def test_reply_generator_never_says_confirmed_or_booked_when_oracle_disabled(test_settings):
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road."
    )
    intent = heuristic_intent(email)

    reply = generate_reply(email, intent, [], test_settings)

    lowered = reply.reply_body.lower()
    assert "confirmed" not in lowered
    assert "booked" not in lowered
    assert "booked successfully" not in lowered
    assert "confirmation number" not in lowered


def test_reply_safety_preserves_cannot_be_guaranteed(test_settings):
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road. "
        "Can I check in early?"
    )
    intent = heuristic_intent(email)
    answer = PolicyAnswer(
        question="Can I check in early?",
        answer="Early check-in is subject to availability and cannot be guaranteed.",
        sources=["Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf page=11"],
        confidence=0.8,
        insufficient_policy_context=False,
    )

    reply = generate_reply(email, intent, [answer], test_settings)

    assert "cannot be guaranteed" in reply.reply_body.lower()


def test_reply_safety_completes_signoff_and_removes_markdown(test_settings):
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request.",
        booking_request=BookingRequest(property_name="Travelodge City Road", missing_fields=[]),
        questions=[],
        next_action="acknowledge_booking_request",
    )
    reply = ReplyResult(
        reply_subject="Re: Hotel request",
        reply_body="Hello,\n\n**Early check-in:** Subject to availability.\n\nKind regards,",
        reply_type="booking_acknowledgement",
        should_send=False,
        requires_human_review=False,
        reason=None,
    )

    polished = _enforce_reply_safety(reply, test_settings, intent, [])

    assert "**" not in polished.reply_body
    assert polished.reply_body.endswith("Travelodge City Road Reservations Team")


def test_reply_safety_aligns_reply_type_with_workflow_state(test_settings):
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request.",
        booking_request=BookingRequest(
            property_name="Travelodge City Road",
            rooms=1,
            missing_fields=[],
        ),
        questions=[],
        next_action="acknowledge_booking_request",
    )
    reply = ReplyResult(
        reply_subject="Re: Hotel request",
        reply_body="Hello",
        reply_type="policy_answer_plus_missing_details",
        should_send=False,
        requires_human_review=False,
        reason=None,
    )

    polished = _enforce_reply_safety(reply, test_settings, intent, [])

    assert polished.reply_type == "booking_acknowledgement"


def test_oracle_availability_reply_includes_quotation_details(test_settings):
    email = make_email("Please check availability for 2 adults from 10 September 2026 to 12 September 2026.")
    intent = IntentResult(
        primary_intent="availability_check",
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        customer_message_summary="Availability check.",
        booking_request=BookingRequest(
            guest_name="Amit Sharma",
            arrival_date="10 September 2026",
            departure_date="12 September 2026",
            adults=2,
            children=0,
            rooms=1,
            room_type="DSPN",
            missing_fields=[],
        ),
        questions=[],
        next_action="acknowledge_booking_request",
    )
    oracle = OracleOperationResult(
        operation="availability_checked",
        success=True,
        message="Requested dates are available. A quotation was prepared.",
        requested_arrival_date="2026-09-10",
        requested_departure_date="2026-09-12",
        options=[
            OracleAvailabilityOption(
                arrival_date="2026-09-10",
                departure_date="2026-09-12",
                room_type="DSPN",
                rate_plan_code="BARFLEX",
                number_of_units=1,
                amount_before_tax=218,
                currency_code="GBP",
                is_requested_dates=True,
            )
        ],
    )

    reply = generate_reply(email, intent, [], test_settings, oracle)

    assert reply.reply_type == "availability_quote"
    assert "quotation details" in reply.reply_body
    assert "Room type: DSPN" in reply.reply_body
    assert "Quoted amount: 218 GBP before tax" in reply.reply_body
    assert "not a reservation confirmation" not in reply.reply_body.lower()
