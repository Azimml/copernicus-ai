from __future__ import annotations

import json
from time import monotonic
from typing import List

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    FAQItem,
    FAQUpsertRequest,
    HandoffAiModeRequest,
    HandoffReplyRequest,
    HandoffResolveRequest,
    LinkRuleItem,
    LinkRuleUpsertRequest,
    PublicQuickActionItem,
    QuickActionItem,
    QuickActionsUpdateRequest,
    ReindexRequest,
    SatisfactionFeedbackRequest,
    SessionHistoryItem,
    SessionResetRequest,
    SupportContactRequest,
    SupportContactResponse,
)
from app.services.analytics import build_summary, record_chat_event
from app.services.chat import ChatService
from app.services.chat_log import append_log, get_session_log, list_sessions
from app.services.faq_store import delete_faq, list_faq, upsert_faq
from app.services.handoff import (
    add_operator_reply,
    append_user_message_to_open_handoff,
    create_handoff,
    get_handoff,
    is_ai_enabled_for_session,
    list_handoffs,
    resolve_handoff,
    set_handoff_ai_enabled,
)
from app.services.indexer import delete_faq_index, upsert_faq_index
from app.services.link_rules import delete_link_rule, list_link_rules, upsert_link_rule
from app.services.monitoring import runtime_monitor
from app.services.operator_bridge import list_operator_messages
from app.services.quick_actions import (
    find_manual_quick_action,
    list_public_quick_actions,
    list_quick_actions,
    save_quick_actions,
)


router = APIRouter()
chat_service = ChatService()


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "env": settings.app_env,
        "runtime": runtime_monitor.snapshot(),
        "caches": chat_service.cache_stats(),
    }


@router.get("/health/ready")
def readiness() -> dict:
    return {"ok": True, "openai_key_configured": bool(settings.openai_api_key)}


def _operator_wait_ack() -> str:
    return "Your message has been forwarded to our team. Please wait for a reply here."


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    runtime_monitor.inc_chat()
    started = monotonic()
    ui_action: str | None = None
    try:
        append_log(session_id=payload.session_id or "", role="user", text=payload.message)

        if payload.session_id and not is_ai_enabled_for_session(payload.session_id):
            append_user_message_to_open_handoff(
                session_id=payload.session_id,
                text=payload.message,
            )
            answer = _operator_wait_ack()
            append_log(session_id=payload.session_id or "", role="assistant", text=answer)
            record_chat_event(
                session_id=payload.session_id,
                message=payload.message,
                needs_human=True,
                confidence=1.0,
                latency_ms=int((monotonic() - started) * 1000),
            )
            return ChatResponse(answer=answer, confidence=1.0, needs_human=False)

        manual = find_manual_quick_action(payload.message)
        if manual:
            append_log(session_id=payload.session_id or "", role="assistant", text=manual["answer"])
            record_chat_event(
                session_id=payload.session_id,
                message=payload.message,
                needs_human=False,
                confidence=1.0,
                latency_ms=int((monotonic() - started) * 1000),
            )
            return ChatResponse(answer=manual["answer"], confidence=1.0, needs_human=False)

        if chat_service.is_contact_query(payload.message):
            ui_action = "open_support_modal"

        result = chat_service.ask(payload.message, payload.language, payload.session_id)
        append_log(session_id=payload.session_id or "", role="assistant", text=result.answer)
        record_chat_event(
            session_id=payload.session_id,
            message=payload.message,
            needs_human=result.needs_human,
            confidence=result.confidence,
            latency_ms=int((monotonic() - started) * 1000),
        )
    except RuntimeError as exc:
        runtime_monitor.inc_chat_error()
        record_chat_event(
            session_id=payload.session_id,
            message=payload.message,
            error=str(exc),
            latency_ms=int((monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        runtime_monitor.inc_chat_error()
        record_chat_event(
            session_id=payload.session_id,
            message=payload.message,
            error=str(exc),
            latency_ms=int((monotonic() - started) * 1000),
        )
        raise HTTPException(status_code=502, detail=f"Chat provider error: {exc}") from exc
    return ChatResponse(
        answer=result.answer,
        confidence=result.confidence,
        needs_human=result.needs_human,
        ui_action=ui_action,
    )


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    runtime_monitor.inc_chat_stream()

    def event_iter():
        started = monotonic()
        collected: list[str] = []
        try:
            append_log(session_id=payload.session_id or "", role="user", text=payload.message)

            if payload.session_id and not is_ai_enabled_for_session(payload.session_id):
                append_user_message_to_open_handoff(session_id=payload.session_id, text=payload.message)
                answer = _operator_wait_ack()
                append_log(session_id=payload.session_id or "", role="assistant", text=answer)
                record_chat_event(
                    session_id=payload.session_id,
                    message=payload.message,
                    needs_human=True,
                    confidence=1.0,
                    latency_ms=int((monotonic() - started) * 1000),
                )
                step = max(8, settings.stream_chunk_chars)
                for i in range(0, len(answer), step):
                    yield json.dumps({"type": "token", "text": answer[i : i + step]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                return

            manual = find_manual_quick_action(payload.message)
            if manual:
                answer = manual["answer"]
                append_log(session_id=payload.session_id or "", role="assistant", text=answer)
                record_chat_event(
                    session_id=payload.session_id,
                    message=payload.message,
                    needs_human=False,
                    confidence=1.0,
                    latency_ms=int((monotonic() - started) * 1000),
                )
                step = max(8, settings.stream_chunk_chars)
                for i in range(0, len(answer), step):
                    yield json.dumps({"type": "token", "text": answer[i : i + step]}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
                return

            if chat_service.is_contact_query(payload.message):
                yield json.dumps(
                    {"type": "ui_action", "action": "open_support_modal", "prefill_question": payload.message},
                    ensure_ascii=False,
                ) + "\n"

            for token in chat_service.stream_answer(
                message=payload.message,
                language=payload.language,
                session_id=payload.session_id,
            ):
                collected.append(token)
                yield json.dumps({"type": "token", "text": token}, ensure_ascii=False) + "\n"

            full_answer = "".join(collected).strip()
            needs_human = chat_service.infer_needs_human(full_answer, confidence=None)
            record_chat_event(
                session_id=payload.session_id,
                message=payload.message,
                needs_human=needs_human,
                confidence=None,
                latency_ms=int((monotonic() - started) * 1000),
            )
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            if full_answer:
                append_log(session_id=payload.session_id or "", role="assistant", text=full_answer)
        except RuntimeError as exc:
            runtime_monitor.inc_chat_error()
            record_chat_event(
                session_id=payload.session_id,
                message=payload.message,
                error=str(exc),
                latency_ms=int((monotonic() - started) * 1000),
            )
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        except Exception as exc:
            runtime_monitor.inc_chat_error()
            record_chat_event(
                session_id=payload.session_id,
                message=payload.message,
                error=str(exc),
                latency_ms=int((monotonic() - started) * 1000),
            )
            yield json.dumps({"type": "error", "message": f"Chat provider error: {exc}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_iter(), media_type="application/x-ndjson")


@router.post("/chat/reset")
def chat_reset(payload: SessionResetRequest) -> dict:
    chat_service.clear_session(payload.session_id)
    return {"ok": True}


@router.get("/quick-actions", response_model=List[PublicQuickActionItem])
def public_quick_actions() -> list[PublicQuickActionItem]:
    return [PublicQuickActionItem(**item) for item in list_public_quick_actions()]


@router.post("/chat/support", response_model=SupportContactResponse)
def chat_support(payload: SupportContactRequest) -> SupportContactResponse:
    question = payload.question.strip()
    contact = {
        "name": payload.name.strip(),
        "email": payload.email.strip(),
    }
    log_text = (
        "Support request\n"
        f"Name: {contact['name']}\n"
        f"Email: {contact['email']}\n"
        f"Question: {question}"
    )
    if payload.session_id:
        append_log(session_id=payload.session_id, role="user", text=log_text)

    ack = "Thanks! Your request has been sent to our team — someone will reply to your email shortly."
    handoff = create_handoff(
        session_id=payload.session_id,
        user_message=question,
        bot_answer=ack,
        confidence=0.0,
        needs_human_reason="support_contact_form",
        contact=contact,
        ai_enabled=True,
    )
    if payload.session_id:
        append_log(session_id=payload.session_id, role="assistant", text=ack)

    record_chat_event(
        session_id=payload.session_id,
        message=question,
        needs_human=True,
        confidence=0.0,
        latency_ms=0,
    )
    return SupportContactResponse(ok=True, handoff_id=handoff["id"], message=ack)


@router.post("/chat/satisfaction")
def chat_satisfaction(payload: SatisfactionFeedbackRequest) -> dict:
    text = "Yes" if payload.response == "yes" else "No"
    if payload.session_id:
        append_log(
            session_id=payload.session_id,
            role="user",
            text=text,
            meta={"kind": "satisfaction_response", "value": payload.response},
        )
    record_chat_event(
        session_id=payload.session_id,
        message=text,
        needs_human=False,
        confidence=1.0,
        latency_ms=0,
        event_type="satisfaction",
        satisfaction=payload.response,
    )
    return {"ok": True}


@router.get("/chat/inbox")
def chat_inbox(session_id: str, after_id: str | None = Query(default=None)) -> dict:
    items = list_operator_messages(session_id=session_id, after_id=after_id, limit=100)
    return {"items": items}


def _verify_admin_token(token: str | None) -> None:
    """Admin auth disabled: the dashboard is open inside the deployment."""
    return None


@router.get("/admin/faq", response_model=List[FAQItem])
def get_faq(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> list[FAQItem]:
    _verify_admin_token(x_admin_token)
    return [FAQItem(**i) for i in list_faq()]


@router.post("/admin/faq", response_model=FAQItem)
def create_faq(
    payload: FAQUpsertRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> FAQItem:
    _verify_admin_token(x_admin_token)
    created = upsert_faq(payload.model_dump())
    try:
        upsert_faq_index(created)
        chat_service.reload_index()
    except Exception:
        pass
    return FAQItem(**created)


@router.put("/admin/faq/{faq_id}", response_model=FAQItem)
def update_faq(
    faq_id: str,
    payload: FAQUpsertRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> FAQItem:
    _verify_admin_token(x_admin_token)
    updated = upsert_faq(payload.model_dump(), faq_id=faq_id)
    try:
        upsert_faq_index(updated)
        chat_service.reload_index()
    except Exception:
        pass
    return FAQItem(**updated)


@router.delete("/admin/faq/{faq_id}")
def remove_faq(faq_id: str, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict:
    _verify_admin_token(x_admin_token)
    ok = delete_faq(faq_id)
    if not ok:
        raise HTTPException(status_code=404, detail="FAQ not found")
    try:
        delete_faq_index(faq_id)
        chat_service.reload_index()
    except Exception:
        pass
    return {"ok": True}


@router.get("/admin/quick-actions", response_model=List[QuickActionItem])
def get_quick_actions(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> list[QuickActionItem]:
    _verify_admin_token(x_admin_token)
    return [QuickActionItem(**item) for item in list_quick_actions()]


@router.put("/admin/quick-actions", response_model=List[QuickActionItem])
def update_quick_actions(
    payload: QuickActionsUpdateRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> list[QuickActionItem]:
    _verify_admin_token(x_admin_token)
    saved = save_quick_actions([item.model_dump() for item in payload.items])
    return [QuickActionItem(**item) for item in saved]


@router.get("/admin/link-rules", response_model=List[LinkRuleItem])
def get_link_rules(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> list[LinkRuleItem]:
    _verify_admin_token(x_admin_token)
    return [LinkRuleItem(**item) for item in list_link_rules()]


@router.post("/admin/link-rules", response_model=LinkRuleItem)
def create_link_rule(
    payload: LinkRuleUpsertRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> LinkRuleItem:
    _verify_admin_token(x_admin_token)
    return LinkRuleItem(**upsert_link_rule(payload.model_dump()))


@router.put("/admin/link-rules/{rule_id}", response_model=LinkRuleItem)
def update_link_rule(
    rule_id: str,
    payload: LinkRuleUpsertRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> LinkRuleItem:
    _verify_admin_token(x_admin_token)
    return LinkRuleItem(**upsert_link_rule(payload.model_dump(), rule_id=rule_id))


@router.delete("/admin/link-rules/{rule_id}")
def remove_link_rule(rule_id: str, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> dict:
    _verify_admin_token(x_admin_token)
    ok = delete_link_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Link rule not found")
    return {"ok": True}


@router.post("/admin/reindex")
def reindex(
    payload: ReindexRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Kick off a reindex in the background. Returns immediately with the
    job row; poll ``/api/admin/reindex-status`` for progress."""
    from app.services.reindex_jobs import start_job
    _verify_admin_token(x_admin_token)
    try:
        job = start_job(
            full_crawl=payload.full_crawl,
            on_done=lambda d, c: chat_service.reload_index(),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "job": job}


@router.get("/admin/reindex-status")
def reindex_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Current reindex job state. The admin UI polls this every 2-3 sec
    while a job is running."""
    from app.services.reindex_jobs import get_latest_job, get_active_job
    _verify_admin_token(x_admin_token)
    latest = get_latest_job()
    active = get_active_job()
    return {"active": active, "latest": latest}


@router.get("/admin/index-status")
def index_status(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    """Stats about the current retrieval index: file sizes, doc/chunk counts,
    last update time, and the list of indexed URLs. Used by the Reindex page."""
    from datetime import datetime, timezone
    from app.core.io import read_json
    from app.services.indexer import DOCS_PATH, INDEX_META_PATH, INDEX_EMB_PATH
    from app.core.config import settings

    _verify_admin_token(x_admin_token)

    def _file_stat(p):
        if not p.exists():
            return {"exists": False, "size_bytes": 0, "modified_at": ""}
        st = p.stat()
        return {
            "exists": True,
            "size_bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        }

    docs_payload = read_json(DOCS_PATH, default={"documents": []})
    chunks_payload = read_json(INDEX_META_PATH, default={"chunks": []})
    documents = docs_payload.get("documents", []) if isinstance(docs_payload, dict) else []
    chunks_meta = chunks_payload.get("chunks", []) if isinstance(chunks_payload, dict) else []

    # Per-URL chunk count
    chunks_by_url: dict[str, int] = {}
    for c in chunks_meta:
        url = str(c.get("url") or "")
        if not url:
            continue
        chunks_by_url[url] = chunks_by_url.get(url, 0) + 1

    docs_info = []
    for d in documents:
        url = d.get("url", "")
        docs_info.append({
            "url": url,
            "title": d.get("title", ""),
            "text_chars": len(d.get("text", "") or ""),
            "chunks": chunks_by_url.get(url, 0),
        })
    docs_info.sort(key=lambda x: x["text_chars"], reverse=True)

    return {
        "site_root": settings.site_root,
        "crawl_paths": settings.crawl_paths,
        "documents_total": len(documents),
        "chunks_total": len(chunks_meta),
        "documents_file": _file_stat(DOCS_PATH),
        "chunks_file": _file_stat(INDEX_META_PATH),
        "embeddings_file": _file_stat(INDEX_EMB_PATH),
        "runtime": runtime_monitor.snapshot(),
        "documents": docs_info,
    }


@router.get("/admin/analytics")
def admin_analytics(
    days: int = 0,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    return build_summary(days=days)


@router.get("/admin/handoffs")
def admin_handoffs(
    status: str | None = None,
    limit: int = 100,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> list[dict]:
    _verify_admin_token(x_admin_token)
    return list_handoffs(status=status, limit=limit)


@router.get("/admin/handoffs/{handoff_id}")
def admin_handoff_detail(
    handoff_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    item = get_handoff(handoff_id)
    if not item:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return item


@router.get("/admin/sessions/{session_id}")
def admin_session_log(
    session_id: str,
    limit: int = 200,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    items = get_session_log(session_id=session_id, limit=limit)
    return {"items": items}


@router.get("/admin/history", response_model=List[SessionHistoryItem])
def admin_history(
    limit: int = 200,
    q: str | None = None,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> list[SessionHistoryItem]:
    _verify_admin_token(x_admin_token)
    items = list_sessions(limit=limit, query=q)
    return [SessionHistoryItem(**item) for item in items]


@router.post("/admin/handoffs/{handoff_id}/reply")
def admin_handoff_reply(
    handoff_id: str,
    payload: HandoffReplyRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    updated = add_operator_reply(handoff_id, message=payload.message, operator_name=payload.operator_name)
    if not updated:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return updated


@router.post("/admin/handoffs/{handoff_id}/ai-mode")
def admin_handoff_ai_mode(
    handoff_id: str,
    payload: HandoffAiModeRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    updated = set_handoff_ai_enabled(handoff_id, payload.ai_enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return updated


@router.post("/admin/handoffs/{handoff_id}/resolve")
def admin_handoffs_resolve(
    handoff_id: str,
    payload: HandoffResolveRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict:
    _verify_admin_token(x_admin_token)
    updated = resolve_handoff(handoff_id, note=payload.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return updated
