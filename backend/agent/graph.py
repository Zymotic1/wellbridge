"""
LangGraph state machine — LLM-as-Brain architecture.

The brain is ONE continuous LLM conversation with function calling.
The graph is minimal — just safety checks around the brain.

Topology:
  START → safety_precheck (regex, no LLM, < 1ms)
        → REFUSAL → refusal_node → END  (hard-coded text, HIPAA-critical)
        → SAFE → brain → validator → response_assembler → END

The brain node:
  - Receives the user's message + conversation history
  - Has access to tools: fetch_records, get_appointments, etc.
  - Decides on its own whether to call tools (via OpenAI function calling)
  - Generates the complete response with jargon notation, action cards, etc.
  - Typically 1 LLM call (no tools) or 2 calls (1 tool round-trip)

Defense-in-depth for medical advice:
  Layer 1: safety_precheck regex catches obvious advice requests
  Layer 2: brain's constitutional system prompt prohibits advice
  Layer 3: validator's guardrail regex catches advice in output
"""

from langgraph.graph import StateGraph, END

from agent.state import AgentState
from agent.nodes import safety_precheck
from agent.nodes import refusal_node
from agent.nodes import brain
from agent.nodes import validator
from agent.nodes import response_assembler


def route_after_precheck(state: AgentState) -> str:
    """Route based on safety_precheck result."""
    if state.get("is_refusal"):
        return "refusal"
    return "brain"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("safety_precheck",   safety_precheck.run)
    graph.add_node("refusal",           refusal_node.run)
    graph.add_node("brain",             brain.run)
    graph.add_node("validator",         validator.run)
    graph.add_node("response_assembler", response_assembler.run)

    graph.set_entry_point("safety_precheck")

    graph.add_conditional_edges(
        "safety_precheck",
        route_after_precheck,
        {"refusal": "refusal", "brain": "brain"},
    )

    graph.add_edge("refusal", END)
    graph.add_edge("brain", "validator")
    graph.add_edge("validator", "response_assembler")
    graph.add_edge("response_assembler", END)

    return graph


_compiled_graph = None


def compile_graph():
    """Compile once at startup, stored in app.state.agent_graph."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph
