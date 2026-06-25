from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import PolicyQuestion
from app.config import Settings, load_settings
from app.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)

RAW_RETRIEVAL_TOP_K = 8

CATEGORY_QUERY_TERMS: dict[str, list[str]] = {
    "early check-in": ["early check-in", "early arrival", "arrival time", "before check-in", "check in early"],
    "late check-out": ["late check-out", "late checkout", "departure time", "after check-out"],
    "luggage storage": ["luggage storage", "luggage drop", "bags", "leave luggage", "before check-in"],
    "parking": ["parking", "car park", "parking space", "vehicle", "additional charges"],
    "taxi / airport transfer": ["taxi", "airport transfer", "transfer", "pickup", "third-party charges"],
    "extra bed": ["extra bed", "rollaway bed", "child bed", "occupancy", "additional charges"],
    "baby cot": ["baby cot", "cot", "crib", "infant", "availability"],
    "accessibility": ["accessibility", "accessible room", "wheelchair", "special assistance"],
    "invoice": ["invoice", "receipt", "billing", "booking reference"],
    "refund/cancellation": ["refund", "cancellation", "free cancellation", "booking terms", "payment issue"],
    "smoking": ["smoking", "smoking room", "non-smoking", "property rules"],
    "pet policy": ["pet", "dog", "cat", "property policy", "additional charges"],
    "bed type": ["bed type", "twin", "double", "king", "preference"],
    "room preference": ["room preference", "high floor", "low floor", "quiet room", "view"],
}

GENERIC_POLICY_TERMS = {
    "hotel",
    "policy",
    "available",
    "availability",
    "request",
    "requested",
    "reservation",
    "booking",
    "please",
    "can",
    "could",
    "would",
}

GENERIC_CONTEXT_PENALTIES = [
    "coverage audit",
    "category frequency snapshot",
    "full excel source row traceability appendix",
    "source row traceability",
    "canonical category action matrix",
]


class RetrievedChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float | None = None


def retrieve_policy_context(
    question: PolicyQuestion | str,
    settings: Settings | None = None,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    settings = settings or load_settings()
    policy_question = (
        question
        if isinstance(question, PolicyQuestion)
        else PolicyQuestion(question=question, category=None, needs_rag_answer=True)
    )
    try:
        store = get_vector_store(settings)
        if store.count() == 0:
            return []
        result = store.query(expand_policy_query(policy_question), top_k=max(top_k, RAW_RETRIEVAL_TOP_K))
    except Exception as exc:
        logger.warning("Policy retrieval failed: %s", exc)
        return []
    return rerank_policy_chunks(policy_question, _chunks_from_query_result(result, 0), limit=top_k)


def retrieve_policy_contexts(
    questions: list[PolicyQuestion],
    settings: Settings | None = None,
    top_k: int = 5,
) -> dict[str, list[RetrievedChunk]]:
    settings = settings or load_settings()
    active_questions = [question for question in questions if question.needs_rag_answer]
    if not active_questions:
        return {}
    try:
        store = get_vector_store(settings)
        if store.count() == 0:
            return {question.question: [] for question in active_questions}
        result = store.query_many(
            [expand_policy_query(question) for question in active_questions],
            top_k=max(top_k, RAW_RETRIEVAL_TOP_K),
        )
    except Exception as exc:
        logger.warning("Policy retrieval failed: %s", exc)
        return {question.question: [] for question in active_questions}
    return {
        question.question: rerank_policy_chunks(
            question, _chunks_from_query_result(result, index), limit=top_k
        )
        for index, question in enumerate(active_questions)
    }


def expand_policy_query(question: PolicyQuestion) -> str:
    category = (question.category or "").lower()
    terms = [question.question, category]
    terms.extend(CATEGORY_QUERY_TERMS.get(category, []))
    terms.extend(_content_terms(f"{question.question} {category}")[:8])
    return " ".join(_dedupe_terms(term for term in terms if term))


def rerank_policy_chunks(
    question: PolicyQuestion,
    chunks: list[RetrievedChunk],
    limit: int = 5,
) -> list[RetrievedChunk]:
    if not chunks:
        return []
    scored = [
        (_chunk_relevance_score(question, chunk), _distance_sort_value(chunk), index, chunk)
        for index, chunk in enumerate(chunks)
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))

    selected: list[RetrievedChunk] = []
    seen_sources: set[str] = set()
    for _, _, _, chunk in scored:
        source = _source_key(chunk)
        if source in seen_sources:
            continue
        selected.append(chunk)
        seen_sources.add(source)
        if len(selected) >= limit:
            return selected
    for _, _, _, chunk in scored:
        if chunk in selected:
            continue
        selected.append(chunk)
        if len(selected) >= limit:
            break
    return selected


def _chunks_from_query_result(result: dict[str, Any], result_index: int) -> list[RetrievedChunk]:
    documents_by_query = result.get("documents") or []
    metadatas_by_query = result.get("metadatas") or []
    distances_by_query = result.get("distances") or []
    documents = documents_by_query[result_index] if result_index < len(documents_by_query) else []
    metadatas = metadatas_by_query[result_index] if result_index < len(metadatas_by_query) else []
    distances = distances_by_query[result_index] if result_index < len(distances_by_query) else []
    chunks: list[RetrievedChunk] = []
    for index, document in enumerate(documents or []):
        chunks.append(
            RetrievedChunk(
                text=document,
                metadata=metadatas[index] if index < len(metadatas) else {},
                distance=distances[index] if index < len(distances) else None,
            )
        )
    return chunks


def _chunk_relevance_score(question: PolicyQuestion, chunk: RetrievedChunk) -> float:
    text = chunk.text.lower()
    category = (question.category or "").lower()
    category_terms = CATEGORY_QUERY_TERMS.get(category, [])
    content_terms = _content_terms(f"{question.question} {category}")
    score = 0.0
    for term in category_terms:
        if term in text:
            score += 3.0
    for term in content_terms:
        if term in text:
            score += 1.0
    if any(term in text for term in GENERIC_CONTEXT_PENALTIES):
        score -= 1.0
    if "actual message on extranet" in text:
        score -= 0.25
    if chunk.distance is not None:
        score += max(0.0, 1.0 - min(float(chunk.distance), 1.0))
    return score


def _content_terms(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z-]{2,}", text.lower())
    return [
        word
        for word in _dedupe_terms(words)
        if word not in GENERIC_POLICY_TERMS and not word.endswith("ing")
    ]


def _dedupe_terms(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = re.sub(r"\s+", " ", term.strip().lower())
        if normalized and normalized not in seen:
            deduped.append(term.strip())
            seen.add(normalized)
    return deduped


def _distance_sort_value(chunk: RetrievedChunk) -> float:
    return float(chunk.distance) if chunk.distance is not None else 999.0


def _source_key(chunk: RetrievedChunk) -> str:
    metadata = chunk.metadata
    return f"{metadata.get('source_file', '')}|{metadata.get('page_number', '')}"
