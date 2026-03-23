"""
LangGraph state machine — the core of the WellBridge agentic brain.

Optimized topology (latency-focused):
  START → triage (single LLM call: emotional assessment + intent classification)
        → MEDICAL_ADVICE → refusal_node → END  (static text, NO LLM)
        → High-confidence single intent → fast_dispatch (skip supervisor, direct to specialist)
        → Complex/multi-concern → supervisor (LLM-based multi-agent orchestrator)
        → response_synthesizer → validator → response_assembler → END

LATENCY CHAIN (simple message, fast path):
  1. triage (1 LLM call, gpt-4o-mini) — emotional state + intent + confidence
  2. fast_dispatch → specialist node (1 LLM call, gpt-5.2) — the actual response
  3. response_synthesizer (passthrough, no LLM)
  4. validator (regex + readability, no LLM unless readability fails)
  5. response_assembler (static suggestions, no LLM)
  Total: 2 LLM calls for simple messages (down from 5)

LATENCY CHAIN (complex message, supervisor path):
  1. triage (1 LLM call)
  2. supervisor (1+ LLM calls) → dispatches multiple specialists
  3. response_synthesizer (1 LLM call if multi-agent merge needed)
  4. validator + response_assembler (no LLM)
  Total: 3-5 LLM calls for complex multi-concern messages

CRITICAL SAFETY PROPERTIES (unchanged):
  1. MEDICAL_ADVICE routes to refusal_node, which NEVER calls the LLM.
  2. refusal_node is NOT in the supervisor's available agents list.
  3. All LLM-generated outputs pass through the validator.
  4. Triage runs before any specialist — emotional state always available.
"""

from langgraph.graph import StateGraph, END

from agent.state import AgentState, IntentType
from agent.nodes import triage
from agent.nodes import refusal_node
from agent.nodes import supervisor
from agent.nodes import response_synthesizer
from agent.nodes import validator
from agent.nodes import response_assembler


# ---------------------------------------------------------------------------
# Fast dispatch — direct single-agent routing without supervisor LLM call
# ---------------------------------------------------------------------------

# Import specialist run() functions for fast-path dispatch
from agent.nodes import (
    care_navigator, record_collector, record_lookup,
    note_summarizer, note_explainer, jargon_explainer,
    calendar_tool, pre_visit_prep,
)

_FAST_ROUTE_MAP = {
    "NOTE_EXPLANATION":  note_explainer.run,
    "CARE_NAVIGATION":   care_navigator.run,
    "RECORD_COLLECTION": record_collector.run,
    "SCHEDULING":        calendar_tool.run,
    "RECORD_LOOKUP":     record_lookup.run,
    "JARGON_EXPLAIN":    jargon_explainer.run,
    "PRE_VISIT_PREP":    pre_visit_prep.run,
    "GENERAL":           note_summarizer.run,
}


async def fast_dispatch(state: AgentState) -> dict:
    """
    Skip the supervisor LLM call — directly invoke the specialist agent
    based on the triage intent. Used for high-confidence single-intent messages.
    """
    intent = state.get("intent", "GENERAL")
    agent_fn = _FAST_ROUTE_MAP.get(intent, care_navigator.run)

    result = await agent_fn(state)

    # Package as a single agent_output for the synthesizer
    from agent.state import AgentOutput
    agent_name = {v: k for k, v in _FAST_ROUTE_MAP.items()}.get(agent_fn, "care_navigator")
    ao = AgentOutput(
        agent_name=agent_name.lower(),
        raw_response=result.get("raw_response", ""),
        jargon_entries=result.get("jargon_map", []),
        citations=result.get("citations", []),
        records_used=[r.get("id", "") for r in result.get("records", []) if isinstance(r, dict)],
        action_cards=result.get("action_cards", []),
    )

    return {
        "agent_outputs": [ao],
        "records": result.get("records", state.get("records", [])),
        "appointments": result.get("appointments", state.get("appointments", [])),
        "supervisor_iterations": 0,
        "supervisor_reasoning": ["fast_dispatch: high-confidence single intent, skipped supervisor"],
    }


# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

FAST_PATH_CONFIDENCE = 0.85  # Threshold for skipping supervisor


def route_after_triage(state: AgentState) -> str:
    """
    Three-way routing after triage:
      1. MEDICAL_ADVICE → refusal (hard safety gate)
      2. High-confidence single intent → fast_dispatch (skip supervisor)
      3. Everything else → supervisor (LLM-based multi-agent routing)
    """
    intent: IntentType | None = state.get("intent")
    confidence: float = state.get("confidence", 0.0)

    # Safety gate: MEDICAL_ADVICE always refused
    if intent == "MEDICAL_ADVICE":
        return "refusal"

    # Low confidence on non-safe intent → refusal
    safe_low_confidence = {
        "GENERAL", "CARE_NAVIGATION", "RECORD_COLLECTION",
        "RECORD_LOOKUP", "NOTE_EXPLANATION",
        "PRE_VISIT_PREP", "SCHEDULING", "JARGON_EXPLAIN",
    }
    if confidence < 0.70 and intent not in safe_low_confidence:
        return "refusal"

    # Fast path: high confidence + known single-agent intent → skip supervisor
    if confidence >= FAST_PATH_CONFIDENCE and intent in _FAST_ROUTE_MAP:
        return "fast_dispatch"

    # Complex or ambiguous → supervisor decides
    return "supervisor"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("triage",                triage.run)
    graph.add_node("refusal",               refusal_node.run)
    graph.add_node("fast_dispatch",         fast_dispatch)
    graph.add_node("supervisor",            supervisor.run)
    graph.add_node("response_synthesizer",  response_synthesizer.run)
    graph.add_node("validator",             validator.run)
    graph.add_node("response_assembler",    response_assembler.run)

    # Entry: single triage call (emotional assessment + intent classification)
    graph.set_entry_point("triage")

    # Three-way routing after triage
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "refusal":       "refusal",
            "fast_dispatch": "fast_dispatch",
            "supervisor":    "supervisor",
        },
    )

    # Refusal → END (bypasses everything; pre-approved static text)
    graph.add_edge("refusal", END)

    # Both fast_dispatch and supervisor → synthesizer → validator → assembler → END
    graph.add_edge("fast_dispatch", "response_synthesizer")
    graph.add_edge("supervisor", "response_synthesizer")
    graph.add_edge("response_synthesizer", "validator")
    graph.add_edge("validator", "response_assembler")
    graph.add_edge("response_assembler", END)

    return graph


# ---------------------------------------------------------------------------
# Singleton compiled graph
# ---------------------------------------------------------------------------

_compiled_graph = None


def compile_graph():
    """Compile once at startup, stored in app.state.agent_graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph
