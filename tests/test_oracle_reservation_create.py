from __future__ import annotations

import pytest
import requests

from app.ai.schemas import BookingRequest
from app.tools.oracle_reservation_create import (
    OracleReservationCreateClient,
    build_create_reservation_request,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", url="") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"reservationId": "RES123"}
        self.text = text or "{}"
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("request failed")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        if url.endswith("/oauth/v1/tokens"):
            return FakeResponse(
                payload={"access_token": "token-123", "token_type": "Bearer"},
                text='{"access_token":"token-123"}',
            )
        return FakeResponse(
            payload={"reservations": {"reservation": [{"reservationId": "RES123"}]}},
            text='{"reservations":{"reservation":[{"reservationId":"RES123"}]}}',
            url=url,
        )


def oracle_settings(test_settings, allow_create=False):
    return test_settings.__class__(
        **{
            **test_settings.__dict__,
            "oracle_allow_reservation_create": allow_create,
            "oracle_host_name": "https://oracle.example.com",
            "oracle_app_key": "app-key-123",
            "oracle_client_id": "client-id-123",
            "oracle_client_secret": "client-secret-456",
            "oracle_auth_mode": "basic",
            "oracle_enterprise_id": "TGE",
            "oracle_scope": "urn:opc:hgbu:ws:__myscopes__",
            "oracle_hotel_code": "GB0783",
            "oracle_room_type": "DSPN",
            "oracle_rate_plan_code": "BARFLEX",
            "oracle_market_code": "WHOL",
            "oracle_source_code": "CEN",
            "oracle_guarantee_code": "PP",
            "oracle_payment_method": "CA",
            "oracle_booking_medium": "CEN",
            "oracle_custom_reference_prefix": "HTL-WBD",
        }
    )


def booking() -> BookingRequest:
    return BookingRequest(
        guest_name="Test First Name Lastname",
        arrival_date="2026-11-15",
        departure_date="2026-11-18",
        adults=2,
        children=0,
        rooms=1,
        hotel_code="IGNORE_THIS",
        room_type="suite",
        custom_reference="HTL-WBD-773520926",
    )


def test_create_payload_matches_required_shape_and_locked_constants(test_settings):
    request = build_create_reservation_request(booking(), oracle_settings(test_settings))
    reservation = request.payload["reservations"]["reservation"][0]
    room_stay = reservation["roomStay"]
    room_rate = room_stay["roomRates"][0]
    guest_name = reservation["reservationGuests"][0]["profileInfo"]["profile"]["customer"]["personName"][0]

    assert request.hotel_code == "GB0783"
    assert reservation["sourceOfSale"] == {"sourceType": "PMS", "sourceCode": "GB0783"}
    assert reservation["hotelId"] == "GB0783"
    assert reservation["customReference"] == "HTL-WBD-773520926"
    assert room_rate["roomType"] == "DSPN"
    assert room_rate["roomTypeCharged"] == "DSPN"
    assert room_rate["ratePlanCode"] == "BARFLEX"
    assert room_rate["marketCode"] == "WHOL"
    assert room_rate["sourceCode"] == "CEN"
    assert room_rate["numberOfUnits"] == "1"
    assert room_rate["guestCounts"] == {"adults": "2", "children": "0"}
    assert room_stay["arrivalDate"] == "2026-11-15"
    assert room_stay["departureDate"] == "2026-11-18"
    assert room_stay["guarantee"] == {"guaranteeCode": "PP"}
    assert room_stay["bookingMedium"] == "CEN"
    assert guest_name == {
        "givenName": "Test First Name",
        "surname": "Lastname",
        "nameType": "Primary",
    }
    assert reservation["reservationPaymentMethods"] == [
        {"paymentMethod": "CA", "folioView": "1"},
        {"paymentMethod": "", "folioView": "2"},
    ]
    assert reservation["overrideInventoryCheck"] is True
    assert reservation["reservationStatus"] == "Reserved"


def test_create_payload_requires_booking_values(test_settings):
    with pytest.raises(RuntimeError, match="guest_name"):
        build_create_reservation_request(
            BookingRequest(arrival_date="2026-11-15", departure_date="2026-11-18", adults=2, rooms=1),
            oracle_settings(test_settings),
        )


def test_create_client_refuses_live_post_without_safety_flag(test_settings):
    client = OracleReservationCreateClient(oracle_settings(test_settings, allow_create=False), session=FakeSession())

    with pytest.raises(RuntimeError, match="disabled"):
        client.create_reservation(booking())


def test_create_client_posts_expected_url_headers_and_json_when_enabled(test_settings):
    session = FakeSession()
    client = OracleReservationCreateClient(oracle_settings(test_settings, allow_create=True), session=session)

    result = client.create_reservation(booking())

    reservation_call = session.posts[1]
    assert result.status_code == 200
    assert reservation_call["url"] == "https://oracle.example.com/rsv/v1/hotels/GB0783/reservations"
    assert reservation_call["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer token-123",
        "x-app-key": "app-key-123",
        "enterpriseId": "TGE",
        "x-hotelid": "GB0783",
    }
    assert reservation_call["json"]["reservations"]["reservation"][0]["hotelId"] == "GB0783"
    assert reservation_call["json"]["reservations"]["reservation"][0]["roomStay"]["roomRates"][0]["roomType"] == "DSPN"
