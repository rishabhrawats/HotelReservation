from __future__ import annotations

import argparse
import json
import secrets
import sys
from dataclasses import dataclass
from typing import Any

import requests

from app.ai.schemas import BookingRequest
from app.config import Settings, load_settings
from app.tools.oracle_auth import OracleAuthClient
from app.tools.oracle_availability import (
    _parse_stay_date,
    _reference_year,
    _response_body,
    _safe_text,
    load_booking_from_file_email,
)


@dataclass(frozen=True)
class OracleReservationCreateRequest:
    hotel_code: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class OracleReservationCreateResponse:
    request: OracleReservationCreateRequest
    status_code: int
    body: dict[str, Any] | list[Any] | str | None
    request_url: str


class OracleReservationCreateClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def create_reservation(
        self,
        booking: BookingRequest,
        reference_date: str | None = None,
        custom_reference: str | None = None,
    ) -> OracleReservationCreateResponse:
        if not self.settings.oracle_allow_reservation_create:
            raise RuntimeError(
                "Oracle reservation creation is disabled. Set ORACLE_ALLOW_RESERVATION_CREATE=true "
                "and rerun with --execute only when you intentionally want to create a reservation."
            )
        create_request = build_create_reservation_request(
            booking,
            self.settings,
            reference_date=reference_date,
            custom_reference=custom_reference,
        )
        token = OracleAuthClient(self.settings, session=self.session).fetch_token()
        response = self.session.post(
            self._reservation_url(create_request.hotel_code),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token.access_token}",
                "x-app-key": self.settings.oracle_app_key or "",
                "enterpriseId": self.settings.oracle_enterprise_id,
                "x-hotelid": create_request.hotel_code,
            },
            json=create_request.payload,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Oracle reservation creation failed: HTTP {response.status_code} {_safe_text(response)}"
            ) from exc
        return OracleReservationCreateResponse(
            request=create_request,
            status_code=response.status_code,
            body=_response_body(response),
            request_url=response.url,
        )

    def _reservation_url(self, hotel_code: str) -> str:
        host = (self.settings.oracle_host_name or "").strip().rstrip("/")
        if not host:
            self.settings.require_oracle_auth_config()
        if not host.startswith(("http://", "https://")):
            host = f"https://{host}"
        return f"{host}/rsv/v1/hotels/{hotel_code}/reservations"


def build_create_reservation_request(
    booking: BookingRequest,
    settings: Settings,
    reference_date: str | None = None,
    custom_reference: str | None = None,
) -> OracleReservationCreateRequest:
    missing = [
        field
        for field in ["guest_name", "arrival_date", "departure_date", "adults", "rooms"]
        if getattr(booking, field) in (None, "", 0)
    ]
    if missing:
        raise RuntimeError(f"Cannot create Oracle reservation. Missing booking fields: {', '.join(missing)}.")
    year = _reference_year(reference_date)
    arrival_date = _parse_stay_date(str(booking.arrival_date), year)
    departure_date = _parse_stay_date(str(booking.departure_date), year)
    adults = str(int(booking.adults or 1))
    children = str(int(booking.children or 0))
    rooms = str(int(booking.rooms or 1))
    given_name, surname = _split_guest_name(str(booking.guest_name))
    custom_ref = custom_reference or booking.custom_reference or _generate_custom_reference(settings)

    room_rate = {
        "total": {"amountBeforeTax": "0"},
        "rates": {
            "rate": [
                {
                    "base": {"amountBeforeTax": "0"},
                    "shareDistributionInstruction": "Full",
                    "total": {"amountBeforeTax": "0"},
                }
            ]
        },
        "guestCounts": {"adults": adults, "children": children},
        "roomType": settings.oracle_room_type,
        "ratePlanCode": settings.oracle_rate_plan_code,
        "start": arrival_date,
        "end": departure_date,
        "suppressRate": True,
        "marketCode": settings.oracle_market_code,
        "sourceCode": settings.oracle_source_code,
        "numberOfUnits": rooms,
        "roomTypeCharged": settings.oracle_room_type,
        "fixedRate": False,
    }
    payload = {
        "reservations": {
            "reservation": [
                {
                    "sourceOfSale": {
                        "sourceType": "PMS",
                        "sourceCode": settings.oracle_hotel_code,
                    },
                    "roomStay": {
                        "roomRates": [room_rate],
                        "guestCounts": {"adults": adults, "children": children},
                        "arrivalDate": arrival_date,
                        "departureDate": departure_date,
                        "roomNumberLocked": False,
                        "guarantee": {"guaranteeCode": settings.oracle_guarantee_code},
                        "printRate": False,
                        "bookingMedium": settings.oracle_booking_medium,
                    },
                    "reservationGuests": [
                        {
                            "profileInfo": {
                                "profile": {
                                    "customer": {
                                        "personName": [
                                            {
                                                "givenName": given_name,
                                                "surname": surname,
                                                "nameType": "Primary",
                                            }
                                        ],
                                        "language": "E",
                                    },
                                    "profileType": "Guest",
                                }
                            },
                            "primary": True,
                        }
                    ],
                    "reservationPaymentMethods": [
                        {"paymentMethod": settings.oracle_payment_method, "folioView": "1"},
                        {"paymentMethod": "", "folioView": "2"},
                    ],
                    "hotelId": settings.oracle_hotel_code,
                    "roomStayReservation": True,
                    "overrideInventoryCheck": True,
                    "reservationStatus": "Reserved",
                    "computedReservationStatus": "Reserved",
                    "optedForCommunication": False,
                    "customReference": custom_ref,
                }
            ]
        }
    }
    return OracleReservationCreateRequest(hotel_code=settings.oracle_hotel_code, payload=payload)


def _split_guest_name(guest_name: str) -> tuple[str, str]:
    parts = [part for part in guest_name.strip().split() if part]
    if not parts:
        return "Guest", "Guest"
    if len(parts) == 1:
        return parts[0], "Guest"
    return " ".join(parts[:-1]), parts[-1]


def _generate_custom_reference(settings: Settings) -> str:
    return f"{settings.oracle_custom_reference_prefix}-{secrets.randbelow(1_000_000_000):09d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or execute Oracle reservation creation.")
    parser.add_argument("--execute", action="store_true", help="Actually POST the reservation to Oracle.")
    parser.add_argument("--custom-reference", help="Override generated customReference.")
    args = parser.parse_args()

    settings = load_settings()
    try:
        booking, reference_date = load_booking_from_file_email(settings)
        create_request = build_create_reservation_request(
            booking,
            settings,
            reference_date=reference_date,
            custom_reference=args.custom_reference,
        )
        client = OracleReservationCreateClient(settings)
        url = client._reservation_url(create_request.hotel_code)
        if not args.execute:
            print("Oracle reservation creation dry run. No reservation was created.")
            print(f"request_url: {url}")
            print("request_body:")
            print(json.dumps(create_request.payload, indent=2, ensure_ascii=False))
            print("\nTo execute, set ORACLE_ALLOW_RESERVATION_CREATE=true and run with --execute.")
            return 0
        result = client.create_reservation(
            booking,
            reference_date=reference_date,
            custom_reference=args.custom_reference,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Oracle reservation creation succeeded.")
    print(f"request_url: {result.request_url}")
    print(f"status_code: {result.status_code}")
    print("request_body:")
    print(json.dumps(result.request.payload, indent=2, ensure_ascii=False))
    print("response_body:")
    print(json.dumps(result.body, indent=2, ensure_ascii=False) if not isinstance(result.body, str) else result.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
