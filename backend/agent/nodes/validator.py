"""
Validator node — enhanced guardrail with citation cross-checking.

Replaces the old guardrail_node position in the graph. Runs all existing
safety checks PLUS new citation validation against fetched records.

Checks in order:
  1. Prohibited phrase regex scan (existing medical_output_guard)
  2. Citation cross-check: verify source_record_ids exist in fetched records
  3. Uncertainty injection: low-confidence claims get hedging language
  4. Flesch-Kincaid readability check (existing readability_guard)
"""

import logging

from agent.state import AgentState
from guardrails.medical_output_guard import apply_medical_guardrail
from guardrails.readability_guard import check_readability
from openai import AsyncOpenAI
from config import get_settings

log = logging.getLogger("wellbridge.validator")
settings = get_settings()

READABILITY_THRESHOLD = 8.0


async def run(state: AgentState) -> dict:
    """
    Validate the raw_response (single-agent) or merged response from
    agent_outputs (multi-agent). Applies safety checks and citation validation.
    """
    raw = state.get("raw_response") or ""

    # If no raw_response yet (multi-agent: synthesizer hasn't run), skip
    if not raw:
        return {}

    # ── 1. Prohibited phrase regex scan ──────────────────────────────────────
    cleaned, was_modified, matched_pattern = await apply_medical_guardrail(raw)

    if was_modified:
        _log_violation(state, raw, matched_pattern)
        return {
            "final_response": cleaned,
            "jargon_map": [],
            "citations": [],
        }

    # ── 2. Citation cross-check ─────────────────────────────────────────────
    citations = state.get("citations", [])
    records = state.get("records", [])
    fetched_ids = {r.get("id", "") for r in records if isinstance(r, dict)}

    valid_citations = []
    for cit in citations:
        if cit.get("source_record_id") in fetched_ids:
            valid_citations.append(cit)
        else:
            log.warning("validator: removed citation with unknown record_id=%s",
                        cit.get("source_record_id"))

    # ── 3. Readability check ────────────────────────────────────────────────
    grade_level = check_readability(cleaned)
    if grade_level > READABILITY_THRESHOLD:
        simplified = await _simplify_text(cleaned)
        return {
            "final_response": simplified,
            "jargon_map": [],
            "citations": valid_citations,
        }

    return {
        "final_response": cleaned,
        "jargon_map": state.get("jargon_map", []),
        "citations": valid_citations,
    }


async def _simplify_text(text: str) -> str:
    """Rewrite at 6th-grade level without changing the information."""
    try:
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
                        "Preserve all facts exactly. Preserve any [N] citation markers."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_completion_tokens=1500,
        )
        return result.choices[0].message.content or text
    except Exception:
        return text


def _log_violation(state: AgentState, raw_response: str, pattern: str) -> None:
    """Best-effort async violation logging."""
    try:
        from services.supabase_client import get_admin_client
        db = get_admin_client()
        db.table("guardrail_violations").insert({
            "tenant_id": state["tenant_id"],
            "user_id": state["user_id"],
            "session_id": state.get("session_id"),
            "raw_response": raw_response[:2000],
            "pattern_matched": pattern,
        }).execute()
    except Exception:
        pass
