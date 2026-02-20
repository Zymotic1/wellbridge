"""
AgentState — the single source of truth flowing through every LangGraph node.

Key design decisions:
  - tenant_id and user_id are injected at the graph entry point and treated
    as immutable throughout the graph. No node should ever modify these.
  - jargon_map carries character-offset annotations produced by note_summarizer
    and consumed by the frontend JargonHighlighter component.
  - refusal_context_facts holds documented facts from the patient's own records
    shown alongside a MEDICAL_ADVICE refusal, making the refusal still useful.
  - raw_response is the pre-guardrail LLM output; final_response is post-guardrail.
    Only final_response is ever sent to the frontend.
  - emotional_state and care_stage are assessed early and influence how every
    downstream node frames its response — tone, pacing, question count.
  - care_context accumulates facts extracted from conversation so the user
    never has to repeat themselves across turns.
  - action_cards are structured prompts returned alongside the text response
    that the frontend renders as interactive cards (upload, email, confirm).
"""

from typing import TypedDict, Literal, Optional
from langgraph.graph import MessagesState

IntentType = Literal[
    "MEDICAL_ADVICE",    # Advice/diagnosis/prognosis — always refused, no LLM
    "NOTE_EXPLANATION",  # "I don't understand what my doctor told me" — look up + explain
    "SCHEDULING",
    "RECORD_LOOKUP",
    "JARGON_EXPLAIN",
    "PRE_VISIT_PREP",
    "CARE_NAVIGATION",   # Proactive: user navigating their care journey
    "RECORD_COLLECTION", # Proactive: user mentioned a document/visit we should collect
    "GENERAL",
]

EmotionalState = Literal[
    "anxious",    # Scared, overwhelmed, uncertain — go slow, ask fewer questions
    "confused",   # Needs clarity and simple framing
    "engaged",    # Active, curious, ready for information
    "calm",       # Neutral, matter-of-fact
]

CareStage = Literal[
    "unknown",       # Not yet determined from conversation
    "pre-visit",     # Upcoming appointment, preparing
    "post-visit",    # Just had an appointment, processing info
    "pre-surgery",   # Awaiting a procedure
    "post-surgery",  # Recovery phase
    "treatment",     # Ongoing treatment / medication management
    "diagnosis",     # Recently received a diagnosis
]


class JargonMapping(TypedDict):
    """
    Maps a highlighted term in the assistant response to its source in clinical notes.
    char_offset_start / char_offset_end index into the final_response string.
    """
    term: str                   # e.g., "patellofemoral syndrome"
    plain_english: str          # e.g., "knee cap pain"
    source_note_id: str         # UUID of the patient_records row
    source_sentence: str        # Exact sentence from the original note
    char_offset_start: int      # Byte offset in final_response
    char_offset_end: int


class ActionCard(TypedDict):
    """
    Structured action prompt rendered by the frontend as an interactive card.
    Allows the agent to request specific actions from the user without forms.
    """
    id: str               # e.g., "upload_records", "email_records"
    type: str             # "upload" | "email" | "confirm" | "link"
    label: str            # Button text, e.g., "Upload a document"
    description: str      # Supporting text shown below label
    payload: dict         # Type-specific data (email template, link href, etc.)


class AgentState(MessagesState):
    # ---- Routing (set by intent_classifier, never modified after) ----
    intent: Optional[IntentType]
    confidence: float

    # ---- Tenant context (injected at graph entry, immutable) ----
    tenant_id: str
    user_id: str
    role: str           # "patient" | "caregiver" | "admin"

    # ---- Current chat session ----
    session_id: str

    # ---- Emotional intelligence (set by emotional_assessor, used downstream) ----
    emotional_state: EmotionalState          # Shapes tone and pacing
    care_stage: CareStage                    # Where in the care journey they are
    care_context: dict                       # Accumulated facts from conversation

    # ---- Tool outputs ----
    records: list          # list[dict] — patient_records rows from Supabase
    appointments: list     # list[dict] — upcoming appointments
    tool_error: Optional[str]

    # ---- Response assembly ----
    raw_response: Optional[str]    # LLM output before guardrail pass
    final_response: Optional[str]  # Guardrail-approved output (sent to frontend)
    jargon_map: list               # list[JargonMapping] — for hover feature
    action_cards: list             # list[ActionCard] — interactive prompts for user
    suggested_replies: list        # list[str] — AI-generated quick-reply pills (ephemeral, not persisted)

    # ---- Refusal context ----
    # Documented facts from patient's own records shown alongside refusal
    refusal_context_facts: list    # list[str]
