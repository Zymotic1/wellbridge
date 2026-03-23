"""
Triage node — combined emotional assessment + intent classification in ONE LLM call.

Replaces the sequential emotional_assessor → safety_gate chain, cutting the
pre-routing phase from 2 LLM calls (~1.5-2.5s) to 1 call (~0.6-1.0s).

Returns all the state needed for routing:
  - emotional_state, care_stage, care_context (from emotional assessment)
  - intent, confidence (from intent classification)

SAFETY: MEDICAL_ADVICE classification is still the gate to refusal_node.
This node's output is consumed by route_safety_gate() in graph.py exactly
as before — the architectural safety invariant is unchanged.
"""

import json
import logging

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, IntentType, EmotionalState, CareStage
from agent.nodes.intent_classifier import CLASSIFIER_SYSTEM
from agent.prompts import EMOTIONAL_ASSESSOR_SYSTEM
from services.openai_client import get_openai_client
from config import get_settings

log = logging.getLogger("wellbridge.triage")
settings = get_settings()


class TriageResult(BaseModel):
    # Emotional assessment
    emotional_state: EmotionalState = Field(default="calm")
    care_stage: CareStage = Field(default="unknown")
    new_facts: list[str] = Field(default_factory=list)
    # Intent classification
    intent: IntentType = Field(default="GENERAL")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


TRIAGE_SYSTEM = f"""You are the WellBridge triage system. You perform TWO tasks in a single pass:

TASK 1 — EMOTIONAL ASSESSMENT:
{EMOTIONAL_ASSESSOR_SYSTEM}

TASK 2 — INTENT CLASSIFICATION:
{CLASSIFIER_SYSTEM}

Respond with a single JSON object containing ALL fields:
{{
  "emotional_state": "anxious|confused|engaged|calm",
  "care_stage": "unknown|pre-visit|post-visit|pre-surgery|post-surgery|treatment|diagnosis",
  "new_facts": ["fact1", "fact2"],
  "intent": "MEDICAL_ADVICE|NOTE_EXPLANATION|CARE_NAVIGATION|RECORD_COLLECTION|RECORD_LOOKUP|JARGON_EXPLAIN|PRE_VISIT_PREP|SCHEDULING|GENERAL",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}
"""


async def run(state: AgentState) -> dict:
    """
    Single LLM call that assesses emotion AND classifies intent.
    Falls back to safe defaults if the call fails.
    """
    # Use classification model if configured, otherwise main model
    model = getattr(settings, "openai_classification_model", None) or settings.openai_model

    messages_for_llm = [{"role": "system", "content": TRIAGE_SYSTEM}]

    # Add conversation context (last 3 turns)
    prior_messages = state.get("messages", [])
    for msg in prior_messages[:-1][-6:]:
        if isinstance(msg, HumanMessage):
            messages_for_llm.append({"role": "user", "content": f"[PRIOR] {msg.content}"})
        elif isinstance(msg, AIMessage):
            messages_for_llm.append({"role": "assistant", "content": f"[PRIOR] {msg.content[:100]}"})

    last_message = state["messages"][-1].content
    messages_for_llm.append({
        "role": "user",
        "content": f"Assess emotional state and classify intent. Respond with JSON.\n\nMessage: {last_message}",
    })

    try:
        client = get_openai_client()
        result = await client.chat.completions.create(
            model=model,
            messages=messages_for_llm,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=400,
        )

        raw = result.choices[0].message.content or ""
        parsed = TriageResult(**json.loads(raw))

        log.info("triage: intent=%s confidence=%.2f emotional=%s stage=%s",
                 parsed.intent, parsed.confidence, parsed.emotional_state, parsed.care_stage)

        # Merge new facts into care_context
        care_context = dict(state.get("care_context", {}))
        existing_facts = care_context.get("facts", [])
        care_context["facts"] = existing_facts + parsed.new_facts

        return {
            "emotional_state": parsed.emotional_state,
            "care_stage": parsed.care_stage,
            "care_context": care_context,
            "intent": parsed.intent,
            "confidence": parsed.confidence,
        }

    except Exception as exc:
        log.warning("triage: failed — %s. Falling back to CARE_NAVIGATION.", exc)
        return {
            "emotional_state": "calm",
            "care_stage": state.get("care_stage", "unknown"),
            "care_context": state.get("care_context", {}),
            "intent": "CARE_NAVIGATION",
            "confidence": 0.0,
        }
