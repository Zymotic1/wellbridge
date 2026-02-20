"""
Intent classifier node — routes messages through the agentic graph.

Classifies the user's message into an IntentType using GPT-4o structured output.
Temperature 0.0 for deterministic, reproducible classification.

Key changes from the original:
  - History-aware: reads last 3 turns so "I just had surgery" followed by
    "What does that report say?" classifies as RECORD_LOOKUP, not GENERAL.
  - NOTE_EXPLANATION intent: separates "help me understand what doctor told me"
    (allowed: summarize notes + explain public medication info) from
    MEDICAL_ADVICE (refused: prescriptive advice, diagnosis, prognosis).
  - CARE_NAVIGATION and RECORD_COLLECTION: two new proactive intents.
  - Refined safety bias: ambiguity between comprehension and advice defaults
    to NOTE_EXPLANATION (ask for the note) rather than an outright refusal.
    The refusal path is reserved for genuinely prescriptive requests.

SAFETY RULE: Messages that are clearly seeking new advice/diagnosis/prognosis
→ MEDICAL_ADVICE (refused, no LLM). Messages seeking to understand documented
information → NOTE_EXPLANATION or RECORD_LOOKUP (allowed, with guardrails).
"""

import json
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState, IntentType
from config import get_settings

settings = get_settings()

CLASSIFIER_SYSTEM = """
You are a medical chat triage classifier for WellBridge. Your ONLY job is to classify
user messages. Do not answer the question — only classify it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE MOST IMPORTANT DISTINCTION IN THIS SYSTEM:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MEDICAL_ADVICE — Messages asking for NEW prescriptive guidance:
  • "What should I do about X?"
  • "Should I take X?"
  • "Is X normal for me?"
  • "Do I have X?"
  • "Will I be okay?"
  • "Am I going to recover?"
  → These ask the app to act as a doctor. ALWAYS route to refusal.

NOTE_EXPLANATION — Messages asking to UNDERSTAND what they were already told:
  • "I don't understand what my doctor told me"
  • "My doctor said I have X — what does that mean?"
  • "I was prescribed X — what is it for?"
  • "I got my results and I don't know what any of it means"
  • "Can you explain my discharge notes?"
  • "What are the side effects of X?" (when X was prescribed to them)
  → These ask the app to translate documented information. ALLOWED.
  → Route here even when no records exist yet — the node will ask them to share notes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ALL CATEGORIES:

MEDICAL_ADVICE
  New prescriptive guidance: "what should I do", "should I take", "is this normal for me",
  "do I have X", "will I be okay", "am I going to be okay", prognosis, diagnosis questions.
  This is ONLY for messages asking the app to act as a doctor going forward.

NOTE_EXPLANATION
  Comprehension of documented information: "I don't understand what my doctor told me",
  "what does my note say", "explain what I was told", "what is this medication I was
  prescribed for", "can you go through my discharge summary with me",
  "what are the side effects of [prescribed drug]".

CARE_NAVIGATION
  Emotional journey: sharing news about diagnosis/surgery/treatment; expressing feelings
  about care; asking "what happens next"; describing situation without a specific task.
  Examples: "I just found out I need surgery", "I'm scared about my results",
  "I just got back from my oncologist", "I don't know what to do".

RECORD_COLLECTION
  User mentions a document/visit/scan that isn't stored in WellBridge yet.
  Examples: "I have a letter from my cardiologist", "I picked up my prescription",
  "I got my lab results in the mail", "I have discharge papers".

RECORD_LOOKUP
  Looking up information already stored in WellBridge records.
  ANY request to search, check, or read uploaded documents — even when a medical
  topic is mentioned — is RECORD_LOOKUP if the user is asking what their records say.
  Examples: "Show me my records", "What did my last test say", "What was my visit about",
  "Can you look at my recent records?", "Do my records mention blood pressure?",
  "What does my file say about [topic]?", "Are there any notes about [condition] in my records?",
  "Look through my documents", "Check my records for [anything]".

JARGON_EXPLAIN
  Asking what a specific medical term means (isolated term, not tied to a note they want
  explained). Examples: "What does hypertension mean?", "What is an ablation?".

PRE_VISIT_PREP
  Preparing for an upcoming appointment OR generating question lists for a doctor.
  This includes ANY request for questions to ask a doctor, even without mentioning
  a specific appointment date. "What questions should I ask?" after a medical
  discussion = PRE_VISIT_PREP, NOT MEDICAL_ADVICE. The distinction: PRE_VISIT_PREP
  generates factual, information-seeking questions ("what were my results?" "what does
  this medication do?") — it does NOT give advice ("take this", "you have that").
  Examples: "Help me prepare for tomorrow", "What should I ask the doctor",
  "What questions should I ask?", "What should I bring up at my appointment?",
  "Give me questions for my next visit", "Help me prepare questions",
  "What should I discuss with my doctor?", "How should I prepare?",
  "What should I ask about my records?", "What questions should I ask based on my records?".

SCHEDULING
  Booking, cancelling, or rescheduling appointments; calendar questions.

GENERAL
  Greetings, app how-to questions, other non-medical topics.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLASSIFICATION RULES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. If the user is asking to UNDERSTAND documented information → NOTE_EXPLANATION
   (even if no records exist yet — the response will ask them to share the note)
2. If the user is asking for NEW advice or interpretation of their personal situation → MEDICAL_ADVICE
3. Emotional, journey-oriented messages without a task → CARE_NAVIGATION
4. "I have a document" → RECORD_COLLECTION, not RECORD_LOOKUP
5. Use conversation history: recent context shapes the intent
6. When genuinely ambiguous between NOTE_EXPLANATION and MEDICAL_ADVICE:
   → Ask: is the user asking the app to help them understand something, or to tell them what to do?
   → Understanding documented info = NOTE_EXPLANATION
   → Being told what to do = MEDICAL_ADVICE
7. CRITICAL: If the user says "look at my records", "check my documents", "what do my records say"
   or any variant asking about stored files → RECORD_LOOKUP, NOT MEDICAL_ADVICE.
   The medical topic they ask about (blood pressure, medications, etc.) does not change this —
   they are asking what is DOCUMENTED, not asking for advice.
8. CRITICAL: "What questions should I ask [my doctor]?" or "What should I discuss [at my visit]?"
   or "Help me prepare questions" → PRE_VISIT_PREP, NOT MEDICAL_ADVICE.
   The key test: is the user asking for QUESTIONS TO ASK (PRE_VISIT_PREP) or ANSWERS/ADVICE
   (MEDICAL_ADVICE)? Generating a list of questions to bring to an appointment is always safe.
   Even a short "What questions should I ask?" after a medical discussion → PRE_VISIT_PREP.

EXAMPLES:
- "My leg hurts, what should I do?" → MEDICAL_ADVICE
- "I saw my doctor and I don't understand what she told me" → NOTE_EXPLANATION
- "I was prescribed metformin, what is that for?" → NOTE_EXPLANATION
- "My doctor said I have hypertension, can you explain my notes?" → NOTE_EXPLANATION
- "Should I take my blood pressure pill today?" → MEDICAL_ADVICE
- "Is my blood pressure result normal?" → MEDICAL_ADVICE
- "What does my discharge summary say?" → NOTE_EXPLANATION
- "I just found out I need knee surgery" → CARE_NAVIGATION
- "I have my discharge papers from yesterday" → RECORD_COLLECTION
- "Show me what Dr. Smith said about my leg" → RECORD_LOOKUP
- "What does 'patellofemoral' mean?" → JARGON_EXPLAIN
- "Book an appointment with Dr. Smith" → SCHEDULING
- "Help me prepare questions for tomorrow" → PRE_VISIT_PREP
- "What questions should I ask?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "What questions should I ask at my next visit?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "What questions should I ask the doctor?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "What questions should I have for my appointment?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "What should I ask my doctor?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "What should I discuss with my doctor on my next visit?" → PRE_VISIT_PREP
- "Given my visit notes, what should I bring up?" → PRE_VISIT_PREP
- "Help me prepare for my appointment" → PRE_VISIT_PREP
- "What should I ask based on my records?" → PRE_VISIT_PREP
- "Can you give me questions for my doctor visit?" → PRE_VISIT_PREP
- "What do I need to ask my doctor?" → PRE_VISIT_PREP  ← NOT MEDICAL_ADVICE
- "Am I going to be okay?" → MEDICAL_ADVICE
- "I'm scared about my upcoming procedure" → CARE_NAVIGATION
- "What were my last blood test results?" → RECORD_LOOKUP
- "What are the side effects of lisinopril I was prescribed?" → NOTE_EXPLANATION
- "Can you look at my recent records?" → RECORD_LOOKUP
- "Do my records mention anything about blood pressure?" → RECORD_LOOKUP
- "What do my uploaded documents say about my medications?" → RECORD_LOOKUP
- "Look through my records and tell me what conditions are listed" → RECORD_LOOKUP
- "Ways to reduce blood pressure" (with no mention of records) → MEDICAL_ADVICE
- "What do my records say about blood pressure?" → RECORD_LOOKUP
- "I have questions about what happens next" (emotional, no specific task) → CARE_NAVIGATION
- "What happens next after surgery?" (no records, seeking info) → CARE_NAVIGATION
- "What questions should I ask about what happens next?" → PRE_VISIT_PREP
"""


class IntentResult(BaseModel):
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence 0–1")
    reasoning: str = Field(description="Brief explanation (for audit log, not shown to user)")


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Include recent conversation context so classification is history-aware
    messages_for_llm = [{"role": "system", "content": CLASSIFIER_SYSTEM}]

    # Add up to 3 prior turns as context
    prior_messages = state.get("messages", [])
    for msg in prior_messages[:-1][-6:]:  # Last 3 exchanges (6 messages)
        if isinstance(msg, HumanMessage):
            messages_for_llm.append({"role": "user", "content": f"[PRIOR] {msg.content}"})
        elif isinstance(msg, AIMessage):
            messages_for_llm.append({"role": "assistant", "content": f"[PRIOR] {msg.content[:100]}"})

    # The message to classify
    last_message = state["messages"][-1].content
    messages_for_llm.append({
        "role": "user",
        "content": f"Classify this message: {last_message}",
    })

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages_for_llm,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=200,
        )

        raw = result.choices[0].message.content or ""
        data = json.loads(raw)
        parsed = IntentResult(**data)

        return {
            "intent": parsed.intent,
            "confidence": parsed.confidence,
        }

    except Exception:
        # Classification failure → CARE_NAVIGATION (safer than blanket refusal;
        # care_navigator will ask the user to clarify what they need)
        return {
            "intent": "CARE_NAVIGATION",
            "confidence": 0.0,
        }
