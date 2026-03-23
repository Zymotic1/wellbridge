"""
Safety precheck — pure-Python regex gate for obvious MEDICAL_ADVICE requests.

NO LLM call. This runs in < 1ms. It catches the most unambiguous patterns
of medical advice seeking before the brain LLM even sees the message.

This is layer 1 of defense-in-depth:
  Layer 1: safety_precheck (regex, catches "should I take X", "do I have X")
  Layer 2: brain's constitutional rules (LLM won't generate advice)
  Layer 3: validator's guardrail regex (catches advice in output)

The precheck intentionally has HIGH SPECIFICITY (few false positives).
Ambiguous messages go to the brain, which handles them with nuance.
"""

import re
from agent.state import AgentState

# High-specificity patterns — these are almost always medical advice requests.
# We do NOT try to catch everything here. Ambiguous cases go to the brain.
_REFUSAL_PATTERNS = [
    re.compile(r"\bshould I (take|stop|start|change|increase|decrease|skip)\b", re.I),
    re.compile(r"\bshould I be (worried|concerned|scared)\b", re.I),
    re.compile(r"\bis (my|this) .{0,30} (normal|okay|safe|dangerous|concerning|bad|good)\b", re.I),
    re.compile(r"\bdo I have\b .{0,20}\b(disease|cancer|diabetes|condition)\b", re.I),
    re.compile(r"\bam I (developing|getting|going to die|at risk)\b", re.I),
    re.compile(r"\bwhat('s| is) wrong with me\b", re.I),
    re.compile(r"\bwill I (be okay|recover|survive|die)\b", re.I),
    re.compile(r"\bcan you (diagnose|prescribe|recommend a treatment)\b", re.I),
]


async def run(state: AgentState) -> dict:
    """Check for obvious medical advice patterns. Returns is_refusal flag."""
    user_message = state["messages"][-1].content

    for pattern in _REFUSAL_PATTERNS:
        if pattern.search(user_message):
            return {"is_refusal": True}

    return {"is_refusal": False}
