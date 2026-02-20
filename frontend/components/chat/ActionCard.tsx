"use client";

/**
 * ActionCard — interactive card rendered below assistant messages.
 *
 * Card types:
 *  - upload:               opens the system file picker, fires onUpload(file)
 *  - email:                shows an email template modal with copy-to-clipboard
 *  - link:                 navigates to a route in the app
 *  - confirm:              triggers a callback action
 *  - medication_reminder:  shows medication details + reminder setup guidance
 *  - appointment_reminder: shows follow-up appointment details
 *  - referral_followup:    shows referral details + scheduling guidance
 */

import { useState, useRef } from "react";
import {
  Upload, Mail, ExternalLink, Check, Copy, X,
  Pill, CalendarClock, UserRound, Calendar, Download,
} from "lucide-react";
import type { ActionCard as ActionCardType } from "@/lib/types";
import {
  isMobile,
  generateMedicationICS,
  generateAppointmentICS,
  downloadICS,
  openGoogleCalendar,
} from "@/lib/calendarUtils";

interface ActionCardProps {
  card: ActionCardType;
  onUpload?: (file: File) => void;
}

const iconMap: Record<string, React.ElementType> = {
  upload: Upload,
  email: Mail,
  link: ExternalLink,
  confirm: Check,
  medication_reminder: Pill,
  appointment_reminder: CalendarClock,
  referral_followup: UserRound,
};

const colorMap: Record<string, { bg: string; border: string; icon: string; text: string }> = {
  medication_reminder:  { bg: "bg-violet-50", border: "border-violet-200", icon: "bg-violet-100 text-violet-600", text: "text-violet-700" },
  appointment_reminder: { bg: "bg-teal-50",   border: "border-teal-200",   icon: "bg-teal-100 text-teal-600",    text: "text-teal-700"   },
  referral_followup:    { bg: "bg-amber-50",  border: "border-amber-200",  icon: "bg-amber-100 text-amber-600",  text: "text-amber-700"  },
};
const defaultColor = { bg: "bg-brand-50", border: "border-brand-200", icon: "bg-brand-100 text-brand-600", text: "text-brand-700" };
function getColor(type: string) { return colorMap[type] ?? defaultColor; }


// ── Shared modal shell ───────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-lg p-6 z-10">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-slate-800">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500 uppercase tracking-wide mb-0.5">{label}</p>
      <p className="text-sm text-slate-800">{value}</p>
    </div>
  );
}


// ── Detail modals for each new card type ─────────────────────────────────────

function MedicationModal({ card, onClose }: { card: ActionCardType; onClose: () => void }) {
  const p = card.payload;
  const mobile = isMobile();

  function handleAddToCalendar() {
    const ics = generateMedicationICS({
      medication: String(p.medication ?? "Medication"),
      dose: p.dose ? String(p.dose) : undefined,
      frequency: p.frequency ? String(p.frequency) : undefined,
      instructions: p.instructions ? String(p.instructions) : undefined,
    });
    downloadICS(`reminder-${String(p.medication ?? "medication").replace(/\s+/g, "-")}`, ics);
  }

  function handleGoogleCalendar() {
    const med = String(p.medication ?? "Medication");
    const now = new Date();
    now.setDate(now.getDate() + (now.getHours() >= 8 ? 1 : 0));
    now.setHours(8, 0, 0, 0);
    const end = new Date(now.getTime() + 15 * 60 * 1000);
    const details = [
      p.dose ? `Dose: ${p.dose}` : "",
      p.frequency ? `Frequency: ${p.frequency}` : "",
      p.instructions ? `Instructions: ${p.instructions}` : "",
    ].filter(Boolean).join("\n");
    openGoogleCalendar({ title: `Take ${med}`, startDate: now, endDate: end, details });
  }

  return (
    <Modal title="Medication reminder" onClose={onClose}>
      <div className="space-y-3 mb-4">
        <Row label="Medication" value={String(p.medication ?? "")} />
        {p.dose         && <Row label="Dose"           value={String(p.dose)} />}
        {p.frequency    && <Row label="When to take"   value={String(p.frequency)} />}
        {p.instructions && <Row label="Instructions"   value={String(p.instructions)} />}
        {p.duration     && <Row label="Duration"       value={String(p.duration)} />}
      </div>

      {/* Calendar actions */}
      {mobile ? (
        <button
          onClick={handleAddToCalendar}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                     bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
        >
          <Calendar size={15} />
          Add Reminder to Calendar
        </button>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={handleGoogleCalendar}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                       bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            <Calendar size={15} />
            Google Calendar
          </button>
          <button
            onClick={handleAddToCalendar}
            className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                       border border-violet-200 text-violet-700 text-sm font-medium
                       hover:bg-violet-50 transition-colors"
            title="Download .ics file"
          >
            <Download size={15} />
            .ics
          </button>
        </div>
      )}

      <p className="text-xs text-slate-400 mt-2">
        {mobile
          ? "Opens your device's Calendar app."
          : "Google Calendar opens in a new tab. Use .ics to import into Apple Calendar or Outlook."}
      </p>
    </Modal>
  );
}

function AppointmentModal({ card, onClose }: { card: ActionCardType; onClose: () => void }) {
  const p = card.payload;
  const mobile = isMobile();

  // date_or_timeframe may be an ISO string or a natural-language phrase
  const dateStr = p.date_or_timeframe ? String(p.date_or_timeframe) : undefined;

  function handleAddToCalendar() {
    const ics = generateAppointmentICS({
      provider: p.provider_name ? String(p.provider_name) : undefined,
      specialty: p.specialty ? String(p.specialty) : undefined,
      date: dateStr,
      reason: p.reason ? String(p.reason) : undefined,
      location: p.location ? String(p.location) : undefined,
    });
    const who = (p.provider_name ?? p.specialty ?? "appointment") as string;
    downloadICS(`appt-${who.replace(/\s+/g, "-")}`, ics);
  }

  function handleGoogleCalendar() {
    const who = (p.provider_name ?? p.specialty ?? "your doctor") as string;
    // Best-effort date: try ISO parse, fall back to 1 week from now at 9 AM
    let start = new Date();
    if (dateStr && !isNaN(new Date(dateStr).getTime())) {
      start = new Date(dateStr);
      if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) start.setHours(9, 0, 0, 0);
    } else {
      start.setDate(start.getDate() + 7);
      start.setHours(9, 0, 0, 0);
    }
    const end = new Date(start.getTime() + 60 * 60 * 1000);
    openGoogleCalendar({
      title: `Appointment with ${who}`,
      startDate: start,
      endDate: end,
      details: p.reason ? String(p.reason) : undefined,
      location: p.location ? String(p.location) : undefined,
    });
  }

  return (
    <Modal title="Follow-up appointment" onClose={onClose}>
      <div className="space-y-3 mb-4">
        {p.provider_name    && <Row label="Doctor"    value={String(p.provider_name)} />}
        {p.specialty        && <Row label="Specialty" value={String(p.specialty)} />}
        {p.date_or_timeframe && <Row label="When"     value={String(p.date_or_timeframe)} />}
        {p.location         && <Row label="Location"  value={String(p.location)} />}
        {p.reason           && <Row label="Reason"    value={String(p.reason)} />}
      </div>

      {/* Calendar actions */}
      {mobile ? (
        <button
          onClick={handleAddToCalendar}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                     bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 transition-colors"
        >
          <Calendar size={15} />
          Add to Calendar
        </button>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={handleGoogleCalendar}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                       bg-teal-600 text-white text-sm font-medium hover:bg-teal-700 transition-colors"
          >
            <Calendar size={15} />
            Google Calendar
          </button>
          <button
            onClick={handleAddToCalendar}
            className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                       border border-teal-200 text-teal-700 text-sm font-medium
                       hover:bg-teal-50 transition-colors"
            title="Download .ics file"
          >
            <Download size={15} />
            .ics
          </button>
        </div>
      )}

      <p className="text-xs text-slate-400 mt-2">
        {mobile
          ? "Opens your device's Calendar app. Book with your clinic first."
          : "Google Calendar opens in a new tab. Use .ics for Apple Calendar or Outlook."}
      </p>
    </Modal>
  );
}

function ReferralModal({ card, onClose }: { card: ActionCardType; onClose: () => void }) {
  const p = card.payload;
  return (
    <Modal title="Referral" onClose={onClose}>
      <div className="space-y-3 mb-4">
        <Row label="Specialist type" value={String(p.specialty ?? "")} />
        {p.provider_name && <Row label="Referred to" value={String(p.provider_name)} />}
        {p.reason        && <Row label="Reason"      value={String(p.reason)} />}
        {p.urgency       && <Row label="Urgency"     value={String(p.urgency)} />}
      </div>
      <p className="text-xs text-slate-500">
        The referring doctor&apos;s office will usually send the referral letter directly.
        Once you have a referral number, you can call the specialist to book.
      </p>
    </Modal>
  );
}


// ── Main component ────────────────────────────────────────────────────────────

export default function ActionCard({ card, onUpload }: ActionCardProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const Icon = iconMap[card.type] ?? ExternalLink;
  const color = getColor(card.type);

  function handleClick() {
    switch (card.type) {
      case "upload":
        fileInputRef.current?.click();
        break;
      case "email":
        setEmailOpen(true);
        break;
      case "link": {
        const href = card.payload?.href as string | undefined;
        if (href) window.location.href = href;
        break;
      }
      case "medication_reminder":
      case "appointment_reminder":
      case "referral_followup":
        setModalOpen(true);
        break;
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file && onUpload) onUpload(file);
    e.target.value = "";
  }

  async function copyTemplate() {
    const template = card.payload?.template as string | undefined;
    if (!template) return;
    await navigator.clipboard.writeText(template);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <>
      {/* Card button */}
      <button
        onClick={handleClick}
        className={`flex items-center gap-3 w-full max-w-xs rounded-xl border ${color.border}
                   ${color.bg} px-4 py-3 text-left transition-all
                   hover:brightness-95 focus:outline-none focus:ring-2 focus:ring-brand-500`}
      >
        <span className={`flex-shrink-0 w-8 h-8 rounded-full ${color.icon} flex items-center justify-center`}>
          <Icon size={16} />
        </span>
        <span className="flex-1 min-w-0">
          <span className={`block text-sm font-medium ${color.text}`}>{card.label}</span>
          <span className="block text-xs text-slate-500 mt-0.5 line-clamp-2">{card.description}</span>
        </span>
      </button>

      {/* Hidden file input */}
      {card.type === "upload" && (
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.doc,.txt,.rtf,.png,.jpg,.jpeg,.tiff,.tif,.heic,.bmp,.mp3,.mp4,.m4a,.wav,.webm"
          className="hidden"
          onChange={handleFileChange}
        />
      )}

      {/* Medication reminder modal */}
      {modalOpen && card.type === "medication_reminder" && (
        <MedicationModal card={card} onClose={() => setModalOpen(false)} />
      )}

      {/* Follow-up appointment modal */}
      {modalOpen && card.type === "appointment_reminder" && (
        <AppointmentModal card={card} onClose={() => setModalOpen(false)} />
      )}

      {/* Referral modal */}
      {modalOpen && card.type === "referral_followup" && (
        <ReferralModal card={card} onClose={() => setModalOpen(false)} />
      )}

      {/* Email template modal */}
      {emailOpen && card.type === "email" && (
        <Modal title="Email template" onClose={() => setEmailOpen(false)}>
          <p className="text-xs text-slate-500 mb-3">
            Copy this template and send it to your provider&apos;s records department.
          </p>
          <pre className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs
                          text-slate-700 whitespace-pre-wrap leading-relaxed mb-4 font-sans">
            {card.payload?.template as string}
          </pre>
          <button
            onClick={copyTemplate}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white
                       rounded-xl text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
            {copied ? "Copied!" : "Copy to clipboard"}
          </button>
        </Modal>
      )}
    </>
  );
}
