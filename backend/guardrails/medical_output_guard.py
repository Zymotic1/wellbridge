"""
Medical output guardrail — regex-based prohibited phrase detector.

Scans LLM output for phrases that would constitute medical advice, diagnosis,
or treatment recommendations. If ANY prohibited pattern matches, the entire
response is replaced with the SAFE_FALLBACK string.

This runs deterministically (no LLM call) and is the last line of defense
before a response reaches the user.

Design rationale: Regex over LLM-based classification for the guardrail
because regex is:
  - Deterministic (always same result for same input)
  - No network dependency (works if OpenAI is down)
  - Auditable (exactly which pattern fired is logged)
  - Fast (microseconds, not seconds)

Trade-off: Regex may miss novel phrasing. Future enhancement: layer an
LLM-based guard on top for lower-confidence cases.
"""

import re
from typing import Tuple

SAFE_FALLBACK = (
    "I wasn't able to generate a safe response for that request. "
    "Please contact your care team directly for medical guidance.\n\n"
    "You can reach me for factual questions about your own documented records."
)

# ---------------------------------------------------------------------------
# Prohibited phrase patterns
# Each tuple: (compiled_regex, human_readable_name_for_logging)
# ---------------------------------------------------------------------------
_RAW_PATTERNS: list[tuple[str, str]] = [
    (r"\bI diagnose\b",                             "I_diagnose"),
    (r"\bI recommend\b",                            "I_recommend"),
    (r"\bI suggest\b",                              "I_suggest"),
    (r"\btry this instead\b",                       "try_this_instead"),
    (r"\byou (should|must|need to) (take|stop|start|avoid|use)\b",
                                                    "prescriptive_should"),
    (r"\bThis (indicates|suggests|means) you have\b",
                                                    "diagnostic_this_indicates"),
    (r"\bYou (likely|probably|definitely) have\b",  "you_likely_have"),
    (r"\bYour condition is\b",                      "your_condition_is"),
    (r"\bI (would|will|can) prescribe\b",           "prescribe"),
    (r"\byou are (likely|probably) (developing|experiencing)\b",
                                                    "you_are_developing"),
    (r"\b(cut out|stop eating|avoid eating)\b",     "dietary_advice"),
    (r"\btake (\d+\s*)?(mg|milligram|tablet|pill|dose)\b",
                                                    "dosage_recommendation"),
    (r"\bseek (immediate|emergency|urgent) (medical )?(help|care|attention)\b",
                                                    "emergency_directive"),
]

COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), name)
    for pattern, name in _RAW_PATTERNS
]


async def apply_medical_guardrail(text: str) -> Tuple[str, bool, str]:
    """
    Scan text for prohibited medical advice patterns.

    Returns:
        (cleaned_text, was_modified, matched_pattern_name)
        - cleaned_text: SAFE_FALLBACK if modified, original text if clean
        - was_modified: True if any pattern fired
        - matched_pattern_name: name of the first matched pattern (for audit log)
    """
    for pattern, name in COMPILED_PATTERNS:
        if pattern.search(text):
            return SAFE_FALLBACK, True, name

    return text, False, ""
