"""Shared knowledge retrieval primitives used by both Agent runtime and Eval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

import numpy as np

from core.vector_engine import _fallback_embedding, embed_text


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source: str
    text: str
    metadata: Dict[str, str]


def chunk_markdown(text: str, source: str, chunk_size: int, overlap: int = 40) -> List[KnowledgeChunk]:
    """Preserve heading sections, then split only oversized sections with overlap."""
    if chunk_size <= overlap or chunk_size < 80:
        raise ValueError("chunk_size must be at least 80 and greater than overlap")
    sections = re.split(r"(?=^#{1,3}\s)", text.strip(), flags=re.MULTILINE)
    chunks: List[KnowledgeChunk] = []
    for section_index, raw_section in enumerate(section for section in sections if section.strip()):
        section = raw_section.strip()
        start = 0
        part = 0
        while start < len(section):
            end = min(len(section), start + chunk_size)
            # Prefer a natural boundary near the end of a window.
            if end < len(section):
                boundary = max(section.rfind("\n", start, end), section.rfind("。", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary + 1
            value = section[start:end].strip()
            if value:
                digest = hashlib.sha256(f"{source}:{section_index}:{part}:{value}".encode("utf-8")).hexdigest()[:12]
                chunks.append(KnowledgeChunk(f"rag-{digest}", source, value, {"source": source, "section": str(section_index)}))
            if end >= len(section):
                break
            start = max(start + 1, end - overlap)
            part += 1
    return chunks


def load_chunks(directory: Path, chunk_size: int, overlap: int = 40) -> List[KnowledgeChunk]:
    chunks: List[KnowledgeChunk] = []
    for path in sorted(list(directory.glob("*.md")) + list(directory.glob("*.txt"))):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            chunks.extend(chunk_markdown(text, path.name, chunk_size, overlap))
    return chunks


def _terms(text: str) -> set[str]:
    ascii_terms = re.findall(r"[a-z0-9_/-]+", text.lower())
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    chinese_bigrams = [chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))]
    return set(ascii_terms + chinese_bigrams)


def keyword_search(query: str, chunks: Iterable[KnowledgeChunk], top_k: int) -> List[Tuple[KnowledgeChunk, float]]:
    query_terms = _terms(query)
    scored = []
    for chunk in chunks:
        chunk_terms = _terms(chunk.text)
        overlap = len(query_terms & chunk_terms)
        if overlap:
            scored.append((chunk, overlap / max(1, len(query_terms))))
    return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))[:top_k]


def vector_search(
    query: str,
    chunks: Iterable[KnowledgeChunk],
    top_k: int,
    embedding_fn: Callable[[str], np.ndarray] = _fallback_embedding,
) -> List[Tuple[KnowledgeChunk, float]]:
    query_vector = embedding_fn(query)
    scored = []
    for chunk in chunks:
        score = float(np.dot(query_vector, embedding_fn(chunk.text)))
        if score > 0:
            scored.append((chunk, score))
    return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))[:top_k]


def hybrid_search(
    query: str,
    chunks: List[KnowledgeChunk],
    top_k: int,
    embedding_fn: Callable[[str], np.ndarray] = _fallback_embedding,
) -> List[Tuple[KnowledgeChunk, float]]:
    """Fuse keyword and vector rank using Reciprocal Rank Fusion (RRF)."""
    candidates: Dict[str, Tuple[KnowledgeChunk, float]] = {}
    for ranking in (
        keyword_search(query, chunks, len(chunks)),
        vector_search(query, chunks, len(chunks), embedding_fn),
    ):
        for rank, (chunk, _score) in enumerate(ranking, start=1):
            previous = candidates.get(chunk.chunk_id)
            rrf_score = (previous[1] if previous else 0.0) + 1 / (60 + rank)
            candidates[chunk.chunk_id] = (chunk, rrf_score)
    return sorted(candidates.values(), key=lambda item: (-item[1], item[0].chunk_id))[:top_k]


def retrieve(
    query: str,
    chunks: List[KnowledgeChunk],
    mode: str,
    top_k: int = 3,
    embedding_fn: Callable[[str], np.ndarray] = _fallback_embedding,
) -> List[Tuple[KnowledgeChunk, float]]:
    if mode == "keyword":
        return keyword_search(query, chunks, top_k)
    if mode == "vector":
        return vector_search(query, chunks, top_k, embedding_fn)
    if mode == "hybrid":
        return hybrid_search(query, chunks, top_k, embedding_fn)
    raise ValueError(f"unsupported retrieval mode: {mode}")


class KnowledgeRetriever:
    """One retrieval implementation shared by runtime and evaluation.

    The retriever owns the exact chunks and embedding function used for a run.
    This prevents Eval from silently benchmarking a different retrieval path.
    """

    def __init__(
        self,
        chunks: List[KnowledgeChunk],
        mode: str = "hybrid",
        embedding_fn: Callable[[str], np.ndarray] = embed_text,
    ) -> None:
        self.chunks = chunks
        self.mode = mode
        self._embedding_fn = embedding_fn
        self._embedding_cache: Dict[str, np.ndarray] = {}

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        chunk_size: int = 400,
        overlap: int = 40,
        mode: str = "hybrid",
        embedding_fn: Callable[[str], np.ndarray] = embed_text,
    ) -> "KnowledgeRetriever":
        return cls(load_chunks(directory, chunk_size, overlap), mode, embedding_fn)

    def _embed(self, text: str) -> np.ndarray:
        vector = self._embedding_cache.get(text)
        if vector is None:
            vector = self._embedding_fn(text)
            self._embedding_cache[text] = vector
        return vector

    def search(self, query: str, top_k: int = 5, mode: str | None = None) -> List[Tuple[KnowledgeChunk, float]]:
        if not query or top_k <= 0:
            return []
        return retrieve(query, self.chunks, mode or self.mode, top_k, self._embed)

    def search_records(self, query: str, top_k: int = 5, mode: str | None = None) -> List[Dict[str, object]]:
        return [
            {
                "id": chunk.chunk_id,
                "type": "knowledge",
                "source": chunk.source,
                "text": f"【来源: {chunk.source}】\n{chunk.text}",
                "score": round(score, 4),
            }
            for chunk, score in self.search(query, top_k, mode)
        ]
