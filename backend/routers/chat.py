"""
Chat router — POST /chat/stream

Accepts a user message and streams the agent response back as Server-Sent Events.

SSE event types:
  {"type": "token",        "content": "word "}   — incremental response tokens
  {"type": "jargon_map",   "data": [...]}         — jargon mapping (after all tokens)
  {"type": "action_cards", "data": [...]}         — interactive action cards (after tokens)
  {"type": "suggested_replies", "data": [...]}    — quick-reply pills (after tokens)
  {"type": "done"}                                — stream complete
  {"type": "error",        "message": "..."}      — error event

action_cards are sent alongside jargon_map as trailing metadata events.
The frontend renders them as interactive cards below the message bubble.

Session creation now automatically sends a warm opener message from the agent,
stored as an assistant message so it appears in history on reload.
"""

import json
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

from middleware.tenant import get_tenant_context, TenantContext
from dependencies import get_agent_graph
from agent.state import AgentState
from agent.nodes.session_opener import get_opener_message
from services.supabase_client import get_admin_client
from services.note_analysis_service import analyze_note, build_action_cards, build_upload_suggestions
from services.llama_parse_service import parse_document, UNSUPPORTED_FILE_MESSAGE
from services.journey_update_service import update_journey_from_analysis
from services.embedding_service import get_embedding

log = logging.getLogger("wellbridge.chat")

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    message: str


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    graph=Depends(get_agent_graph),
):
    """
    Stream the agent response for a chat message.
    Uses LangGraph to route through the safety-first state machine.
    """
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    # Admin client is used for all DB operations in this endpoint.
    # get_scoped_client() relies on RLS session variables or PostgREST JWT auth,
    # both of which can silently return 0 rows if not correctly configured.
    # The admin client bypasses RLS; security is enforced by explicit
    # tenant_id / user_id filters on every query.
    db = get_admin_client()

    # Load the last 10 prior messages from this session to give the agent
    # conversation context (uploaded document summaries, prior answers, etc.)
    history_messages: list = []
    try:
        history_result = (
            db.table("chat_messages")
            .select("role, content")
            .eq("session_id", req.session_id)
            .eq("tenant_id", ctx.tenant_id)
            .order("created_at", desc=False)
            .limit(10)
            .execute()
        )
        for row in (history_result.data or []):
            if row["role"] == "user":
                history_messages.append(HumanMessage(content=row["content"]))
            else:
                history_messages.append(AIMessage(content=row["content"]))
        log.info("chat_stream: loaded %d history messages for session=%s",
                 len(history_messages), req.session_id)
    except Exception as exc:
        log.warning("chat_stream: failed to load history — %s", exc)

    # Persist the user message before invoking the graph
    try:
        db.table("chat_messages").insert({
            "session_id": req.session_id,
            "tenant_id": ctx.tenant_id,
            "role": "user",
            "content": req.message,
            "jargon_map": [],
        }).execute()
        log.info("chat_stream: saved user message for session=%s", req.session_id)
    except Exception as exc:
        log.warning("chat_stream: failed to save user message — %s", exc)

    # The current user message is always last; history provides prior context
    initial_state: AgentState = {
        "messages": history_messages + [HumanMessage(content=req.message)],
        "intent": None,
        "confidence": 0.0,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user_id,
        "role": ctx.role,
        "session_id": req.session_id,
        "emotional_state": "calm",
        "care_stage": "unknown",
        "care_context": {},
        "records": [],
        "appointments": [],
        "tool_error": None,
        "raw_response": None,
        "final_response": None,
        "jargon_map": [],
        "action_cards": [],
        "suggested_replies": [],
        "refusal_context_facts": [],
    }

    async def event_generator():
        try:
            final_state: AgentState = await graph.ainvoke(initial_state)
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        response_text = final_state.get("final_response") or ""
        jargon_map = final_state.get("jargon_map", [])
        action_cards = final_state.get("action_cards", [])
        suggested_replies = final_state.get("suggested_replies", [])

        # Persist the assistant message before streaming tokens back
        try:
            db.table("chat_messages").insert({
                "session_id": req.session_id,
                "tenant_id": ctx.tenant_id,
                "role": "assistant",
                "content": response_text,
                "intent": final_state.get("intent"),
                "jargon_map": jargon_map,
                "action_cards": action_cards,
            }).execute()
            log.info("chat_stream: saved assistant message for session=%s intent=%s",
                     req.session_id, final_state.get("intent"))
        except Exception as exc:
            log.error("chat_stream: failed to save assistant message — %s", exc, exc_info=True)

        # For MEDICAL_ADVICE refusals (which bypass response_assembler),
        # inject static contextual suggestions so the user always has a path forward
        if not suggested_replies and final_state.get("intent") == "MEDICAL_ADVICE":
            suggested_replies = [
                "I have a note from my doctor to share",
                "Tell me what my records say",
                "Help me write a question for my care team",
            ]

        # Stream response word by word (simulated streaming)
        words = response_text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

        # Trailing metadata events
        yield f"data: {json.dumps({'type': 'jargon_map', 'data': jargon_map})}\n\n"
        yield f"data: {json.dumps({'type': 'action_cards', 'data': action_cards})}\n\n"
        yield f"data: {json.dumps({'type': 'suggested_replies', 'data': suggested_replies})}\n\n"

        # Signal completion
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions")
async def list_sessions(ctx: TenantContext = Depends(get_tenant_context)):
    """Return the user's chat sessions, newest first."""
    try:
        db = get_admin_client()
        result = (
            db.table("chat_sessions")
            .select("id, title, created_at, updated_at")
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .order("updated_at", desc=True)
            .limit(50)
            .execute()
        )
        return {"sessions": result.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/sessions")
async def create_session(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Create a new chat session and immediately post a warm opener message
    from the agent. The opener is stored as an assistant message so it
    appears in history when the session is loaded — no user input required.
    """
    try:
        db = get_admin_client()

        # Create the session
        session_result = (
            db.table("chat_sessions")
            .insert({
                "tenant_id": ctx.tenant_id,
                "user_id": ctx.user_id,
                "title": "New conversation",
            })
            .execute()
        )
        session = session_result.data[0]
        session_id = session["id"]

        # Check whether this is the user's first-ever session
        try:
            prior = (
                db.table("chat_sessions")
                .select("id", count="exact")
                .eq("tenant_id", ctx.tenant_id)
                .eq("user_id", ctx.user_id)
                .neq("id", session_id)
                .limit(1)
                .execute()
            )
            is_first = (prior.count or 0) == 0
        except Exception:
            is_first = False

        # Look up the patient's stored first name for a personalised greeting.
        # Uses the admin client (service-role) because the patients RLS policy
        # relies on app.tenant_id session variables that are not set in the
        # production JWT path — the admin client bypasses RLS safely here since
        # we explicitly filter by ctx.tenant_id and ctx.user_id.
        first_name = ""
        try:
            admin = get_admin_client()
            profile = (
                admin.table("patients")
                .select("first_name")
                .eq("tenant_id", ctx.tenant_id)
                .eq("user_id", ctx.user_id)
                .limit(1)
                .execute()
            )
            if profile.data and profile.data[0].get("first_name"):
                first_name = profile.data[0]["first_name"]
        except Exception:
            pass  # Greeting degrades gracefully without a name

        # Store the opener as the first assistant message
        opener_text = get_opener_message(is_first_session=is_first, first_name=first_name)
        try:
            db.table("chat_messages").insert({
                "session_id": session_id,
                "tenant_id": ctx.tenant_id,
                "role": "assistant",
                "content": opener_text,
                "jargon_map": [],
                "intent": "GENERAL",
            }).execute()
            log.info("create_session: stored opener message for session=%s is_first=%s",
                     session_id, is_first)
        except Exception as exc:
            log.warning("create_session: failed to store opener — %s", exc)  # Non-blocking

        return {**session, "opener_message": opener_text}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    request: Request = None,
):
    """Rename a chat session title."""
    try:
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="Title cannot be empty.")
        db = get_admin_client()
        result = (
            db.table("chat_sessions")
            .update({"title": title})
            .eq("id", session_id)
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Session not found.")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Delete a chat session and all its messages."""
    try:
        db = get_admin_client()
        # Messages cascade via FK; delete messages first if no cascade configured
        db.table("chat_messages").delete().eq("session_id", session_id).execute()
        result = (
            db.table("chat_sessions")
            .delete()
            .eq("id", session_id)
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Session not found.")
        return {"deleted": session_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/sessions/{session_id}/upload")
async def upload_note(
    session_id: str,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Upload a clinical note or document into the chat session.

    Supported formats (via LlamaParse):
      Documents: PDF, DOCX, DOC, TXT, RTF
      Images:    PNG, JPG, JPEG, TIFF, HEIC
      Audio:     MP3, MP4, M4A, WAV, WEBM

    Flow:
      1. Validate file extension — return 422 with friendly message if unsupported
      2. Parse with LlamaParse → clean markdown text
      3. Run GPT-4o analysis: plain-English summary + prescriptions + appointments + referrals
      4. Store the full note as a patient_record (RLS-scoped)
      5. Update Journey: upsert medications and appointments with dedup
      6. Store the summary as an assistant chat_message in this session
      7. Return the summary + action cards for the frontend to render immediately
    """
    try:
        filename = file.filename or "document"
        file_bytes = await file.read()
        log.info("upload_note: received file=%s size=%d session=%s", filename, len(file_bytes), session_id)

        if not file_bytes:
            raise HTTPException(status_code=422, detail="The uploaded file is empty.")

        # ── Step 1: Parse document with LlamaParse ───────────────────────────
        log.info("upload_note: step 1 — parsing with LlamaParse")
        try:
            note_text = await parse_document(file_bytes, filename)
            log.info("upload_note: LlamaParse returned %d chars", len(note_text))
        except ValueError as exc:
            log.warning("upload_note: unsupported file type — %s", exc)
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            log.error("upload_note: LlamaParse error — %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc))

        if not note_text.strip():
            raise HTTPException(
                status_code=422,
                detail="The document appears to be empty or could not be read. "
                       "Please try a different file or type out the contents instead.",
            )

        # ── Step 2: Analyze the note with GPT-4o ────────────────────────────
        log.info("upload_note: step 2 — running GPT-4o note analysis")
        try:
            analysis = await analyze_note(note_text)
            log.info(
                "upload_note: analysis done — %d prescriptions, %d appointments, %d referrals",
                len(analysis.prescriptions),
                len(analysis.follow_up_appointments),
                len(analysis.referrals),
            )
        except Exception as exc:
            log.error("upload_note: analyze_note error — %s", exc, exc_info=True)
            raise

        action_cards = build_action_cards(analysis)
        suggested_replies = build_upload_suggestions(analysis)

        # ── Step 3: Store the full note as a patient_record ──────────────────
        log.info("upload_note: step 3 — storing clinical_note in patient_records")
        # Use admin client — get_scoped_client() may not set RLS session vars
        # correctly in all auth configurations (dev mode / JWT path). The admin
        # client bypasses RLS; security is enforced by the explicit tenant_id
        # and patient_user_id values in the insert payload below.
        db = get_admin_client()

        # Generate embedding for semantic search (non-blocking on failure)
        log.info("upload_note: step 3a — generating content embedding")
        content_to_store = note_text[:10000]
        try:
            embedding = await get_embedding(content_to_store)
        except Exception:
            embedding = []
        log.info("upload_note: embedding dims=%d", len(embedding))

        try:
            insert_payload: dict = {
                "tenant_id": ctx.tenant_id,
                "patient_user_id": ctx.user_id,
                "record_type": "clinical_note",
                "provider_name": f"Uploaded: {filename}",
                "note_date": date.today().isoformat(),
                "content": content_to_store,
            }
            if embedding:
                insert_payload["content_vector"] = embedding

            record_result = db.table("patient_records").insert(insert_payload).execute()
            record_id = record_result.data[0]["id"] if record_result.data else None
            log.info("upload_note: stored patient_record id=%s (embedding=%s)",
                     record_id, "yes" if embedding else "no")
        except Exception as exc:
            log.error("upload_note: patient_records insert error — %s", exc, exc_info=True)
            raise

        # ── Step 4: Update Journey (medications + appointments, deduped) ──────
        log.info("upload_note: step 4 — updating journey")
        try:
            journey_result = await update_journey_from_analysis(analysis, ctx)
            log.info("upload_note: journey updated — %s", journey_result)
        except Exception as exc:
            log.warning("upload_note: journey update failed (non-blocking) — %s", exc, exc_info=True)
            journey_result = {}  # Non-blocking

        # ── Step 5: Store the summary as an assistant message ─────────────────
        log.info("upload_note: step 5 — storing assistant summary message")
        summary_text = analysis.summary
        try:
            db.table("chat_messages").insert({
                "session_id": session_id,
                "tenant_id": ctx.tenant_id,
                "role": "assistant",
                "content": summary_text,
                "jargon_map": [],
                "action_cards": action_cards,
                "intent": "NOTE_EXPLANATION",
                "suggested_replies": suggested_replies,
            }).execute()
        except Exception as exc:
            log.warning("upload_note: chat_messages insert failed (non-blocking) — %s", exc)

        # ── Step 6: Build jargon_map for the summary ──────────────────────────
        jargon_map = []
        lower_summary = summary_text.lower()
        for entry in analysis.jargon_entries:
            idx = lower_summary.find(entry.term.lower())
            if idx == -1:
                continue
            jargon_map.append({
                "term": entry.term,
                "plain_english": entry.plain_english,
                "source_note_id": record_id or "",
                "source_sentence": entry.term,
                "char_offset_start": idx,
                "char_offset_end": idx + len(entry.term),
            })

        log.info("upload_note: complete — returning response")
        return {
            "message": summary_text,
            "jargon_map": jargon_map,
            "action_cards": action_cards,
            "suggested_replies": suggested_replies,
            "record_id": record_id,
            "journey_updates": journey_result,
        }

    except HTTPException:
        raise
    except Exception as exc:
        log.error("upload_note: unhandled error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Return all messages for a session."""
    try:
        db = get_admin_client()
        # Verify the session belongs to this user before returning messages
        session_check = (
            db.table("chat_sessions")
            .select("id")
            .eq("id", session_id)
            .eq("tenant_id", ctx.tenant_id)
            .eq("user_id", ctx.user_id)
            .limit(1)
            .execute()
        )
        if not session_check.data:
            raise HTTPException(status_code=404, detail="Session not found.")
        result = (
            db.table("chat_messages")
            .select("id, role, content, intent, jargon_map, action_cards, suggested_replies, created_at")
            .eq("session_id", session_id)
            .eq("tenant_id", ctx.tenant_id)
            .order("created_at")
            .execute()
        )
        return {"messages": result.data or []}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
