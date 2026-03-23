"""
LangGraph state machine — the core of the WellBridge agentic brain.

Phase 2 Topology (Multi-Agent Supervisor):
  START → emotional_assessor (always — read emotional state + extract facts)
        → safety_gate        (classify intent; MEDICAL_ADVICE → refusal)
          → MEDICAL_ADVICE   → refusal_node → END  (static text, NO LLM)
          → ALL OTHER INTENTS → supervisor (LLM-based multi-agent orchestrator)
        → supervisor
          (internal loop: dispatches 1+ specialist nodes, collects agent_outputs)
        → response_synthesizer (merges multi-agent outputs into single response)
        → validator            (enhanced guardrail + citation cross-check)
        → response_assembler   (generates suggested_replies)
        → END

CRITICAL SAFETY PROPERTIES (unchanged from Phase 1):
  1. MEDICAL_ADVICE is caught by safety_gate BEFORE the Supervisor.
     The Supervisor CANNOT override this — refusal_node is not in its
     available agents list.
  2. refusal_node NEVER calls the LLM. Static Python strings only.
  3. All LLM-generated outputs pass through the Validator (enhanced guardrail).
  4. emotional_assessor runs first every turn.
  5. Specialist nodes are called as functions inside the Supervisor loop,
     not as separate LangGraph nodes. This enables multi-agent composition.
"""

from langgraph.graph import StateGraph, END

from agent.state import AgentState, IntentType
from agent.nodes import emotional_assessor
from agent.nodes import safety_gate
from agent.nodes import refusal_node
from agent.nodes import supervisor
from agent.nodes import response_synthesizer
from agent.nodes import validator
from agent.nodes import response_assembler


# ---------------------------------------------------------------------------
# Conditional edge: safety gate routing
# ---------------------------------------------------------------------------

def route_safety_gate(state: AgentState) -> str:
    """
    Called after safety_gate. Routes MEDICAL_ADVICE to refusal (hard gate),
    everything else to the Supervisor for LLM-based multi-agent routing.

    Low-confidence MEDICAL_ADVICE with confidence < 0.70 also goes to refusal
    if the intent is specifically MEDICAL_ADVICE.
    """
    intent: IntentType | None = state.get("intent")

    if intent == "MEDICAL_ADVICE":
        return "refusal"

    # Low confidence on a non-safe intent → refusal
    confidence: float = state.get("confidence", 0.0)
    safe_low_confidence = {
        "GENERAL", "CARE_NAVIGATION", "RECORD_COLLECTION",
        "RECORD_LOOKUP", "NOTE_EXPLANATION",
        "PRE_VISIT_PREP", "SCHEDULING", "JARGON_EXPLAIN",
    }
    if confidence < 0.70 and intent not in safe_low_confidence:
        return "refusal"

    return "supervisor"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Register nodes in the new topology
    graph.add_node("emotional_assessor",    emotional_assessor.run)
    graph.add_node("safety_gate",           safety_gate.run)
    graph.add_node("refusal",               refusal_node.run)
    graph.add_node("supervisor",            supervisor.run)
    graph.add_node("response_synthesizer",  response_synthesizer.run)
    graph.add_node("validator",             validator.run)
    graph.add_node("response_assembler",    response_assembler.run)

    # Entry: emotional assessment → safety gate
    graph.set_entry_point("emotional_assessor")
    graph.add_edge("emotional_assessor", "safety_gate")

    # Safety gate: MEDICAL_ADVICE → refusal (hard), everything else → supervisor
    graph.add_conditional_edges(
        "safety_gate",
        route_safety_gate,
        {
            "refusal":    "refusal",
            "supervisor": "supervisor",
        },
    )

    # Refusal → END (bypasses everything; text is pre-approved static)
    graph.add_edge("refusal", END)

    # Supervisor → synthesizer → validator → assembler → END
    graph.add_edge("supervisor", "response_synthesizer")
    graph.add_edge("response_synthesizer", "validator")
    graph.add_edge("validator", "response_assembler")
    graph.add_edge("response_assembler", END)

    return graph


# ---------------------------------------------------------------------------
# Singleton compiled graph (thread-safe; compiled once at startup)
# ---------------------------------------------------------------------------

_compiled_graph = None


def compile_graph():
    """
    Compile the LangGraph state machine. Called once at application startup
    and stored in app.state.agent_graph for reuse across requests.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph
