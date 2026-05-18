"""Pre-warm the chat answer cache on server startup.

Calls ``ChatService.ask()`` for a curated list of common questions so that
the first user to ask them gets a cache hit (~10 ms) instead of waiting
for OpenAI (~2-5 s). Runs in a background daemon thread so server boot
isn't delayed.

The list is intentionally small (~10 questions) so warmup finishes in
roughly 30-60 seconds total — enough to cover the demo without burning
the OpenAI rate limit.
"""
from __future__ import annotations

import logging
import threading
import time

from app.services.quick_actions import list_quick_actions

logger = logging.getLogger(__name__)

# Curated demo questions. Mix of:
#   - The default quick-action chips users see in the welcome screen
#   - The questions our profiling shows take the longest (and so benefit
#     most from caching)
#   - The most likely "what does this org do?" framings
_DEMO_QUESTIONS = [
    "Tell me about the IES program",
    "What does Copernicus Berlin do?",
    "How can I apply for a scholarship?",
    "What Erasmus+ projects are available?",
    "How can I volunteer?",
    "How much does the IES scholarship cost?",
    "What is the difference between Full, Partial Plus, and Partial scholarship?",
    "How can I contact Copernicus Berlin?",
    "What is the application deadline?",
    "Who is on the Copernicus Berlin team?",
]


def _collect_warmup_questions() -> list[str]:
    """Combine curated demo questions with enabled quick-action chips."""
    questions: list[str] = list(_DEMO_QUESTIONS)
    seen_norm = {q.strip().lower() for q in questions}
    try:
        for item in list_quick_actions():
            if not item.get("enabled", True):
                continue
            q = str(item.get("question") or "").strip()
            if not q:
                continue
            if q.lower() not in seen_norm:
                questions.append(q)
                seen_norm.add(q.lower())
    except Exception:
        logger.exception("Failed to load quick actions for warmup")
    return questions


def warm_cache(chat_service, max_questions: int = 12) -> None:
    """Block-call ``ask()`` for each demo question to populate the cache.

    Called from a background thread by :func:`start_warmup`. Each ask costs
    ~2-5s + ~$0.0003, so 12 questions is ~30-60s and ~$0.004.
    """
    questions = _collect_warmup_questions()[:max_questions]
    if not questions:
        return
    logger.info("Pre-warming chat answer cache (%d questions)…", len(questions))
    started = time.time()
    hits = 0
    for q in questions:
        try:
            chat_service.ask(q, session_id=None)
            hits += 1
        except Exception as exc:
            logger.warning("Warmup failed for %r: %s", q, exc)
    elapsed = time.time() - started
    logger.info(
        "Warmup complete: %d/%d questions in %.1fs (avg %.1fs each)",
        hits, len(questions), elapsed, elapsed / max(1, hits),
    )


def start_warmup(chat_service) -> threading.Thread:
    """Kick off warmup in a background daemon thread."""
    t = threading.Thread(
        target=warm_cache,
        args=(chat_service,),
        name="cache-warmup",
        daemon=True,
    )
    t.start()
    return t
