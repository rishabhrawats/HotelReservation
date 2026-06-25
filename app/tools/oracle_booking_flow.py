from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.ai.schemas import BookingRequest, EmailInput, IntentResult, OracleAvailabilityOption, OracleOperationResult
from app.config import Settings
from app.tools.oracle_availability import OracleAvailabilityClient, _parse_stay_date, _reference_year
from app.tools.oracle_cancellation import OracleCancellationClient
from app.tools.oracle_reservation_create import OracleReservationCreateClient


def run_oracle_booking_flow(
    email: EmailInput,
    intent: IntentResult,
    settings: Settings,
) -> OracleOperationResult | None:
    if not settings.enable_oracle_api:
        return None
    if intent.primary_intent == "booking_cancellation":
        confirmation = _confirmation_number(email, intent)
        if not confirmation:
            return OracleOperationResult(
                operation="failed",
                success=False,
                message="Cancellation request is missing a confirmation or booking reference.",
                error="missing_confirmation_number",
            )
        try:
            result = OracleCancellationClient(settings).cancel_by_confirmation(confirmation)
            return OracleOperationResult(
                operation="booking_cancelled",
                success=True,
                message="Reservation cancelled in Oracle.",
                reservation_id=result.reservation_id,
                confirmation_number=result.confirmation_number,
                cancellation_id=result.cancellation_id,
            )
        except Exception as exc:
            return OracleOperationResult(
                operation="failed",
                success=False,
                message="Oracle cancellation failed.",
                confirmation_number=confirmation,
                error=str(exc),
            )

    booking = intent.booking_request
    if intent.primary_intent not in {"booking_request", "availability_check", "booking_enquiry"} or not booking:
        return None
    if booking.missing_fields:
        return None
    try:
        return _book_or_offer_alternatives(email, intent, booking, settings)
    except Exception as exc:
        return OracleOperationResult(
            operation="failed",
            success=False,
            message="Oracle availability or booking operation failed.",
            error=str(exc),
        )


def _book_or_offer_alternatives(
    email: EmailInput,
    intent: IntentResult,
    booking: BookingRequest,
    settings: Settings,
) -> OracleOperationResult:
    reference_year = _reference_year(email.received_datetime)
    requested_start = _parse_date(booking.arrival_date, reference_year)
    requested_end = _parse_date(booking.departure_date, reference_year)
    exact_response = OracleAvailabilityClient(settings).check_availability(
        booking,
        reference_date=email.received_datetime,
    )
    exact_options = _availability_options(exact_response.body, requested_start, requested_end, True)
    if exact_options:
        if intent.primary_intent in {"availability_check", "booking_enquiry"}:
            return OracleOperationResult(
                operation="availability_checked",
                success=True,
                message="Requested dates are available. A quotation was prepared.",
                requested_arrival_date=requested_start.isoformat(),
                requested_departure_date=requested_end.isoformat(),
                options=exact_options[: settings.oracle_alternative_max_options],
            )
        created = OracleReservationCreateClient(settings).create_reservation(
            booking,
            reference_date=email.received_datetime,
        )
        reservation_id, confirmation = _created_ids(created.body)
        return OracleOperationResult(
            operation="booking_created",
            success=True,
            message="Requested dates are available and the reservation was created in Oracle.",
            requested_arrival_date=requested_start.isoformat(),
            requested_departure_date=requested_end.isoformat(),
            options=exact_options[:1],
            reservation_id=reservation_id,
            confirmation_number=confirmation,
            custom_reference=_created_custom_reference(created.request.payload),
        )

    alternatives = _nearby_options(booking, settings, email.received_datetime, requested_start, requested_end)
    if alternatives:
        return OracleOperationResult(
            operation="booking_alternatives",
            success=True,
            message="Requested dates were not available. Nearby alternatives were found.",
            requested_arrival_date=requested_start.isoformat(),
            requested_departure_date=requested_end.isoformat(),
            options=alternatives,
        )
    return OracleOperationResult(
        operation="booking_unavailable",
        success=True,
        message="Requested dates were not available and no nearby alternatives were found.",
        requested_arrival_date=requested_start.isoformat(),
        requested_departure_date=requested_end.isoformat(),
        options=[],
    )


def _nearby_options(
    booking: BookingRequest,
    settings: Settings,
    reference_date: str,
    requested_start: date,
    requested_end: date,
) -> list[OracleAvailabilityOption]:
    stay_length = requested_end - requested_start
    options: list[OracleAvailabilityOption] = []
    for offset in _offsets(settings.oracle_alternative_search_days):
        start = requested_start + timedelta(days=offset)
        end = start + stay_length
        shifted = booking.model_copy(
            update={"arrival_date": start.isoformat(), "departure_date": end.isoformat()}
        )
        try:
            response = OracleAvailabilityClient(settings).check_availability(shifted, reference_date=reference_date)
        except Exception:
            continue
        options.extend(_availability_options(response.body, start, end, False))
        if len(options) >= settings.oracle_alternative_max_options:
            break
    return options[: settings.oracle_alternative_max_options]


def _offsets(days: int) -> list[int]:
    offsets: list[int] = []
    for value in range(1, days + 1):
        offsets.extend([-value, value])
    return offsets


def _availability_options(
    body: dict[str, Any] | list[Any] | str | None,
    arrival: date,
    departure: date,
    is_requested_dates: bool,
) -> list[OracleAvailabilityOption]:
    if not isinstance(body, dict):
        return []
    options: list[OracleAvailabilityOption] = []
    for availability in body.get("hotelAvailability", []):
        for room_stay in availability.get("roomStays", []):
            for rate in room_stay.get("roomRates", []) or []:
                units = _optional_int(rate.get("numberOfUnits"))
                if units is not None and units <= 0:
                    continue
                total = rate.get("total") or {}
                amount = _optional_float(total.get("amountBeforeTax"))
                currency = total.get("currencyCode")
                options.append(
                    OracleAvailabilityOption(
                        arrival_date=arrival.isoformat(),
                        departure_date=departure.isoformat(),
                        room_type=str(rate.get("roomType") or ""),
                        rate_plan_code=rate.get("ratePlanCode"),
                        number_of_units=units,
                        amount_before_tax=amount,
                        currency_code=str(currency) if currency else None,
                        is_requested_dates=is_requested_dates,
                    )
                )
    return options


def _parse_date(value: str | None, reference_year: int) -> date:
    if not value:
        raise RuntimeError("Missing date for Oracle operation.")
    return date.fromisoformat(_parse_stay_date(str(value), reference_year))


def _confirmation_number(email: EmailInput, intent: IntentResult) -> str | None:
    booking = intent.booking_request
    for value in [
        booking.booking_reference if booking else None,
        booking.ota_reference if booking else None,
        booking.custom_reference if booking else None,
    ]:
        if value:
            return str(value)
    text = f"{email.subject}\n{email.body_text}"
    match = re.search(
        r"(?:confirmation|booking|reservation)\s*(?:number|reference|ref)?\s*[:#]?\s*([A-Z0-9-]{4,})",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _created_ids(body: dict[str, Any] | list[Any] | str | None) -> tuple[str | None, str | None]:
    if not isinstance(body, dict):
        return None, None
    for link in body.get("links", []):
        href = str(link.get("href", ""))
        if "/reservations/" in href:
            reservation_id = href.rstrip("/").split("/")[-1]
            break
    else:
        reservation_id = None
    confirmation = None
    for link in body.get("links", []):
        href = str(link.get("href", ""))
        match = re.search(r"confirmationNumberList=([^&]+)", href)
        if match:
            confirmation = match.group(1)
            break
    return reservation_id, confirmation


def _created_custom_reference(payload: dict[str, Any]) -> str | None:
    try:
        return payload["reservations"]["reservation"][0].get("customReference")
    except Exception:
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
