from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.ai.schemas import PolicyQuestion
from app.rag.answer_policy import answer_policy_question
from app.rag.evaluate_policy import RAG_EVAL_CASES
from app.rag.ingest_policy import EXPECTED_POLICY_PDF, ingest_policy, read_pdf_policy_files
from app.rag.retriever import (
    RetrievedChunk,
    expand_policy_query,
    rerank_policy_chunks,
    retrieve_policy_context,
    retrieve_policy_contexts,
)


def test_pure_policy_question_answers_from_retrieved_context(test_settings):
    question = PolicyQuestion(
        question="Can I check in early and leave my luggage before check-in?",
        category="early check-in",
        needs_rag_answer=True,
    )
    chunks = [
        RetrievedChunk(
            text=(
                "Early check-in is subject to availability and may incur additional charges. "
                "Guests may leave luggage with the hotel before check-in at hotel discretion."
            ),
            metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 4},
        )
    ]

    answer = answer_policy_question(question, chunks, test_settings)

    assert answer.insufficient_policy_context is False
    assert "subject to availability" in answer.answer.lower()
    assert "luggage" in answer.answer.lower()


def test_context_only_early_checkin_answer_is_customer_ready(test_settings):
    question = PolicyQuestion(
        question="Can I check in early?",
        category="early check-in",
        needs_rag_answer=True,
    )
    chunks = [
        RetrievedChunk(
            text=(
                "Actual Message on Extranet: Hello, Do you think it's possible to have an early check-in around 10:30am? "
                "Category: Arrival Time. Actual Message: Thank you for allowing the early check in."
            ),
            metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 11},
        )
    ]

    answer = answer_policy_question(question, chunks, test_settings)

    assert answer.insufficient_policy_context is False
    assert "subject to availability" in answer.answer.lower()
    assert "cannot be guaranteed" in answer.answer.lower()
    assert "actual message" not in answer.answer.lower()


def test_policy_ingestion_ignores_excel_and_adds_only_pdf_chunks(tmp_path: Path, test_settings, monkeypatch):
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    (policy_dir / "Dry run.xlsx").write_text("Excel should be ignored", encoding="utf-8")
    _write_text_pdf(
        policy_dir / EXPECTED_POLICY_PDF,
        "Early check-in is subject to availability. Luggage storage is available at hotel discretion.",
    )
    captured = {}

    class FakeStore:
        def reset_collection(self):
            captured["reset"] = True

        def add_documents(self, ids, documents, metadatas):
            captured["ids"] = ids
            captured["documents"] = documents
            captured["metadatas"] = metadatas

    monkeypatch.setattr("app.rag.ingest_policy.get_vector_store", lambda settings: FakeStore())
    settings = test_settings.__class__(**{**test_settings.__dict__, "policy_dir": policy_dir})

    result = ingest_policy(settings)

    assert result["blocks"] == 1
    assert captured["reset"] is True
    assert all(metadata["source_type"] == "pdf" for metadata in captured["metadatas"])
    assert all(metadata["source_file"] == EXPECTED_POLICY_PDF for metadata in captured["metadatas"])
    assert "Dry run.xlsx" not in "\n".join(captured["documents"])


def test_policy_ingestion_reads_pdf_pages(tmp_path: Path):
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    pdf_path = policy_dir / "policy.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as file:
        writer.write(file)

    blocks = read_pdf_policy_files(policy_dir)

    assert len(blocks) == 1
    assert blocks[0].metadata["source_type"] == "pdf"
    assert blocks[0].metadata["page_number"] == 1


def test_retriever_returns_pdf_chunks_from_vector_store(monkeypatch, test_settings):
    class FakeStore:
        def count(self):
            return 1

        def query(self, query_text, top_k):
            return {
                "documents": [["Early check-in is subject to availability."]],
                "metadatas": [[{"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 3}]],
                "distances": [[0.12]],
            }

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda settings: FakeStore())

    chunks = retrieve_policy_context("early check-in", settings=test_settings)

    assert chunks
    assert chunks[0].metadata["source_type"] == "pdf"
    assert chunks[0].metadata["source_file"] == EXPECTED_POLICY_PDF


def test_batch_retriever_uses_one_store_query_for_multiple_questions(monkeypatch, test_settings):
    calls = {"query_many": 0}
    captured = {}

    class FakeStore:
        def count(self):
            return 1

        def query_many(self, query_texts, top_k):
            calls["query_many"] += 1
            captured["query_texts"] = query_texts
            captured["top_k"] = top_k
            return {
                "documents": [["Early check-in is subject to availability."], ["Luggage storage may be available."]],
                "metadatas": [
                    [{"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 3}],
                    [{"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 4}],
                ],
                "distances": [[0.1], [0.2]],
            }

    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda settings: FakeStore())
    questions = [
        PolicyQuestion(question="Can I check in early?", category="early check-in", needs_rag_answer=True),
        PolicyQuestion(question="Can I leave luggage?", category="luggage storage", needs_rag_answer=True),
    ]

    contexts = retrieve_policy_contexts(questions, settings=test_settings)

    assert calls["query_many"] == 1
    assert len(contexts) == 2
    assert len(captured["query_texts"]) == 2
    assert "arrival time" in captured["query_texts"][0]
    assert "luggage drop" in captured["query_texts"][1]
    assert captured["top_k"] == 8


def test_query_expansion_includes_category_synonyms():
    query = expand_policy_query(
        PolicyQuestion(
            question="Can I arrange an airport pickup?",
            category="taxi / airport transfer",
            needs_rag_answer=True,
        )
    )

    assert "airport transfer" in query
    assert "third-party charges" in query


def test_rerank_prefers_relevant_chunk_over_generic_appendix():
    question = PolicyQuestion(question="Is parking available?", category="parking", needs_rag_answer=True)
    generic = RetrievedChunk(
        text="Appendix A. Category frequency snapshot. Parking category count summary.",
        metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 10},
        distance=0.01,
    )
    relevant = RetrievedChunk(
        text="Parking requests are subject to availability and may incur additional charges.",
        metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 22},
        distance=0.7,
    )

    chunks = rerank_policy_chunks(question, [generic, relevant], limit=1)

    assert chunks[0].metadata["page_number"] == 22


def test_irrelevant_context_returns_insufficient_policy_answer(test_settings):
    question = PolicyQuestion(
        question="Does the hotel have a swimming pool or gym?",
        category="general policy",
        needs_rag_answer=True,
    )
    chunks = [
        RetrievedChunk(
            text="Parking requests are subject to availability and may incur additional charges.",
            metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 22},
        )
    ]

    answer = answer_policy_question(question, chunks, test_settings)

    assert answer.insufficient_policy_context is True
    assert answer.sources == []


@pytest.mark.parametrize(
    ("question", "category", "context", "required"),
    [
        (
            "Can I check in early?",
            "early check-in",
            "Early check-in and early arrival requests relate to arrival time.",
            ["subject to availability", "cannot be guaranteed"],
        ),
        (
            "Is late check-out available?",
            "late check-out",
            "Late check-out and departure time requests are reviewed by the hotel.",
            ["hotel review", "cannot be guaranteed"],
        ),
        (
            "Can I leave my luggage before check-in?",
            "luggage storage",
            "Guests ask about luggage storage, luggage drop, and bags before check-in.",
            ["hotel discretion"],
        ),
        (
            "Is parking available?",
            "parking",
            "Parking and car park requests may involve parking space limits.",
            ["additional charges"],
        ),
        (
            "Can you arrange airport transfer?",
            "taxi / airport transfer",
            "Airport transfer, taxi, and transfer support may involve third-party charges.",
            ["third-party"],
        ),
        (
            "Can I request an extra bed or baby cot?",
            "extra bed",
            "Extra bed, rollaway bed, baby cot, cot, and occupancy rules apply.",
            ["occupancy", "additional charges"],
        ),
        (
            "Do you have accessible rooms?",
            "accessibility",
            "Accessibility, accessible room, wheelchair, and special assistance requests are reviewed.",
            ["cannot be guaranteed"],
        ),
        (
            "Can I request an invoice or receipt?",
            "invoice",
            "Invoice, receipt, billing, and booking reference details may be needed.",
            ["booking reference"],
        ),
        (
            "Can I get a refund or free cancellation?",
            "refund/cancellation",
            "Refund, cancellation, free cancellation, booking terms, and payment issue rows.",
            ["booking terms", "review"],
        ),
        (
            "Can I request a smoking room?",
            "smoking",
            "Smoking and non-smoking room rules are property-specific.",
            ["cannot be guaranteed"],
        ),
    ],
)
def test_category_answers_are_safe_and_customer_ready(
    question, category, context, required, test_settings
):
    answer = answer_policy_question(
        PolicyQuestion(question=question, category=category, needs_rag_answer=True),
        [
            RetrievedChunk(
                text=f"Actual Message on Extranet: customer text. {context}",
                metadata={"source_file": EXPECTED_POLICY_PDF, "source_type": "pdf", "page_number": 6},
            )
        ],
        test_settings,
    )

    assert answer.insufficient_policy_context is False
    for term in required:
        assert term in answer.answer.lower()
    assert "actual message" not in answer.answer.lower()
    assert "sheet1" not in answer.answer.lower()
    assert all("page=" in source for source in answer.sources)


def test_eval_cases_cover_required_categories():
    categories = {case.category for case in RAG_EVAL_CASES}

    assert {
        "early check-in",
        "late check-out",
        "luggage storage",
        "parking",
        "taxi / airport transfer",
        "extra bed",
        "accessibility",
        "invoice",
        "refund/cancellation",
        "general policy",
    } <= categories


def test_policy_ingestion_skips_unchanged_pdf_to_save_embedding_cost(tmp_path: Path, test_settings, monkeypatch):
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    _write_text_pdf(policy_dir / EXPECTED_POLICY_PDF, "Early check-in is subject to availability.")
    calls = {"add": 0}

    class FakeStore:
        def __init__(self):
            self._count = 1

        def count(self):
            return self._count

        def reset_collection(self):
            pass

        def add_documents(self, ids, documents, metadatas):
            calls["add"] += 1
            self._count = len(documents)

    store = FakeStore()
    monkeypatch.setattr("app.rag.ingest_policy.get_vector_store", lambda settings: store)
    settings = test_settings.__class__(**{**test_settings.__dict__, "policy_dir": policy_dir})

    first = ingest_policy(settings)
    second = ingest_policy(settings)

    assert first["skipped"] == 0
    assert second["skipped"] == 1
    assert calls["add"] == 1


def _write_text_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_text(text)}) Tj ET".encode("latin-1")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    output = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output += obj
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode("ascii")
    output += f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    path.write_bytes(output)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
