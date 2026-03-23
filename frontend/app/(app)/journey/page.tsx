/**
 * My Journey — care timeline + medication tracking.
 *
 * Senior-friendly design principles:
 *  - Large headings (text-2xl+) and body text (text-sm minimum)
 *  - High contrast colors (dark on light, no low-contrast grays for important info)
 *  - Clear section labels ("Medications You Take Now", not "Active Rx")
 *  - No confusing icons without text labels
 *  - Large tap targets (48px+ for all interactive elements)
 *  - Simple visual hierarchy: medications first, then timeline below
 *
 * Layout:
 *  1. "Medications You Take Now" — card grid of active medications with dose/frequency
 *  2. "Medications You Used to Take" — collapsed section, shows discontinued meds
 *  3. "Your Care Timeline" — chronological events (visits, documents, conversations)
 */

"use client";

import { useEffect, useState } from "react";
import {
  CalendarDays,
  FileText,
  MessageCircle,
  Pill,
  Activity,
  ChevronDown,
  ChevronUp,
  Loader2,
} from "lucide-react";
import MedicationCard from "@/components/journey/MedicationCard";

// ── Types ─────────────────────────────────────────────────────────────────────

interface MedicationData {
  id: string;
  name: string;
  dose: string | null;
  frequency: string | null;
  instructions: string | null;
  status: string;
  prescribed_date: string | null;
  discontinued_date: string | null;
  predecessor_id: string | null;
}

type EntryType = "visit" | "document" | "conversation" | "medication" | "symptom";

interface TimelineEntry {
  id: string;
  type: EntryType;
  date: string;
  title: string;
  summary: string;
  source: string;
  actions?: string[];
  expandable?: boolean;
}

type FilterType = "all" | "visits" | "medications" | "symptoms" | "documents";

const TYPE_META: Record<EntryType, { icon: React.ElementType; color: string; label: string }> = {
  visit:        { icon: CalendarDays,   color: "text-brand-500 bg-brand-50",    label: "Visit" },
  document:     { icon: FileText,       color: "text-violet-500 bg-violet-50",  label: "Document" },
  conversation: { icon: MessageCircle,  color: "text-slate-400 bg-slate-50",    label: "Conversation" },
  medication:   { icon: Pill,           color: "text-emerald-500 bg-emerald-50", label: "Medication" },
  symptom:      { icon: Activity,       color: "text-amber-500 bg-amber-50",    label: "Symptom" },
};

const FILTER_LABELS: Record<FilterType, string> = {
  all:         "All",
  visits:      "Visits",
  medications: "Medications",
  symptoms:    "Symptoms",
  documents:   "Documents",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDateGroup(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatRecordType(t: string): string {
  const map: Record<string, string> = {
    clinical_note: "Clinical note",
    lab_result: "Lab result",
    discharge_summary: "Discharge summary",
    prescription: "Prescription",
    imaging_report: "Imaging report",
  };
  return map[t] ?? t;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function JourneyPage() {
  // Medications
  const [activeMeds, setActiveMeds] = useState<MedicationData[]>([]);
  const [pastMeds, setPastMeds] = useState<MedicationData[]>([]);
  const [showPastMeds, setShowPastMeds] = useState(false);
  const [medsLoading, setMedsLoading] = useState(true);

  // Timeline
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadMedications();
    loadTimeline();
  }, []);

  // ── Load medications ────────────────────────────────────────────────────────

  async function loadMedications() {
    try {
      const res = await fetch("/api/medications");
      if (res.ok) {
        const { medications = [] } = await res.json();
        setActiveMeds(medications.filter((m: MedicationData) => m.status === "active"));
        setPastMeds(medications.filter((m: MedicationData) =>
          m.status === "discontinued" || m.status === "adjusted"
        ));
      }
    } catch { /* non-blocking */ }
    setMedsLoading(false);
  }

  // ── Load timeline ──────────────────────────────────────────────────────────

  async function loadTimeline() {
    const timeline: TimelineEntry[] = [];

    try {
      const apptRes = await fetch("/api/appointments?limit=20");
      if (apptRes.ok) {
        const { appointments = [] } = await apptRes.json();
        for (const a of appointments) {
          timeline.push({
            id: `appt-${a.id}`,
            type: "visit",
            date: a.appointment_date,
            title: a.provider_name
              ? `Appointment with ${a.provider_name}`
              : "Medical appointment",
            summary: [
              a.facility_name ? `At ${a.facility_name}` : null,
              a.notes ?? null,
            ].filter(Boolean).join(" · ") || "Appointment details recorded.",
            source: `Saved from ${a.source === "scan_to_calendar" ? "scanned document" : a.source === "google_calendar" ? "Google Calendar" : "your conversation"}`,
          });
        }
      }
    } catch { /* non-blocking */ }

    try {
      const recRes = await fetch("/api/records?limit=20");
      if (recRes.ok) {
        const { records = [] } = await recRes.json();
        for (const r of records) {
          const isRx = r.record_type === "prescription";
          timeline.push({
            id: `rec-${r.id}`,
            type: isRx ? "medication" : "document",
            date: r.note_date ?? r.created_at,
            title: r.provider_name
              ? `${formatRecordType(r.record_type)} — ${r.provider_name}`
              : formatRecordType(r.record_type),
            summary: r.content?.slice(0, 200) ?? "Document stored in your records.",
            source: r.facility_name ?? "Your records",
            expandable: true,
          });
        }
      }
    } catch { /* non-blocking */ }

    try {
      const sessRes = await fetch("/api/chat/sessions");
      if (sessRes.ok) {
        const { sessions = [] } = await sessRes.json();
        for (const s of sessions.slice(0, 10)) {
          timeline.push({
            id: `sess-${s.id}`,
            type: "conversation",
            date: s.updated_at,
            title: s.title && s.title !== "New conversation" ? s.title : "Conversation with WellBridge",
            summary: "Your care team and WellBridge discussed your health. Saved to your journey.",
            source: "WellBridge conversation",
          });
        }
      }
    } catch { /* non-blocking */ }

    timeline.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    setEntries(timeline);
    setTimelineLoading(false);
  }

  // ── Filter + group timeline ────────────────────────────────────────────────

  const filtered = entries.filter((e) => {
    if (filter === "all") return true;
    if (filter === "visits") return e.type === "visit";
    if (filter === "medications") return e.type === "medication";
    if (filter === "symptoms") return e.type === "symptom";
    if (filter === "documents") return e.type === "document";
    return true;
  });

  const groups = filtered.reduce<Record<string, TimelineEntry[]>>((acc, entry) => {
    const key = formatDateGroup(entry.date);
    if (!acc[key]) acc[key] = [];
    acc[key].push(entry);
    return acc;
  }, {});

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-full bg-slate-50 p-6 md:p-10 max-w-2xl mx-auto">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-800">My Journey</h1>
        <p className="text-sm text-slate-500 mt-1">
          Your medications and care history, all in one place.
        </p>
      </div>

      {/* ════════════════════════════════════════════════════════════════════════
         MEDICATIONS SECTION
         ════════════════════════════════════════════════════════════════════════ */}

      {/* Current medications */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Pill size={18} className="text-emerald-600" />
          <h2 className="text-lg font-bold text-slate-800">
            Medications You Take Now
          </h2>
        </div>

        {medsLoading ? (
          <div className="flex items-center gap-2 text-slate-400 py-4 text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading your medications...
          </div>
        ) : activeMeds.length === 0 ? (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-6 py-8 text-center">
            <Pill size={28} className="mx-auto mb-3 text-slate-200" />
            <p className="text-sm text-slate-500 font-medium">
              No medications recorded yet.
            </p>
            <p className="text-xs text-slate-400 mt-1.5 max-w-sm mx-auto leading-relaxed">
              When you upload a clinical note or prescription, your medications
              will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {activeMeds.map((med) => (
              <MedicationCard key={med.id} medication={med} />
            ))}
          </div>
        )}
      </section>

      {/* Past medications (collapsed by default) */}
      {pastMeds.length > 0 && (
        <section className="mb-10">
          <button
            onClick={() => setShowPastMeds(!showPastMeds)}
            className="flex items-center gap-2 w-full text-left py-3 px-1
                       text-sm font-semibold text-slate-500 hover:text-slate-700
                       transition-colors"
          >
            {showPastMeds ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            Medications You Used to Take ({pastMeds.length})
          </button>

          {showPastMeds && (
            <div className="space-y-3 mt-2">
              {pastMeds.map((med) => (
                <MedicationCard key={med.id} medication={med} isPast />
              ))}
            </div>
          )}
        </section>
      )}

      {/* ════════════════════════════════════════════════════════════════════════
         CARE TIMELINE
         ════════════════════════════════════════════════════════════════════════ */}

      <section>
        <h2 className="text-lg font-bold text-slate-800 mb-4">
          Your Care Timeline
        </h2>

        {/* Filter tabs */}
        <div className="flex gap-2 mb-5 flex-wrap">
          {(Object.keys(FILTER_LABELS) as FilterType[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
                filter === f
                  ? "bg-brand-600 text-white"
                  : "bg-white text-slate-500 border border-slate-200 hover:border-brand-300 hover:text-brand-600"
              }`}
            >
              {FILTER_LABELS[f]}
            </button>
          ))}
        </div>

        {/* Timeline entries */}
        {timelineLoading ? (
          <div className="flex items-center gap-2 text-slate-400 py-8 text-sm">
            <Loader2 size={16} className="animate-spin" />
            Building your timeline...
          </div>
        ) : filtered.length === 0 ? (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-6 py-10 text-center">
            <MessageCircle size={32} className="mx-auto mb-3 text-slate-200" />
            <p className="text-sm font-medium text-slate-500">
              Your journey starts with a conversation.
            </p>
            <p className="text-xs text-slate-400 mt-2 max-w-xs mx-auto leading-relaxed">
              Everything you tell WellBridge — appointments, medications, visits — will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="space-y-8">
            {Object.entries(groups).map(([dateLabel, dayEntries]) => (
              <div key={dateLabel}>
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    {dateLabel}
                  </span>
                  <div className="flex-1 h-px bg-slate-200" />
                </div>

                <div className="space-y-2">
                  {dayEntries.map((entry) => {
                    const meta = TYPE_META[entry.type];
                    const Icon = meta.icon;
                    const isExpanded = expanded.has(entry.id);

                    return (
                      <div
                        key={entry.id}
                        className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden"
                      >
                        <div className="flex items-start gap-3 px-4 py-3.5">
                          <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${meta.color}`}>
                            <Icon size={16} />
                          </div>

                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">
                                  {meta.label}
                                </span>
                                <p className="text-sm font-semibold text-slate-800 mt-0.5 leading-snug">
                                  {entry.title}
                                </p>
                              </div>
                              <span className="text-xs text-slate-400 flex-shrink-0 mt-0.5">
                                {formatTime(entry.date)}
                              </span>
                            </div>

                            <p className={`text-sm text-slate-500 mt-1.5 leading-relaxed ${
                              !isExpanded && entry.summary.length > 100 ? "line-clamp-2" : ""
                            }`}>
                              {entry.summary}
                            </p>

                            {isExpanded && entry.actions && entry.actions.length > 0 && (
                              <div className="mt-2 pt-2 border-t border-slate-100">
                                <p className="text-xs font-medium text-slate-500 mb-1">Actions</p>
                                <ul className="space-y-1">
                                  {entry.actions.map((a, i) => (
                                    <li key={i} className="flex items-center gap-1.5 text-sm text-slate-500">
                                      <span className="w-1.5 h-1.5 rounded-full bg-slate-300 flex-shrink-0" />
                                      {a}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {isExpanded && (
                              <p className="text-xs text-slate-400 mt-2">
                                Source: {entry.source}
                              </p>
                            )}

                            {(entry.expandable || entry.summary.length > 100) && (
                              <button
                                onClick={() => toggle(entry.id)}
                                className="flex items-center gap-1 text-sm text-brand-500 mt-2
                                           hover:text-brand-700 transition-colors py-1"
                              >
                                {isExpanded ? (
                                  <><ChevronUp size={14} /> Show less</>
                                ) : (
                                  <><ChevronDown size={14} /> Show more</>
                                )}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
