from __future__ import annotations

import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

from app.config import Settings, load_settings
from app.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)

EXPECTED_POLICY_PDF = "Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf"


@dataclass(frozen=True)
class PolicyBlock:
    text: str
    metadata: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int | float | bool]


def read_pdf_policy_files(policy_dir: Path) -> list[PolicyBlock]:
    blocks: list[PolicyBlock] = []
    for path in policy_pdf_files(policy_dir):
        reader = PdfReader(str(path))
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                text = "[No extractable text found on this PDF page.]"
            blocks.append(
                PolicyBlock(
                    text=f"Source file: {path.name}\nSource type: pdf\nPage: {index}\n{text}",
                    metadata={
                        "source_file": path.name,
                        "source_type": "pdf",
                        "sheet_name": "",
                        "row_number": 0,
                        "page_number": index,
                        "category": "",
                    },
                )
            )
    return blocks


def policy_pdf_files(policy_dir: Path) -> list[Path]:
    expected = policy_dir / EXPECTED_POLICY_PDF
    pdfs = sorted(path for path in policy_dir.glob("*.pdf") if path.is_file())
    if expected.exists():
        if len(pdfs) > 1:
            ignored = ", ".join(path.name for path in pdfs if path.name != EXPECTED_POLICY_PDF)
            if ignored:
                logger.warning("Ignoring additional PDF policy files because %s is present: %s", EXPECTED_POLICY_PDF, ignored)
        return [expected]
    if pdfs:
        logger.warning(
            "Expected policy PDF %s was not found in %s; ingesting available PDF files only.",
            EXPECTED_POLICY_PDF,
            policy_dir,
        )
    return pdfs


def chunk_policy_blocks(blocks: Iterable[PolicyBlock]) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    for block in blocks:
        for chunk_index, text_chunk in enumerate(chunk_text(block.text), start=1):
            metadata = dict(block.metadata)
            metadata["chunk_index"] = chunk_index
            chunk_id = _stable_chunk_id(text_chunk, metadata)
            chunks.append(PolicyChunk(chunk_id=chunk_id, text=text_chunk, metadata=metadata))
    return chunks


def chunk_text(text: str, target_tokens: int = 700, overlap_tokens: int = 80) -> list[str]:
    text = text.strip()
    if not text:
        return []
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        if len(tokens) <= target_tokens:
            return [text]
        chunks: list[str] = []
        step = max(1, target_tokens - overlap_tokens)
        for start in range(0, len(tokens), step):
            window = tokens[start : start + target_tokens]
            chunk = encoding.decode(window).strip()
            if chunk:
                chunks.append(chunk)
        return chunks
    except Exception:
        max_chars = 3500
        overlap_chars = 400
        if len(text) <= max_chars:
            return [text]
        chunks = []
        step = max_chars - overlap_chars
        for start in range(0, len(text), step):
            chunk = text[start : start + max_chars].strip()
            if chunk:
                chunks.append(chunk)
        return chunks


def ingest_policy(settings: Settings | None = None, reset: bool = True) -> dict[str, int]:
    settings = settings or load_settings()
    if settings.strict_real_mode:
        settings.require_openai_credentials()
    settings.policy_dir.mkdir(parents=True, exist_ok=True)
    excel_files = [path for path in settings.policy_dir.glob("*.xlsx") if path.is_file()]
    if excel_files:
        logger.warning("Ignoring Excel policy files because RAG is PDF-only: %s", ", ".join(path.name for path in excel_files))
    pdf_files = policy_pdf_files(settings.policy_dir)
    if not pdf_files:
        logger.warning(
            "Policy PDF not found. Add %s to %s before ingesting policy context.",
            EXPECTED_POLICY_PDF,
            settings.policy_dir,
        )

    blocks = read_pdf_policy_files(settings.policy_dir)
    chunks = chunk_policy_blocks(blocks)
    store = get_vector_store(settings)
    if (
        not settings.force_policy_reingest
        and chunks
        and _manifest_matches(settings, chunks)
        and store.count() >= len(chunks)
    ):
        logger.info(
            "Policy PDF and embedding model unchanged; skipping re-ingestion to avoid embedding cost."
        )
        return {"blocks": len(blocks), "chunks": len(chunks), "skipped": 1}
    if reset:
        store.reset_collection()
    store.add_documents(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=[chunk.metadata for chunk in chunks],
    )
    if chunks:
        _write_manifest(settings, chunks)
    logger.info("Ingested %s policy blocks into %s chunks.", len(blocks), len(chunks))
    return {"blocks": len(blocks), "chunks": len(chunks), "skipped": 0}


def _stable_chunk_id(text: str, metadata: dict[str, str | int | float | bool]) -> str:
    basis = "|".join(f"{key}={metadata[key]}" for key in sorted(metadata)) + "|" + text
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _manifest_path(settings: Settings) -> Path:
    return settings.chroma_dir / "policy_manifest.json"


def _manifest(settings: Settings, chunks: list[PolicyChunk]) -> dict[str, object]:
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    return {
        "embedding_model": settings.openai_embedding_model if settings.openai_api_key else "chroma-default",
        "chunk_count": len(chunks),
        "chunk_ids_sha256": hashlib.sha256("\n".join(chunk_ids).encode("utf-8")).hexdigest(),
    }


def _manifest_matches(settings: Settings, chunks: list[PolicyChunk]) -> bool:
    path = _manifest_path(settings)
    if not path.exists():
        return False
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return saved == _manifest(settings, chunks)


def _write_manifest(settings: Settings, chunks: list[PolicyChunk]) -> None:
    path = _manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_manifest(settings, chunks), indent=2), encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        result = ingest_policy()
        print(result)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
