from app.ai.intent_agent import heuristic_intent, normalize_intent_result
from app.ai.schemas import BookingRequest, EmailInput, IntentResult, PolicyQuestion


def make_email(body: str, subject: str = "Hotel request") -> EmailInput:
    return EmailInput(
        email_id="email-1",
        internet_message_id=None,
        subject=subject,
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text=body,
    )


def test_complete_booking_request_is_extracted():
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road."
    )

    intent = heuristic_intent(email)

    assert intent.primary_intent == "booking_request"
    assert intent.booking_request is not None
    assert intent.booking_request.missing_fields == []
    assert intent.next_action == "acknowledge_booking_request"


def test_cancellation_requires_human_review():
    intent = heuristic_intent(make_email("Please cancel my booking reference ABC123."))

    assert intent.primary_intent == "booking_cancellation"
    assert intent.requires_human_review is True
    assert intent.next_action == "cancellation_human_review"


def test_complaint_requires_human_review():
    intent = heuristic_intent(make_email("I have a complaint about my stay. The service was terrible."))

    assert intent.primary_intent == "complaint"
    assert intent.requires_human_review is True


def test_unknown_email_asks_for_clarification_intent():
    intent = heuristic_intent(make_email("Hi, please help with my stay."))

    assert intent.primary_intent == "unknown"
    assert intent.requires_human_review is True


def test_sample_email_detects_early_checkin_and_luggage_questions():
    intent = heuristic_intent(
        make_email(
            "Hello, please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road. "
            "Also, can I check in early and leave my luggage before check-in?"
        )
    )

    categories = {question.category for question in intent.questions}
    assert "early check-in" in categories
    assert "luggage storage" in categories


def test_normalize_intent_adds_missing_policy_questions_from_secondary_intents():
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road. "
        "Also, can I check in early and leave my luggage before check-in?"
    )
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=["early_checkin_request", "luggage_storage_request"],
        confidence=0.95,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request with early check-in and luggage storage.",
        booking_request=BookingRequest(
            guest_name="John Smith",
            arrival_date="10 July",
            departure_date="12 July",
            adults=2,
            children=0,
            rooms=1,
            room_type="double room",
            property_name="Travelodge City Road",
            special_requests=["early check-in", "luggage storage"],
            missing_fields=[],
        ),
        questions=[],
        next_action="acknowledge_booking_request",
    )

    normalized = normalize_intent_result(intent, email)

    categories = {question.category for question in normalized.questions}
    assert "early check-in" in categories
    assert "luggage storage" in categories
    assert normalized.next_action == "answer_question_and_acknowledge_booking"


def test_normalize_intent_backfills_clear_room_count_from_email_text():
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road."
    )
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=[],
        confidence=0.86,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request.",
        booking_request=BookingRequest(
            guest_name="John Smith",
            arrival_date="10 July",
            departure_date="12 July",
            adults=2,
            rooms=None,
            room_type="double room",
            property_name="Travelodge City Road",
            missing_fields=["rooms"],
        ),
        questions=[],
        next_action="ask_missing_details",
    )

    normalized = normalize_intent_result(intent, email)

    assert normalized.booking_request is not None
    assert normalized.booking_request.rooms == 1
    assert normalized.booking_request.missing_fields == []
    assert normalized.next_action == "acknowledge_booking_request"


def test_normalize_intent_promotes_known_policy_questions_to_rag():
    email = make_email(
        "Please book one double room for John Smith, 2 adults, from 10 July to 12 July at Travelodge City Road. "
        "Can I check in early?"
    )
    intent = IntentResult(
        primary_intent="booking_request",
        secondary_intents=["early_checkin_request"],
        confidence=0.86,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request with early check-in question.",
        booking_request=BookingRequest(
            guest_name="John Smith",
            arrival_date="10 July",
            departure_date="12 July",
            adults=2,
            rooms=1,
            room_type="double room",
            property_name="Travelodge City Road",
            missing_fields=[],
        ),
        questions=[
            PolicyQuestion(
                question="Can I check in early?",
                category="early check-in",
                needs_rag_answer=False,
            )
        ],
        next_action="answer_question_and_acknowledge_booking",
    )

    normalized = normalize_intent_result(intent, email)

    assert len(normalized.questions) == 1
    assert normalized.questions[0].needs_rag_answer is True
