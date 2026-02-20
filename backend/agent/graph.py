"""
LangGraph state machine — the core of the WellBridge agentic brain.

Graph topology:
  START → emotional_assessor (always — read emotional state + extract facts)
        → intent_classifier  (history-aware routing)
          → MEDICAL_ADVICE    → refusal_node    → END  (static text, NO LLM)
          → NOTE_EXPLANATION  → note_explainer  → guardrail → response_assembler → END
          → CARE_NAVIGATION   → care_navigator  → guardrail → response_assembler → END
          → RECORD_COLLECTION → record_collector → guardrail → response_assembler → END
          → SCHEDULING        → calendar_tool   → guardrail → response_assembler → END
          → RECORD_LOOKUP     → record_lookup   → guardrail → response_assembler → END
          → JARGON_EXPLAIN    → jargon_explainer → guardrail → response_assembler → END
          → PRE_VISIT_PREP    → pre_visit_prep  → guardrail → response_assembler → END
          → GENERAL           → note_summarizer → guardrail → response_assembler → END

NOTE_EXPLANATION vs MEDICAL_ADVICE:
  NOTE_EXPLANATION: "I don't understand what my doctor told me" — translates
    documented notes and explains medications using publicly available info.
  MEDICAL_ADVICE: "What should I do about X?" / "Should I take X?" — any
    request for new prescriptive guidance. Always refused, no LLM involved.

CRITICAL SAFETY PROPERTIES:
  1. MEDICAL_ADVICE routes to refusal_node, which NEVER calls the LLM.
     The LLM is out of the loop from that point forward.
  2. All LLM-generated outputs pass through guardrail_node before reaching
     response_assembler. refusal_node output is pre-approved static text
     and bypasses the guardrail.
  3. No node has access to "general knowledge" — all answers come from
     explicitly fetched tool data (Supabase, Calendar, FDA APIs).
  4. emotional_assessor runs first every turn so downstream nodes always
     have emotional_state and care_stage available.
"""

from langgraph.graph import StateGraph, END

from agent.state import AgentState, IntentType
from agent.nodes import intent_classifier
from agent.nodes import emotional_assessor
from agent.nodes import refusal_node
from agent.nodes import care_navigator
from agent.nodes import record_collector
from agent.nodes import record_lookup
from agent.nodes import note_summarizer
from agent.nodes import note_explainer
from agent.nodes import jargon_explainer
from agent.nodes import calendar_tool
from agent.nodes import medication_info
from agent.nodes import pre_visit_prep
from agent.nodes import guardrail_node
from agent.nodes import response_assembler

# ---------------------------------------------------------------------------
# Conditional edge functions
# ---------------------------------------------------------------------------

def route_by_intent(state: AgentState) -> str:
    """
    Called after intent_classifier. Returns the next node name.
    MEDICAL_ADVICE is always routed to refusal — no way to bypass this.
    When confidence is low (and not a clearly safe intent), defaults to refusal.
    """
    intent: IntentType | None = state.get("intent")
    confidence: float = state.get("confidence", 0.0)

    # Safe intents can proceed even at lower confidence.
    # PRE_VISIT_PREP and SCHEDULING are explicitly safe — they never give advice,
    # so we should not refuse them just because the classifier is uncertain.
    safe_low_confidence = {
        "GENERAL", "CARE_NAVIGATION", "RECORD_COLLECTION",
        "RECORD_LOOKUP", "NOTE_EXPLANATION",
        "PRE_VISIT_PREP", "SCHEDULING", "JARGON_EXPLAIN",
    }

    if confidence < 0.70 and intent not in safe_low_confidence:
        return "refusal"

    routing_map: dict[str | None, str] = {
        "MEDICAL_ADVICE":    "refusal",
        "NOTE_EXPLANATION":  "note_explainer",  # New: explain what doctor told them
        "CARE_NAVIGATION":   "care_navigator",
        "RECORD_COLLECTION": "record_collector",
        "SCHEDULING":        "calendar_tool",
        "RECORD_LOOKUP":     "record_lookup",
        "JARGON_EXPLAIN":    "jargon_explainer",
        "PRE_VISIT_PREP":    "pre_visit_prep",
        "GENERAL":           "note_summarizer",
        None:                "care_navigator",  # Classification failure → ask to clarify
    }
    return routing_map.get(intent, "care_navigator")


def after_tool_node(state: AgentState) -> str:
    """
    Called after any tool node (except refusal).
    Routes to guardrail if there's a raw_response to check,
    or to response_assembler if the tool already produced a final response.
    """
    if state.get("raw_response") is not None:
        return "guardrail"
    # Tool produced a tool_error — assemble a safe error response
    return "response_assembler"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("emotional_assessor", emotional_assessor.run)
    graph.add_node("intent_classifier",  intent_classifier.run)
    graph.add_node("refusal",            refusal_node.run)
    graph.add_node("care_navigator",     care_navigator.run)
    graph.add_node("record_collector",   record_collector.run)
    graph.add_node("record_lookup",      record_lookup.run)
    graph.add_node("note_summarizer",    note_summarizer.run)
    graph.add_node("note_explainer",     note_explainer.run)
    graph.add_node("jargon_explainer",   jargon_explainer.run)
    graph.add_node("calendar_tool",      calendar_tool.run)
    graph.add_node("medication_info",    medication_info.run)
    graph.add_node("pre_visit_prep",     pre_visit_prep.run)
    graph.add_node("guardrail",          guardrail_node.run)
    graph.add_node("response_assembler", response_assembler.run)

    # Entry point: always assess emotional state first
    graph.set_entry_point("emotional_assessor")
    graph.add_edge("emotional_assessor", "intent_classifier")

    # Intent router — the critical safety branch
    graph.add_conditional_edges(
        "intent_classifier",
        route_by_intent,
        {
            "refusal":          "refusal",
            "note_explainer":   "note_explainer",
            "care_navigator":   "care_navigator",
            "record_collector": "record_collector",
            "record_lookup":    "record_lookup",
            "note_summarizer":  "note_summarizer",
            "jargon_explainer": "jargon_explainer",
            "calendar_tool":    "calendar_tool",
            "pre_visit_prep":   "pre_visit_prep",
        },
    )

    # MEDICAL_ADVICE path: refusal → END (bypasses guardrail; text is static)
    graph.add_edge("refusal", END)

    # All other tool nodes → conditional → guardrail OR response_assembler
    tool_nodes = [
        "care_navigator", "record_collector",
        "record_lookup", "note_summarizer", "note_explainer",
        "jargon_explainer", "calendar_tool", "medication_info", "pre_visit_prep",
    ]
    for node_name in tool_nodes:
        graph.add_conditional_edges(
            node_name,
            after_tool_node,
            {"guardrail": "guardrail", "response_assembler": "response_assembler"},
        )

    # Guardrail → response_assembler (always; guardrail writes final_response)
    graph.add_edge("guardrail", "response_assembler")
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
