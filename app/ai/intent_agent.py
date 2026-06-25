from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from app.ai.prompts import INTENT_SYSTEM_PROMPT
from app.ai.schemas import BookingRequest, EmailInput, IntentResult, PolicyQuestion
from app.config import Settings, load_settings

logger = logging.getLogger(__name__)

WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

ROOM_TYPES = [
    "single",
    "double",
    "twin",
    "king",
    "queen",
    "family",
    "accessible",
    "suite",
]

INTENT_CATEGORY_QUESTIONS = {
    "early_checkin_request": ("early check-in", "Can I check in early?"),
    "late_checkout_request": ("late check-out", "Is late check-out available?"),
    "luggage_storage_request": ("luggage storage", "Can I leave my luggage before check-in?"),
    "parking_request": ("parking", "Is parking available?"),
    "taxi_transfer_request": ("taxi / airport transfer", "Is taxi or airport transfer available?"),
    "pet_policy_question": ("pet policy", "What is the pet policy?"),
    "refund_cancellation_policy_question": ("refund/cancellation", "What is the cancellation or refund policy?"),
    "bed_type_request": ("bed type", "Can I request a specific bed type?"),
    "room_preference_request": ("room preference", "Can I request a room preference?"),
    "accessibility_request": ("accessibility", "What accessibility options are available?"),
    "invoice_request": ("invoice", "Can I request an invoice?"),
}

SPECIAL_REQUEST_CATEGORY_QUESTIONS = {
    "early check-in": ("early check-in", "Can I check in early?"),
    "luggage storage": ("luggage storage", "Can I leave my luggage before check-in?"),
    "parking": ("parking", "Is parking available?"),
    "taxi transfer": ("taxi / airport transfer", "Is taxi or airport transfer available?"),
    "airport transfer": ("taxi / airport transfer", "Is taxi or airport transfer available?"),
}


def classify_email(email: EmailInput, settings: Settings | None = None) -> IntentResult:
    settings = settings or load_settings()
    if settings.strict_real_mode:
        settings.require_openai_credentials()
    if settings.openai_api_key:
        try:
            return normalize_intent_result(_classify_with_openai(email, settings), email)
        except Exception as exc:
            if not settings.can_use_local_ai_fallback:
                raise RuntimeError(f"OpenAI intent classification failed in real mode: {exc}") from exc
            logger.warning("OpenAI intent classification failed; using safe local fallback: %s", exc)
    if not settings.can_use_local_ai_fallback:
        settings.require_openai_credentials()
    return normalize_intent_result(heuristic_intent(email), email)


def _classify_with_openai(email: EmailInput, settings: Settings) -> IntentResult:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "subject": email.subject,
        "sender_name": email.sender_name,
        "sender_email": email.sender_email,
        "body_text": email.body_text,
        "allowed_intents": IntentResult.model_fields["primary_intent"].annotation.__args__,
        "allowed_next_actions": IntentResult.model_fields["next_action"].annotation.__args__,
        "booking_required_fields": [
            "guest_name",
            "arrival_date",
            "departure_date",
            "adults",
            "rooms",
            "room_type/property_name/hotel_code is optional because the operational room type is configured by the system",
        ],
    }
    response = client.responses.parse(
        model=settings.openai_model,
        instructions=INTENT_SYSTEM_PROMPT,
        input=json.dumps(payload, ensure_ascii=False),
        text_format=IntentResult,
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed
    return IntentResult.model_validate_json(response.output_text)


def heuristic_intent(email: EmailInput) -> IntentResult:
    text = f"{email.subject}\n{email.body_text}".strip()
    lowered = text.lower()
    booking = _extract_booking(text) if _looks_like_booking(lowered) else None
    questions = _extract_questions(email.body_text.strip(), email.body_text.lower())
    intents = _detect_intents(lowered, booking, questions)
    primary = intents[0] if intents else "unknown"
    secondary = [intent for intent in intents[1:] if intent != primary]
    confidence = _heuristic_confidence(primary, booking, questions, lowered)
    requires_human_review, reason = _human_review_signal(primary, lowered, confidence)
    next_action = _next_action(primary, booking, questions, requires_human_review)
    summary = _summary(email.body_text)
    return IntentResult(
        primary_intent=primary,
        secondary_intents=secondary,
        confidence=confidence,
        requires_human_review=requires_human_review,
        human_review_reason=reason,
        customer_message_summary=summary,
        booking_request=booking,
        questions=questions,
        next_action=next_action,
    )


def normalize_intent_result(intent: IntentResult, email: EmailInput) -> IntentResult:
    questions = list(intent.questions)
    for intent_name in [intent.primary_intent, *intent.secondary_intents]:
        mapped = INTENT_CATEGORY_QUESTIONS.get(intent_name)
        if mapped:
            questions.append(
                PolicyQuestion(question=mapped[1], category=mapped[0], needs_rag_answer=True)
            )
    booking = intent.booking_request
    if booking:
        for request in booking.special_requests:
            mapped = SPECIAL_REQUEST_CATEGORY_QUESTIONS.get(request.lower())
            if mapped:
                questions.append(
                    PolicyQuestion(question=mapped[1], category=mapped[0], needs_rag_answer=True)
                )
        booking = _normalize_booking_request(booking, email)
    questions = _dedupe_questions(questions)
    updates: dict = {"questions": questions}
    if booking:
        updates["booking_request"] = booking
    if questions and booking and not intent.requires_human_review:
        updates["next_action"] = (
            "ask_missing_details"
            if booking.missing_fields
            else "answer_question_and_acknowledge_booking"
        )
    elif questions and not booking and not intent.requires_human_review:
        updates["next_action"] = "answer_policy_question"
    elif booking and not intent.requires_human_review:
        updates["next_action"] = (
            "ask_missing_details" if booking.missing_fields else "acknowledge_booking_request"
        )
    return intent.model_copy(update=updates)


def _normalize_booking_request(booking: BookingRequest, email: EmailInput) -> BookingRequest:
    text = f"{email.subject}\n{email.body_text}".strip()
    updates: dict = {}
    if booking.guest_name in (None, ""):
        updates["guest_name"] = _extract_guest_name(text)
    if booking.adults in (None, 0):
        updates["adults"] = _extract_count(
            text, r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+adults?"
        )
    if booking.rooms in (None, 0):
        updates["rooms"] = _extract_rooms(text)
    if booking.room_type in (None, ""):
        updates["room_type"] = _extract_room_type(text)
    if booking.property_name in (None, ""):
        updates["property_name"] = _extract_property_name(text)
    if booking.arrival_date in (None, "") or booking.departure_date in (None, ""):
        arrival, departure = _extract_dates(text)
        if booking.arrival_date in (None, ""):
            updates["arrival_date"] = arrival
        if booking.departure_date in (None, ""):
            updates["departure_date"] = departure
    special_requests = list(booking.special_requests)
    for request in _extract_special_requests(text.lower()):
        if request not in special_requests:
            special_requests.append(request)
    updates["special_requests"] = special_requests
    normalized = booking.model_copy(update=updates)
    return normalized.model_copy(update={"missing_fields": missing_booking_fields(normalized)})


def _looks_like_booking(lowered: str) -> bool:
    booking_terms = ["book", "reserve", "reservation", "availability", "room"]
    exclusion_terms = ["cancel", "modify", "change my booking", "invoice", "complaint"]
    return any(term in lowered for term in booking_terms) and not any(
        term in lowered for term in exclusion_terms
    )


def _extract_booking(text: str) -> BookingRequest:
    booking = BookingRequest(
        guest_name=_extract_guest_name(text),
        arrival_date=None,
        departure_date=None,
        adults=_extract_count(text, r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+adults?"),
        children=_extract_count(text, r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+children?"),
        rooms=_extract_rooms(text),
        room_type=_extract_room_type(text),
        property_name=_extract_property_name(text),
        booking_reference=_extract_reference(text, r"booking\s+(?:reference|ref)\s*[:#]?\s*([A-Z0-9-]+)"),
        ota_reference=_extract_reference(text, r"ota\s+(?:reference|ref)\s*[:#]?\s*([A-Z0-9-]+)"),
        custom_reference=_extract_reference(text, r"(?:custom|customer)\s+(?:reference|ref)\s*[:#]?\s*([A-Z0-9-]+)"),
        special_requests=_extract_special_requests(text.lower()),
    )
    arrival, departure = _extract_dates(text)
    booking.arrival_date = arrival
    booking.departure_date = departure
    booking.missing_fields = missing_booking_fields(booking)
    return booking


def missing_booking_fields(booking: BookingRequest) -> list[str]:
    missing: list[str] = []
    for field in ["guest_name", "arrival_date", "departure_date", "adults", "rooms"]:
        if getattr(booking, field) in (None, "", 0):
            missing.append(field)
    return missing


def _extract_count(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    if value.isdigit():
        return int(value)
    return WORD_NUMBERS.get(value)


def _extract_rooms(text: str) -> int | None:
    match = re.search(
        r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:\w+\s+)?rooms?\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).lower()
    return int(value) if value.isdigit() else WORD_NUMBERS.get(value)


def _extract_room_type(text: str) -> str | None:
    lowered = text.lower()
    for room_type in ROOM_TYPES:
        if re.search(rf"\b{room_type}\s+room\b", lowered):
            return room_type
    return None


def _extract_guest_name(text: str) -> str | None:
    match = re.search(
        r"\bfor\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})(?=,|\s+\d|\s+from|\.|$)",
        text,
    )
    if not match:
        return None
    candidate = match.group(1).strip()
    if candidate.lower() in {"tomorrow", "today", "tonight"}:
        return None
    if any(month in candidate.lower() for month in _months()):
        return None
    return candidate


def _extract_property_name(text: str) -> str | None:
    match = re.search(
        r"\bat\s+([A-Z][\w'&-]+(?:\s+[A-Z][\w'&-]+){0,6})(?=\.|,|\?|$|\s+also\b)",
        text,
    )
    return match.group(1).strip() if match else None


def _extract_reference(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_dates(text: str) -> tuple[str | None, str | None]:
    pattern = (
        r"\bfrom\s+(.+?)\s+(?:to|until|-)\s+(.+?)"
        r"(?=\s+at\b|\.|,|\?|$|\s+for\b|\s+with\b|\s+also\b)"
    )
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return _clean_date(match.group(1)), _clean_date(match.group(2))
    match = re.search(r"\bbetween\s+(.+?)\s+and\s+(.+?)(?=\.|,|\?|$)", text, re.IGNORECASE)
    if match:
        return _clean_date(match.group(1)), _clean_date(match.group(2))
    one_date = re.search(r"\b(?:on|for)\s+(tomorrow|today|tonight)\b", text, re.IGNORECASE)
    if one_date:
        return one_date.group(1), None
    return None, None


def _clean_date(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,-"))


def _months() -> Iterable[str]:
    return (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )


def _extract_special_requests(lowered: str) -> list[str]:
    requests: list[str] = []
    keyword_map = {
        "early check": "early check-in",
        "late checkout": "late check-out",
        "late check-out": "late check-out",
        "luggage": "luggage storage",
        "parking": "parking",
        "taxi": "taxi transfer",
        "airport transfer": "airport transfer",
        "high floor": "high floor",
        "low floor": "low floor",
        "view": "room view",
        "baby cot": "baby cot",
        "extra bed": "extra bed",
        "birthday": "birthday",
        "anniversary": "anniversary",
        "honeymoon": "honeymoon",
    }
    for keyword, label in keyword_map.items():
        if keyword in lowered and label not in requests:
            requests.append(label)
    return requests


def _extract_questions(text: str, lowered: str) -> list[PolicyQuestion]:
    questions: list[PolicyQuestion] = []
    question_segments = [segment.strip() for segment in re.split(r"\?", text) if segment.strip()]
    if "?" in text:
        for segment in question_segments:
            for category in _categories_for_text(segment.lower()):
                questions.append(
                    PolicyQuestion(
                        question=_question_for_category(segment, category),
                        category=category,
                        needs_rag_answer=True,
                    )
                )
    if not questions:
        for keyword in [
            "early check",
            "late checkout",
            "late check-out",
            "luggage",
            "parking",
            "pet",
            "refund",
            "free cancellation",
            "taxi",
            "airport transfer",
            "invoice",
        ]:
            if keyword in lowered:
                for category in _categories_for_text(lowered):
                    questions.append(
                        PolicyQuestion(
                            question=_question_for_category(text.strip(), category),
                            category=category,
                            needs_rag_answer=True,
                        )
                    )
                break
    return _dedupe_questions(questions)


def _dedupe_questions(questions: list[PolicyQuestion]) -> list[PolicyQuestion]:
    seen: set[str] = set()
    index_by_key: dict[str, int] = {}
    deduped: list[PolicyQuestion] = []
    for question in questions:
        key = f"{question.question.lower()}|{question.category or ''}"
        if key in seen:
            existing_index = index_by_key[key]
            existing = deduped[existing_index]
            if question.needs_rag_answer and not existing.needs_rag_answer:
                deduped[existing_index] = existing.model_copy(update={"needs_rag_answer": True})
            continue
        deduped.append(question)
        seen.add(key)
        index_by_key[key] = len(deduped) - 1
    return deduped


def _question_for_category(segment: str, category: str) -> str:
    text = re.sub(r"\s+", " ", segment.strip(" ?"))
    if category == "early check-in":
        return "Can I check in early?"
    if category == "luggage storage":
        return "Can I leave my luggage before check-in?"
    if category == "parking":
        return "Is parking available?"
    if category == "taxi / airport transfer":
        return "Is taxi or airport transfer available?"
    if category == "late check-out":
        return "Is late check-out available?"
    return f"{text}?"


def _categories_for_text(lowered: str) -> list[str]:
    mapping = [
        (("early check", "before check-in"), "early check-in"),
        (("late checkout", "late check-out"), "late check-out"),
        (("luggage", "bag"), "luggage storage"),
        (("parking", "car park"), "parking"),
        (("taxi", "airport transfer", "transfer"), "taxi / airport transfer"),
        (("pet", "dog", "cat"), "pet policy"),
        (("refund", "free cancellation", "cancellation"), "refund/cancellation"),
        (("invoice", "receipt"), "invoice"),
        (("bed", "beds"), "bed type"),
        (("view", "high floor", "low floor", "connecting"), "room preference"),
        (("accessib", "wheelchair"), "accessibility"),
        (("smoking",), "smoking"),
    ]
    categories: list[str] = []
    for keywords, category in mapping:
        if any(keyword in lowered for keyword in keywords):
            categories.append(category)
    if not categories and "?" in lowered:
        categories.append("general policy")
    return list(dict.fromkeys(categories))


def _detect_intents(
    lowered: str, booking: BookingRequest | None, questions: list[PolicyQuestion]
) -> list[str]:
    intents: list[str] = []
    if any(term in lowered for term in ["complaint", "unhappy", "terrible", "angry", "bad service"]):
        intents.append("complaint")
    if re.search(r"\bcancel\b|\bcancellation\b", lowered):
        intents.append("booking_cancellation")
    if any(term in lowered for term in ["modify", "change my booking", "amend", "reschedule"]):
        intents.append("booking_modification")
    if "invoice" in lowered or "receipt" in lowered:
        intents.append("invoice_request")
    if booking:
        intents.append("booking_request")
        if "availability" in lowered:
            intents.append("availability_check")
    for question in questions:
        category = (question.category or "").lower()
        if "early check" in category:
            intents.append("early_checkin_request")
        elif "late check" in category:
            intents.append("late_checkout_request")
        elif "luggage" in category:
            intents.append("luggage_storage_request")
        elif "parking" in category:
            intents.append("parking_request")
        elif "taxi" in category or "transfer" in category:
            intents.append("taxi_transfer_request")
        elif "pet" in category:
            intents.append("pet_policy_question")
        elif "refund" in category or "cancellation" in category:
            intents.append("refund_cancellation_policy_question")
        elif "bed" in category:
            intents.append("bed_type_request")
        elif "room preference" in category:
            intents.append("room_preference_request")
        elif "accessibility" in category:
            intents.append("accessibility_request")
        elif "invoice" in category:
            intents.append("invoice_request")
        else:
            intents.append("policy_question")
    if not intents:
        intents.append("unknown")
    return list(dict.fromkeys(intents))


def _heuristic_confidence(
    primary: str, booking: BookingRequest | None, questions: list[PolicyQuestion], lowered: str
) -> float:
    if primary == "unknown":
        return 0.45
    if primary in {"booking_cancellation", "booking_modification", "complaint"}:
        return 0.9
    if booking and not booking.missing_fields:
        return 0.88 if questions else 0.84
    if booking and booking.missing_fields:
        return 0.8
    if questions:
        return 0.82
    if "help" in lowered:
        return 0.55
    return 0.7


def _human_review_signal(primary: str, lowered: str, confidence: float) -> tuple[bool, str | None]:
    if primary == "complaint":
        return True, "Complaint requires reservations team review."
    if primary == "booking_cancellation":
        return True, "Cancellation requests require reservations team review."
    if primary == "booking_modification":
        return True, "Modification requests require reservations team review."
    if any(term in lowered for term in ["refund", "free cancellation", "payment issue", "chargeback"]):
        return True, "Refund, payment, or free-cancellation wording requires human review."
    if confidence < 0.75:
        return True, "Low confidence classification requires human review."
    return False, None


def _next_action(
    primary: str,
    booking: BookingRequest | None,
    questions: list[PolicyQuestion],
    requires_human_review: bool,
) -> str:
    if primary == "booking_cancellation":
        return "cancellation_human_review"
    if primary == "booking_modification":
        return "modification_human_review"
    if primary == "complaint":
        return "complaint_human_review"
    if requires_human_review and primary not in {"unknown"}:
        return "escalate_to_human"
    if booking and booking.missing_fields:
        return "ask_missing_details"
    if booking and questions:
        return "answer_question_and_acknowledge_booking"
    if booking:
        return "acknowledge_booking_request"
    if questions:
        return "answer_policy_question"
    if requires_human_review:
        return "escalate_to_human"
    return "no_action"


def _summary(body_text: str) -> str:
    compact = re.sub(r"\s+", " ", body_text).strip()
    return compact[:240] if compact else "No customer message text found."
