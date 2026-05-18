from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterator

from openai import OpenAI

from app.core.config import settings
from app.services.link_rules import find_matching_link_rule
from app.services.memory import SessionMemory
from app.services.retrieval import Retriever


@dataclass
class ChatResult:
    answer: str
    language: str
    confidence: float
    needs_human: bool


SYSTEM_PROMPT = """
You are the official assistant for Copernicus Berlin e. V. (copernicusberlin.org).
You help visitors understand the organisation's mission, programs, and how to engage with them.

Topics you cover (based on the provided context):
- About Copernicus Berlin, its history, mission, and team
- Educational exchange, scholarships, and Erasmus+ projects
- Volunteering, internships, and career opportunities at Copernicus Berlin
- Events, hackathons, and initiatives (local and international)
- COBI Studio creative outputs (comics, stickers, postcards)
- News, publications, and media coverage
- Donations, partnerships, and contact information
- General information available on copernicusberlin.org/en

Rules:
1) Answer ONLY from the provided context. If the context does not contain enough information, say so honestly and suggest the user contact Copernicus Berlin directly or visit the relevant page.
2) NEVER change your answer just because the user disagrees. Only update your answer if you find new supporting evidence in context.
3) If a question is unrelated to Copernicus Berlin (e.g., unrelated companies, generic programming, cooking), politely decline: "I can only help with questions about Copernicus Berlin and its programs."
4) Keep answers concise, friendly, and accurate. Default 3–7 lines unless the user asks for detail.
5) Always reply in English.
6) Use recent conversation history to resolve follow-up questions like "and then?", "what about that?", "tell me more".
7) Format output for chat readability: short opening sentence, short bullet points when listing, **bold** for key terms or numbers.
8) Each context chunk has a "Source:" URL. Note which chunk(s) you used; the system will append "Learn more" links at the end. **Do NOT add any URLs, "Source:" lines, or "(Source: ...)" parenthetical references in your answer.** The user already sees the links automatically.
9) For contact-related questions (email, address, phone, social media), use exactly what appears in the context. Never invent contact channels.
10) Speak naturally as a helpful representative. Do NOT use meta wording such as "according to the context" or "the retrieved information says".
11) If the user asks to talk to a human, acknowledge and suggest using the support form on the widget.
12) **Program-specific numbers (cost, duration, eligibility, deadlines) MUST come from the Source URL that matches the program the user asked about.** If the user asks about IES, use only context chunks from a `/en/ies` URL. If they ask about PIR, use only `/en/pir`. Different scholarship programs have different costs and rules — never mix numbers across programs. If the relevant program's chunk is not in context, say you do not have that specific information rather than substituting numbers from another program.
13) When listing costs or breakdowns, quote the exact numbers from the matching context chunk verbatim. Do not round, average, or estimate.
""".strip()


def _extract_response_text(response: Any) -> str:
    try:
        return (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        return ""


CONTACT_PATTERNS = (
    "contact", "email", "phone", "address", "reach you", "get in touch",
    "talk to someone", "support", "office", "where are you", "located",
)

HUMAN_REQUEST_PATTERNS = (
    "talk to a human", "speak to a human", "human agent", "real person",
    "talk to someone", "speak to operator", "operator", "live agent",
    "customer support",
)

NO_INFO_PATTERNS = (
    r"\bi (?:do not|don't) (?:have|know)",
    r"\bnot (?:enough|sufficient) information",
    r"\binformation .{0,20} (?:not available|missing)",
    r"\bunable to (?:find|locate)",
    r"\bno information",
)


def _looks_like_no_info(answer: str) -> bool:
    low = (answer or "").lower()
    if not low:
        return True
    return any(re.search(p, low) for p in NO_INFO_PATTERNS)


_INLINE_SOURCE_LINE = re.compile(
    r"(?im)^[ \t]*(?:\*+\s*)?source[s]?\s*[:\-]?\s*(?:\(.*?\)|https?://\S+|copernicusberlin\S*)[^\n]*\n?"
)
_INLINE_SOURCE_PAREN = re.compile(
    r"\s*\((?:source|sources)\s*[:\-]?\s*[^)]*\)",
    re.IGNORECASE,
)


def _strip_inline_sources(text: str) -> str:
    """Remove 'Source: <url>' lines and '(Source: ...)' inline references.

    The model occasionally inserts these even though the system prompt forbids it.
    The widget appends a 'Learn more:' block separately, so inline sources are
    redundant noise.
    """
    if not text:
        return text
    cleaned = _INLINE_SOURCE_LINE.sub("", text)
    cleaned = _INLINE_SOURCE_PAREN.sub("", cleaned)
    # collapse blank-line runs created by the removals
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
    return cleaned


def _looks_like_scope_refusal(answer: str) -> bool:
    low = (answer or "").lower()
    return (
        "i can only help with questions about copernicus berlin" in low
        or "only help with copernicus berlin" in low
    )


class ChatService:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._retriever = Retriever()
        self._memory = SessionMemory(max_turns=settings.memory_max_turns)

    def reload_index(self) -> None:
        self._retriever.reload()

    def clear_session(self, session_id: str) -> None:
        self._memory.clear(session_id)

    def override_last_assistant_turn(self, session_id: str | None, content: str) -> None:
        if not session_id:
            return
        self._memory.replace_last_assistant_turn(session_id, content)

    def _client_or_raise(self) -> OpenAI:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if not self._client:
            self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def _fallback_message(self) -> str:
        return "Sorry, I could not process the response right now. Please try again shortly."

    def _scope_only_message(self) -> str:
        return (
            "I can only help with questions about Copernicus Berlin and its programs. "
            "Try asking about our projects, scholarships, events, or how to get in touch."
        )

    def _human_handoff_ack(self) -> str:
        return (
            "Sure — I'll let our team know. You can also use the **“Contact a human”** "
            "button to leave your name and email, and someone from Copernicus Berlin will get back to you."
        )

    @staticmethod
    def is_contact_query(message: str) -> bool:
        low = (message or "").lower()
        return any(p in low for p in CONTACT_PATTERNS)

    @staticmethod
    def _is_human_request(message: str) -> bool:
        low = (message or "").lower()
        return any(p in low for p in HUMAN_REQUEST_PATTERNS)

    @staticmethod
    def _is_smalltalk(message: str) -> bool:
        low = (message or "").lower().strip().rstrip("!?. ")
        if not low:
            return True
        greetings = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "good morning",
                     "good afternoon", "good evening", "yes", "no", "cool", "great"}
        return low in greetings

    def should_force_operator_handoff(self, message: str, session_id: str | None = None) -> bool:
        return False

    def _build_context_block(self, chunks: list[tuple]) -> tuple[str, list[str]]:
        lines: list[str] = []
        used_urls: list[str] = []
        seen_urls: set[str] = set()
        char_budget = settings.retrieval_max_context_chars
        for chunk, score in chunks:
            block = f"Source: {chunk.url}\nTitle: {chunk.title}\n{chunk.text}\n---"
            if len("\n".join(lines)) + len(block) > char_budget:
                break
            lines.append(block)
            if chunk.url not in seen_urls and not chunk.url.startswith("faq://"):
                seen_urls.add(chunk.url)
                used_urls.append(chunk.url)
        return "\n".join(lines), used_urls

    def _build_messages(self, message: str, session_id: str | None, context_block: str) -> list[dict]:
        history: list[dict] = []
        if session_id:
            for turn in self._memory.get_history(session_id)[-(settings.memory_max_turns * 2):]:
                history.append({"role": turn.get("role", "user"), "content": turn.get("content", "")})

        ctx_section = f"\n\nContext:\n{context_block}" if context_block else "\n\nContext: (no relevant pages found)"
        return [
            {"role": "system", "content": SYSTEM_PROMPT + ctx_section},
            *history,
            {"role": "user", "content": message},
        ]

    def _append_source_links(self, answer: str, urls: list[str]) -> str:
        answer = _strip_inline_sources(answer)
        if not urls:
            return answer
        if _looks_like_no_info(answer) or _looks_like_scope_refusal(answer):
            return answer
        # 2 links is plenty for the widget; more than that gets noisy.
        bullet = "\n".join(f"- {u}" for u in urls[:2])
        return f"{answer.rstrip()}\n\nLearn more:\n{bullet}"

    def _resolve_link_rule(self, message: str) -> dict | None:
        rule = find_matching_link_rule(message)
        if not rule:
            return None
        return rule

    def ask(self, message: str, language: str | None = None, session_id: str | None = None) -> ChatResult:
        if self._is_smalltalk(message):
            answer = ("Hi! I'm the Copernicus Berlin assistant. "
                      "Ask me about our programs, events, scholarships, or how to get involved.")
            self._memory.add_turn(session_id or "", "user", message)
            self._memory.add_turn(session_id or "", "assistant", answer)
            return ChatResult(answer=answer, language="en", confidence=1.0, needs_human=False)

        if self._is_human_request(message):
            answer = self._human_handoff_ack()
            self._memory.add_turn(session_id or "", "user", message)
            self._memory.add_turn(session_id or "", "assistant", answer)
            return ChatResult(answer=answer, language="en", confidence=1.0, needs_human=False)

        # Manual link rule override.
        rule = self._resolve_link_rule(message)
        if rule and rule.get("mode") == "disable":
            answer = ("I don't have a confirmed answer for that here. "
                      "Please check copernicusberlin.org or use the contact form for help.")
            return ChatResult(answer=answer, language="en", confidence=0.5, needs_human=False)
        forced_url = rule.get("url", "").strip() if rule and rule.get("mode") == "manual" else ""

        chunks = self._retriever.query(message, "en", k=settings.retrieval_top_k)
        context_block, used_urls = self._build_context_block(chunks)

        client = self._client_or_raise()
        try:
            response = client.chat.completions.create(
                model=settings.openai_chat_model,
                messages=self._build_messages(message, session_id, context_block),
                temperature=0.2,
                max_tokens=600,
            )
        except Exception as exc:
            raise RuntimeError(f"chat provider error: {exc}") from exc

        answer = _extract_response_text(response) or self._fallback_message()

        confidence = 0.5
        if chunks:
            top_score = (chunks[0][1] + 1.0) / 2.0
            confidence = round(float(top_score), 3)

        needs_human = False
        if _looks_like_no_info(answer) and confidence < 0.55:
            needs_human = True

        if forced_url:
            answer = f"{answer.rstrip()}\n\nMore info: {forced_url}"
        else:
            answer = self._append_source_links(answer, used_urls)

        self._memory.add_turn(session_id or "", "user", message)
        self._memory.add_turn(session_id or "", "assistant", answer)
        return ChatResult(answer=answer, language="en", confidence=confidence, needs_human=needs_human)

    def stream_answer(self, message: str, language: str | None = None, session_id: str | None = None) -> Iterator[str]:
        """Yields incremental tokens of the answer; used by /chat/stream."""
        if self._is_smalltalk(message):
            text = ("Hi! I'm the Copernicus Berlin assistant. "
                    "Ask me about our programs, events, scholarships, or how to get involved.")
            self._memory.add_turn(session_id or "", "user", message)
            self._memory.add_turn(session_id or "", "assistant", text)
            yield text
            return

        if self._is_human_request(message):
            text = self._human_handoff_ack()
            self._memory.add_turn(session_id or "", "user", message)
            self._memory.add_turn(session_id or "", "assistant", text)
            yield text
            return

        chunks = self._retriever.query(message, "en", k=settings.retrieval_top_k)
        context_block, used_urls = self._build_context_block(chunks)
        client = self._client_or_raise()
        try:
            stream = client.chat.completions.create(
                model=settings.openai_chat_model,
                messages=self._build_messages(message, session_id, context_block),
                temperature=0.2,
                max_tokens=600,
                stream=True,
            )
        except Exception as exc:
            raise RuntimeError(f"chat provider error: {exc}") from exc

        # We buffer by line so we can drop "Source: <url>" lines the model
        # sometimes emits despite the prompt. Whole lines are yielded once
        # we're sure they don't start with "Source".
        collected: list[str] = []
        buffer = ""

        def _is_source_line(line: str) -> bool:
            stripped = line.lstrip(" \t-*")
            return stripped.lower().startswith(("source:", "sources:"))

        for event in stream:
            try:
                delta = event.choices[0].delta.content or ""
            except (AttributeError, IndexError):
                delta = ""
            if not delta:
                continue
            buffer += delta
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if _is_source_line(line):
                    continue
                out = line + "\n"
                collected.append(out)
                yield out

        # Flush whatever remains in buffer (no trailing newline)
        if buffer and not _is_source_line(buffer):
            collected.append(buffer)
            yield buffer

        full = _strip_inline_sources("".join(collected)).strip()
        if used_urls and not _looks_like_no_info(full) and not _looks_like_scope_refusal(full):
            tail = "\n\nLearn more:\n" + "\n".join(f"- {u}" for u in used_urls[:2])
            yield tail
            full = full + tail

        self._memory.add_turn(session_id or "", "user", message)
        self._memory.add_turn(session_id or "", "assistant", full)

    def infer_needs_human(self, full_answer: str, confidence: float | None) -> bool:
        return _looks_like_no_info(full_answer)
