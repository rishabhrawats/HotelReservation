from app.ai.intent_agent import heuristic_intent
from app.ai.reply_agent import generate_reply
from app.ai.schemas import BookingRequest, EmailInput, IntentResult
from app.graph.nodes import validate_booking_readiness


def make_email(body: str) -> EmailInput:
    return EmailInput(
        email_id="email-booking",
        internet_message_id=None,
        subject="Booking request",
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text=body,
    )


def test_pure_booking_complete_returns_acknowledgement_not_confirmation(test_settings):
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road."
    )
    intent = heuristic_intent(email)

    reply = generate_reply(email, intent, [], test_settings)

    assert reply.reply_type == "booking_acknowledgement"
    assert "received your request" in reply.reply_body
    assert "confirmed" not in reply.reply_body.lower()
    assert "booked" not in reply.reply_body.lower()


def test_booking_missing_details_asks_only_missing_fields(test_settings):
    email = make_email("Please book a room for tomorrow.")
    intent = heuristic_intent(email)

    reply = generate_reply(email, intent, [], test_settings)

    assert reply.reply_type == "missing_details"
    assert "Guest Name" in reply.reply_body
    assert "Departure Date" in reply.reply_body
    assert "Number of Adults" in reply.reply_body
    assert "Number of Rooms" not in reply.reply_body


def test_booking_readiness_locks_user_room_type_to_configured_oracle_room(test_settings):
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        customer_message_summary="Customer requests a suite.",
        booking_request=BookingRequest(
            guest_name="Amit Sharma",
            arrival_date="10 September 2026",
            departure_date="12 September 2026",
            adults=2,
            children=0,
            rooms=1,
            room_type="suite",
            missing_fields=[],
        ),
        questions=[],
        next_action="acknowledge_booking_request",
    )

    updates = validate_booking_readiness({"settings": test_settings, "intent": intent})

    booking = updates["intent"].booking_request
    assert booking.room_type == "DSPN"
    assert booking.hotel_code == "GB0783"
    assert booking.missing_fields == []
