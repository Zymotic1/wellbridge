/**
 * Appointments page — shows upcoming appointments.
 * Supports manual creation (with NPI provider search) and deletion.
 */

"use client";

import { useState, useEffect, useCallback } from "react";
import { Calendar, Loader2, MapPin, Clock, Plus, Phone, Trash2 } from "lucide-react";
import type { Appointment } from "@/lib/types";
import CreateAppointmentModal from "@/components/appointments/CreateAppointmentModal";

export default function AppointmentsPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadAppointments = useCallback(async () => {
    try {
      const res = await fetch("/api/appointments");
      if (res.ok) {
        const data = await res.json();
        setAppointments(data.appointments ?? []);
      }
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAppointments();
  }, [loadAppointments]);

  async function handleDelete(id: string) {
    if (!confirm("Remove this appointment?")) return;
    setDeletingId(id);
    try {
      const res = await fetch(`/api/appointments/${id}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        setAppointments((prev) => prev.filter((a) => a.id !== id));
      }
    } catch {
      // Ignore
    } finally {
      setDeletingId(null);
    }
  }

  const SOURCE_LABELS: Record<string, string> = {
    manual: "Manually added",
    google_calendar: "From Google Calendar",
    scan_to_calendar: "Detected from document",
  };

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Calendar size={24} className="text-brand-600" />
          <div>
            <h1 className="text-xl font-bold text-slate-800">Appointments</h1>
            <p className="text-sm text-slate-400">Your upcoming medical appointments</p>
          </div>
        </div>
        <button
          onClick={() => setModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white text-sm
                     font-medium rounded-xl hover:bg-brand-700 transition-colors shadow-sm"
        >
          <Plus size={16} />
          New Appointment
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 size={16} className="animate-spin" />
          Loading appointments...
        </div>
      ) : appointments.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <Calendar size={48} className="mx-auto mb-4 text-slate-300" />
          <p className="font-medium text-lg">No upcoming appointments</p>
          <p className="text-sm mt-2 max-w-sm mx-auto">
            Click <strong>New Appointment</strong> to schedule one manually, or upload a
            discharge paper or referral letter in the Records section to automatically
            detect follow-up appointments.
          </p>
          <button
            onClick={() => setModalOpen(true)}
            className="mt-5 inline-flex items-center gap-2 px-5 py-2.5 bg-brand-600
                       text-white text-sm font-medium rounded-xl hover:bg-brand-700
                       transition-colors"
          >
            <Plus size={15} />
            Schedule an appointment
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {appointments.map((appt) => (
            <div
              key={appt.id}
              className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm"
            >
              <div className="flex items-start gap-4">
                {/* Date badge */}
                <div className="w-14 h-14 bg-brand-50 rounded-xl flex flex-col
                                items-center justify-center flex-shrink-0">
                  <span className="text-xs font-bold text-brand-600 uppercase">
                    {new Date(appt.appointment_date).toLocaleString("en-US", { month: "short" })}
                  </span>
                  <span className="text-2xl font-bold text-brand-700 leading-none">
                    {new Date(appt.appointment_date).getDate()}
                  </span>
                </div>

                {/* Details */}
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-slate-800">
                    {appt.provider_name ?? "Medical Appointment"}
                  </p>

                  {appt.facility_name && (
                    <div className="flex items-center gap-1.5 mt-1 text-sm text-slate-500">
                      <MapPin size={13} />
                      {appt.facility_name}
                    </div>
                  )}

                  {appt.address && !appt.facility_name && (
                    <div className="flex items-center gap-1.5 mt-1 text-sm text-slate-500">
                      <MapPin size={13} />
                      {appt.address}
                    </div>
                  )}

                  <div className="flex items-center gap-1.5 mt-1 text-sm text-slate-500">
                    <Clock size={13} />
                    {new Date(appt.appointment_date).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · {appt.duration_minutes} min
                  </div>

                  {appt.phone && (
                    <div className="flex items-center gap-1.5 mt-1 text-sm text-slate-500">
                      <Phone size={13} />
                      {appt.phone}
                    </div>
                  )}

                  {appt.notes && (
                    <p className="mt-2 text-xs text-slate-400 italic">{appt.notes}</p>
                  )}

                  <span className="mt-2 inline-block text-xs bg-slate-100 text-slate-500
                                   rounded-full px-2 py-0.5">
                    {SOURCE_LABELS[appt.source] ?? appt.source}
                  </span>
                </div>

                {/* Delete button */}
                <button
                  onClick={() => handleDelete(appt.id)}
                  disabled={deletingId === appt.id}
                  className="p-2 rounded-lg text-slate-300 hover:text-red-400
                             hover:bg-red-50 transition-colors flex-shrink-0"
                  aria-label="Remove appointment"
                >
                  {deletingId === appt.id
                    ? <Loader2 size={16} className="animate-spin" />
                    : <Trash2 size={16} />
                  }
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create modal */}
      <CreateAppointmentModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={loadAppointments}
      />
    </div>
  );
}
