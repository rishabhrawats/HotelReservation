from __future__ import annotations

from dataclasses import dataclass, replace

from app.ai.schemas import PolicyAnswer, PolicyQuestion
from app.config import Settings, load_settings
from app.rag.answer_policy import NOISY_ANSWER_TERMS, answer_policy_question
from app.rag.retriever import RetrievedChunk, retrieve_policy_contexts


@dataclass(frozen=True)
class RagEvalCase:
    case_id: str
    question: str
    category: str
    required_terms: tuple[tuple[str, ...], ...]
    expect_insufficient: bool = False


@dataclass(frozen=True)
class RagEvalResult:
    case: RagEvalCase
    answer: PolicyAnswer
    chunks: list[RetrievedChunk]
    passed: bool
    failures: list[str]


RAG_EVAL_CASES: tuple[RagEvalCase, ...] = (
    RagEvalCase(
        case_id="early_checkin",
        question="Can I check in early before the normal check-in time?",
        category="early check-in",
        required_terms=(("subject to availability", "availability"), ("cannot be guaranteed", "not guaranteed")),
    ),
    RagEvalCase(
        case_id="late_checkout",
        question="Is late check-out available?",
        category="late check-out",
        required_terms=(("availability",), ("hotel review", "review"), ("cannot be guaranteed", "not guaranteed")),
    ),
    RagEvalCase(
        case_id="luggage_storage",
        question="Can I leave my luggage before check-in?",
        category="luggage storage",
        required_terms=(("hotel discretion", "discretion"),),
    ),
    RagEvalCase(
        case_id="parking",
        question="Is parking available at the hotel?",
        category="parking",
        required_terms=(("availability",), ("additional charges", "charges")),
    ),
    RagEvalCase(
        case_id="airport_transfer",
        question="Can you arrange a taxi or airport transfer?",
        category="taxi / airport transfer",
        required_terms=(("availability",), ("third-party", "additional charges", "charges")),
    ),
    RagEvalCase(
        case_id="extra_bed_cot",
        question="Can we request an extra bed or baby cot?",
        category="extra bed",
        required_terms=(("eligibility", "occupancy"), ("availability",), ("additional charges", "charges")),
    ),
    RagEvalCase(
        case_id="accessibility",
        question="Do you have an accessible room or wheelchair support?",
        category="accessibility",
        required_terms=(("property",), ("confirm", "review"), ("cannot be guaranteed", "not guaranteed")),
    ),
    RagEvalCase(
        case_id="invoice",
        question="Can I request an invoice or receipt?",
        category="invoice",
        required_terms=(("invoice", "receipt"), ("booking reference", "guest name", "billing details")),
    ),
    RagEvalCase(
        case_id="refund_cancellation",
        question="Can I get a refund or free cancellation?",
        category="refund/cancellation",
        required_terms=(("booking terms", "ota conditions"), ("review",), ("promised", "promise")),
    ),
    RagEvalCase(
        case_id="unsupported_pool_gym",
        question="Does the hotel have a swimming pool or gym?",
        category="general policy",
        required_terms=(),
        expect_insufficient=True,
    ),
)


def evaluate_policy(settings: Settings | None = None) -> list[RagEvalResult]:
    settings = replace(settings or load_settings(), use_openai_policy_answer=False)
    questions = [
        PolicyQuestion(question=case.question, category=case.category, needs_rag_answer=True)
        for case in RAG_EVAL_CASES
    ]
    contexts = retrieve_policy_contexts(questions, settings=settings, top_k=5)
    results: list[RagEvalResult] = []
    for case, question in zip(RAG_EVAL_CASES, questions, strict=True):
        chunks = contexts.get(question.question, [])
        answer = answer_policy_question(question, chunks, settings=settings)
        failures = _case_failures(case, answer, chunks)
        results.append(
            RagEvalResult(
                case=case,
                answer=answer,
                chunks=chunks,
                passed=not failures,
                failures=failures,
            )
        )
    return results


def _case_failures(
    case: RagEvalCase, answer: PolicyAnswer, chunks: list[RetrievedChunk]
) -> list[str]:
    failures: list[str] = []
    lowered = answer.answer.lower()
    if case.expect_insufficient:
        if not answer.insufficient_policy_context:
            failures.append("expected insufficient context")
    else:
        if not chunks:
            failures.append("no retrieved chunks")
        if answer.insufficient_policy_context:
            failures.append("unexpected insufficient context")
        for group in case.required_terms:
            if not any(term.lower() in lowered for term in group):
                failures.append(f"missing one of: {', '.join(group)}")
    for term in NOISY_ANSWER_TERMS:
        if term in lowered:
            failures.append(f"contains noisy term: {term}")
    return failures


def print_eval_results(results: list[RagEvalResult]) -> None:
    header = f"{'case':<22} {'category':<24} {'ok':<4} {'pages':<28} failures"
    print(header)
    print("-" * len(header))
    for result in results:
        pages = ", ".join(_page_labels(result.answer.sources)) or "-"
        failures = "; ".join(result.failures) or "-"
        print(
            f"{result.case.case_id:<22} {result.case.category:<24} "
            f"{'PASS' if result.passed else 'FAIL':<4} {pages:<28} {failures}"
        )
        print(f"  answer: {result.answer.answer}")
    passed = sum(1 for result in results if result.passed)
    total = len(results)
    rate = passed / total if total else 0.0
    print(f"\nPassed {passed}/{total} ({rate:.0%})")


def _page_labels(sources: list[str]) -> list[str]:
    labels: list[str] = []
    for source in sources:
        if "page=" in source:
            labels.append(source.split("page=", maxsplit=1)[1])
        else:
            labels.append(source)
    return labels


def main() -> int:
    results = evaluate_policy()
    print_eval_results(results)
    passed = sum(1 for result in results if result.passed)
    return 0 if results and passed / len(results) >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
