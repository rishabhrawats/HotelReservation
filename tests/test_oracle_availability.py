from __future__ import annotations

import pytest
import requests

from app.ai.schemas import BookingRequest
from app.tools.oracle_availability import OracleAvailabilityClient, build_availability_request


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", url="") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"available": True}
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
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakeResponse(
            payload={"access_token": "token-123", "token_type": "Bearer"},
            text='{"access_token":"token-123"}',
        )

    def get(self, url, **kwargs):
        self.gets.append({"url": url, **kwargs})
        query = "&".join(f"{key}={value}" for key, value in kwargs["params"].items())
        return FakeResponse(
            payload={"availability": [{"roomType": "DSPN"}]},
            text='{"availability":[{"roomType":"DSPN"}]}',
            url=f"{url}?{query}",
        )


def oracle_settings(test_settings):
    return test_settings.__class__(
        **{
            **test_settings.__dict__,
            "oracle_host_name": "https://oracle.example.com",
            "oracle_app_key": "app-key-123",
            "oracle_client_id": "client-id-123",
            "oracle_client_secret": "client-secret-456",
            "oracle_auth_mode": "basic",
            "oracle_enterprise_id": "TGE",
            "oracle_scope": "urn:opc:hgbu:ws:__myscopes__",
            "oracle_hotel_code": "GB0783",
            "oracle_room_type": "DSPN",
        }
    )


def test_availability_request_uses_constant_hotel_and_room_type(test_settings):
    booking = BookingRequest(
        arrival_date="26 August 2026",
        departure_date="28 August 2026",
        adults=2,
        children=0,
        rooms=1,
        hotel_code="SHOULD_NOT_USE",
        room_type="suite",
        property_name="Customer Mentioned Hotel",
    )

    request = build_availability_request(booking, oracle_settings(test_settings))

    assert request.hotel_code == "GB0783"
    assert request.room_type == "DSPN"
    assert request.params() == {
        "roomStayStartDate": "2026-08-26",
        "roomStayEndDate": "2026-08-28",
        "roomStayQuantity": 1,
        "adults": 2,
        "children": 0,
        "roomType": "DSPN",
    }


def test_availability_request_uses_reference_year_for_email_dates_without_year(test_settings):
    booking = BookingRequest(
        arrival_date="26 August",
        departure_date="28 August",
        adults=2,
        children=None,
        rooms=1,
    )

    request = build_availability_request(
        booking,
        oracle_settings(test_settings),
        reference_date="2026-06-25T14:35:00Z",
    )

    assert request.room_stay_start_date == "2026-08-26"
    assert request.room_stay_end_date == "2026-08-28"
    assert request.children == 0


def test_availability_client_calls_oracle_with_expected_url_headers_and_params(test_settings):
    session = FakeSession()
    booking = BookingRequest(
        arrival_date="2026-08-26",
        departure_date="2026-08-28",
        adults=2,
        children=0,
        rooms=1,
        hotel_code="IGNORED",
        room_type="ignored",
    )

    result = OracleAvailabilityClient(oracle_settings(test_settings), session=session).check_availability(booking)

    assert result.status_code == 200
    assert session.gets[0]["url"] == "https://oracle.example.com/par/v1/hotels/GB0783/availability"
    assert session.gets[0]["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer token-123",
        "x-app-key": "app-key-123",
        "enterpriseId": "TGE",
        "x-hotelid": "GB0783",
    }
    assert session.gets[0]["params"] == {
        "roomStayStartDate": "2026-08-26",
        "roomStayEndDate": "2026-08-28",
        "roomStayQuantity": 1,
        "adults": 2,
        "children": 0,
        "roomType": "DSPN",
    }


def test_availability_request_requires_email_booking_values(test_settings):
    with pytest.raises(RuntimeError, match="arrival_date"):
        build_availability_request(BookingRequest(adults=2, rooms=1), oracle_settings(test_settings))
