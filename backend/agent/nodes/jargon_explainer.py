"""
Jargon explainer node — explains a single medical term in plain English.

Fetches the patient's records to find where the term appears (providing the
source sentence context), then explains the term using the JARGON_EXPLAINER_SYSTEM
prompt. Never speculates about what the term means for the patient's health.
"""

from openai import AsyncOpenAI

from agent.state import AgentState
from agent.prompts import JARGON_EXPLAINER_SYSTEM
from services.supabase_client import get_scoped_client
from middleware.tenant import TenantContext
from config import get_settings

settings = get_settings()


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_query: str = state["messages"][-1].content

    ctx = TenantContext(
        tenant_id=state["tenant_id"],
        user_id=state["user_id"],
        role=state["role"],
    )

    # Find the term in the patient's records for source context
    source_context = ""
    try:
        db = get_scoped_client(ctx)
        result = db.rpc("search_patient_notes", {
            "query_text": user_query,
            "user_id_param": ctx.user_id,
            "limit_n": 2,
        }).execute()

        rows = result.data or []
        if rows:
            source_context = "\n".join(
                f"From {r.get('provider_name','your care team')} "
                f"({str(r.get('note_date',''))[:10]}): \"{r.get('relevant_excerpt','')}\""
                for r in rows
            )
    except Exception:
        source_context = "(Could not retrieve source context from your records.)"

    prompt_content = f"Question: {user_query}\n\nFrom the patient's records:\n{source_context}"

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": JARGON_EXPLAINER_SYSTEM},
                {"role": "user", "content": prompt_content},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        raw = result.choices[0].message.content or ""
        return {"raw_response": raw, "jargon_map": []}
    except Exception as exc:
        return {
            "tool_error": str(exc),
            "raw_response": "I had trouble looking that up. Please try again.",
            "jargon_map": [],
        }
