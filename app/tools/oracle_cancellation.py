from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

import requests

from app.config import Settings, load_settings
from app.tools.oracle_auth import OracleAuthClient
from app.tools.oracle_availability import _response_body, _safe_text


@dataclass(frozen=True)
class OracleCancellationResponse:
    confirmation_number: str
    reservation_id: str
    cancellation_id: str | None
    status_code: int
    body: dict[str, Any] | list[Any] | str | None
    request_url: str


class OracleCancellationClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def lookup_by_confirmation(self, confirmation_number: str) -> dict[str, Any]:
        token = OracleAuthClient(self.settings, session=self.session).fetch_token()
        response = self.session.get(
            self._reservations_url(),
            headers=self._headers(token.access_token, include_content_type=False),
            params={"confirmationNumberList": confirmation_number},
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Oracle reservation lookup failed: HTTP {response.status_code} {_safe_text(response)}"
            ) from exc
        body = _response_body(response)
        if not isinstance(body, dict):
            raise RuntimeError("Oracle reservation lookup returned an unsupported response body.")
        return body

    def cancel_by_confirmation(
        self,
        confirmation_number: str,
        reason_code: str = "CANCEL",
        reason_description: str = "Reservation Cancelled",
    ) -> OracleCancellationResponse:
        if not self.settings.oracle_allow_cancellation:
            raise RuntimeError("Oracle cancellation is disabled. Set ORACLE_ALLOW_CANCELLATION=true.")
        lookup = self.lookup_by_confirmation(confirmation_number)
        reservation_id = _reservation_id_from_lookup(lookup)
        token = OracleAuthClient(self.settings, session=self.session).fetch_token()
        payload = {"reason": {"code": reason_code, "description": reason_description}}
        response = self.session.post(
            self._cancellation_url(reservation_id),
            headers=self._headers(token.access_token, include_content_type=True),
            json=payload,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Oracle cancellation failed: HTTP {response.status_code} {_safe_text(response)}"
            ) from exc
        body = _response_body(response)
        return OracleCancellationResponse(
            confirmation_number=confirmation_number,
            reservation_id=reservation_id,
            cancellation_id=_cancellation_id_from_body(body),
            status_code=response.status_code,
            body=body,
            request_url=response.url,
        )

    def _headers(self, token: str, include_content_type: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "x-app-key": self.settings.oracle_app_key or "",
            "enterpriseId": self.settings.oracle_enterprise_id,
            "x-hotelid": self.settings.oracle_hotel_code,
        }
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _reservations_url(self) -> str:
        return f"{_host(self.settings)}/rsv/v1/hotels/{self.settings.oracle_hotel_code}/reservations/"

    def _cancellation_url(self, reservation_id: str) -> str:
        return (
            f"{_host(self.settings)}/rsv/v1/hotels/{self.settings.oracle_hotel_code}"
            f"/reservations/{reservation_id}/cancellations"
        )


def _reservation_id_from_lookup(body: dict[str, Any]) -> str:
    reservations = body.get("reservations", {}).get("reservationInfo", [])
    if not reservations:
        raise RuntimeError("No Oracle reservation found for that confirmation number.")
    id_list = reservations[0].get("reservationIdList", [])
    for item in id_list:
        if item.get("type") == "Reservation" and item.get("id"):
            return str(item["id"])
    raise RuntimeError("Oracle lookup did not return a reservation id.")


def _cancellation_id_from_body(body: dict[str, Any] | list[Any] | str | None) -> str | None:
    if not isinstance(body, dict):
        return None
    for reservation in body.get("reservations", []):
        for item in reservation.get("reservationIdList", []):
            if item.get("type") == "Cancellation" and item.get("id"):
                return str(item["id"])
    for activity in body.get("cxlActivityLog", []):
        for item in activity.get("cancellationIdList", []):
            if item.get("id"):
                return str(item["id"])
    return None


def _host(settings: Settings) -> str:
    host = (settings.oracle_host_name or "").strip().rstrip("/")
    if not host:
        settings.require_oracle_auth_config()
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.tools.oracle_cancellation <confirmation_number>", file=sys.stderr)
        return 1
    settings = load_settings()
    try:
        result = OracleCancellationClient(settings).cancel_by_confirmation(sys.argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Oracle cancellation succeeded.")
    print(f"reservation_id: {result.reservation_id}")
    print(f"confirmation_number: {result.confirmation_number}")
    print(f"cancellation_id: {result.cancellation_id or '-'}")
    print(f"status_code: {result.status_code}")
    print("response_body:")
    print(json.dumps(result.body, indent=2, ensure_ascii=False) if not isinstance(result.body, str) else result.body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
