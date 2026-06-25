from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import Settings, load_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "hotel_policy_chunks"


@dataclass
class PolicyVectorStore:
    settings: Settings

    def __post_init__(self) -> None:
        self.settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        import chromadb

        self.client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        kwargs: dict[str, Any] = {"name": COLLECTION_NAME}
        try:
            return self.client.get_or_create_collection(**kwargs)
        except Exception as exc:
            message = str(exc).lower()
            if self.settings.strict_real_mode and "embedding function" in message:
                logger.warning(
                    "Existing Chroma collection has an incompatible embedding function; rebuilding it for strict real mode."
                )
                try:
                    self.client.delete_collection(COLLECTION_NAME)
                except Exception:
                    pass
                return self.client.get_or_create_collection(**kwargs)
            raise

    def reset_collection(self) -> None:
        try:
            self.client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self.collection = self._get_or_create_collection()

    def count(self) -> int:
        return int(self.collection.count())

    def add_documents(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, str | int | float | bool]],
    ) -> None:
        if not documents:
            return
        embeddings = self._embed_texts(documents)
        try:
            self._upsert(ids, documents, metadatas, embeddings)
        except Exception as exc:
            if self.settings.strict_real_mode:
                raise RuntimeError(f"Chroma upsert failed in real mode: {exc}") from exc
            logger.warning("Policy upsert failed; rebuilding policy collection: %s", exc)
            self.reset_collection()
            self._upsert(ids, documents, metadatas, embeddings)

    def _upsert(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, str | int | float | bool]],
        embeddings: list[list[float]] | None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        }
        if embeddings is not None:
            kwargs["embeddings"] = embeddings
        if hasattr(self.collection, "upsert"):
            self.collection.upsert(**kwargs)
            return
        self.collection.add(**kwargs)

    def query(self, query_text: str, top_k: int = 5) -> dict[str, Any]:
        return self.query_many([query_text], top_k=top_k)

    def query_many(self, query_texts: list[str], top_k: int = 5) -> dict[str, Any]:
        embeddings = self._embed_texts(query_texts)
        if embeddings is not None:
            return self.collection.query(query_embeddings=embeddings, n_results=top_k)
        return self.collection.query(query_texts=query_texts, n_results=top_k)

    def _embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.settings.openai_api_key:
            if self.settings.strict_real_mode:
                self.settings.require_openai_credentials()
            return None
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key, timeout=60)
            embeddings: list[list[float]] = []
            batch_size = 64
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                response = client.embeddings.create(
                    model=self.settings.openai_embedding_model,
                    input=batch,
                )
                embeddings.extend(item.embedding for item in response.data)
            return embeddings
        except Exception as exc:
            if self.settings.strict_real_mode:
                raise RuntimeError(f"OpenAI embeddings failed in real mode: {exc}") from exc
            logger.warning("OpenAI embeddings failed; using Chroma default embeddings: %s", exc)
            return None


def get_vector_store(settings: Settings | None = None) -> PolicyVectorStore:
    return PolicyVectorStore(settings or load_settings())
