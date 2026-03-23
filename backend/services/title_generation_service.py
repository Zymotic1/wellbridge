"""
Session title generation service.

Generates a short (3-6 word) topic title for a chat session based on the
first user message and assistant response. Used to replace "New conversation"
with a meaningful label in the sidebar.

Uses a lightweight GPT call (low max_tokens) for cost efficiency.
Non-blocking — if it fails, the session keeps "New conversation" and
the user can rename manually.
"""

import logging

from openai import AsyncOpenAI
from config import get_settings

log = logging.getLogger("wellbridge.title_generation")
settings = get_settings()

TITLE_PROMPT = """Generate a short (3-6 word) topic title for this patient chat conversation.
Focus on the patient's main concern or topic. Use plain language, not medical jargon.

Examples of good titles:
- Heart Medication Questions
- Post-Surgery Follow-Up
- Understanding Lab Results
- Upcoming Cardiology Visit
- Knee Pain Visit Notes
- New Prescription Questions

Return ONLY the title text. No quotes, no punctuation, no explanation."""


async def generate_session_title(user_message: str, assistant_response: str) -> str | None:
    """
    Generate a concise session title from the first exchange.

    Returns the title string, or None if generation fails (non-critical).
    """
    if not settings.openai_api_key:
        return None

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        result = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": TITLE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Patient said: {user_message[:500]}\n\n"
                        f"Assistant replied: {assistant_response[:500]}"
                    ),
                },
            ],
            temperature=0.5,
            max_tokens=20,
        )
        title = (result.choices[0].message.content or "").strip().strip('"\'')
        if title and len(title) <= 60:
            return title
        return None
    except Exception as exc:
        log.warning("title generation failed (non-critical): %s", exc)
        return None
