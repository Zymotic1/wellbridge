"""
Brain node — the single LLM conversation that powers WellBridge.

This replaces ALL specialist nodes. Instead of routing to isolated nodes
that each make their own LLM call, the brain is ONE continuous conversation
with the LLM that uses function calling to access patient data when needed.

Flow:
  1. Build messages: system prompt + conversation history + user message
  2. Call the LLM with tool definitions
  3. If the LLM wants to call tools → execute them, feed results back
  4. LLM generates the final response with full context
  5. Parse response for jargon, action cards, suggested replies

This is typically 1 LLM round-trip for general questions (no tools needed)
or 2 round-trips for record-dependent questions (1 tool call + final response).
"""

import json
import re
import logging

from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, JargonMapping, ActionCard
from agent.brain_prompt import BRAIN_SYSTEM
from agent.tools.tool_definitions import TOOL_DEFINITIONS
from agent.tools.record_tools import fetch_patient_records, list_patient_records, search_patient_notes
from agent.tools.appointment_tools import get_appointments
from services.openai_client import get_openai_client
from config import get_settings

log = logging.getLogger("wellbridge.brain")
settings = get_settings()

MAX_TOOL_ITERATIONS = 5  # Safety cap on tool-calling loops

# Tool dispatcher — maps function names to actual implementations
_TOOL_DISPATCH = {
    "fetch_patient_records": fetch_patient_records,
    "list_patient_records": list_patient_records,
    "get_appointments": get_appointments,
}


async def run(state: AgentState) -> dict:
    """
    The brain: one LLM conversation with function calling.
    """
    client = get_openai_client()

    # ── Build conversation messages for the LLM ─────────────────────────────
    messages = [{"role": "system", "content": BRAIN_SYSTEM}]

    # Add conversation history (last 10 messages)
    for msg in state.get("messages", [])[:-1][-10:]:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content[:500]})

    # Current user message
    user_message = state["messages"][-1].content
    messages.append({"role": "user", "content": user_message})

    # ── Function calling loop ────────────────────────────────────────────────
    tool_calls_log = []
    collected_records = []
    collected_appointments = []

    tenant_id = state["tenant_id"]
    user_id = state["user_id"]

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.3,
                max_completion_tokens=3000,
            )
        except Exception as exc:
            log.error("brain: LLM call failed at iteration %d — %s", iteration, exc)
            return _error_fallback(str(exc))

        choice = response.choices[0]

        # LLM is done generating — extract the response
        if choice.finish_reason == "stop" or choice.finish_reason == "length":
            raw_text = choice.message.content or ""
            break

        # LLM wants to call tools
        if choice.message.tool_calls:
            # Add the assistant's tool-calling message to context
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                log.info("brain: tool_call=%s args=%s", fn_name, fn_args)
                tool_calls_log.append({"tool": fn_name, "args": fn_args})

                # Execute the tool
                result = await _execute_tool(fn_name, fn_args, tenant_id, user_id)

                # Collect records/appointments for state
                if fn_name == "fetch_patient_records" and "records" in result:
                    collected_records = result.get("records", [])
                elif fn_name == "get_appointments" and "appointments" in result:
                    collected_appointments = result.get("appointments", [])

                # Feed result back to LLM
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, default=str),
                })

            continue  # Next iteration — LLM will process tool results

        # Unexpected finish reason — extract whatever content exists
        raw_text = choice.message.content or ""
        break
    else:
        # Exhausted iterations — use whatever we have
        raw_text = choice.message.content or "" if 'choice' in dir() else ""

    if not raw_text.strip():
        return _error_fallback("Empty response from brain")

    # ── Parse the response ───────────────────────────────────────────────────
    jargon_map = _extract_jargon(raw_text)
    action_cards = _extract_action_cards(raw_text)
    suggested_replies = _extract_suggested_replies(raw_text)
    clean_text = _strip_markers(raw_text)

    # Recompute jargon offsets against clean text
    jargon_map = _recompute_offsets(jargon_map, clean_text)

    # Determine intent for logging (infer from what happened)
    intent = _infer_intent(tool_calls_log, user_message)

    return {
        "raw_response": clean_text,
        "jargon_map": jargon_map,
        "action_cards": action_cards,
        "suggested_replies": suggested_replies,
        "records": collected_records,
        "appointments": collected_appointments,
        "intent": intent,
        "tool_calls_log": tool_calls_log,
    }


async def _execute_tool(fn_name: str, fn_args: dict, tenant_id: str, user_id: str) -> dict:
    """Execute a tool call and return the result."""
    if fn_name not in _TOOL_DISPATCH:
        return {"error": f"Unknown tool: {fn_name}"}

    try:
        fn = _TOOL_DISPATCH[fn_name]
        # All tools take tenant_id and user_id as first args
        if fn_name == "fetch_patient_records":
            return await fn(tenant_id, user_id, fn_args.get("query", ""))
        elif fn_name == "list_patient_records":
            return await fn(tenant_id, user_id)
        elif fn_name == "get_appointments":
            return await fn(tenant_id, user_id)
        else:
            return {"error": f"Unhandled tool: {fn_name}"}
    except Exception as exc:
        log.warning("brain: tool %s failed — %s", fn_name, exc)
        return {"error": str(exc)}


def _error_fallback(error_msg: str) -> dict:
    """Minimal fallback when the brain completely fails."""
    log.error("brain: complete failure — %s", error_msg)
    return {
        "raw_response": (
            "I'd like to help with that. Could you tell me a bit more about "
            "what you're looking for? I can explain medical information, help "
            "you understand your records, or help you prepare for a visit."
        ),
        "jargon_map": [],
        "action_cards": [],
        "suggested_replies": [],
        "intent": "GENERAL",
        "tool_calls_log": [],
    }


# ── Response parsers ─────────────────────────────────────────────────────────

_JARGON_PATTERN = re.compile(r'\[JARGON:\s*([^|]+?)\s*\|\s*([^\]]+?)\s*\]')
_ACTION_PATTERN = re.compile(r'<!--\s*ACTION:\s*(\w+)\s*-->')
_REPLIES_PATTERN = re.compile(r'<!--\s*REPLIES:\s*(\[.*?\])\s*-->', re.DOTALL)


def _extract_jargon(text: str) -> list[dict]:
    """Extract [JARGON: term | plain_english] markers from the response."""
    entries = []
    for match in _JARGON_PATTERN.finditer(text):
        entries.append({
            "term": match.group(1).strip(),
            "plain_english": match.group(2).strip(),
            "source_note_id": "",
            "source_sentence": "",
        })
    return entries


def _extract_action_cards(text: str) -> list[ActionCard]:
    """Extract <!-- ACTION: type --> markers from the response."""
    cards = []
    for match in _ACTION_PATTERN.finditer(text):
        action_type = match.group(1)
        if action_type == "upload_records":
            cards.append(ActionCard(
                id="upload_records",
                type="upload",
                label="Upload a document",
                description="Share your clinical notes, letters, or test results",
                payload={},
            ))
    return cards


def _extract_suggested_replies(text: str) -> list[str]:
    """Extract <!-- REPLIES: [...] --> from the response."""
    match = _REPLIES_PATTERN.search(text)
    if match:
        try:
            replies = json.loads(match.group(1))
            if isinstance(replies, list):
                return [str(r).strip() for r in replies if str(r).strip()][:4]
        except json.JSONDecodeError:
            pass
    return []


def _strip_markers(text: str) -> str:
    """Remove [JARGON], <!-- ACTION -->, and <!-- REPLIES --> markers from display text."""
    # Replace [JARGON: term | plain] with just "term"
    text = _JARGON_PATTERN.sub(r'\1', text)
    # Remove action markers
    text = _ACTION_PATTERN.sub('', text)
    # Remove replies markers
    text = _REPLIES_PATTERN.sub('', text)
    # Clean up extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


def _recompute_offsets(jargon_entries: list[dict], clean_text: str) -> list[JargonMapping]:
    """Recompute char offsets against the cleaned text."""
    result = []
    lower_text = clean_text.lower()
    seen = set()

    for entry in jargon_entries:
        term = entry.get("term", "")
        if not term or term.lower() in seen:
            continue
        seen.add(term.lower())

        idx = lower_text.find(term.lower())
        if idx == -1:
            continue

        result.append(JargonMapping(
            term=term,
            plain_english=entry.get("plain_english", ""),
            source_note_id=entry.get("source_note_id", ""),
            source_sentence=entry.get("source_sentence", ""),
            char_offset_start=idx,
            char_offset_end=idx + len(term),
        ))

    return result


def _infer_intent(tool_calls: list[dict], user_message: str) -> str:
    """Infer the intent for logging/analytics based on what happened."""
    tool_names = {tc["tool"] for tc in tool_calls}

    if "fetch_patient_records" in tool_names:
        return "NOTE_EXPLANATION"
    if "get_appointments" in tool_names:
        return "SCHEDULING"
    if "list_patient_records" in tool_names:
        return "RECORD_LOOKUP"

    # No tools called — likely general knowledge or care navigation
    msg_lower = user_message.lower()
    if any(w in msg_lower for w in ["scared", "worried", "anxious", "nervous", "feel"]):
        return "CARE_NAVIGATION"
    if any(w in msg_lower for w in ["what is", "what are", "side effect", "how does"]):
        return "GENERAL"

    return "GENERAL"
