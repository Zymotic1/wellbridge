"""
Record tools — database operations for patient records.

These are callable by the brain LLM via OpenAI function calling.
Each function takes explicit tenant_id/user_id (no implicit state).
"""

import logging
from services.supabase_client import get_admin_client
from services.embedding_service import get_query_embedding

log = logging.getLogger("wellbridge.tools.records")


async def fetch_patient_records(tenant_id: str, user_id: str, query: str) -> dict:
    """
    Search the patient's records by semantic similarity (vector search)
    with keyword fallback. Returns formatted record excerpts.
    """
    db = get_admin_client()

    try:
        # Get all records for index
        index_result = (
            db.table("patient_records")
            .select("id, record_type, provider_name, note_date, content")
            .eq("tenant_id", tenant_id)
            .eq("patient_user_id", user_id)
            .order("note_date", desc=True)
            .limit(20)
            .execute()
        )
        all_records = index_result.data or []
    except Exception as exc:
        log.warning("fetch_patient_records: index query failed — %s", exc)
        return {"records": [], "error": str(exc)}

    if not all_records:
        return {"records": [], "summary": "No records on file."}

    # Try vector search first
    relevant = []
    try:
        embedding = await get_query_embedding(query)
        if embedding:
            vec_result = db.rpc(
                "match_patient_records",
                {
                    "query_embedding": embedding,
                    "match_threshold": 0.35,
                    "match_count": 8,
                    "p_tenant_id": tenant_id,
                    "p_user_id": user_id,
                },
            ).execute()
            relevant = vec_result.data or []
    except Exception:
        pass

    # Fallback to keyword matching
    if not relevant:
        keywords = set(w.lower() for w in query.split() if len(w) > 3)
        if keywords:
            scored = sorted(
                all_records,
                key=lambda r: sum(1 for k in keywords if k in (r.get("content", "") or "").lower()),
                reverse=True,
            )
            relevant = scored[:8]
        else:
            relevant = all_records[:5]

    # Format for the brain
    formatted = []
    for r in relevant:
        formatted.append({
            "record_id": r.get("id", ""),
            "type": r.get("record_type", "note"),
            "provider": r.get("provider_name", "Unknown"),
            "date": str(r.get("note_date", ""))[:10],
            "content": (r.get("content") or "")[:3000],
        })

    index_summary = ", ".join(
        f"{str(r.get('note_date', ''))[:10]} ({r.get('provider_name', '?')})"
        for r in all_records[:10]
    )

    return {
        "records": formatted,
        "total_on_file": len(all_records),
        "all_records_index": index_summary,
    }


async def list_patient_records(tenant_id: str, user_id: str) -> dict:
    """List all patient records on file (metadata only, no content)."""
    try:
        db = get_admin_client()
        result = (
            db.table("patient_records")
            .select("id, record_type, provider_name, note_date")
            .eq("tenant_id", tenant_id)
            .eq("patient_user_id", user_id)
            .order("note_date", desc=True)
            .limit(20)
            .execute()
        )
        records = result.data or []
        return {
            "records": [
                {
                    "id": r["id"],
                    "type": r.get("record_type", "note"),
                    "provider": r.get("provider_name", "Unknown"),
                    "date": str(r.get("note_date", ""))[:10],
                }
                for r in records
            ],
            "total": len(records),
        }
    except Exception as exc:
        return {"records": [], "total": 0, "error": str(exc)}


async def search_patient_notes(tenant_id: str, user_id: str, query: str) -> dict:
    """Full-text search on patient notes."""
    try:
        db = get_admin_client()
        result = db.rpc("search_patient_notes", {
            "query_text": query,
            "user_id_param": user_id,
            "limit_n": 5,
            "p_tenant_id": tenant_id,
        }).execute()
        return {"matches": result.data or []}
    except Exception as exc:
        return {"matches": [], "error": str(exc)}
