from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import INDEX_DIR, RAW_DIR, settings
from app.core.io import read_json, write_json
from app.services.crawler import PageDocument, crawl_site


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    language: str
    url: str
    title: str
    text: str


DOCS_PATH = RAW_DIR / "documents.json"
FAQ_PATH = RAW_DIR / "faq.json"
INDEX_META_PATH = INDEX_DIR / "chunks.json"
INDEX_EMB_PATH = INDEX_DIR / "embeddings.npy"


def split_text(text: str, chunk_chars: int = 1200, overlap_chars: int = 180) -> list[str]:
    if not text.strip():
        return []
    if len(text) <= chunk_chars:
        return [text.strip()]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


@retry(wait=wait_exponential(multiplier=1, min=1, max=15), stop=stop_after_attempt(5))
def _embed_batch(client: OpenAI, texts: list[str]) -> np.ndarray:
    res = client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    arr = np.array([r.embedding for r in res.data], dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def _load_faq_docs() -> list[dict]:
    payload = read_json(FAQ_PATH, default={"items": []})
    return payload.get("items", [])


def _faq_chunk(item: dict) -> ChunkRecord | None:
    faq_id = item.get("id") or ""
    combined = f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}".strip()
    if not faq_id or not combined:
        return None
    return ChunkRecord(
        chunk_id=f"faq_{faq_id}",
        doc_id=f"faq_{faq_id}",
        language="en",
        url="faq://manual",
        title="FAQ",
        text=combined,
    )


def _docs_to_chunks(docs: list[PageDocument], faq_items: list[dict]) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for i, d in enumerate(docs):
        doc_id = f"doc_{i}"
        for j, c in enumerate(split_text(d.text)):
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{doc_id}_c{j}",
                    doc_id=doc_id,
                    language=d.language,
                    url=d.url,
                    title=d.title,
                    text=c,
                )
            )

    for item in faq_items:
        chunk = _faq_chunk(item)
        if chunk:
            chunks.append(chunk)
    return chunks


def build_index(full_crawl: bool = True) -> tuple[int, int]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    docs_payload = read_json(DOCS_PATH, default={"documents": []})

    if full_crawl or not docs_payload.get("documents"):
        crawled = crawl_site()
        docs_payload = {
            "documents": [
                {"url": d.url, "language": d.language, "title": d.title, "text": d.text}
                for d in crawled
            ]
        }
        write_json(DOCS_PATH, docs_payload)

    docs = [PageDocument(**d) for d in docs_payload.get("documents", [])]
    faq_items = _load_faq_docs()
    chunks = _docs_to_chunks(docs, faq_items)

    if not chunks:
        raise RuntimeError("No chunks to index")

    client = OpenAI(api_key=settings.openai_api_key)

    vectors: list[np.ndarray] = []
    batch_size = 64
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        embeds = _embed_batch(client, [c.text for c in batch])
        vectors.append(embeds)

    matrix = np.vstack(vectors).astype(np.float32)
    np.save(INDEX_EMB_PATH, matrix)
    write_json(INDEX_META_PATH, {"chunks": [asdict(c) for c in chunks]})

    return len(docs), len(chunks)


def load_index() -> tuple[np.ndarray, list[ChunkRecord]]:
    if not INDEX_EMB_PATH.exists() or not INDEX_META_PATH.exists():
        raise RuntimeError("Index not built. Run scripts/build_index.py first.")

    matrix = np.load(INDEX_EMB_PATH)
    raw_chunks = read_json(INDEX_META_PATH, default={"chunks": []}).get("chunks", [])
    chunks = [ChunkRecord(**c) for c in raw_chunks]

    if matrix.shape[0] != len(chunks):
        raise RuntimeError("Index mismatch between vectors and metadata")

    return matrix, chunks


def _save_index(matrix: np.ndarray, chunks: list[ChunkRecord]) -> None:
    np.save(INDEX_EMB_PATH, matrix.astype(np.float32))
    write_json(INDEX_META_PATH, {"chunks": [asdict(c) for c in chunks]})


def upsert_faq_index(item: dict) -> None:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    chunk = _faq_chunk(item)
    if not chunk:
        return
    matrix, chunks = load_index()
    keep_chunks: list[ChunkRecord] = []
    keep_vectors: list[np.ndarray] = []
    for i, c in enumerate(chunks):
        if c.doc_id == chunk.doc_id:
            continue
        keep_chunks.append(c)
        keep_vectors.append(matrix[i])
    if keep_vectors:
        matrix = np.vstack(keep_vectors).astype(np.float32)
    else:
        matrix = np.zeros((0, matrix.shape[1]), dtype=np.float32)
    client = OpenAI(api_key=settings.openai_api_key)
    vec = _embed_batch(client, [chunk.text])
    if matrix.size == 0:
        matrix = vec.astype(np.float32)
    else:
        matrix = np.vstack([matrix, vec]).astype(np.float32)
    chunks = [*keep_chunks, chunk]
    _save_index(matrix, chunks)


def delete_faq_index(faq_id: str) -> bool:
    matrix, chunks = load_index()
    if not faq_id:
        return False
    target_doc_id = f"faq_{faq_id}"
    keep_chunks: list[ChunkRecord] = []
    keep_vectors: list[np.ndarray] = []
    removed = False
    for i, c in enumerate(chunks):
        if c.doc_id == target_doc_id:
            removed = True
            continue
        keep_chunks.append(c)
        keep_vectors.append(matrix[i])
    if not removed:
        return False
    if keep_vectors:
        matrix = np.vstack(keep_vectors).astype(np.float32)
    else:
        matrix = np.zeros((0, matrix.shape[1]), dtype=np.float32)
    _save_index(matrix, keep_chunks)
    return True
