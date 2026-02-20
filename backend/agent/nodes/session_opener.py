"""
Session opener — generates the first message in a new conversation.

This is NOT a LangGraph node. It is called directly from the chat router
when a new session is created, before any user message exists.

Matches the wireframe vision:
  "Good morning, Jeanne, and welcome to WellBridge.
   I'm here to help you before, during, and after your medical visits —
   and to keep track of things so you don't have to remember everything yourself.
   If it's okay, I'll ask a few gentle questions to understand what's coming up."

The opener is stored as an assistant message in chat_messages so it appears
in the conversation history on next load.
"""

import random
from datetime import datetime


def _time_of_day() -> str:
    h = datetime.now().hour
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    return "Good evening"


# Full welcome (first session, matches wireframe)
_WELCOME = (
    "{greeting}{name_part}, and welcome to WellBridge.\n\n"
    "I'm here to help you before, during, and after your medical visits — "
    "and to keep track of things so you don't have to remember everything yourself.\n\n"
    "If it's okay, I'll ask a few gentle questions to understand what's coming up."
)

# Lighter returning openers
_RETURNING = [
    (
        "{greeting}{name_part}.\n\n"
        "Good to have you back. Whether you just got back from an appointment, "
        "received some news, or just have a question — I'm here."
    ),
    (
        "{greeting}{name_part}.\n\n"
        "I'm here to help you before, during, and after your medical visits — "
        "and to keep track of things so you don't have to remember everything yourself.\n\n"
        "If it's okay, I'll ask a few gentle questions to understand what's coming up."
    ),
    (
        "{greeting}{name_part}.\n\n"
        "I'm here whenever you're ready. "
        "I'm here to help you before, during, and after your medical visits — "
        "and to keep track of things so you don't have to remember everything yourself.\n\n"
        "If it's okay, I'll ask a few gentle questions to understand what's coming up."
    ),
]


def get_opener_message(is_first_session: bool = False, first_name: str = "") -> str:
    """
    Return a warm, personalised session opener.

    - first_name: the patient's stored first name (empty string if not yet set)
    - is_first_session: full welcome for new users; lighter greeting for returning users
    """
    greeting = _time_of_day()
    name_part = f", {first_name}" if first_name else ""
    template = _WELCOME if is_first_session else random.choice([_WELCOME] + _RETURNING)
    return template.format(greeting=greeting, name_part=name_part)
