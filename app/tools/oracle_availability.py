from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from app.ai.intent_agent import heuristic_intent, normalize_intent_result
from app.ai.schemas import BookingRequest
from app.config import Settings, load_settings
from app.email.file_source import load_email_from_file
from app.tools.oracle_auth import OracleAuthClient


@dataclass(frozen=True)
class OracleAvailabilityRequest:
    hotel_code: str
    room_type: str
    room_stay_start_date: str
    room_stay_end_date: str
    room_stay_quantity: int
    adults: int
    children: int

    def params(self) -> dict[str, str | int]:
        return {
            "roomStayStartDate": self.room_stay_start_date,
            "roomStayEndDate": self.room_stay_end_date,
            "roomStayQuantity": self.room_stay_quantity,
            "adults": self.adults,
            "children": self.children,
            "roomType": self.room_type,
        }


@dataclass(frozen=True)
class OracleAvailabilityResponse:
    request: OracleAvailabilityRequest
    status_code: int
    body: dict[str, Any] | list[Any] | str | None
    request_url: str


class OracleAvailabilityClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def check_availability(self, booking: BookingRequest, reference_date: str | None = None) -> OracleAvailabilityResponse:
        availability_request = build_availability_request(
            booking,
            self.settings,
            reference_date=reference_date,
        )
        token = OracleAuthClient(self.settings, session=self.session).fetch_token()
        response = self.session.get(
            self._availability_url(availability_request.hotel_code),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token.access_token}",
                "x-app-key": self.settings.oracle_app_key or "",
                "enterpriseId": self.settings.oracle_enterprise_id,
                "x-hotelid": availability_request.hotel_code,
            },
            params=availability_request.params(),
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Oracle availability request failed: HTTP {response.status_code} {_safe_text(response)}"
            ) from exc
        return OracleAvailabilityResponse(
            request=availability_request,
            status_code=response.status_code,
            body=_response_body(response),
            request_url=response.url,
        )

    def _availability_url(self, hotel_code: str) -> str:
        host = (self.settings.oracle_host_name or "").strip().rstrip("/")
        if not host:
            self.settings.require_oracle_auth_config()
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return f"{host}/par/v1/hotels/{hotel_code}/availability"


def build_availability_request(
    booking: BookingRequest,
    settings: Settings,
    reference_date: str | None = None,
) -> OracleAvailabilityRequest:
    missing = [
        field
        for field in ["arrival_date", "departure_date", "adults", "rooms"]
        if getattr(booking, field) in (None, "", 0)
    ]
    if missing:
        raise RuntimeError(f"Cannot check Oracle availability. Missing booking fields: {', '.join(missing)}.")
    year = _reference_year(reference_date)
    return OracleAvailabilityRequest(
        hotel_code=settings.oracle_hotel_code,
        room_type=settings.oracle_room_type,
        room_stay_start_date=_parse_stay_date(str(booking.arrival_date), year),
        room_stay_end_date=_parse_stay_date(str(booking.departure_date), year),
        room_stay_quantity=int(booking.rooms or 1),
        adults=int(booking.adults or 1),
        children=int(booking.children or 0),
    )


def load_booking_from_file_email(settings: Settings) -> tuple[BookingRequest, str | None]:
    email = load_email_from_file(settings.email_file_path)
    intent = normalize_intent_result(heuristic_intent(email), email)
    if not intent.booking_request:
        raise RuntimeError("Current email does not contain a booking request.")
    return intent.booking_request, email.received_datetime


def _parse_stay_date(value: str, default_year: int) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            pass
    parsed_without_year = _parse_day_month_without_year(cleaned, default_year)
    if parsed_without_year:
        return parsed_without_year
    raise RuntimeError(f"Could not parse stay date for Oracle availability: {value}")


def _parse_day_month_without_year(value: str, default_year: int) -> str | None:
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)", value)
    if match:
        day = int(match.group(1))
        month = month_names.get(match.group(2).lower())
        if month:
            return datetime(default_year, month, day).date().isoformat()
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})", value)
    if match:
        month = month_names.get(match.group(1).lower())
        day = int(match.group(2))
        if month:
            return datetime(default_year, month, day).date().isoformat()
    return None


def _reference_year(reference_date: str | None) -> int:
    if not reference_date:
        return datetime.now().year
    try:
        return datetime.fromisoformat(reference_date.replace("Z", "+00:00")).year
    except ValueError:
        return datetime.now().year


def _response_body(response: requests.Response) -> dict[str, Any] | list[Any] | str | None:
    text = (response.text or "").strip()
    if not text:
        return None
    try:
        return response.json()
    except ValueError:
        return text


def _safe_text(response: requests.Response) -> str:
    return (response.text or "").strip()[:500]


def main() -> int:
    settings = load_settings()
    try:
        booking, reference_date = load_booking_from_file_email(settings)
        result = OracleAvailabilityClient(settings).check_availability(
            booking,
            reference_date=reference_date,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Oracle availability request succeeded.")
    print(f"request_url: {result.request_url}")
    print(f"status_code: {result.status_code}")
    print("request_params:")
    print(json.dumps(result.request.params(), indent=2, ensure_ascii=False))
    print("response_body:")
    print(json.dumps(result.body, indent=2, ensure_ascii=False) if not isinstance(result.body, str) else result.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
