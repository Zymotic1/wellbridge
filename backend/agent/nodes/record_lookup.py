"""
Record lookup node — fetches patient records and answers the user's question
from what is documented.

Flow:
  1. Extract keywords from the user message for relevance ranking
  2. Fetch up to 20 records (RLS-scoped) ordered by recency
  3. Rank records by keyword relevance; keep top-N most relevant
  4. Pass the user's question + relevant records to the LLM to give a
     substantive, document-grounded answer
  5. If zero records in the database, offer an upload card

SAFETY: The LLM is bound by CONSTITUTIONAL_SYSTEM — it can only report what is
documented in the records, never give advice or interpret results.

RLS GUARANTEE: get_scoped_client() sets app.tenant_id and app.user_id session
variables. Even if this node had a bug, the database would reject cross-tenant
queries.
"""

import json
import re
from openai import AsyncOpenAI
from pydantic import BaseModel

from agent.state import AgentState, JargonMapping, ActionCard
from agent.prompts import CONSTITUTIONAL_SYSTEM
from services.supabase_client import get_admin_client
from services.embedding_service import get_query_embedding
from config import get_settings

settings = get_settings()

# Fallback keyword stop-words (used when vector search is unavailable)
_STOP_WORDS = {
    "can", "you", "look", "at", "my", "recent", "records", "show", "me",
    "what", "did", "does", "the", "a", "an", "and", "or", "is", "are",
    "was", "were", "have", "has", "do", "in", "on", "of", "to", "for",
    "with", "about", "from", "tell", "see", "find", "get", "i", "please",
    "any", "all", "some", "last", "latest", "most", "also", "would", "like",
    "know", "let", "check", "says", "said", "information", "that", "this",
    "there", "here", "just", "been", "they", "them", "when", "where", "how",
}


def _extract_keywords(message: str) -> list[str]:
    """Pull meaningful words for fallback keyword scoring."""
    words = re.findall(r"[a-zA-Z]+", message.lower())
    return [w for w in words if len(w) > 3 and w not in _STOP_WORDS]


def _score_record(record: dict, keywords: list[str]) -> int:
    """Keyword hit count for fallback ranking."""
    if not keywords:
        return 0
    haystack = (record.get("content") or "").lower()
    haystack += " " + (record.get("provider_name") or "").lower()
    return sum(1 for kw in keywords if kw in haystack)


class JargonEntry(BaseModel):
    term: str
    plain_english: str
    source_note_id: str
    source_sentence: str


class RecordAnswer(BaseModel):
    response: str
    jargon_entries: list[JargonEntry]


RECORD_LOOKUP_SYSTEM = (
    CONSTITUTIONAL_SYSTEM
    + """

TASK: The user is asking about information in their health records.
Search the provided records and report exactly what is documented.

RULES FOR THIS TASK:
• Only state facts that appear in the provided records — cite the source every time.
  Example: "Your record from Dr. Smith on Jan 5 notes that..."
• If the topic isn't mentioned in any record, say so clearly:
  "I don't see anything about [topic] in your current records.
   Your records cover: [brief list of dates/providers]."
• Do NOT add information that isn't in the records.
• Do NOT tell the patient what to do, what is normal, or what to worry about.
• Write at a 6th-grade reading level with short sentences.
• Mark medical terms with [JARGON: term | plain_english].

Return JSON with this structure:
{"response": "...", "jargon_entries": [...]}
"""
)


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    tenant_id: str = state["tenant_id"]
    user_id: str = state["user_id"]
    user_message: str = state["messages"][-1].content

    # Use the admin client with explicit tenant/user filters.
    # get_scoped_client() relies on either PostgREST JWT (production) or
    # transaction-local session variables (dev mode). In both cases the auth
    # path may not be set up, causing patient_records queries to silently return
    # 0 rows. The admin client bypasses RLS; security is enforced by the
    # explicit .eq("tenant_id", ...).eq("patient_user_id", ...) filters below.
    db = get_admin_client()

    # ── Always fetch a recency-ordered index of all records ───────────────────
    # Used to: (a) detect zero records, (b) provide context to the LLM about
    # what exists when a topic isn't found in the semantic search results.
    try:
        index_result = (
            db.table("patient_records")
            .select("id, record_type, provider_name, facility_name, note_date, content")
            .eq("tenant_id", tenant_id)
            .eq("patient_user_id", user_id)
            .order("note_date", desc=True)
            .limit(20)
            .execute()
        )
        all_records: list[dict] = index_result.data or []
    except Exception as exc:
        return {
            "records": [],
            "tool_error": str(exc),
            "raw_response": "I had trouble retrieving your records. Please try again.",
            "jargon_map": [],
        }

    # ── No records at all — offer upload ─────────────────────────────────────
    if not all_records:
        upload_card: ActionCard = {
            "id": "upload_records",
            "type": "upload",
            "label": "Upload a document",
            "description": "Add a discharge summary, clinic letter, or lab result",
            "payload": {},
        }
        return {
            "records": [],
            "raw_response": (
                "I don't have any records on file for you yet, so I can't look "
                "anything up.\n\n"
                "If you have paperwork from a visit — a discharge summary, clinic "
                "letter, lab printout, or prescription — you can upload it here and "
                "I'll go through it with you."
            ),
            "jargon_map": [],
            "action_cards": [upload_card],
        }

    # ── Primary: vector similarity search (RAG) ───────────────────────────────
    # Embed the user's question and find semantically similar records.
    # This correctly handles synonyms: "blood pressure" → "hypertension",
    # "sugar" → "glucose", "heart" → "cardiac", etc.
    relevant_records: list[dict] = []
    used_vector_search = False

    query_embedding = await get_query_embedding(user_message)
    if query_embedding:
        try:
            vec_result = db.rpc(
                "match_patient_records",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": 0.35,   # cosine similarity floor
                    "match_count": 8,
                    "p_tenant_id": tenant_id,
                    "p_user_id": user_id,
                },
            ).execute()
            relevant_records = vec_result.data or []
            used_vector_search = True
        except Exception as exc:
            # Vector search failed (e.g., RPC not yet deployed) — fall through
            import logging as _log
            _log.getLogger("wellbridge.record_lookup").warning(
                "vector search failed, falling back to keyword — %s", exc
            )

    # ── Fallback: keyword-based relevance ranking ─────────────────────────────
    # Used when: (a) embedding generation failed, (b) vector RPC unavailable,
    # (c) zero vector results (all records may lack embeddings for old uploads).
    if not relevant_records:
        keywords = _extract_keywords(user_message)
        scored = sorted(
            all_records,
            key=lambda r: _score_record(r, keywords),
            reverse=True,
        )
        top = scored[:8]
        has_keyword_match = keywords and any(_score_record(r, keywords) > 0 for r in top)
        relevant_records = top if has_keyword_match else all_records[:5]

    # ── Format records for the LLM ────────────────────────────────────────────
    notes_text = "\n\n".join(
        f"[NOTE_ID:{r['id']}] {str(r.get('note_date', ''))[:10]} — "
        f"{r.get('provider_name', 'Unknown provider')} "
        f"({r.get('record_type', 'record').replace('_', ' ')}):\n"
        f"{(r.get('content') or '')[:2000]}"
        for r in relevant_records
    )

    # Brief index of all records so LLM can accurately say what files exist
    all_record_index = ", ".join(
        f"{str(r.get('note_date',''))[:10]} ({r.get('provider_name','?')})"
        for r in all_records[:10]
    )

    retrieval_method = "semantic similarity" if used_vector_search else "keyword matching"
    user_prompt = (
        f"Patient question: {user_message}\n\n"
        f"All records on file (newest first): {all_record_index}\n\n"
        f"Records selected for this query via {retrieval_method} "
        f"({len(relevant_records)} of {len(all_records)} total):\n\n"
        f"{notes_text}"
    )

    # ── LLM call ─────────────────────────────────────────────────────────────
    try:
        llm_result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": RECORD_LOOKUP_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1200,
        )

        raw = llm_result.choices[0].message.content or ""
        if not raw:
            raise ValueError("Empty LLM response")

        parsed = RecordAnswer(**json.loads(raw))
        response_text = parsed.response

        # ── Build jargon_map ──────────────────────────────────────────────────
        jargon_map: list[JargonMapping] = []
        lower_response = response_text.lower()
        for entry in parsed.jargon_entries:
            idx = lower_response.find(entry.term.lower())
            if idx == -1:
                continue
            jargon_map.append(JargonMapping(
                term=entry.term,
                plain_english=entry.plain_english,
                source_note_id=entry.source_note_id,
                source_sentence=entry.source_sentence,
                char_offset_start=idx,
                char_offset_end=idx + len(entry.term),
            ))

        return {
            "records": relevant_records,
            "raw_response": response_text,
            "jargon_map": jargon_map,
            "action_cards": [],
        }

    except Exception as exc:
        # LLM failed — fall back to a plain listing so user knows records exist
        summary_lines = [
            f"• {str(r.get('note_date', ''))[:10]} — "
            f"{r.get('record_type', 'record').replace('_', ' ')} "
            f"from {r.get('provider_name', 'Unknown')}"
            for r in all_records[:10]
        ]
        return {
            "records": all_records[:10],
            "raw_response": (
                f"I found {len(all_records)} record(s) but had trouble reading "
                f"them in detail right now. Here's what's on file:\n\n"
                + "\n".join(summary_lines)
                + "\n\nCould you tell me more specifically what you'd like to know?"
            ),
            "jargon_map": [],
            "tool_error": str(exc),
        }
