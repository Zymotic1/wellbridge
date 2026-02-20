"""
Note analysis service — comprehensive GPT-4o analysis of clinical note text.

Called after OCR extracts text from an uploaded document. Produces:
  1. A plain-English summary of what the note says
  2. A list of prescriptions (medication, dose, frequency, instructions)
  3. A list of follow-up appointments (doctor, date, location, reason)
  4. A list of referrals (specialty, doctor name, reason)
  5. A jargon_map for UI term highlighting
  6. Action cards for each prescription, appointment, and referral

This drives the agentic post-upload experience:
  - Prescription action cards → ask user to set medication reminders
  - Appointment action cards → offer to add to calendar + set reminder
  - Referral action cards → offer to help schedule with specialist
"""

import json
import logging
from typing import Optional
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

log = logging.getLogger("wellbridge.note_analysis")

from config import get_settings

settings = get_settings()


# ── Structured output models ────────────────────────────────────────────────

class Prescription(BaseModel):
    medication: str
    dose: Optional[str] = None
    frequency: Optional[str] = None
    instructions: Optional[str] = None  # "take with food", "at bedtime", etc.
    duration: Optional[str] = None      # "for 14 days", "ongoing", etc.


class FollowUpAppointment(BaseModel):
    provider_name: Optional[str] = None
    specialty: Optional[str] = None
    date_or_timeframe: Optional[str] = None  # "in 3 months" or "2026-03-10"
    location: Optional[str] = None
    reason: Optional[str] = None


class Referral(BaseModel):
    specialty: str
    provider_name: Optional[str] = None
    reason: Optional[str] = None
    urgency: Optional[str] = None  # "routine", "urgent", "soon"


class JargonEntry(BaseModel):
    term: str
    plain_english: str


class NoteAnalysisResult(BaseModel):
    summary: str = Field(description="Plain-English summary of the note, 6th-grade level")
    prescriptions: list[Prescription] = Field(default_factory=list)
    follow_up_appointments: list[FollowUpAppointment] = Field(default_factory=list)
    referrals: list[Referral] = Field(default_factory=list)
    jargon_entries: list[JargonEntry] = Field(default_factory=list)


# ── Analysis prompt ─────────────────────────────────────────────────────────

ANALYSIS_SYSTEM = """
You are WellBridge, a personal health companion. A patient has uploaded a clinical
note, discharge summary, or medical letter, and you are translating it into plain
language — like a knowledgeable friend sitting beside them, not a second doctor.

═══════════════════════════════════════════════════════
SUMMARY FORMAT
═══════════════════════════════════════════════════════

Write the summary using these sections. Use markdown bold headers (**Header**) and
bullet points. Address the patient directly as "you" / "your" — never use their name
or "the patient". Keep the entire summary under 400 words.

**Why You Were Seen**
One or two sentences. What brought you in? What was the main complaint or purpose?

**What the Doctor Found**
Bullet points — key exam findings, vital signs, and test results stated as documented
facts. Do NOT label any result as normal, high, low, good, or concerning.

**Your Diagnosis** (omit section if no diagnosis or impression is documented)
State the working diagnosis or clinical impression from the note in plain English.
Use [JARGON: term | plain_english] for every medical term.

**Your Medications** (omit section if no medications are mentioned)
One bullet per medication:
  • **Medication name** (dose, frequency) — what this type of medication is generally
    used for, based on publicly available / FDA-level information.

**Your Next Steps**
Bullet points covering everything the note says you need to do: follow-up visits,
referrals, tests to schedule, lifestyle changes, instructions given at discharge.
If nothing is documented, write: "No specific follow-up steps were documented."

**Watch For** (include ONLY if the note documents warning signs or "return to ED if..."
instructions — omit this section entirely if not mentioned in the note)
Bullet the specific symptoms or conditions the note tells you to watch for.

═══════════════════════════════════════════════════════
STRICT RULES
═══════════════════════════════════════════════════════

• Second-person only — "you", "your", never the patient's name or "the patient"
• 6th-grade reading level — short sentences, everyday words
• Only state what is documented — no speculation, no interpretation of results
• [JARGON: term | plain_english] for every medical term in the summary
• Do NOT add UI instructions like "Tap underlined words..." — the app handles that
• Do NOT give advice beyond what the note documents

═══════════════════════════════════════════════════════
ALSO EXTRACT (for structured data)
═══════════════════════════════════════════════════════

• All prescriptions (medication, dose, frequency, instructions, duration)
• All follow-up appointments (doctor, timeframe/date, reason)
• All referrals (specialty, doctor name, reason, urgency)
• All jargon terms used in the summary

Return a single JSON object — no markdown code fences, no extra keys:
{
  "summary": "...(the structured markdown summary above)...",
  "prescriptions": [
    {"medication": "...", "dose": "...", "frequency": "...", "instructions": "...", "duration": "..."}
  ],
  "follow_up_appointments": [
    {"provider_name": "...", "specialty": "...", "date_or_timeframe": "...", "location": "...", "reason": "..."}
  ],
  "referrals": [
    {"specialty": "...", "provider_name": "...", "reason": "...", "urgency": "..."}
  ],
  "jargon_entries": [
    {"term": "...", "plain_english": "..."}
  ]
}
Omit null fields. Arrays may be empty ([]) if nothing was found.
"""


# ── Main service function ────────────────────────────────────────────────────

async def analyze_note(note_text: str) -> NoteAnalysisResult:
    """
    Analyze clinical note text and return structured results.

    Uses standard JSON-mode (response_format=json_object) so this works on any
    OpenAI project regardless of which models have beta structured-output access.
    Falls back to gpt-4o-mini if the primary model returns a 403/permission error.
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    primary_model = settings.openai_model
    # Fallback order: configured model → gpt-4o-mini
    model_candidates = list(dict.fromkeys([primary_model, "gpt-4o-mini"]))

    messages = [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {
            "role": "user",
            "content": (
                "Please analyze this clinical note and return the structured JSON result:\n\n"
                f"{note_text[:8000]}"  # Truncate to keep within context limits
            ),
        },
    ]

    last_exc: Exception | None = None
    for model in model_candidates:
        try:
            log.info("analyze_note: trying model=%s", model)
            result = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2500,
            )
            raw = result.choices[0].message.content or ""
            data = json.loads(raw)
            parsed = NoteAnalysisResult(**data)
            log.info("analyze_note: success with model=%s", model)
            return parsed
        except Exception as exc:
            err_str = str(exc)
            log.warning("analyze_note: model=%s failed — %s", model, err_str)
            last_exc = exc
            # Only retry on access/permission errors; propagate everything else
            if "model_not_found" not in err_str and "403" not in err_str and "access" not in err_str.lower():
                raise

    raise RuntimeError(
        f"No available OpenAI model could complete the note analysis. "
        f"Tried: {model_candidates}. Last error: {last_exc}"
    )


def build_action_cards(analysis: NoteAnalysisResult) -> list[dict]:
    """
    Convert analysis results into frontend action cards.

    - Each prescription → medication_reminder card (set a reminder to take it)
    - Each follow-up appointment → appointment_reminder card (add to calendar)
    - Each referral → referral_followup card (help schedule with specialist)
    """
    cards = []

    for rx in analysis.prescriptions:
        freq = f" — {rx.frequency}" if rx.frequency else ""
        dose = f" {rx.dose}" if rx.dose else ""
        instr = f". {rx.instructions}" if rx.instructions else ""
        cards.append({
            "id": f"med_reminder_{rx.medication.lower().replace(' ', '_')}",
            "type": "medication_reminder",
            "label": f"Set reminder: {rx.medication}{dose}",
            "description": f"Prescribed{freq}{instr}",
            "payload": {
                "medication": rx.medication,
                "dose": rx.dose,
                "frequency": rx.frequency,
                "instructions": rx.instructions,
                "duration": rx.duration,
            },
        })

    for appt in analysis.follow_up_appointments:
        provider = appt.provider_name or appt.specialty or "your doctor"
        timeframe = appt.date_or_timeframe or "as scheduled"
        cards.append({
            "id": f"appt_reminder_{provider.lower().replace(' ', '_')}",
            "type": "appointment_reminder",
            "label": f"Remind me: follow up with {provider}",
            "description": f"{timeframe}{' — ' + appt.reason if appt.reason else ''}",
            "payload": {
                "provider_name": appt.provider_name,
                "specialty": appt.specialty,
                "date_or_timeframe": appt.date_or_timeframe,
                "location": appt.location,
                "reason": appt.reason,
            },
        })

    for ref in analysis.referrals:
        specialist = ref.provider_name or ref.specialty
        urgency = f" ({ref.urgency})" if ref.urgency else ""
        cards.append({
            "id": f"referral_{ref.specialty.lower().replace(' ', '_')}",
            "type": "referral_followup",
            "label": f"Schedule with {specialist}{urgency}",
            "description": ref.reason or f"Referral to {ref.specialty}",
            "payload": {
                "specialty": ref.specialty,
                "provider_name": ref.provider_name,
                "reason": ref.reason,
                "urgency": ref.urgency,
            },
        })

    return cards


def build_upload_suggestions(analysis: NoteAnalysisResult) -> list[str]:
    """
    Generate 2–4 contextual quick-reply pill suggestions after an upload.

    These are deterministic (no LLM call) — derived directly from what was
    found in the analysis. Priority order:
      1. Medication reminders (one per prescription, up to 2)
      2. Follow-up appointment reminder (first one only)
      3. Referral scheduling (first one only)
      4. Universal fillers when the note has fewer structured items

    Each suggestion is written in the user's voice and capped at 60 chars.
    """
    suggestions: list[str] = []

    # ── Medication reminders ─────────────────────────────────────────────────
    for rx in analysis.prescriptions[:2]:
        med = rx.medication.strip()
        label = f"Set a reminder to take {med}"
        if len(label) > 60:
            label = "Remind me about my new medication"
        suggestions.append(label)

    # ── Follow-up appointment ─────────────────────────────────────────────────
    if analysis.follow_up_appointments:
        appt = analysis.follow_up_appointments[0]
        provider = (appt.provider_name or appt.specialty or "my doctor").strip()
        label = f"Remind me: follow up with {provider}"
        if len(label) > 60:
            label = "Remind me about my follow-up appointment"
        suggestions.append(label)

    # ── Referral scheduling ───────────────────────────────────────────────────
    if analysis.referrals and len(suggestions) < 4:
        ref = analysis.referrals[0]
        specialist = (ref.provider_name or ref.specialty).strip()
        label = f"Help me schedule with {specialist}"
        if len(label) > 60:
            label = f"Help me schedule my {ref.specialty} referral"
        if len(label) <= 60:
            suggestions.append(label)

    # ── Universal fillers ─────────────────────────────────────────────────────
    fillers = [
        "What questions should I ask at my next visit?",
        "I have more paperwork to share",
        "Can you explain anything in simpler terms?",
    ]
    for filler in fillers:
        if len(suggestions) >= 4:
            break
        suggestions.append(filler)

    return suggestions[:4]
