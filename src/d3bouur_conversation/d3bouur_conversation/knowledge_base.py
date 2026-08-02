"""D3BOUUR's knowledge base: local retrieval-augmented generation (RAG) support.

Standalone by design — no knowledge of LLMs, personas, or conversation state.
Its only job is turning text into vectors (via Ollama's local embedding model,
keeping the whole retrieval path offline-capable — same reasoning as the LLM
fallback in llm_router.py) and answering "what's relevant to this query" from
whatever has been indexed.

Sized deliberately for a single organization's own content (tens to low
hundreds of entries): brute-force cosine similarity over an in-memory list,
persisted as plain JSON — not a real vector database. A vector DB (Chroma,
Qdrant, pgvector...) earns its complexity at thousands-to-millions of
documents; at this scale it would be infrastructure with nothing to justify
it. Swap this class for a Chroma-backed one later if the corpus ever
outgrows brute-force search.

An empty index (no files ever added, or build_index.py never run) is a
valid, fully-supported state: search() just returns no results — the safe
default before any real AcaROBOTICS content exists.
"""

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Failed to get an embedding from Ollama."""


@dataclass
class RetrievedChunk:
    text: str
    source: str
    similarity: float


def _default_index_path() -> Path:
    # knowledge_base.py lives at <package_root>/d3bouur_conversation/knowledge_base.py,
    # so parent.parent is <package_root> — same directory as setup.py and .env.
    return Path(__file__).resolve().parent.parent / "knowledge_index.json"


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class KnowledgeBase:
    def __init__(
        self,
        index_path: Optional[Path] = None,
        embedding_model: str = "nomic-embed-text",
        ollama_url: str = "http://localhost:11434/api/embeddings",
        timeout: float = 30.0,
    ):
        self.index_path = index_path or _default_index_path()
        self.embedding_model = embedding_model
        self.ollama_url = ollama_url
        self.timeout = timeout
        self._entries: List[dict] = self._load()

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries = []

    def add_document(self, source: str, text: str) -> None:
        """Embed and add one document. Called by build_index.py while
        (re)building the index — not part of the per-query search path."""
        embedding = self._embed(text)
        self._entries.append({"source": source, "text": text, "embedding": embedding})

    def save(self) -> None:
        self.index_path.write_text(
            json.dumps({"entries": self._entries}, ensure_ascii=False, indent=2)
        )

    def search(self, query: str, top_k: int = 3, min_similarity: float = 0.5) -> List[RetrievedChunk]:
        """Return up to top_k chunks relevant to query, above min_similarity.
        Returns [] if the index is empty, embedding the query fails, or
        nothing clears the similarity threshold — all three are the same
        "nothing to offer" signal from the caller's point of view."""
        if self.is_empty():
            return []

        try:
            query_embedding = self._embed(query)
        except EmbeddingError as exc:
            # Retrieval failing should degrade to "nothing found", not crash
            # the conversation turn — the caller already knows how to handle
            # "nothing found" safely (see llm_router._format_rag_context).
            logger.warning("embedding query failed (%s) — treating as no results", exc)
            return []

        scored = [
            RetrievedChunk(
                text=e["text"],
                source=e["source"],
                similarity=_cosine_similarity(query_embedding, e["embedding"]),
            )
            for e in self._entries
        ]
        scored.sort(key=lambda c: c.similarity, reverse=True)
        return [c for c in scored[:top_k] if c.similarity >= min_similarity]

    def _load(self) -> List[dict]:
        if not self.index_path.exists():
            logger.info("no knowledge index found at %s — starting empty", self.index_path)
            return []
        data = json.loads(self.index_path.read_text())
        return data.get("entries", [])

    def _embed(self, text: str) -> List[float]:
        try:
            resp = requests.post(
                self.ollama_url,
                json={"model": self.embedding_model, "prompt": text},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise EmbeddingError(f"connection error calling Ollama embeddings: {exc}") from exc

        if resp.status_code != 200:
            raise EmbeddingError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        embedding = data.get("embedding")
        if not embedding:
            raise EmbeddingError(f"no embedding in response: {data}")
        return embedding
