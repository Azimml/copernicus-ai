from __future__ import annotations

import re
from threading import RLock

import numpy as np
from openai import OpenAI

from app.core.config import settings
from app.services.indexer import ChunkRecord, load_index


class Retriever:
    """Hybrid semantic + BM25 retriever over crawled site chunks."""

    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._matrix: np.ndarray | None = None
        self._chunks: list[ChunkRecord] | None = None
        self._doc_tokens: list[list[str]] | None = None
        self._doc_lens: np.ndarray | None = None
        self._avg_doc_len: float = 1.0
        self._idf: dict[str, float] = {}
        # Embedding LRU cache (per-worker, in-memory).
        # 2048 entries × ~12KB each ≈ 24MB — fits comfortably even on small VPS.
        self._embedding_cache: dict[str, list[float]] = {}
        self._cache_max: int = 2048
        self._embedding_hits: int = 0
        self._embedding_misses: int = 0
        self._lock = RLock()

    def reload(self) -> None:
        with self._lock:
            try:
                self._matrix, self._chunks = load_index()
            except RuntimeError:
                self._matrix, self._chunks = None, None
            self._build_lexical_index()
            self._embedding_cache = {}

    def _get_embedding(self, text: str) -> list[float]:
        if not self._client:
            self._client = OpenAI(api_key=settings.openai_api_key)
        cache_key = text.strip().lower()
        # Pop+reinsert turns the dict into an LRU — most recently used keys
        # stay; oldest get evicted when we exceed _cache_max.
        if cache_key in self._embedding_cache:
            value = self._embedding_cache.pop(cache_key)
            self._embedding_cache[cache_key] = value
            self._embedding_hits += 1
            return value
        emb = self._client.embeddings.create(
            model=settings.openai_embedding_model, input=[text],
        ).data[0].embedding
        if len(self._embedding_cache) >= self._cache_max:
            oldest_key = next(iter(self._embedding_cache))
            del self._embedding_cache[oldest_key]
        self._embedding_cache[cache_key] = emb
        self._embedding_misses += 1
        return emb

    def cache_stats(self) -> dict:
        with self._lock:
            return {
                "embedding_cache_size": len(self._embedding_cache),
                "embedding_cache_max": self._cache_max,
                "embedding_hits": self._embedding_hits,
                "embedding_misses": self._embedding_misses,
            }

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._matrix is None or self._chunks is None or self._doc_tokens is None:
                self.reload()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[0-9a-z]+", text.lower())

    def _build_lexical_index(self) -> None:
        if not self._chunks:
            self._doc_tokens = []
            self._doc_lens = np.zeros(0, dtype=np.float32)
            self._avg_doc_len = 1.0
            self._idf = {}
            return
        self._doc_tokens = []
        df: dict[str, int] = {}
        lens: list[int] = []
        stop = {"the", "and", "for", "with", "from", "about", "info", "are", "you", "your", "our"}
        for c in self._chunks:
            text_for_tokens = f"{c.title}\n{c.text}"
            toks = [t for t in self._tokenize(text_for_tokens) if len(t) > 1 and t not in stop]
            self._doc_tokens.append(toks)
            lens.append(len(toks))
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

        n_docs = max(1, len(self._chunks))
        self._doc_lens = np.asarray(lens, dtype=np.float32)
        self._avg_doc_len = float(np.mean(self._doc_lens)) if len(lens) else 1.0
        self._idf = {t: float(np.log(1.0 + ((n_docs - f + 0.5) / (f + 0.5)))) for t, f in df.items()}

    def _bm25_scores(self, query_tokens: list[str]) -> np.ndarray:
        assert self._doc_tokens is not None
        assert self._doc_lens is not None
        if not query_tokens:
            return np.zeros(len(self._doc_tokens), dtype=np.float32)

        k1 = 1.5
        b = 0.75
        scores = np.zeros(len(self._doc_tokens), dtype=np.float32)
        for i, toks in enumerate(self._doc_tokens):
            if not toks:
                continue
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            doc_len = float(self._doc_lens[i])
            norm = 1.0 - b + b * (doc_len / max(self._avg_doc_len, 1e-6))
            s = 0.0
            for q in query_tokens:
                f = tf.get(q, 0)
                if f == 0:
                    continue
                idf = self._idf.get(q, 0.0)
                s += idf * ((f * (k1 + 1.0)) / (f + k1 * norm))
            scores[i] = s
        return scores

    def query(self, text: str, language: str = "en", k: int | None = None) -> list[tuple[ChunkRecord, float]]:
        with self._lock:
            self._ensure_loaded()
            if self._matrix is None or self._chunks is None or len(self._chunks) == 0:
                return []
            top_k = k or settings.retrieval_top_k

            emb = self._get_embedding(text)
            v = np.asarray(emb, dtype=np.float32)
            norm = np.linalg.norm(v) or 1.0
            v /= norm
            sims = self._matrix @ v
            sem_norm = np.clip((sims + 1.0) / 2.0, 0.0, 1.0)

            stop = {"the", "and", "for", "with", "from", "about", "info", "are", "you", "your", "our",
                    "what", "how", "when", "where", "who", "why", "is", "this", "that", "do", "does"}
            query_tokens = [t for t in self._tokenize(text) if len(t) > 1 and t not in stop]
            bm25 = self._bm25_scores(query_tokens)
            if np.max(bm25) > 0:
                bm25_norm = bm25 / float(np.max(bm25))
            else:
                bm25_norm = bm25

            combined = (0.6 * sem_norm) + (0.4 * bm25_norm)

            # slug_targets must be defined regardless of whether query_tokens
            # is empty — it's referenced by the _url_matches_slug closure below.
            # (Previously this was scoped inside `if query_tokens:` and crashed
            # with NameError on stopword-only messages like "how are you".)
            slug_aliases = {
                "ies": ["/ies"],
                "pir": ["/pir"],
                "lf": ["/lf"],
                "summer": ["/summer"],
                "ongoing": ["/ongoing"],
                "ukrainian": ["/ukrainian-talent"],
                "ukraine": ["/ukrainian-talent"],
                "leaders": ["/lf"],
                "erasmus": ["/erasmus", "/erasmus-projects"],
                "ka2": ["/ka2"],
                "volunteer": ["/volunteering"],
                "volunteering": ["/volunteering"],
                "hackathon": ["/hackathons", "/hack", "/ai-finance-hackathon"],
                "donation": ["/donation"],
                "donate": ["/donation"],
                "team": ["/our-team"],
                "history": ["/our-history"],
                "contact": ["/contact", "/imprint"],
                "career": ["/career", "/job-vacancy"],
                "job": ["/job-vacancy", "/career"],
                "vacancy": ["/job-vacancy"],
                "comics": ["/cobi-studio/comics"],
                "stickers": ["/cobi-studio/stickers"],
                "postcards": ["/cobi-studio/postcards"],
                "cobi": ["/cobi-studio"],
            }
            slug_targets: list[str] = []

            if query_tokens:
                q_set = set(query_tokens)
                for tok in q_set:
                    for slug in slug_aliases.get(tok, []):
                        if slug not in slug_targets:
                            slug_targets.append(slug)

                for i, chunk in enumerate(self._chunks):
                    chunk_text = f"{chunk.title}\n{chunk.text}".lower()
                    c_tokens = set(self._tokenize(chunk_text))
                    overlap = len(q_set & c_tokens) / max(len(q_set), 1)
                    exact = 0.05 if len(text.strip()) >= 6 and text.lower() in chunk_text else 0.0
                    slug_boost = 0.0
                    if slug_targets:
                        url = chunk.url.lower()
                        if any(url.endswith(s) or s + "/" in url + "/" for s in slug_targets):
                            slug_boost = 0.30
                    combined[i] = combined[i] + 0.12 * overlap + exact + slug_boost

            def _url_matches_slug(url: str) -> bool:
                u = url.lower()
                return any(u.endswith(s) or s + "/" in u + "/" for s in slug_targets) if slug_targets else False

            sorted_idx = list(np.argsort(-combined))
            selected: list[tuple[ChunkRecord, float]] = []
            selected_by_url: dict[str, int] = {}
            for idx in sorted_idx:
                c = self._chunks[int(idx)]
                # Allow up to 5 chunks from URLs the user explicitly asked about
                # (e.g. /en/ies for IES questions) so the breakdown / details
                # chunks aren't pushed out by 2-per-URL cap. Other URLs cap at 2.
                cap = 5 if _url_matches_slug(c.url) else 2
                if selected_by_url.get(c.url, 0) >= cap:
                    continue
                score = float(max(0.0, min(1.0, combined[int(idx)])))
                selected.append((c, (score * 2.0) - 1.0))
                selected_by_url[c.url] = selected_by_url.get(c.url, 0) + 1
                if len(selected) >= top_k:
                    break
            return selected
