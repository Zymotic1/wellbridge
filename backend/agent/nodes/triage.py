"""
Triage node — the brain's first decision point.

Performs THREE tasks in a single LLM call:
  1. Emotional assessment (emotional_state, care_stage, facts)
  2. Intent classification (intent, confidence)
  3. Information source determination (information_source)

The information_source is the key innovation: the LLM itself decides whether
a question can be answered from public knowledge, needs patient records,
or should be refused. This replaces brittle regex patterns with the LLM's
own reasoning about what kind of information is needed.

INFORMATION SOURCES:
  public_knowledge — The question is about general medical knowledge that is
    publicly available: medication side effects, what a condition is, how a
    procedure works, what a medical term means, general health education.
    These do NOT require the patient's personal records.

  patient_records — The question is about the patient's specific medical
    history, visit notes, test results, or provider instructions. Requires
    uploaded documents to answer accurately.

  conversation — The question is emotional, logistical, or about the app
    itself. Can be answered from conversation context alone (care navigation,
    scheduling, record collection prompts).

  refuse — The question asks for medical advice, diagnosis, or prognosis.
    Always routed to refusal_node.

SAFETY: MEDICAL_ADVICE → refuse. This is architecturally enforced in graph.py.
"""

import json
import logging

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, IntentType, EmotionalState, CareStage, InformationSource
from agent.nodes.intent_classifier import CLASSIFIER_SYSTEM
from agent.prompts import EMOTIONAL_ASSESSOR_SYSTEM
from services.openai_client import get_openai_client
from config import get_settings

log = logging.getLogger("wellbridge.triage")
settings = get_settings()


class TriageResult(BaseModel):
    emotional_state: EmotionalState = Field(default="calm")
    care_stage: CareStage = Field(default="unknown")
    new_facts: list[str] = Field(default_factory=list)
    intent: IntentType = Field(default="GENERAL")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    information_source: InformationSource = Field(default="conversation")
    reasoning: str = Field(default="")


TRIAGE_SYSTEM = f"""You are the WellBridge triage system. You perform THREE tasks in a single pass.

TASK 1 — EMOTIONAL ASSESSMENT:
{EMOTIONAL_ASSESSOR_SYSTEM}

TASK 2 — INTENT CLASSIFICATION:
{CLASSIFIER_SYSTEM}

TASK 3 — INFORMATION SOURCE DETERMINATION:
Decide what kind of information is needed to answer the user's question:

"public_knowledge" — The answer is PUBLICLY AVAILABLE medical information that does NOT
  require the patient's personal records. Use this for:
  • Medication questions: "What are side effects of Amlodipine?", "What is metformin used for?"
  • Condition explanations: "What is atrial fibrillation?", "What causes high blood pressure?"
  • Procedure information: "What happens during a cardiac catheterization?", "What is an ablation?"
  • Medical term definitions: "What does ejection fraction mean?", "What is an ECG?"
  • General health education: "How does blood pressure medication work?", "What is a stress test?"
  • Treatment explanations: "What is cardiac rehab?", "How does chemotherapy work?"
  Even if the patient has records, if the question is asking about GENERAL medical knowledge
  (not what their specific records say), classify as public_knowledge.

"patient_records" — The answer requires the patient's OWN medical documents. Use this for:
  • "What did my doctor say about my blood pressure?"
  • "Explain my discharge summary"
  • "What medications am I on?" (their specific prescriptions, not general drug info)
  • "What were my test results?"
  • "I don't understand what my doctor told me" (about their specific visit)
  • Any question about THEIR specific care, results, or provider instructions

"conversation" — Can be answered from conversation context, logistics, or emotional support:
  • Emotional sharing: "I'm scared about my surgery"
  • Logistics: "I have a document to upload", "When is my appointment?"
  • App questions: "How do I use this?", "Can you help me?"
  • Confirming details: "Yes, that's right"

"refuse" — Medical advice, diagnosis, or prognosis requests:
  • "Should I take this medication?", "Is my blood pressure normal?", "Do I have diabetes?"

THE KEY DISTINCTION:
  "What are the side effects of Amlodipine?" → public_knowledge (general FDA info)
  "What did my doctor say about my Amlodipine dose?" → patient_records (specific to their care)
  "Should I stop taking Amlodipine?" → refuse (medical advice)

Respond with a single JSON object:
{{
  "emotional_state": "anxious|confused|engaged|calm",
  "care_stage": "unknown|pre-visit|post-visit|pre-surgery|post-surgery|treatment|diagnosis",
  "new_facts": ["fact1", "fact2"],
  "intent": "MEDICAL_ADVICE|NOTE_EXPLANATION|CARE_NAVIGATION|RECORD_COLLECTION|RECORD_LOOKUP|JARGON_EXPLAIN|PRE_VISIT_PREP|SCHEDULING|GENERAL",
  "confidence": 0.0-1.0,
  "information_source": "public_knowledge|patient_records|conversation|refuse",
  "reasoning": "brief explanation of classification logic"
}}
"""


async def run(state: AgentState) -> dict:
    """
    Single LLM call: emotional assessment + intent classification + information source.
    """
    model = getattr(settings, "openai_classification_model", None) or settings.openai_model

    messages_for_llm = [{"role": "system", "content": TRIAGE_SYSTEM}]

    # Add conversation context (last 3 turns)
    prior_messages = state.get("messages", [])
    for msg in prior_messages[:-1][-6:]:
        if isinstance(msg, HumanMessage):
            messages_for_llm.append({"role": "user", "content": f"[PRIOR] {msg.content}"})
        elif isinstance(msg, AIMessage):
            messages_for_llm.append({"role": "assistant", "content": f"[PRIOR] {msg.content[:200]}"})

    last_message = state["messages"][-1].content
    messages_for_llm.append({
        "role": "user",
        "content": (
            "Assess emotional state, classify intent, and determine information source. "
            "Respond with JSON.\n\n"
            f"Message: {last_message}"
        ),
    })

    try:
        client = get_openai_client()
        result = await client.chat.completions.create(
            model=model,
            messages=messages_for_llm,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=500,
        )

        raw = result.choices[0].message.content or ""
        if not raw.strip():
            raise ValueError("Empty response")
        parsed = TriageResult(**json.loads(raw))

        log.info("triage: intent=%s source=%s confidence=%.2f emotional=%s reasoning=%s",
                 parsed.intent, parsed.information_source, parsed.confidence,
                 parsed.emotional_state, parsed.reasoning[:80])

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
            "information_source": parsed.information_source,
        }

    except Exception as exc:
        log.warning("triage: failed — %s. Falling back to CARE_NAVIGATION.", exc)
        return {
            "emotional_state": "calm",
            "care_stage": state.get("care_stage", "unknown"),
            "care_context": state.get("care_context", {}),
            "intent": "CARE_NAVIGATION",
            "confidence": 0.0,
            "information_source": "conversation",
        }
