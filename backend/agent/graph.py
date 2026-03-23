"""
LangGraph state machine — the core of the WellBridge agentic brain.

Optimized topology with LLM-driven information source routing:
  START → triage (1 LLM call: emotion + intent + information_source)
        → MEDICAL_ADVICE → refusal → END
        → public_knowledge → public_knowledge node → validator → assembler → END
        → High-confidence single intent → fast_dispatch → specialist → ...
        → Complex/ambiguous → supervisor → specialist(s) → ...
        → ... → response_synthesizer → validator → response_assembler → END

The triage LLM determines WHAT KIND of information the user needs:
  public_knowledge  — General medical knowledge (FDA info, conditions, procedures)
  patient_records   — The user's own uploaded medical documents
  conversation      — Emotional support, logistics, app usage
  refuse            — Medical advice request → refusal

This eliminates brittle regex patterns — the LLM reasons about what
information source is appropriate for each question.
"""

from langgraph.graph import StateGraph, END

from agent.state import AgentState, IntentType
from agent.nodes import triage
from agent.nodes import refusal_node
from agent.nodes import public_knowledge
from agent.nodes import supervisor
from agent.nodes import response_synthesizer
from agent.nodes import validator
from agent.nodes import response_assembler


# ---------------------------------------------------------------------------
# Fast dispatch — direct single-agent routing without supervisor LLM call
# ---------------------------------------------------------------------------

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
    Skip the supervisor — directly invoke the specialist agent based on
    the triage intent. Used for high-confidence single-intent messages.
    """
    intent = state.get("intent", "GENERAL")
    agent_fn = _FAST_ROUTE_MAP.get(intent, care_navigator.run)

    result = await agent_fn(state)

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
        "supervisor_reasoning": [f"fast_dispatch: {intent}"],
    }


async def public_knowledge_dispatch(state: AgentState) -> dict:
    """
    Route public knowledge questions directly to the public_knowledge node.
    No supervisor needed — the triage already determined the info source.
    """
    result = await public_knowledge.run(state)

    from agent.state import AgentOutput
    ao = AgentOutput(
        agent_name="public_knowledge",
        raw_response=result.get("raw_response", ""),
        jargon_entries=result.get("jargon_map", []),
        citations=[],
        records_used=[],
        action_cards=result.get("action_cards", []),
    )

    return {
        "agent_outputs": [ao],
        "supervisor_iterations": 0,
        "supervisor_reasoning": ["public_knowledge: general medical question, no records needed"],
    }


# ---------------------------------------------------------------------------
# Conditional edge: four-way routing after triage
# ---------------------------------------------------------------------------

FAST_PATH_CONFIDENCE = 0.85


def route_after_triage(state: AgentState) -> str:
    """
    Four-way routing based on triage output:
      1. refuse / MEDICAL_ADVICE → refusal (hard safety gate)
      2. public_knowledge → public_knowledge_dispatch (no records needed)
      3. High-confidence single intent → fast_dispatch (skip supervisor)
      4. Complex/ambiguous → supervisor (LLM multi-agent routing)
    """
    intent: IntentType | None = state.get("intent")
    confidence: float = state.get("confidence", 0.0)
    info_source: str = state.get("information_source", "conversation")

    # Safety gate: MEDICAL_ADVICE or refuse → always refused
    if intent == "MEDICAL_ADVICE" or info_source == "refuse":
        return "refusal"

    # Low confidence on non-safe intent → refusal
    safe_low_confidence = {
        "GENERAL", "CARE_NAVIGATION", "RECORD_COLLECTION",
        "RECORD_LOOKUP", "NOTE_EXPLANATION",
        "PRE_VISIT_PREP", "SCHEDULING", "JARGON_EXPLAIN",
    }
    if confidence < 0.70 and intent not in safe_low_confidence:
        return "refusal"

    # Public knowledge: general medical questions answered without records
    if info_source == "public_knowledge":
        return "public_knowledge"

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
    graph.add_node("public_knowledge",      public_knowledge_dispatch)
    graph.add_node("fast_dispatch",         fast_dispatch)
    graph.add_node("supervisor",            supervisor.run)
    graph.add_node("response_synthesizer",  response_synthesizer.run)
    graph.add_node("validator",             validator.run)
    graph.add_node("response_assembler",    response_assembler.run)

    # Entry
    graph.set_entry_point("triage")

    # Four-way routing after triage
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "refusal":          "refusal",
            "public_knowledge": "public_knowledge",
            "fast_dispatch":    "fast_dispatch",
            "supervisor":       "supervisor",
        },
    )

    # Refusal → END
    graph.add_edge("refusal", END)

    # All other paths → synthesizer → validator → assembler → END
    graph.add_edge("public_knowledge", "response_synthesizer")
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
