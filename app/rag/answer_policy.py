from __future__ import annotations

import json
import logging
import re

from app.ai.prompts import POLICY_ANSWER_SYSTEM_PROMPT
from app.ai.schemas import PolicyAnswer, PolicyQuestion
from app.config import Settings, load_settings
from app.rag.retriever import CATEGORY_QUERY_TERMS, RetrievedChunk

logger = logging.getLogger(__name__)

INSUFFICIENT_POLICY_ANSWER = (
    "I'm unable to confirm this from the available hotel policy information. "
    "Our reservations team will review and confirm."
)

NOISY_ANSWER_TERMS = [
    "actual message",
    "actual message on extranet",
    "category:",
    "genai / model",
    "sheet1:",
    "sheet2:",
    "sheet3:",
    "source file:",
    "source type:",
    "page:",
    "vector store",
    "json",
]

RELEVANCE_STOPWORDS = {
    "can",
    "could",
    "would",
    "what",
    "does",
    "the",
    "have",
    "has",
    "there",
    "with",
    "for",
    "from",
    "your",
    "you",
    "please",
    "available",
    "hotel",
    "policy",
    "general",
    "request",
    "requested",
}


def answer_policy_question(
    question: PolicyQuestion,
    chunks: list[RetrievedChunk],
    settings: Settings | None = None,
) -> PolicyAnswer:
    settings = settings or load_settings()
    if not chunks:
        return PolicyAnswer(
            question=question.question,
            answer=INSUFFICIENT_POLICY_ANSWER,
            sources=[],
            confidence=0.2,
            insufficient_policy_context=True,
        )
    if settings.use_openai_policy_answer:
        if settings.strict_real_mode:
            settings.require_openai_credentials()
        try:
            return _answer_with_openai(question, chunks, settings)
        except Exception as exc:
            if not settings.can_use_local_ai_fallback:
                raise RuntimeError(f"OpenAI policy answer failed in real mode: {exc}") from exc
            logger.warning("OpenAI policy answer failed; using context-only fallback: %s", exc)
    return _context_only_answer(question, chunks)


def _answer_with_openai(
    question: PolicyQuestion,
    chunks: list[RetrievedChunk],
    settings: Settings,
) -> PolicyAnswer:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    payload = {
        "question": question.model_dump(mode="json"),
        "retrieved_context": [
            {
                "text": chunk.text,
                "metadata": chunk.metadata,
                "source_label": source_label(chunk),
            }
            for chunk in chunks
        ],
        "rules": [
            "Answer only from retrieved context.",
            "If context is insufficient, use the required insufficient-context sentence.",
            "Do not include technical source labels in the answer text.",
            "Put source labels only in sources.",
        ],
    }
    response = client.responses.parse(
        model=settings.openai_model,
        instructions=POLICY_ANSWER_SYSTEM_PROMPT,
        input=json.dumps(payload, ensure_ascii=False),
        text_format=PolicyAnswer,
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed
    return PolicyAnswer.model_validate_json(response.output_text)


def _context_only_answer(question: PolicyQuestion, chunks: list[RetrievedChunk]) -> PolicyAnswer:
    context = "\n".join(chunk.text for chunk in chunks)
    if not _context_is_relevant(question, context):
        return PolicyAnswer(
            question=question.question,
            answer=INSUFFICIENT_POLICY_ANSWER,
            sources=[],
            confidence=0.25,
            insufficient_policy_context=True,
        )
    category_answer = _category_answer_from_context(question, context)
    if category_answer:
        return PolicyAnswer(
            question=question.question,
            answer=category_answer,
            sources=_source_labels(chunks),
            confidence=0.72,
            insufficient_policy_context=False,
        )
    selected = _select_relevant_sentences(question, context)
    if not selected:
        return PolicyAnswer(
            question=question.question,
            answer=INSUFFICIENT_POLICY_ANSWER,
            sources=_source_labels(chunks),
            confidence=0.35,
            insufficient_policy_context=True,
        )
    answer = " ".join(selected[:4]).strip()
    answer = _apply_cautious_language(answer, question)
    answer = _clean_answer_text(answer)
    if not answer or _contains_noise(answer):
        return PolicyAnswer(
            question=question.question,
            answer=INSUFFICIENT_POLICY_ANSWER,
            sources=_source_labels(chunks),
            confidence=0.35,
            insufficient_policy_context=True,
        )
    return PolicyAnswer(
        question=question.question,
        answer=answer,
        sources=_source_labels(chunks),
        confidence=0.72,
        insufficient_policy_context=False,
    )


def _category_answer_from_context(question: PolicyQuestion, context: str) -> str | None:
    category = (question.category or "").lower()
    question_text = question.question.lower()
    raw = f"{question_text} {category}"
    lowered = context.lower()
    if _has_any(raw, ["early check", "check in early", "early arrival"]) and _has_any(
        lowered, ["early check", "early arrival", "arrival time"]
    ):
        answer = (
            "Early check-in can be requested, but it is subject to availability and cannot be guaranteed. "
            "The reservations team can note the requested arrival time and confirm what is possible."
        )
        if "luggage" in raw and "luggage" in lowered:
            answer = (
                f"{answer} Leaving luggage with the hotel before check-in can also be requested "
                "and is handled at hotel discretion."
            )
        return answer
    if _has_any(raw, ["late check", "late checkout"]) and _has_any(
        lowered, ["late check", "late checkout", "departure time"]
    ):
        return (
            "Late check-out can be requested, but it is subject to availability and hotel review. "
            "It cannot be guaranteed, and additional charges may apply depending on the property."
        )
    if _has_any(raw, ["luggage", "bag"]) and _has_any(lowered, ["luggage", "luggage drop", "bags"]):
        return (
            "Leaving luggage with the hotel before check-in can be requested and is handled at hotel discretion. "
            "Our reservations team will review and confirm the arrangements for the property."
        )
    if "parking" in raw and _has_any(lowered, ["parking", "car park"]):
        return (
            "Parking requests are subject to availability, may incur additional charges, and cannot be guaranteed. "
            "Our reservations team will confirm the property-specific parking options."
        )
    if _has_any(raw, ["taxi", "transfer", "airport"]) and _has_any(
        lowered, ["taxi", "airport transfer", "transfer"]
    ):
        return (
            "Taxi or airport transfer requests are subject to availability and may involve third-party or "
            "additional charges. Our reservations team will review and confirm the available options."
        )
    if _has_any(raw, ["extra bed", "baby cot", "cot", "crib", "bed type"]) and _has_any(
        lowered, ["extra bed", "rollaway", "baby cot", "cot", "occupancy"]
    ):
        return (
            "Extra bed or baby cot requests depend on room eligibility, occupancy rules, and availability. "
            "They cannot be guaranteed, and additional charges may apply where the property permits them."
        )
    if _has_any(raw, ["accessib", "wheelchair"]) and _has_any(
        lowered, ["accessib", "wheelchair", "special assistance"]
    ):
        return (
            "Accessibility requests should be reviewed with the property-specific room and facilities information. "
            "Our reservations team will confirm the available options; availability cannot be guaranteed until reviewed."
        )
    if _has_any(raw, ["invoice", "receipt"]) and _has_any(lowered, ["invoice", "receipt", "billing"]):
        return (
            "An invoice or receipt can be requested, but the reservations team may need the booking reference, "
            "guest name, stay dates, and any required billing details before it can be reviewed."
        )
    if _has_any(raw, ["refund", "cancellation", "free cancellation"]) and _has_any(
        lowered, ["refund", "cancellation", "free cancellation", "payment issue"]
    ):
        return (
            "Refund or cancellation outcomes depend on the applicable booking terms, OTA conditions, and hotel review. "
            "The reservations team will review the booking before any refund or free-cancellation outcome is promised."
        )
    if "smoking" in raw and _has_any(lowered, ["smoking", "non-smoking"]):
        return (
            "Smoking-related requests depend on the property's room rules and cannot be guaranteed. "
            "Our reservations team will confirm the property-specific smoking policy."
        )
    return None


def _select_relevant_sentences(question: PolicyQuestion, context: str) -> list[str]:
    keywords = _keywords(question)
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", context)
        if sentence.strip()
    ]
    selected = [
        sentence
        for sentence in sentences
        if any(keyword in sentence.lower() for keyword in keywords)
        and not _contains_noise(sentence)
    ]
    if selected:
        return selected
    return [
        sentence
        for sentence in sentences
        if not _contains_noise(sentence)
    ][:2]


def _keywords(question: PolicyQuestion) -> list[str]:
    raw = f"{question.question} {question.category or ''}".lower()
    words = re.findall(r"[a-z][a-z-]{2,}", raw)
    priority = [
        "early",
        "check-in",
        "check",
        "luggage",
        "parking",
        "taxi",
        "transfer",
        "cancellation",
        "refund",
        "pet",
        "bed",
        "invoice",
        "accessibility",
        "smoking",
        "receipt",
        "cot",
        "wheelchair",
    ]
    return list(dict.fromkeys([word for word in priority if word in raw] + words))


def _apply_cautious_language(answer: str, question: PolicyQuestion) -> str:
    raw = f"{question.question} {question.category or ''}".lower()
    availability_terms = [
        "early",
        "late",
        "parking",
        "taxi",
        "transfer",
        "upgrade",
        "extra bed",
        "cot",
        "view",
        "connecting",
        "adjacent",
    ]
    if any(term in raw for term in availability_terms):
        caution = "These requests are subject to availability, may incur additional charges, and cannot be guaranteed."
        if "subject to availability" not in answer.lower():
            answer = f"{answer} {caution}"
    if any(term in raw for term in ["free cancellation", "refund", "cancellation"]):
        caution = "Any refund or cancellation outcome depends on the applicable booking terms and hotel review."
        if "booking terms" not in answer.lower():
            answer = f"{answer} {caution}"
    return answer


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _context_is_relevant(question: PolicyQuestion, context: str) -> bool:
    lowered = context.lower()
    category = (question.category or "").lower()
    terms = CATEGORY_QUERY_TERMS.get(category, [])
    keywords = [
        keyword
        for keyword in _keywords(question)
        if keyword not in RELEVANCE_STOPWORDS
    ]
    return any(term in lowered for term in [*terms, *keywords])


def _clean_answer_text(answer: str) -> str:
    cleaned = answer
    cleaned = re.sub(r"\bSource file:.*?(?=(?:[A-Z][a-z]+:)|$)", "", cleaned)
    cleaned = re.sub(r"\bSource type:\s*\w+", "", cleaned)
    cleaned = re.sub(r"\bPage:\s*\d+", "", cleaned)
    cleaned = re.sub(r"\bSheet\d+:\d+\b", "", cleaned)
    cleaned = re.sub(r"\bActual Message(?: on Extranet)?:", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bCategory:\s*[^.]+", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _contains_noise(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in NOISY_ANSWER_TERMS)


def _source_labels(chunks: list[RetrievedChunk]) -> list[str]:
    return list(dict.fromkeys(source_label(chunk) for chunk in chunks))


def source_label(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata
    source_file = metadata.get("source_file", "unknown source")
    source_type = metadata.get("source_type", "")
    if source_type == "pdf":
        return f"{source_file} page={metadata.get('page_number', '')}"
    return str(source_file)
