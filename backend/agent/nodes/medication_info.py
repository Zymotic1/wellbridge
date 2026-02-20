"""
Medication info node — provides factual information about medications.

Uses GPT-4o with the MEDICATION_INFO_SYSTEM prompt, which restricts output
to FDA drug class and intended use category. NEVER recommends dosage, whether
the patient should take it, or alternatives.

In production, this would be supplemented by a direct API call to:
  - FDA DailyMed API (https://dailymed.nlm.nih.gov/dailymed/)
  - NIH MedlinePlus API
to ensure factual accuracy beyond the LLM's training data.
"""

from openai import AsyncOpenAI

from agent.state import AgentState
from agent.prompts import MEDICATION_INFO_SYSTEM
from config import get_settings

settings = get_settings()


async def run(state: AgentState) -> dict:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_query: str = state["messages"][-1].content

    try:
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": MEDICATION_INFO_SYSTEM},
                {"role": "user", "content": user_query},
            ],
            temperature=0.1,
            max_tokens=350,
        )
        raw = result.choices[0].message.content or ""

        # Add mandatory disclaimer
        raw += (
            "\n\n*This is general drug class information only. "
            "It is NOT personalized medical advice. "
            "Please ask your pharmacist or doctor about your specific situation.*"
        )

        return {"raw_response": raw, "jargon_map": []}
    except Exception as exc:
        return {
            "tool_error": str(exc),
            "raw_response": "I had trouble looking up that medication. Please try again.",
            "jargon_map": [],
        }
