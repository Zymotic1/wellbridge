/**
 * My Journey — auto-assembled care timeline.
 *
 * The wireframe describes this as "a living medical diary that assembles
 * itself automatically from conversations, documents, recordings, and events."
 *
 * Key principles (from wireframe slide 7):
 *  - The patient does NOT maintain it or organize it
 *  - Every meaningful moment in care becomes a timeline entry
 *  - Each entry has: When, Type, Summary, Actions, Source
 *  - Filters: All, Visits, Medications, Symptoms, Documents
 *  - "Conversation creates structure. Memory becomes record."
 *
 * This page pulls data from:
 *  - appointments (visits, surgeries)
 *  - patient_records (documents, notes)
 *  - chat_sessions (conversations — each is a care moment)
 * and merges them into a single chronological narrative.
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
  visit:        { icon: CalendarDays,   color: "text-brand-500 bg-brand-50",   label: "Visit" },
  document:     { icon: FileText,       color: "text-violet-500 bg-violet-50",  label: "Document" },
  conversation: { icon: MessageCircle,  color: "text-slate-400 bg-slate-50",   label: "Conversation" },
  medication:   { icon: Pill,           color: "text-emerald-500 bg-emerald-50", label: "Medication" },
  symptom:      { icon: Activity,       color: "text-amber-500 bg-amber-50",   label: "Symptom" },
};

const FILTER_LABELS: Record<FilterType, string> = {
  all:          "All",
  visits:       "Visits",
  medications:  "Medications",
  symptoms:     "Symptoms",
  documents:    "Documents",
};

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
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function JourneyPage() {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    loadJourney();
  }, []);

  async function loadJourney() {
    const timeline: TimelineEntry[] = [];

    try {
      // Fetch appointments
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
      // Fetch patient records
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
      // Fetch conversations (as care moments)
      const sessRes = await fetch("/api/chat/sessions");
      if (sessRes.ok) {
        const { sessions = [] } = await sessRes.json();
        for (const s of sessions.slice(0, 10)) {
          timeline.push({
            id: `sess-${s.id}`,
            type: "conversation",
            date: s.updated_at,
            title: s.title && s.title !== "New conversation"
              ? s.title
              : "Conversation with WellBridge",
            summary: "Your care team and WellBridge discussed your health. Saved to your journey.",
            source: "WellBridge conversation",
          });
        }
      }
    } catch { /* non-blocking */ }

    // Sort by date, newest first
    timeline.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    setEntries(timeline);
    setLoading(false);
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

  const filtered = entries.filter((e) => {
    if (filter === "all") return true;
    if (filter === "visits") return e.type === "visit";
    if (filter === "medications") return e.type === "medication";
    if (filter === "symptoms") return e.type === "symptom";
    if (filter === "documents") return e.type === "document";
    return true;
  });

  // Group by date
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

  return (
    <div className="min-h-full bg-slate-50 p-6 md:p-10 max-w-2xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-800">My Journey</h1>
        <p className="text-slate-400 text-sm mt-1">
          Your care history — assembled automatically from your conversations, documents, and appointments.
        </p>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1.5 mb-6 flex-wrap">
        {(Object.keys(FILTER_LABELS) as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f
                ? "bg-brand-600 text-white"
                : "bg-white text-slate-500 border border-slate-200 hover:border-brand-300 hover:text-brand-600"
            }`}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
      </div>

      {/* Timeline */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 py-8">
          <Loader2 size={16} className="animate-spin" />
          Building your journey...
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-6 py-10 text-center">
          <MessageCircle size={32} className="mx-auto mb-3 text-slate-200" />
          <p className="text-sm font-medium text-slate-500">
            Your journey starts with a conversation.
          </p>
          <p className="text-xs text-slate-300 mt-2 max-w-xs mx-auto">
            Everything you tell WellBridge — appointments, medications, visits — will appear here automatically.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(groups).map(([dateLabel, dayEntries]) => (
            <div key={dateLabel}>
              {/* Date group label */}
              <div className="flex items-center gap-3 mb-3">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  {dateLabel}
                </span>
                <div className="flex-1 h-px bg-slate-200" />
              </div>

              {/* Entries */}
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
                        {/* Type icon */}
                        <div className={`w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 ${meta.color}`}>
                          <Icon size={15} />
                        </div>

                        {/* Content */}
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

                          {/* Summary — always shown */}
                          <p className={`text-xs text-slate-500 mt-1.5 leading-relaxed ${
                            !isExpanded && entry.summary.length > 100 ? "line-clamp-2" : ""
                          }`}>
                            {entry.summary}
                          </p>

                          {/* Actions */}
                          {isExpanded && entry.actions && entry.actions.length > 0 && (
                            <div className="mt-2 pt-2 border-t border-slate-100">
                              <p className="text-xs font-medium text-slate-500 mb-1">Actions</p>
                              <ul className="space-y-1">
                                {entry.actions.map((a, i) => (
                                  <li key={i} className="flex items-center gap-1.5 text-xs text-slate-500">
                                    <span className="w-1 h-1 rounded-full bg-slate-300 flex-shrink-0" />
                                    {a}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {/* Source */}
                          {isExpanded && (
                            <p className="text-xs text-slate-300 mt-2">
                              Source: {entry.source}
                            </p>
                          )}

                          {/* Expand toggle */}
                          {entry.expandable || entry.summary.length > 100 ? (
                            <button
                              onClick={() => toggle(entry.id)}
                              className="flex items-center gap-1 text-xs text-brand-500 mt-2
                                         hover:text-brand-700 transition-colors"
                            >
                              {isExpanded ? (
                                <><ChevronUp size={12} /> Show less</>
                              ) : (
                                <><ChevronDown size={12} /> Show more</>
                              )}
                            </button>
                          ) : null}
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
    </div>
  );
}
