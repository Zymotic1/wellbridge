"""
Guardrail node — post-LLM output filter.

Runs after every tool node that produces an LLM response (skipped for refusal_node,
which produces static text). Applies two checks in order:
  1. Prohibited phrase regex scan (immediate replacement with SAFE_FALLBACK)
  2. Flesch-Kincaid readability check (simplification pass if grade > 8.0)

If the prohibited phrase check fires, the jargon_map is also cleared because
the entire response is replaced and char offsets are now invalid.

All violations are logged to the guardrail_violations table for audit review.
"""

from agent.state import AgentState
from guardrails.medical_output_guard import apply_medical_guardrail
from guardrails.readability_guard import check_readability
from openai import AsyncOpenAI
from config import get_settings

settings = get_settings()

READABILITY_THRESHOLD = 8.0  # FK grade level above which we trigger simplification


async def run(state: AgentState) -> dict:
    raw = state.get("raw_response") or ""

    # 1. Prohibited phrase check
    cleaned, was_modified, matched_pattern = await apply_medical_guardrail(raw)

    if was_modified:
        # Log the violation asynchronously (best-effort — don't block response)
        _log_violation(state, raw, matched_pattern)
        return {
            "final_response": cleaned,
            "jargon_map": [],    # Char offsets are invalid after full replacement
        }

    # 2. Readability check
    grade_level = check_readability(cleaned)
    if grade_level > READABILITY_THRESHOLD:
        simplified = await _simplify_text(cleaned)
        # Jargon offsets may have shifted after rewrite — clear them to avoid errors
        return {
            "final_response": simplified,
            "jargon_map": [],
        }

    return {
        "final_response": cleaned,
        "jargon_map": state.get("jargon_map", []),
    }


async def _simplify_text(text: str) -> str:
    """Rewrite at 6th-grade level without changing the information."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    result = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Rewrite the following text at a 6th-grade reading level. "
                    "Use shorter sentences and simpler words. "
                    "Do not add new information. "
                    "Do not give medical advice or recommendations. "
                    "Preserve all facts exactly."
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.2,
        max_tokens=800,
    )
    return result.choices[0].message.content or text


def _log_violation(state: AgentState, raw_response: str, pattern: str) -> None:
    """
    Best-effort async violation logging. Import here to avoid circular deps.
    Failures in logging should never block the user response.
    """
    try:
        from services.supabase_client import get_admin_client
        db = get_admin_client()
        db.table("guardrail_violations").insert({
            "tenant_id": state["tenant_id"],
            "user_id": state["user_id"],
            "session_id": state.get("session_id"),
            "raw_response": raw_response[:2000],  # Truncate for storage
            "pattern_matched": pattern,
        }).execute()
    except Exception:
        pass  # Never let logging block user response
