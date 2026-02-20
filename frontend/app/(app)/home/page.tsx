/**
 * Home — calm status view.
 *
 * The wireframe calls this "What's coming up" — no dashboard, no charts,
 * no forms. Just a warm greeting, upcoming events, and pending reminders.
 * Everything here was created automatically from conversations, never by
 * the user navigating to a "settings" or "add reminder" screen.
 *
 * The primary CTA is always "Ask or say anything" → opens Talk.
 */

"use client";

import { useEffect, useState } from "react";
import { useUser } from "@auth0/nextjs-auth0/client";
import Link from "next/link";
import {
  MessageCircle,
  CalendarDays,
  CheckCircle2,
  Circle,
  ChevronRight,
  Loader2,
} from "lucide-react";

interface Appointment {
  id: string;
  provider_name: string | null;
  facility_name: string | null;
  appointment_date: string;
  notes: string | null;
}

interface Reminder {
  id: string;
  text: string;
  done: boolean;
  date: string;
}

function timeOfDay(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function daysUntil(iso: string): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(iso);
  target.setHours(0, 0, 0, 0);
  const diff = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff < 0) return `${Math.abs(diff)}d ago`;
  return `In ${diff} days`;
}

export default function HomePage() {
  const { user } = useUser();
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [firstName, setFirstName] = useState<string>("");

  // Auth0 name as initial fallback (avoids blank greeting while profile loads).
  // Skip user.name when it looks like an email — Auth0 sets name=email for
  // email/password accounts that have no given_name claim.
  useEffect(() => {
    const raw = String(user?.given_name ?? user?.name ?? "");
    const auth0Name = raw.includes("@") ? "" : raw.split(" ")[0];
    setFirstName(auth0Name);
  }, [user]);

  useEffect(() => {
    async function load() {
      // Fetch stored profile name and appointments in parallel
      const [profileRes, apptRes] = await Promise.allSettled([
        fetch("/api/users"),
        fetch("/api/appointments?upcoming=true&limit=3"),
      ]);

      if (profileRes.status === "fulfilled" && profileRes.value.ok) {
        const data = await profileRes.value.json();
        if (data.first_name) setFirstName(data.first_name);
      }

      if (apptRes.status === "fulfilled" && apptRes.value.ok) {
        const data = await apptRes.value.json();
        setAppointments(data.appointments ?? []);
      }

      setLoading(false);
    }
    load();
  }, []);

  // Reminders would come from the agent/DB in a full implementation.
  // For now we derive them from upcoming appointments to show the concept.
  const reminders: Reminder[] = appointments.slice(0, 2).map((a) => ({
    id: a.id,
    text: `Prepare for your appointment${a.provider_name ? ` with ${a.provider_name}` : ""}`,
    done: false,
    date: a.appointment_date,
  }));

  return (
    <div className="min-h-full bg-slate-50 p-6 md:p-10 max-w-2xl mx-auto">
      {/* Greeting */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-800">
          {timeOfDay()}{firstName ? `, ${firstName}` : ""}.
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Here&apos;s what&apos;s coming up.
        </p>
      </div>

      {/* Primary CTA — "Ask or say anything" */}
      <Link
        href="/chat"
        className="flex items-center gap-4 w-full bg-white border border-brand-200
                   rounded-2xl px-5 py-4 mb-6 shadow-sm hover:shadow-md hover:border-brand-300
                   transition-all group"
      >
        <span className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center
                         group-hover:bg-brand-100 transition-colors flex-shrink-0">
          <MessageCircle size={20} className="text-brand-600" />
        </span>
        <span className="flex-1 text-left">
          <span className="block text-sm font-semibold text-slate-700">
            Ask or say anything
          </span>
          <span className="block text-xs text-slate-400 mt-0.5">
            Your health companion is here — no forms, just conversation
          </span>
        </span>
        <ChevronRight size={18} className="text-slate-300 group-hover:text-brand-400 transition-colors" />
      </Link>

      {/* Upcoming Actions / Reminders */}
      {reminders.length > 0 && (
        <section className="mb-6">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Upcoming actions
          </h2>
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm divide-y divide-slate-100">
            {reminders.map((r) => (
              <div key={r.id} className="flex items-start gap-3 px-4 py-3.5">
                {r.done ? (
                  <CheckCircle2 size={16} className="text-green-400 mt-0.5 flex-shrink-0" />
                ) : (
                  <Circle size={16} className="text-slate-300 mt-0.5 flex-shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className={`text-sm ${r.done ? "text-slate-400 line-through" : "text-slate-700"}`}>
                    {r.text}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{daysUntil(r.date)}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Upcoming Events */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Upcoming events
        </h2>
        {loading ? (
          <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
            <Loader2 size={14} className="animate-spin" />
            Loading...
          </div>
        ) : appointments.length === 0 ? (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm px-5 py-6 text-center">
            <CalendarDays size={28} className="mx-auto mb-2 text-slate-200" />
            <p className="text-sm text-slate-400">
              No upcoming appointments.
            </p>
            <p className="text-xs text-slate-300 mt-1">
              Tell WellBridge about an appointment and it will appear here automatically.
            </p>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm divide-y divide-slate-100">
            {appointments.map((a) => (
              <div key={a.id} className="flex items-start gap-3 px-4 py-3.5">
                <div className="w-9 h-9 rounded-xl bg-brand-50 flex items-center justify-center flex-shrink-0">
                  <CalendarDays size={16} className="text-brand-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-700">
                    {a.provider_name
                      ? `Appointment with ${a.provider_name}`
                      : "Medical appointment"}
                  </p>
                  {a.facility_name && (
                    <p className="text-xs text-slate-400 mt-0.5">{a.facility_name}</p>
                  )}
                  <p className="text-xs text-brand-500 font-medium mt-0.5">
                    {formatDate(a.appointment_date)} · {daysUntil(a.appointment_date)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* My Journey link */}
      <Link
        href="/journey"
        className="mt-6 flex items-center justify-between w-full px-4 py-3
                   text-sm text-slate-500 hover:text-brand-600 transition-colors"
      >
        <span>View your full care history in My Journey</span>
        <ChevronRight size={16} />
      </Link>
    </div>
  );
}
