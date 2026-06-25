from __future__ import annotations

from app.ai.schemas import BookingRequest, EmailInput, IntentResult
from app.tools.oracle_booking_flow import run_oracle_booking_flow


def oracle_settings(test_settings):
    return test_settings.__class__(
        **{
            **test_settings.__dict__,
            "enable_oracle_api": True,
            "oracle_allow_reservation_create": True,
            "oracle_allow_cancellation": True,
            "oracle_alternative_search_days": 7,
            "oracle_alternative_max_options": 3,
        }
    )


def email(body: str = "Please book one room.") -> EmailInput:
    return EmailInput(
        email_id="email-1",
        internet_message_id=None,
        subject="Hotel request",
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text=body,
    )


def booking() -> BookingRequest:
    return BookingRequest(
        guest_name="Priya Sharma",
        arrival_date="2026-09-10",
        departure_date="2026-09-12",
        adults=2,
        children=0,
        rooms=1,
        missing_fields=[],
    )


def intent(primary="booking_request", booking_request=None) -> IntentResult:
    return IntentResult(
        primary_intent=primary,
        secondary_intents=[],
        confidence=0.9,
        requires_human_review=False,
        human_review_reason=None,
        customer_message_summary="Booking request.",
        booking_request=booking_request,
        questions=[],
        next_action="acknowledge_booking_request",
    )


def availability_body(start="2026-09-10", end="2026-09-12"):
    return {
        "hotelAvailability": [
            {
                "roomStays": [
                    {
                        "roomRates": [
                            {
                                "total": {"amountBeforeTax": 218, "currencyCode": "GBP"},
                                "roomType": "DSPN",
                                "ratePlanCode": "ONDAY",
                                "start": start,
                                "end": end,
                                "numberOfUnits": 1,
                            }
                        ]
                    }
                ],
                "hotelId": "GB0783",
            }
        ]
    }


def test_oracle_flow_creates_booking_when_requested_dates_available(monkeypatch, test_settings):
    class FakeAvailabilityClient:
        def __init__(self, settings):
            pass

        def check_availability(self, booking, reference_date=None):
            return type("Response", (), {"body": availability_body()})()

    class FakeCreateClient:
        def __init__(self, settings):
            pass

        def create_reservation(self, booking, reference_date=None):
            return type(
                "Response",
                (),
                {
                    "body": {
                        "links": [
                            {"href": "https://example/reservations/123"},
                            {"href": "https://example/reservations?confirmationNumberList=456"},
                        ]
                    },
                    "request": type(
                        "Request",
                        (),
                        {"payload": {"reservations": {"reservation": [{"customReference": "HTL-WBD-1"}]}}},
                    )(),
                },
            )()

    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleAvailabilityClient", FakeAvailabilityClient)
    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleReservationCreateClient", FakeCreateClient)

    result = run_oracle_booking_flow(email(), intent(booking_request=booking()), oracle_settings(test_settings))

    assert result is not None
    assert result.operation == "booking_created"
    assert result.confirmation_number == "456"
    assert result.reservation_id == "123"
    assert result.options[0].amount_before_tax == 218


def test_oracle_flow_quotes_availability_check_without_creating_booking(monkeypatch, test_settings):
    create_called = False

    class FakeAvailabilityClient:
        def __init__(self, settings):
            pass

        def check_availability(self, booking, reference_date=None):
            return type("Response", (), {"body": availability_body()})()

    class FakeCreateClient:
        def __init__(self, settings):
            pass

        def create_reservation(self, booking, reference_date=None):
            nonlocal create_called
            create_called = True
            raise AssertionError("Availability checks should not create reservations")

    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleAvailabilityClient", FakeAvailabilityClient)
    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleReservationCreateClient", FakeCreateClient)

    result = run_oracle_booking_flow(
        email("Please check availability."),
        intent(primary="availability_check", booking_request=booking()),
        oracle_settings(test_settings),
    )

    assert result is not None
    assert result.operation == "availability_checked"
    assert result.message == "Requested dates are available. A quotation was prepared."
    assert result.options[0].amount_before_tax == 218
    assert create_called is False


def test_oracle_flow_returns_three_nearby_options_when_exact_unavailable(monkeypatch, test_settings):
    calls = []

    class FakeAvailabilityClient:
        def __init__(self, settings):
            pass

        def check_availability(self, request_booking, reference_date=None):
            calls.append(request_booking.arrival_date)
            if len(calls) == 1:
                return type("Response", (), {"body": {"hotelAvailability": [{"roomStays": [{"roomRates": []}]}]}})()
            return type(
                "Response",
                (),
                {"body": availability_body(request_booking.arrival_date, request_booking.departure_date)},
            )()

    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleAvailabilityClient", FakeAvailabilityClient)

    result = run_oracle_booking_flow(email(), intent(booking_request=booking()), oracle_settings(test_settings))

    assert result is not None
    assert result.operation == "booking_alternatives"
    assert len(result.options) == 3
    assert calls[:4] == ["2026-09-10", "2026-09-09", "2026-09-11", "2026-09-08"]


def test_oracle_flow_cancels_by_confirmation_number(monkeypatch, test_settings):
    class FakeCancelClient:
        def __init__(self, settings):
            pass

        def cancel_by_confirmation(self, confirmation):
            return type(
                "CancelResponse",
                (),
                {
                    "reservation_id": "708496",
                    "confirmation_number": confirmation,
                    "cancellation_id": "7407120",
                },
            )()

    monkeypatch.setattr("app.tools.oracle_booking_flow.OracleCancellationClient", FakeCancelClient)
    cancel_intent = intent(primary="booking_cancellation", booking_request=None)

    result = run_oracle_booking_flow(
        email("Please cancel confirmation number 7407100."),
        cancel_intent,
        oracle_settings(test_settings),
    )

    assert result is not None
    assert result.operation == "booking_cancelled"
    assert result.confirmation_number == "7407100"
    assert result.cancellation_id == "7407120"
