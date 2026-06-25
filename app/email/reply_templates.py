from __future__ import annotations

from app.ai.schemas import BookingRequest


FIELD_LABELS = {
    "guest_name": "Guest Name",
    "arrival_date": "Arrival Date",
    "departure_date": "Departure Date",
    "adults": "Number of Adults",
    "rooms": "Number of Rooms",
    "room_type/property_name/hotel_code": "Room Type or Hotel/Property",
    "room_type": "Room Type or Hotel/Property",
    "property_name": "Room Type or Hotel/Property",
    "hotel_code": "Room Type or Hotel/Property",
}


def reply_subject(original_subject: str) -> str:
    subject = original_subject.strip() or "Your hotel enquiry"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def user_friendly_missing_fields(missing_fields: list[str]) -> list[str]:
    labels: list[str] = []
    for field in missing_fields:
        label = FIELD_LABELS.get(field, field.replace("_", " ").title())
        if label not in labels:
            labels.append(label)
    return labels


def booking_details_sentence(booking: BookingRequest | None) -> str:
    if not booking:
        return "your reservation request"
    parts: list[str] = []
    if booking.rooms and booking.room_type:
        room_text = "room" if booking.rooms == 1 else "rooms"
        parts.append(f"{booking.rooms} {booking.room_type} {room_text}")
    elif booking.rooms:
        room_text = "room" if booking.rooms == 1 else "rooms"
        parts.append(f"{booking.rooms} {room_text}")
    elif booking.room_type:
        parts.append(f"{booking.room_type} room")
    if booking.guest_name:
        parts.append(f"for {booking.guest_name}")
    if booking.adults:
        adult_text = "adult" if booking.adults == 1 else "adults"
        parts.append(f"for {booking.adults} {adult_text}")
    if booking.arrival_date and booking.departure_date:
        parts.append(f"from {booking.arrival_date} to {booking.departure_date}")
    if booking.property_name:
        parts.append(f"at {booking.property_name}")
    return " ".join(parts) if parts else "your reservation request"
