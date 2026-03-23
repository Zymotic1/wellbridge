"""
Response synthesizer node — merges multi-agent outputs into a single response.

When the Supervisor dispatches multiple specialist agents, their outputs need
to be combined into a coherent, unified response. This node handles that merge.

Single-agent case: passes through directly (no LLM call needed).
Multi-agent case: LLM merges the outputs, preserving all jargon and citations.

Also responsible for:
  - Assigning citation indices ([1], [2], etc.)
  - Building the unified jargon_map with correct char offsets
  - Merging action_cards from all agents
"""

import json
import logging

from openai import AsyncOpenAI

from agent.state import AgentState, JargonMapping, Citation
from config import get_settings

log = logging.getLogger("wellbridge.response_synthesizer")
settings = get_settings()

SYNTHESIS_SYSTEM = """You are merging outputs from multiple WellBridge specialist agents
into a single coherent response for a patient. The response should read as one unified
message, not as separate sections pasted together.

Rules:
- Write at a 6th-grade reading level
- Use "you/your" not "the patient"
- Preserve ALL [JARGON: term | plain_english] markers exactly as they appear
- NEVER give medical advice or interpret results
- Combine overlapping information (don't repeat the same fact twice)
- Use markdown headers (##) to organize sections logically
- Keep the warm, supportive WellBridge tone throughout

Return ONLY the merged response text. No JSON wrapping."""


async def run(state: AgentState) -> dict:
    """
    Merge agent_outputs into raw_response, jargon_map, citations, and action_cards.
    """
    agent_outputs = state.get("agent_outputs", [])

    if not agent_outputs:
        # No agents produced output — error state
        return {
            "raw_response": state.get("raw_response") or
                "I'm sorry, I wasn't able to process that. Please try again.",
            "jargon_map": [],
            "action_cards": [],
            "citations": [],
        }

    # ── Single agent: pass through directly (no synthesis needed) ────────────
    if len(agent_outputs) == 1:
        ao = agent_outputs[0]
        return {
            "raw_response": ao["raw_response"],
            "jargon_map": ao.get("jargon_entries", []),
            "action_cards": ao.get("action_cards", []),
            "citations": _number_citations(ao.get("citations", [])),
        }

    # ── Multiple agents: synthesize via LLM ──────────────────────────────────
    log.info("response_synthesizer: merging %d agent outputs", len(agent_outputs))

    # Collect all inputs for synthesis
    agent_texts = []
    all_jargon = []
    all_action_cards = []
    all_citations = []

    for ao in agent_outputs:
        if ao["raw_response"]:
            agent_texts.append(f"--- From {ao['agent_name']} ---\n{ao['raw_response']}")
        all_jargon.extend(ao.get("jargon_entries", []))
        all_action_cards.extend(ao.get("action_cards", []))
        all_citations.extend(ao.get("citations", []))

    # Deduplicate action cards by id
    seen_ids = set()
    deduped_cards = []
    for card in all_action_cards:
        card_id = card.get("id", "")
        if card_id not in seen_ids:
            seen_ids.add(card_id)
            deduped_cards.append(card)

    # If only one agent actually produced text, skip the merge LLM call
    non_empty = [t for t in agent_texts if t.strip()]
    if len(non_empty) <= 1:
        merged_text = non_empty[0].split("---\n", 1)[-1] if non_empty else ""
    else:
        merged_text = await _merge_texts(non_empty)

    # Rebuild jargon_map with char offsets against the merged text
    jargon_map = _rebuild_jargon_map(merged_text, all_jargon)

    # Number citations sequentially
    numbered_citations = _number_citations(all_citations)

    return {
        "raw_response": merged_text,
        "jargon_map": jargon_map,
        "action_cards": deduped_cards,
        "citations": numbered_citations,
    }


async def _merge_texts(agent_texts: list[str]) -> str:
    """LLM call to merge multiple agent outputs into one coherent response."""
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        combined = "\n\n".join(agent_texts)

        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYNTHESIS_SYSTEM},
                {"role": "user", "content": f"Merge these agent outputs into one response:\n\n{combined}"},
            ],
            temperature=0.3,
            max_completion_tokens=3000,
        )
        return result.choices[0].message.content or combined
    except Exception as exc:
        log.warning("response_synthesizer: merge LLM failed — %s", exc)
        # Fallback: concatenate with headers
        return "\n\n".join(t.split("---\n", 1)[-1] for t in agent_texts)


def _rebuild_jargon_map(text: str, jargon_entries: list) -> list[JargonMapping]:
    """Recompute char offsets for all jargon entries against the final text."""
    jargon_map = []
    lower_text = text.lower()

    # Deduplicate by term (keep first occurrence)
    seen_terms = set()
    for entry in jargon_entries:
        term = ""
        plain = ""
        source_id = ""
        source_sent = ""

        if isinstance(entry, dict):
            term = entry.get("term", "")
            plain = entry.get("plain_english", "")
            source_id = entry.get("source_note_id", "")
            source_sent = entry.get("source_sentence", "")
        elif hasattr(entry, "term"):
            term = entry.term
            plain = getattr(entry, "plain_english", "")
            source_id = getattr(entry, "source_note_id", "")
            source_sent = getattr(entry, "source_sentence", "")

        if not term or term.lower() in seen_terms:
            continue
        seen_terms.add(term.lower())

        idx = lower_text.find(term.lower())
        if idx == -1:
            continue

        jargon_map.append(JargonMapping(
            term=term,
            plain_english=plain,
            source_note_id=source_id,
            source_sentence=source_sent,
            char_offset_start=idx,
            char_offset_end=idx + len(term),
        ))

    return jargon_map


def _number_citations(citations: list) -> list[Citation]:
    """Assign sequential [1], [2], etc. indices to citations."""
    numbered = []
    for i, cit in enumerate(citations):
        if isinstance(cit, dict):
            numbered.append(Citation(
                source_record_id=cit.get("source_record_id", ""),
                source_quote=cit.get("source_quote", ""),
                claim_text=cit.get("claim_text", ""),
                citation_index=i + 1,
                confidence=cit.get("confidence", 1.0),
            ))
    return numbered
