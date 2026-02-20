/**
 * Shared TypeScript types used across frontend and API route handlers.
 */

// ---------------------------------------------------------------------------
// Chat / Agent
// ---------------------------------------------------------------------------

export interface JargonMapping {
  term: string;
  plain_english: string;
  source_note_id: string;
  source_sentence: string;
  char_offset_start: number;
  char_offset_end: number;
}

export type IntentType =
  | "MEDICAL_ADVICE"
  | "NOTE_EXPLANATION"
  | "SCHEDULING"
  | "RECORD_LOOKUP"
  | "JARGON_EXPLAIN"
  | "PRE_VISIT_PREP"
  | "CARE_NAVIGATION"
  | "RECORD_COLLECTION"
  | "GENERAL";

export type ActionCardType =
  | "upload"
  | "email"
  | "confirm"
  | "link"
  | "medication_reminder"    // Set a reminder to take a prescribed medication
  | "appointment_reminder"   // Add a follow-up appointment to calendar + reminder
  | "referral_followup";     // Help schedule with a referred specialist

export interface ActionCard {
  id: string;
  type: ActionCardType;
  label: string;
  description: string;
  payload: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  jargon_map: JargonMapping[];
  action_cards?: ActionCard[];
  suggested_replies?: string[];   // Quick-reply pills — stored in DB for history replay
  intent?: IntentType;
  created_at: string;
}

export interface ChatSession {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  opener_message?: string;
}

// SSE event types from the backend streaming endpoint
export type SSEEvent =
  | { type: "token"; content: string }
  | { type: "jargon_map"; data: JargonMapping[] }
  | { type: "suggested_replies"; data: string[] }
  | { type: "action_cards"; data: ActionCard[] }
  | { type: "done" }
  | { type: "error"; message: string };

// ---------------------------------------------------------------------------
// Medical Records
// ---------------------------------------------------------------------------

export type RecordType =
  | "clinical_note"
  | "lab_result"
  | "discharge_summary"
  | "prescription"
  | "imaging_report";

export interface PatientRecord {
  id: string;
  record_type: RecordType;
  provider_name: string | null;
  facility_name: string | null;
  note_date: string;
  content: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Appointments
// ---------------------------------------------------------------------------

export interface Appointment {
  id: string;
  provider_name: string | null;
  facility_name: string | null;
  appointment_date: string;
  duration_minutes: number;
  notes: string | null;
  source: "manual" | "google_calendar" | "scan_to_calendar";
  phone: string | null;
  address: string | null;
  npi: string | null;
}

export interface NpiResult {
  npi: string;
  name: string;        // Provider's personal name (or org name for pure orgs)
  facility: string;    // Affiliated practice / facility name (may be empty)
  specialty: string;
  address: string;
  phone: string;
  city: string;
  state: string;
}

// OCR extraction result from Scan-to-Calendar
export interface ExtractedAppointment {
  provider_name: string | null;
  date: string | null;   // ISO 8601 string
  location: string | null;
  raw_text: string;       // Original sentence from document for user verification
}

// ---------------------------------------------------------------------------
// RBAC / Sharing
// ---------------------------------------------------------------------------

export type ShareRole = "viewer" | "editor";

export interface RecordShare {
  id: string;
  record_id: string;
  granted_to: string;    // Auth0 user ID
  role: ShareRole;
  expires_at: string | null;
  created_at: string;
}

export interface ShareGrantRequest {
  record_id: string;
  granted_to_user_id: string;
  role: ShareRole;
  expires_at?: string;
}
