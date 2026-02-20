"use client";

/**
 * CalendarConfirmDialog — shows extracted appointments for user review.
 *
 * The user sees the extracted data alongside the exact sentence from the
 * document (raw_text) so they can verify accuracy before confirming.
 * Confirmed appointments are POSTed to /api/backend/ocr/confirm-appointment.
 */

import { useState } from "react";
import { Check, X, Calendar, AlertCircle, Loader2 } from "lucide-react";
import type { ExtractedAppointment } from "@/lib/types";
import { isMobile, generateAppointmentICS, downloadICS } from "@/lib/calendarUtils";

interface CalendarConfirmDialogProps {
  appointments: ExtractedAppointment[];
  onDismiss: () => void;
}

export default function CalendarConfirmDialog({
  appointments,
  onDismiss,
}: CalendarConfirmDialogProps) {
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState<Set<number>>(new Set());
  const [saved, setSaved] = useState<Set<number>>(new Set());
  const [errors, setErrors] = useState<Map<number, string>>(new Map());
  const mobile = isMobile();

  const handleConfirm = async (idx: number, appt: ExtractedAppointment) => {
    setSaving((prev) => new Set([...prev, idx]));
    setErrors((prev) => { const m = new Map(prev); m.delete(idx); return m; });

    try {
      if (isMobile()) {
        // Mobile: generate ICS and hand off to native Calendar app
        const ics = generateAppointmentICS({
          provider: appt.provider_name ?? undefined,
          date: appt.date ?? undefined,
          location: appt.location ?? undefined,
        });
        const filename = appt.provider_name
          ? `appt-${appt.provider_name.replace(/\s+/g, "-")}`
          : "appointment";
        downloadICS(filename, ics);
        setSaved((prev) => new Set([...prev, idx]));
      } else {
        // Desktop: POST to backend → Google Calendar
        const res = await fetch("/api/backend/ocr/confirm-appointment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_name: appt.provider_name,
            date: appt.date,
            location: appt.location,
            raw_text: appt.raw_text,
          }),
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Failed to save" }));
          throw new Error(err.detail);
        }

        setSaved((prev) => new Set([...prev, idx]));
      }
    } catch (err) {
      setErrors((prev) => {
        const m = new Map(prev);
        m.set(idx, err instanceof Error ? err.message : "Save failed");
        return m;
      });
    } finally {
      setSaving((prev) => { const s = new Set(prev); s.delete(idx); return s; });
    }
  };

  if (!appointments.length) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center">
        <AlertCircle className="mx-auto text-slate-300 mb-3" size={32} />
        <p className="font-medium text-slate-600">No follow-up dates found</p>
        <p className="text-sm text-slate-400 mt-1">
          I couldn't find any follow-up appointment instructions in this document.
        </p>
        <button
          onClick={onDismiss}
          className="mt-4 text-sm text-brand-600 hover:underline"
        >
          Try another document
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Calendar size={20} className="text-brand-600" />
          <h3 className="font-semibold text-slate-800">
            Found {appointments.length} follow-up appointment(s)
          </h3>
        </div>
        <button
          onClick={onDismiss}
          className="text-slate-400 hover:text-slate-600 rounded-lg p-1"
        >
          <X size={18} />
        </button>
      </div>

      <div className="divide-y divide-slate-100">
        {appointments.map((appt, idx) => (
          <div key={idx} className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                {/* Appointment details */}
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-slate-800">
                    {appt.provider_name ?? "Medical Follow-up"}
                  </span>
                  {appt.date && (
                    <span className="text-xs bg-brand-50 text-brand-700 rounded-full px-2 py-0.5 font-medium">
                      {new Date(appt.date).toLocaleDateString("en-US", {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </span>
                  )}
                </div>

                {/* Source sentence for verification */}
                <p className="text-xs text-slate-400 mb-2">From document:</p>
                <blockquote className="text-sm text-slate-600 italic border-l-2 border-slate-200 pl-3">
                  "{appt.raw_text}"
                </blockquote>

                {errors.get(idx) && (
                  <p className="mt-2 text-xs text-red-600">{errors.get(idx)}</p>
                )}
              </div>

              {/* Action button */}
              <div className="flex-shrink-0">
                {saved.has(idx) ? (
                  <div className="flex items-center gap-1.5 text-green-600 text-sm font-medium">
                    <Check size={16} />
                    Added
                  </div>
                ) : (
                  <button
                    onClick={() => handleConfirm(idx, appt)}
                    disabled={saving.has(idx)}
                    className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white
                               rounded-xl text-sm font-medium hover:bg-brand-700 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {saving.has(idx) ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        {mobile ? "Opening..." : "Saving..."}
                      </>
                    ) : (
                      <>
                        <Calendar size={14} />
                        {mobile ? "Open in Calendar" : "Add to Calendar"}
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="px-6 py-3 bg-slate-50 border-t border-slate-100">
        <p className="text-xs text-slate-400 text-center">
          Please verify the extracted details match your document before confirming.
        </p>
      </div>
    </div>
  );
}
