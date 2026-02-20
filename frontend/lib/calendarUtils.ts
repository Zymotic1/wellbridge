/**
 * calendarUtils — device-aware calendar event creation.
 *
 * Mobile (iOS / Android):
 *   Downloads / opens an .ics file which triggers the native Calendar app
 *   to import the event. No backend call required.
 *
 * Desktop:
 *   Opens Google Calendar web in a new tab with a pre-filled event form
 *   AND offers an ICS file download as a fallback.
 */

// ── Device detection ──────────────────────────────────────────────────────────

export type DeviceType = "ios" | "android" | "desktop";

export function getDeviceType(): DeviceType {
  if (typeof navigator === "undefined") return "desktop";
  const ua = navigator.userAgent.toLowerCase();
  if (/ipad|iphone|ipod/.test(ua)) return "ios";
  if (/android/.test(ua)) return "android";
  return "desktop";
}

export function isMobile(): boolean {
  const d = getDeviceType();
  return d === "ios" || d === "android";
}

// ── ICS helpers ───────────────────────────────────────────────────────────────

/** Pad a number to 2 digits. */
const pad = (n: number) => String(n).padStart(2, "0");

/** Format a Date as YYYYMMDDTHHMMSS (local time). */
function icsDateTime(d: Date): string {
  return (
    `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}` +
    `T${pad(d.getHours())}${pad(d.getMinutes())}00`
  );
}

/** Format a Date as YYYYMMDD (all-day event). */
function icsDateOnly(d: Date): string {
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

/** Escape special characters in ICS text fields (RFC 5545). */
function icsEscape(s: string): string {
  return s
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\n|\r\n/g, "\\n");
}

/** Parse a free-text frequency string into an ICS RRULE line, or null for PRN. */
function frequencyToRRule(frequency: string): string | null {
  const f = frequency.toLowerCase();
  if (/as.?needed|prn|when.?needed/.test(f)) return null;
  if (/4.?times|four.?times|every.?6.?hour/.test(f))
    return "RRULE:FREQ=DAILY;BYHOUR=8,12,16,20;BYMINUTE=0;BYSECOND=0";
  if (/3.?times|three.?times|every.?8.?hour/.test(f))
    return "RRULE:FREQ=DAILY;BYHOUR=8,14,20;BYMINUTE=0;BYSECOND=0";
  if (/twice|2.?times|every.?12.?hour/.test(f))
    return "RRULE:FREQ=DAILY;BYHOUR=8,20;BYMINUTE=0;BYSECOND=0";
  if (/every.?other.?day|every.?2.?day/.test(f)) return "RRULE:FREQ=DAILY;INTERVAL=2";
  if (/weekly|once.?a.?week/.test(f)) return "RRULE:FREQ=WEEKLY";
  // Default: once daily
  return "RRULE:FREQ=DAILY";
}

// ── ICS generators ─────────────────────────────────────────────────────────────

export interface MedicationICSParams {
  medication: string;
  dose?: string;
  frequency?: string;
  instructions?: string;
}

/** Generate an ICS string for a recurring medication reminder. */
export function generateMedicationICS({
  medication,
  dose,
  frequency,
  instructions,
}: MedicationICSParams): string {
  // Start: today at 8 AM; if we're already past 8 AM, start tomorrow
  const start = new Date();
  start.setHours(8, 0, 0, 0);
  if (start <= new Date()) start.setDate(start.getDate() + 1);

  const end = new Date(start.getTime() + 15 * 60 * 1000); // 15-minute block

  const descParts: string[] = [];
  if (dose) descParts.push(`Dose: ${dose}`);
  if (frequency) descParts.push(`Frequency: ${frequency}`);
  if (instructions) descParts.push(`Instructions: ${instructions}`);

  const rrule = frequency ? frequencyToRRule(frequency) : "RRULE:FREQ=DAILY";
  const uid = `wellbridge-med-${Date.now()}@wellbridge.app`;

  const lines: (string | null)[] = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//WellBridge//WellBridge//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTART:${icsDateTime(start)}`,
    `DTEND:${icsDateTime(end)}`,
    `SUMMARY:Take ${icsEscape(medication)}`,
    descParts.length > 0
      ? `DESCRIPTION:${icsEscape(descParts.join("\n"))}`
      : null,
    rrule,
    // Alarm fires at event start time
    "BEGIN:VALARM",
    "TRIGGER:-PT0S",
    "ACTION:DISPLAY",
    `DESCRIPTION:Time to take ${icsEscape(medication)}`,
    "END:VALARM",
    "END:VEVENT",
    "END:VCALENDAR",
  ];

  return lines.filter(Boolean).join("\r\n");
}

export interface AppointmentICSParams {
  provider?: string;
  specialty?: string;
  date?: string | null;   // ISO 8601 date or datetime string
  reason?: string;
  location?: string;
  durationMinutes?: number;
}

/** Generate an ICS string for a medical appointment. */
export function generateAppointmentICS({
  provider,
  specialty,
  date,
  reason,
  location,
  durationMinutes = 60,
}: AppointmentICSParams): string {
  const who = provider ?? specialty ?? "your doctor";
  const title = `Appointment with ${who}`;

  let startDate: Date;
  let isAllDay = false;

  if (date) {
    // Date-only string (YYYY-MM-DD)?
    if (/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      startDate = new Date(`${date}T09:00:00`);
      isAllDay = false; // Schedule at 9 AM so the alarm still fires
    } else {
      startDate = new Date(date);
      if (isNaN(startDate.getTime())) {
        // Unparseable — all-day event one week from now
        startDate = new Date();
        startDate.setDate(startDate.getDate() + 7);
        isAllDay = true;
      }
    }
  } else {
    startDate = new Date();
    startDate.setDate(startDate.getDate() + 7);
    startDate.setHours(9, 0, 0, 0);
  }

  const endDate = new Date(startDate.getTime() + durationMinutes * 60 * 1000);

  const descParts: string[] = [];
  if (reason) descParts.push(reason);
  descParts.push("Bring your insurance card and a photo ID.");
  descParts.push("Arrive 10 minutes early.");

  const uid = `wellbridge-appt-${Date.now()}@wellbridge.app`;

  const dtStart = isAllDay
    ? `DTSTART;VALUE=DATE:${icsDateOnly(startDate)}`
    : `DTSTART:${icsDateTime(startDate)}`;
  const dtEnd = isAllDay
    ? `DTEND;VALUE=DATE:${icsDateOnly(endDate)}`
    : `DTEND:${icsDateTime(endDate)}`;

  const lines: (string | null)[] = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//WellBridge//WellBridge//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    dtStart,
    dtEnd,
    `SUMMARY:${icsEscape(title)}`,
    `DESCRIPTION:${icsEscape(descParts.join("\n"))}`,
    location ? `LOCATION:${icsEscape(location)}` : null,
    // 1-day reminder
    "BEGIN:VALARM",
    "TRIGGER:-P1D",
    "ACTION:DISPLAY",
    `DESCRIPTION:Appointment tomorrow: ${icsEscape(title)}`,
    "END:VALARM",
    // 1-hour reminder (only for timed events)
    ...(isAllDay
      ? []
      : [
          "BEGIN:VALARM",
          "TRIGGER:-PT1H",
          "ACTION:DISPLAY",
          `DESCRIPTION:Appointment in 1 hour: ${icsEscape(title)}`,
          "END:VALARM",
        ]),
    "END:VEVENT",
    "END:VCALENDAR",
  ];

  return lines.filter(Boolean).join("\r\n");
}

// ── Download / open ───────────────────────────────────────────────────────────

/**
 * Trigger calendar import.
 *
 * iOS:    Opens the ICS blob in a new tab → Safari hands it to Calendar.app
 * Android + Desktop: Downloads the .ics file (Android opens it with Google
 *          Calendar or the user's default calendar handler).
 */
export function downloadICS(filename: string, icsContent: string): void {
  const safeFilename = filename.endsWith(".ics") ? filename : `${filename}.ics`;
  const blob = new Blob([icsContent], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  const device = getDeviceType();
  if (device === "ios") {
    // iOS Safari opens the blob URL inline and prompts Calendar import
    window.open(url, "_blank");
  } else {
    const a = document.createElement("a");
    a.href = url;
    a.download = safeFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

// ── Google Calendar (desktop shortcut) ───────────────────────────────────────

export interface GCalParams {
  title: string;
  startDate: Date;
  endDate: Date;
  details?: string;
  location?: string;
}

/** Open Google Calendar web with a pre-filled event (new tab). */
export function openGoogleCalendar({ title, startDate, endDate, details, location }: GCalParams): void {
  const fmt = (d: Date) => icsDateTime(d); // YYYYMMDDTHHMMSS
  const url = new URL("https://calendar.google.com/calendar/render");
  url.searchParams.set("action", "TEMPLATE");
  url.searchParams.set("text", title);
  url.searchParams.set("dates", `${fmt(startDate)}/${fmt(endDate)}`);
  if (details) url.searchParams.set("details", details);
  if (location) url.searchParams.set("location", location);
  window.open(url.toString(), "_blank");
}
