"""
Refusal node — handles MEDICAL_ADVICE intent.

HIPAA COMPLIANCE CRITICAL: This node NEVER calls the LLM.
The refusal message is a hard-coded Python string. The LLM was involved
only in intent_classifier.py to route the message; it is now out of the loop.

This means:
  - The refusal text cannot be manipulated by prompt injection
  - The refusal text cannot hallucinate or drift
  - The refusal works even if the OpenAI API is down

After refusing, this node fetches documented facts from the patient's own
records (via Supabase RLS-scoped query) to show alongside the refusal.
This makes the refusal helpful while remaining strictly factual.
"""

from agent.state import AgentState
from services.supabase_client import get_admin_client

REFUSAL_TEMPLATE = (
    "I'm not able to give medical advice, diagnoses, or treatment recommendations. "
    "For medical concerns, please contact your care team directly.\n\n"
    "I found these notes from your care team that may be relevant:"
)

NO_RECORDS_TEMPLATE = (
    "I'm not able to give medical advice, diagnoses, or treatment recommendations. "
    "Please contact your care team directly for medical questions."
)


async def run(state: AgentState) -> dict:
    """
    Hard-coded refusal. The LLM is NOT invoked here.

    Fetches up to 3 relevant excerpts from the patient's clinical notes
    and presents them as documented facts alongside the refusal.
    """
    tenant_id: str = state["tenant_id"]
    user_id: str = state["user_id"]
    user_query: str = state["messages"][-1].content
    context_facts: list[str] = []

    try:
        # Admin client — p_tenant_id passed explicitly so the RPC can filter
        # correctly without relying on session variables.
        db = get_admin_client()

        # Full-text search on the patient's own records
        result = db.rpc("search_patient_notes", {
            "query_text": user_query,
            "user_id_param": user_id,
            "limit_n": 3,
            "p_tenant_id": tenant_id,
        }).execute()

        for row in (result.data or []):
            date_str = str(row.get("note_date", ""))[:10]
            provider = row.get("provider_name", "Your care team")
            excerpt = row.get("relevant_excerpt", "").strip()
            if excerpt:
                context_facts.append(f"{provider} ({date_str}): {excerpt}")

    except Exception:
        # If the DB call fails, still return a safe refusal — never propagate the error
        context_facts = []

    if context_facts:
        bullets = "\n".join(f"  \u2022 {fact}" for fact in context_facts)
        final = f"{REFUSAL_TEMPLATE}\n\n{bullets}"
    else:
        final = NO_RECORDS_TEMPLATE

    return {
        "final_response": final,
        "refusal_context_facts": context_facts,
        "jargon_map": [],
        "raw_response": None,  # No LLM output to audit
    }
