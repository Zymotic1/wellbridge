"use client";

/**
 * MedicationCard — displays a single medication with dose, frequency,
 * and expandable dose history.
 *
 * Senior-friendly design principles:
 *  - Large, readable text (16px+ for medication name, 14px for details)
 *  - High contrast (dark text on white/light backgrounds)
 *  - Clear labels ("What you take", "How often", not medical shorthand)
 *  - Large tap targets (48px+ buttons)
 *  - No ambiguous icons — text labels on everything
 *  - Expandable dose history uses clear "View dose history" text, not a tiny chevron
 */

import { useState } from "react";
import { Pill, Clock, ChevronDown, ChevronUp } from "lucide-react";

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
  created_at?: string;
}

interface MedicationCardProps {
  medication: MedicationData;
  /** If true, shows a "Discontinued" badge instead of active styling */
  isPast?: boolean;
}

export default function MedicationCard({ medication, isPast }: MedicationCardProps) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<MedicationData[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const hasHistory = medication.predecessor_id !== null;

  async function loadHistory() {
    if (history.length > 0) {
      setHistoryOpen(!historyOpen);
      return;
    }
    setLoadingHistory(true);
    try {
      const res = await fetch(`/api/medications?status=adjusted`);
      if (res.ok) {
        const data = await res.json();
        // Filter to same medication name, sort by date
        const chain = (data.medications || [])
          .filter((m: MedicationData) => m.name.toLowerCase() === medication.name.toLowerCase())
          .sort((a: MedicationData, b: MedicationData) =>
            new Date(a.created_at || a.prescribed_date || "").getTime() -
            new Date(b.created_at || b.prescribed_date || "").getTime()
          );
        setHistory(chain);
      }
    } catch { /* non-blocking */ }
    setLoadingHistory(false);
    setHistoryOpen(true);
  }

  function formatDate(iso: string | null): string {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
  }

  return (
    <div className={`rounded-2xl border shadow-sm overflow-hidden ${
      isPast
        ? "bg-slate-50 border-slate-200"
        : "bg-white border-slate-200"
    }`}>
      <div className="p-5">
        {/* Medication name — large and bold */}
        <div className="flex items-start gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
            isPast ? "bg-slate-100 text-slate-400" : "bg-emerald-50 text-emerald-600"
          }`}>
            <Pill size={20} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className={`text-base font-bold leading-tight ${
                isPast ? "text-slate-400" : "text-slate-800"
              }`}>
                {medication.name}
              </h3>
              {isPast && (
                <span className="px-2 py-0.5 rounded-full bg-slate-200 text-slate-500 text-xs font-medium">
                  No longer taking
                </span>
              )}
            </div>

            {/* Dose */}
            {medication.dose && (
              <p className={`text-sm mt-1.5 ${isPast ? "text-slate-400" : "text-slate-700"}`}>
                <span className="font-medium text-slate-500">Dose:</span>{" "}
                <span className="font-semibold">{medication.dose}</span>
              </p>
            )}

            {/* Frequency — use friendly language */}
            {medication.frequency && (
              <p className={`text-sm mt-1 flex items-center gap-1.5 ${
                isPast ? "text-slate-400" : "text-slate-600"
              }`}>
                <Clock size={13} className="flex-shrink-0" />
                <span>{medication.frequency}</span>
              </p>
            )}

            {/* Instructions */}
            {medication.instructions && (
              <p className={`text-sm mt-1 italic ${isPast ? "text-slate-300" : "text-slate-500"}`}>
                {medication.instructions}
              </p>
            )}

            {/* Date prescribed */}
            {medication.prescribed_date && (
              <p className="text-xs text-slate-400 mt-2">
                {isPast && medication.discontinued_date
                  ? `Prescribed ${formatDate(medication.prescribed_date)} · Stopped ${formatDate(medication.discontinued_date)}`
                  : `Prescribed ${formatDate(medication.prescribed_date)}`
                }
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Dose history toggle */}
      {hasHistory && !isPast && (
        <div className="border-t border-slate-100">
          <button
            onClick={loadHistory}
            className="w-full flex items-center justify-center gap-2 px-5 py-3
                       text-sm text-brand-600 font-medium hover:bg-brand-50
                       transition-colors"
          >
            {loadingHistory ? (
              "Loading..."
            ) : historyOpen ? (
              <><ChevronUp size={16} /> Hide dose history</>
            ) : (
              <><ChevronDown size={16} /> View dose history</>
            )}
          </button>

          {historyOpen && history.length > 0 && (
            <div className="px-5 pb-4 space-y-2">
              {history.map((h) => (
                <div
                  key={h.id}
                  className="flex items-center gap-3 pl-3 border-l-2 border-slate-200"
                >
                  <div className="flex-1">
                    <p className="text-sm text-slate-500">
                      <span className="font-medium">{h.dose || "Dose not recorded"}</span>
                      {h.frequency && <span className="text-slate-400"> · {h.frequency}</span>}
                    </p>
                    {h.prescribed_date && (
                      <p className="text-xs text-slate-400">{formatDate(h.prescribed_date)}</p>
                    )}
                  </div>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-400 flex-shrink-0">
                    Previous dose
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
