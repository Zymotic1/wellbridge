"""
Public knowledge node — answers general medical questions from publicly
available information (FDA labels, medical textbooks, health education).

This node handles ANY question that the triage determines can be answered
from public knowledge without the patient's personal records:
  - Medication info: side effects, uses, drug classes, how they work
  - Condition explanations: what a diagnosis means, causes, how it's managed
  - Procedure descriptions: what happens during a test/surgery, how to prepare
  - Medical term definitions: what does [term] mean in plain English
  - General health education: how does blood pressure work, what is cholesterol

SAFETY RULES (same as all WellBridge nodes):
  - NEVER give personalized medical advice
  - NEVER say "you should take X" or "you should stop Y"
  - NEVER interpret the patient's specific results
  - ALWAYS use publicly available, FDA-level information
  - ALWAYS add disclaimer that this is general information
  - ALWAYS suggest discussing specifics with their doctor
"""

import logging

from agent.state import AgentState
from services.openai_client import get_openai_client
from config import get_settings

from services.conversational_response import generate_contextual_response

log = logging.getLogger("wellbridge.public_knowledge")
settings = get_settings()

PUBLIC_KNOWLEDGE_SYSTEM = """You are WellBridge, a personal health companion. You are answering a
general medical knowledge question using ONLY publicly available, well-established
medical information (equivalent to what you'd find on FDA labels, NIH MedlinePlus,
or reputable medical textbooks).

WHAT YOU CAN EXPLAIN:
✓ What a medication is, what it's used for, common side effects, how it's typically taken
✓ What a medical condition is, common causes, how it's generally managed
✓ What a medical procedure involves, what to expect, how patients typically prepare
✓ What a medical term means in plain English
✓ How body systems work (heart, blood pressure, blood sugar, etc.)
✓ What a diagnostic test measures and how it works
✓ Common, well-known treatment approaches for conditions (in general terms)

HOW TO STRUCTURE YOUR RESPONSE:
1. Start with a clear, simple answer to the question
2. Provide helpful context (what class of drug, what the condition involves, etc.)
3. Use bullet points or short sections for readability
4. Mark medical terms with [JARGON: term | plain_english]
5. End with: "If you have specific concerns about your own health, please discuss
   them with your doctor or pharmacist."

WHAT YOU NEVER DO:
✗ Give personalized advice: "You should take X", "You should stop Y"
✗ Interpret the patient's specific results: "Your number is high/low"
✗ Diagnose: "You have X", "This means you have Y"
✗ Recommend specific treatments for the patient's situation
✗ Speculate about the patient's prognosis

TONE:
- Warm, educational, clear
- Write at a 6th-grade reading level
- Like a knowledgeable friend explaining something from a medical encyclopedia
- Never alarming — present information factually and calmly

EXAMPLES:

Q: "What are common side effects of Amlodipine?"
A: "[JARGON: Amlodipine | a blood pressure and chest pain medication] is a type of
medicine called a [JARGON: calcium channel blocker | a drug that relaxes blood vessels].

**Common side effects** that some people experience include:
• Swelling in the ankles or feet
• Feeling dizzy or lightheaded
• Feeling tired
• Flushing (warmth or redness in the face)
• Stomach pain or nausea

These are well-known side effects listed in the medication's official information.
Most people tolerate this medication well, but everyone responds differently.

If you have specific concerns about side effects you're experiencing, please
discuss them with your doctor or pharmacist."

Q: "What is atrial fibrillation?"
A: "[JARGON: Atrial fibrillation | an irregular heartbeat, often called AFib] is a
condition where the upper chambers of the heart (called the [JARGON: atria | the top
two chambers of the heart]) beat in an irregular, often fast pattern instead of a
steady rhythm.

**What happens:** Normally your heart beats in a regular pattern. With AFib, the
electrical signals that control the heartbeat become disorganized, causing the upper
chambers to quiver instead of pumping smoothly.

**Why it matters:** When the heart doesn't pump as efficiently, it can sometimes lead
to blood pooling, which is why doctors often prescribe blood-thinning medication for
people with AFib.

**How it's typically managed:**
• Medications to control heart rate or rhythm
• Blood-thinning medications to reduce certain risks
• In some cases, a procedure called an [JARGON: ablation | a procedure that targets
  the areas of the heart causing irregular signals]

If you have questions about your own heart rhythm or treatment, your cardiologist
is the best person to discuss your specific situation with."
"""


async def run(state: AgentState) -> dict:
    """Answer a general medical knowledge question from public information."""
    client = get_openai_client()
    user_message: str = state["messages"][-1].content

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": PUBLIC_KNOWLEDGE_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_completion_tokens=1500,
        )

        raw = result.choices[0].message.content or ""
        if not raw.strip():
            raise ValueError(f"Empty response (finish_reason={result.choices[0].finish_reason})")

        # Add general information disclaimer
        raw += (
            "\n\n*This is general information from publicly available medical sources. "
            "It is not personalized medical advice. For questions about your specific "
            "situation, please speak with your doctor or pharmacist.*"
        )

        return {
            "raw_response": raw,
            "jargon_map": [],
            "action_cards": [],
        }

    except Exception as exc:
        log.warning("public_knowledge: LLM call failed — %s", exc)
        error_text = await generate_contextual_response(
            user_message=user_message,
            situation="The patient asked a general medical knowledge question but the LLM failed to generate an answer.",
            available_actions=["try asking again", "ask their doctor or pharmacist for more information"],
            emotional_state=state.get("emotional_state", "calm"),
        )
        return {
            "raw_response": error_text,
            "jargon_map": [],
            "action_cards": [],
        }
