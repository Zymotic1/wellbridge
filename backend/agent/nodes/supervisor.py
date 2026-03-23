"""
Supervisor node — multi-agent orchestrator with LLM-based routing.

Replaces the flat intent_classifier → single_node routing with a reasoning
loop that can dispatch multiple specialist agents per turn and iterate
until confidence is sufficient.

SAFETY INVARIANT:
  MEDICAL_ADVICE is NOT in the available agents list. The safety_gate
  catches MEDICAL_ADVICE before the Supervisor runs. The Supervisor
  cannot dispatch refusal_node or override the safety gate.

DESIGN:
  The Supervisor calls specialist nodes as Python coroutines (not LangGraph
  edges). Each agent's output is collected into agent_outputs[]. After
  all dispatches for an iteration, the Supervisor re-evaluates whether
  more agents are needed. Max 3 iterations.

FALLBACK:
  If the Supervisor's LLM call fails, it falls back to the original
  route_by_intent() single-dispatch logic.
"""

import json
import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent.state import AgentState, AgentOutput
from agent.nodes import (
    care_navigator,
    record_collector,
    record_lookup,
    note_summarizer,
    note_explainer,
    jargon_explainer,
    calendar_tool,
    pre_visit_prep,
)
from config import get_settings

log = logging.getLogger("wellbridge.supervisor")
settings = get_settings()

MAX_ITERATIONS = 3

# All specialist agents the Supervisor can dispatch.
# MEDICAL_ADVICE / refusal_node is deliberately excluded.
AVAILABLE_AGENTS = {
    "note_explainer":   note_explainer.run,
    "care_navigator":   care_navigator.run,
    "record_collector": record_collector.run,
    "record_lookup":    record_lookup.run,
    "note_summarizer":  note_summarizer.run,
    "jargon_explainer": jargon_explainer.run,
    "calendar_tool":    calendar_tool.run,
    "pre_visit_prep":   pre_visit_prep.run,
}

AGENT_DESCRIPTIONS = """
Available specialist agents:

note_explainer — Translates clinical notes into plain language. Use when the user wants
  to understand what their doctor told them, or when records need explanation.

care_navigator — Empathetic journey guidance. Use when the user shares emotional news
  (diagnosis, upcoming surgery, fear) or needs to feel heard and guided.

record_collector — Helps gather documents the user mentions having. Use when the user
  says "I have a letter/report/scan" that should be uploaded.

record_lookup — Searches the user's stored records by semantic similarity. Use when
  the user asks "what do my records say about X".

note_summarizer — Summarizes all stored clinical notes into a structured overview.
  Use when the user wants a general summary of their records.

jargon_explainer — Explains a single medical term. Use when the user asks "what does
  [term] mean?".

calendar_tool — Shows upcoming appointments. Use when the user asks about their schedule.

pre_visit_prep — Generates questions for the user to ask at their next doctor visit.
  Use when the user wants to prepare for an appointment.

DISPATCH RULES:
- You may dispatch 1-3 agents per iteration.
- If the user's request spans multiple concerns (e.g., "explain my notes and help me
  prepare for tomorrow"), dispatch both relevant agents.
- If a previous agent's output reveals a gap (e.g., note mentions a test but no results
  found), dispatch record_collector or record_lookup to investigate.
- Set is_complete=true when the collected agent outputs fully address the user's request.
"""


class SupervisorDecision(BaseModel):
    agents_to_dispatch: list[str] = Field(
        description="Agent names to dispatch this iteration"
    )
    reasoning: str = Field(
        description="Brief explanation of why these agents were chosen"
    )
    is_complete: bool = Field(
        description="True if no more agents are needed after this iteration"
    )


SUPERVISOR_SYSTEM = f"""You are the WellBridge Supervisor. You coordinate specialist agents
to answer a patient's question. You decide which agent(s) to dispatch based on the
user's message, emotional state, care stage, and any outputs already collected.

{AGENT_DESCRIPTIONS}

Respond with JSON matching this schema:
{{
  "agents_to_dispatch": ["agent_name", ...],
  "reasoning": "brief explanation",
  "is_complete": true/false
}}

If the user's request is simple (single concern), dispatch one agent and set is_complete=true.
If the request spans multiple concerns, dispatch relevant agents.
If a previous agent's output reveals gaps, dispatch another agent to fill them.
Never dispatch more than 3 agents in a single iteration.
"""


async def run(state: AgentState) -> dict:
    """
    Supervisor loop: LLM decides which agents to dispatch, collects outputs,
    and iterates until the response is complete or max iterations reached.
    """
    agent_outputs: list[AgentOutput] = []
    reasoning_trail: list[str] = []
    iteration = 0

    user_message = state["messages"][-1].content
    intent = state.get("intent", "GENERAL")
    emotional_state = state.get("emotional_state", "calm")
    care_stage = state.get("care_stage", "unknown")

    for iteration in range(MAX_ITERATIONS):
        # Build context for the Supervisor LLM
        collected_summary = ""
        if agent_outputs:
            parts = []
            for ao in agent_outputs:
                snippet = ao["raw_response"][:300] if ao["raw_response"] else "(no output)"
                parts.append(f"  {ao['agent_name']}: {snippet}")
            collected_summary = "Agent outputs collected so far:\n" + "\n".join(parts)

        decision = await _supervisor_decide(
            user_message=user_message,
            intent=intent,
            emotional_state=emotional_state,
            care_stage=care_stage,
            collected_summary=collected_summary,
            iteration=iteration,
        )

        if decision is None:
            # LLM call failed — fallback to single-dispatch
            log.warning("supervisor: LLM decision failed, using fallback routing")
            fallback_agent = _fallback_agent(intent)
            decision = SupervisorDecision(
                agents_to_dispatch=[fallback_agent],
                reasoning="Fallback: Supervisor LLM call failed",
                is_complete=True,
            )

        reasoning_trail.append(f"Iter {iteration}: {decision.reasoning}")
        log.info("supervisor: iter=%d dispatch=%s complete=%s reasoning=%s",
                 iteration, decision.agents_to_dispatch, decision.is_complete,
                 decision.reasoning[:80])

        # Dispatch each agent
        for agent_name in decision.agents_to_dispatch:
            if agent_name not in AVAILABLE_AGENTS:
                log.warning("supervisor: unknown agent '%s', skipping", agent_name)
                continue

            try:
                result = await AVAILABLE_AGENTS[agent_name](state)

                # Merge result into state so the next agent sees updated records, etc.
                for key in ("records", "appointments"):
                    if key in result and result[key]:
                        state[key] = result[key]

                agent_outputs.append(AgentOutput(
                    agent_name=agent_name,
                    raw_response=result.get("raw_response", ""),
                    jargon_entries=result.get("jargon_map", []),
                    citations=result.get("citations", []),
                    records_used=[r.get("id", "") for r in result.get("records", []) if isinstance(r, dict)],
                    action_cards=result.get("action_cards", []),
                ))
                log.info("supervisor: agent=%s produced %d chars",
                         agent_name, len(result.get("raw_response", "")))

            except Exception as exc:
                log.error("supervisor: agent=%s failed — %s", agent_name, exc, exc_info=True)
                agent_outputs.append(AgentOutput(
                    agent_name=agent_name,
                    raw_response="",
                    jargon_entries=[],
                    citations=[],
                    records_used=[],
                    action_cards=[],
                ))

        if decision.is_complete:
            break

    return {
        "agent_outputs": agent_outputs,
        "supervisor_iterations": iteration + 1,
        "supervisor_reasoning": reasoning_trail,
    }


async def _supervisor_decide(
    user_message: str,
    intent: str,
    emotional_state: str,
    care_stage: str,
    collected_summary: str,
    iteration: int,
) -> SupervisorDecision | None:
    """Make a single Supervisor LLM decision call."""
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        user_prompt = (
            f"User message: {user_message}\n"
            f"Classified intent: {intent}\n"
            f"Emotional state: {emotional_state}\n"
            f"Care stage: {care_stage}\n"
            f"Iteration: {iteration}\n"
        )
        if collected_summary:
            user_prompt += f"\n{collected_summary}\n"
        user_prompt += "\nDecide which agents to dispatch next."

        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SUPERVISOR_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=300,
        )

        raw = result.choices[0].message.content or ""
        data = json.loads(raw)
        return SupervisorDecision(**data)

    except Exception as exc:
        log.warning("supervisor: decision LLM call failed — %s", exc)
        return None


def _fallback_agent(intent: str | None) -> str:
    """Map intent to a single agent name for fallback routing."""
    routing_map = {
        "NOTE_EXPLANATION":  "note_explainer",
        "CARE_NAVIGATION":   "care_navigator",
        "RECORD_COLLECTION": "record_collector",
        "SCHEDULING":        "calendar_tool",
        "RECORD_LOOKUP":     "record_lookup",
        "JARGON_EXPLAIN":    "jargon_explainer",
        "PRE_VISIT_PREP":    "pre_visit_prep",
        "GENERAL":           "note_summarizer",
    }
    return routing_map.get(intent or "", "care_navigator")
