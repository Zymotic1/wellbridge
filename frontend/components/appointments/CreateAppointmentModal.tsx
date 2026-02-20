"use client";

/**
 * CreateAppointmentModal
 *
 * A slide-up modal for manually scheduling an appointment.
 *
 * Features:
 *  - Provider name field with live NPI Registry search (debounced, 300 ms)
 *  - Search results show specialty, address, and phone; clicking one
 *    auto-populates provider name, address, phone, and NPI
 *  - Date + time picker, duration selector, optional notes
 *  - "Create" calls POST /api/appointments; on success updates the parent list
 *
 * NPI Registry source:
 *  https://npiregistry.cms.hhs.gov — free, public, no API key required.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  X, Search, Loader2, MapPin, Phone, Stethoscope, Check,
} from "lucide-react";
import type { NpiResult } from "@/lib/types";
import MultiSelectFilter, { type FilterOption } from "./MultiSelectFilter";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const DURATIONS = [15, 30, 45, 60, 90, 120];

// ── Filter data ───────────────────────────────────────────────────────────────

const STATE_OPTIONS: FilterOption[] = [
  { value: "AL", label: "AL — Alabama",          badgeLabel: "AL" },
  { value: "AK", label: "AK — Alaska",           badgeLabel: "AK" },
  { value: "AZ", label: "AZ — Arizona",          badgeLabel: "AZ" },
  { value: "AR", label: "AR — Arkansas",         badgeLabel: "AR" },
  { value: "CA", label: "CA — California",       badgeLabel: "CA" },
  { value: "CO", label: "CO — Colorado",         badgeLabel: "CO" },
  { value: "CT", label: "CT — Connecticut",      badgeLabel: "CT" },
  { value: "DE", label: "DE — Delaware",         badgeLabel: "DE" },
  { value: "FL", label: "FL — Florida",          badgeLabel: "FL" },
  { value: "GA", label: "GA — Georgia",          badgeLabel: "GA" },
  { value: "HI", label: "HI — Hawaii",           badgeLabel: "HI" },
  { value: "ID", label: "ID — Idaho",            badgeLabel: "ID" },
  { value: "IL", label: "IL — Illinois",         badgeLabel: "IL" },
  { value: "IN", label: "IN — Indiana",          badgeLabel: "IN" },
  { value: "IA", label: "IA — Iowa",             badgeLabel: "IA" },
  { value: "KS", label: "KS — Kansas",           badgeLabel: "KS" },
  { value: "KY", label: "KY — Kentucky",         badgeLabel: "KY" },
  { value: "LA", label: "LA — Louisiana",        badgeLabel: "LA" },
  { value: "ME", label: "ME — Maine",            badgeLabel: "ME" },
  { value: "MD", label: "MD — Maryland",         badgeLabel: "MD" },
  { value: "MA", label: "MA — Massachusetts",    badgeLabel: "MA" },
  { value: "MI", label: "MI — Michigan",         badgeLabel: "MI" },
  { value: "MN", label: "MN — Minnesota",        badgeLabel: "MN" },
  { value: "MS", label: "MS — Mississippi",      badgeLabel: "MS" },
  { value: "MO", label: "MO — Missouri",         badgeLabel: "MO" },
  { value: "MT", label: "MT — Montana",          badgeLabel: "MT" },
  { value: "NE", label: "NE — Nebraska",         badgeLabel: "NE" },
  { value: "NV", label: "NV — Nevada",           badgeLabel: "NV" },
  { value: "NH", label: "NH — New Hampshire",    badgeLabel: "NH" },
  { value: "NJ", label: "NJ — New Jersey",       badgeLabel: "NJ" },
  { value: "NM", label: "NM — New Mexico",       badgeLabel: "NM" },
  { value: "NY", label: "NY — New York",         badgeLabel: "NY" },
  { value: "NC", label: "NC — North Carolina",   badgeLabel: "NC" },
  { value: "ND", label: "ND — North Dakota",     badgeLabel: "ND" },
  { value: "OH", label: "OH — Ohio",             badgeLabel: "OH" },
  { value: "OK", label: "OK — Oklahoma",         badgeLabel: "OK" },
  { value: "OR", label: "OR — Oregon",           badgeLabel: "OR" },
  { value: "PA", label: "PA — Pennsylvania",     badgeLabel: "PA" },
  { value: "RI", label: "RI — Rhode Island",     badgeLabel: "RI" },
  { value: "SC", label: "SC — South Carolina",   badgeLabel: "SC" },
  { value: "SD", label: "SD — South Dakota",     badgeLabel: "SD" },
  { value: "TN", label: "TN — Tennessee",        badgeLabel: "TN" },
  { value: "TX", label: "TX — Texas",            badgeLabel: "TX" },
  { value: "UT", label: "UT — Utah",             badgeLabel: "UT" },
  { value: "VT", label: "VT — Vermont",          badgeLabel: "VT" },
  { value: "VA", label: "VA — Virginia",         badgeLabel: "VA" },
  { value: "WA", label: "WA — Washington",       badgeLabel: "WA" },
  { value: "WV", label: "WV — West Virginia",    badgeLabel: "WV" },
  { value: "WI", label: "WI — Wisconsin",        badgeLabel: "WI" },
  { value: "WY", label: "WY — Wyoming",          badgeLabel: "WY" },
  { value: "DC", label: "DC — Washington D.C.",  badgeLabel: "DC" },
];

/** CMS pri_spec values — value is the exact CMS string; label is title-cased for display */
const SPECIALTY_OPTIONS: FilterOption[] = [
  "ADDICTION MEDICINE",
  "ALLERGY/ IMMUNOLOGY",
  "ANESTHESIOLOGY",
  "CARDIAC SURGERY",
  "CARDIOLOGY",
  "CLINICAL NEUROPSYCHOLOGY",
  "COLORECTAL SURGERY (PROCTOLOGY)",
  "CRITICAL CARE (INTENSIVISTS)",
  "DENTIST",
  "DERMATOLOGY",
  "DIAGNOSTIC RADIOLOGY",
  "EMERGENCY MEDICINE",
  "ENDOCRINOLOGY",
  "FAMILY PRACTICE",
  "GASTROENTEROLOGY",
  "GENERAL PRACTICE",
  "GENERAL SURGERY",
  "GERIATRIC MEDICINE",
  "GERIATRIC PSYCHIATRY",
  "GYNECOLOGICAL ONCOLOGY",
  "HAND SURGERY",
  "HEMATOLOGY",
  "HEMATOLOGY/ONCOLOGY",
  "HOSPICE AND PALLIATIVE CARE",
  "HOSPITALIST",
  "INFECTIOUS DISEASE",
  "INTERNAL MEDICINE",
  "INTERVENTIONAL CARDIOLOGY",
  "INTERVENTIONAL PAIN MANAGEMENT",
  "INTERVENTIONAL RADIOLOGY",
  "MAXILLOFACIAL SURGERY",
  "NEPHROLOGY",
  "NEUROLOGY",
  "NEUROPSYCHIATRY",
  "NEUROSURGERY",
  "NUCLEAR MEDICINE",
  "OBSTETRICS/GYNECOLOGY",
  "ONCOLOGY",
  "OPHTHALMOLOGY",
  "ORAL SURGERY",
  "ORTHOPEDIC SURGERY",
  "OSTEOPATHIC MANIPULATIVE MEDICINE",
  "OTOLARYNGOLOGY",
  "PAIN MANAGEMENT",
  "PATHOLOGY",
  "PEDIATRIC MEDICINE",
  "PHYSICAL MEDICINE AND REHABILITATION",
  "PLASTIC AND RECONSTRUCTIVE SURGERY",
  "PODIATRY",
  "PREVENTIVE MEDICINE",
  "PSYCHIATRY",
  "PULMONARY DISEASE",
  "RADIATION ONCOLOGY",
  "RHEUMATOLOGY",
  "SLEEP MEDICINE",
  "SPORTS MEDICINE",
  "THORACIC SURGERY",
  "UROLOGY",
  "VASCULAR SURGERY",
].map((s) => ({
  value: s,
  label: s.toLowerCase().replace(/(?:^|[\s/(])\S/g, (c) => c.toUpperCase()),
}));

export default function CreateAppointmentModal({ open, onClose, onCreated }: Props) {
  // Form fields
  const [providerName, setProviderName] = useState("");
  const [facilityName, setFacilityName] = useState("");
  const [apptDate, setApptDate] = useState("");
  const [apptTime, setApptTime] = useState("09:00");
  const [duration, setDuration] = useState(30);
  const [notes, setNotes] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [npi, setNpi] = useState("");

  // Provider search state
  const [searchQuery, setSearchQuery] = useState("");
  const [filterStates, setFilterStates] = useState<string[]>([]);
  const [filterSpecialties, setFilterSpecialties] = useState<string[]>([]);
  const [searchResults, setSearchResults] = useState<NpiResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<NpiResult | null>(null);

  // Form state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Escape closes modal
  useEffect(() => {
    if (!open) return;
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Debounced NPI search — re-fires when filters change via the useEffect below
  const runSearch = useCallback(async (
    q: string,
    states: string[],
    specialties: string[],
  ) => {
    // Cancel any in-flight request before starting a new one
    abortRef.current?.abort();

    if (q.trim().length < 2) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setSearching(true);
    try {
      const params = new URLSearchParams({ q });
      states.forEach((s)     => params.append("state",     s));
      specialties.forEach((s) => params.append("specialty", s));
      const res = await fetch(`/api/appointments/search-provider?${params}`, {
        signal: controller.signal,
      });
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.results ?? []);
        setShowDropdown(true);
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return; // stale request — ignore
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }, []);

  function handleSearchChange(value: string) {
    setSearchQuery(value);
    setProviderName(value);
    setSelectedProvider(null);
    // Clear results and hide dropdown immediately — the dropdown will
    // reopen only when fresh results arrive from the new query
    setSearchResults([]);
    setShowDropdown(false);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(value, filterStates, filterSpecialties), 300);
  }

  // Re-run search when filters change (if query already entered)
  useEffect(() => {
    if (searchQuery.trim().length >= 2) {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(
        () => runSearch(searchQuery, filterStates, filterSpecialties), 150
      );
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStates, filterSpecialties]);

  function selectProvider(result: NpiResult) {
    setSelectedProvider(result);
    setProviderName(result.name);
    setSearchQuery(result.name);
    setAddress(result.address);
    setPhone(result.phone);
    setNpi(result.npi);
    // Auto-fill facility from CMS data; user can still edit
    setFacilityName(result.facility || "");
    setShowDropdown(false);
  }

  function resetForm() {
    setProviderName(""); setFacilityName(""); setApptDate("");
    setApptTime("09:00"); setDuration(30); setNotes("");
    setPhone(""); setAddress(""); setNpi("");
    setSearchQuery(""); setFilterStates([]); setFilterSpecialties([]);
    setSearchResults([]); setShowDropdown(false);
    setSelectedProvider(null); setError(null);
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!providerName.trim() && !facilityName.trim()) {
      setError("Please enter a provider or facility name.");
      return;
    }
    if (!apptDate) {
      setError("Please choose a date.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const appointmentDate = new Date(`${apptDate}T${apptTime}:00`);
      const body: Record<string, unknown> = {
        provider_name: providerName.trim() || null,
        facility_name: facilityName.trim() || null,
        appointment_date: appointmentDate.toISOString(),
        duration_minutes: duration,
        notes: notes.trim() || null,
        phone: phone.trim() || null,
        address: address.trim() || null,
        npi: npi || null,
      };

      const res = await fetch("/api/appointments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.detail ?? "Failed to create appointment.");
        return;
      }

      resetForm();
      onCreated();
      onClose();
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={handleClose}
        aria-hidden="true"
      />

      {/* Modal panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Schedule appointment"
        className="fixed inset-x-4 bottom-0 md:inset-auto md:left-1/2 md:top-1/2
                   md:-translate-x-1/2 md:-translate-y-1/2 md:w-full md:max-w-lg
                   z-50 bg-white rounded-t-2xl md:rounded-2xl shadow-2xl
                   flex flex-col max-h-[90vh]"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 flex-shrink-0">
          <h2 className="text-base font-semibold text-slate-800">New Appointment</h2>
          <button
            onClick={handleClose}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Scrollable form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-5 space-y-5">

          {/* Provider search */}
          <div ref={searchRef} className="relative">
            <label className="block text-xs font-medium text-slate-600 mb-1.5">
              Provider or Doctor Name
            </label>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
                placeholder="Search doctor or practice name…"
                className="w-full pl-9 pr-3 py-2.5 text-sm border border-slate-200 rounded-xl
                           focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
              />
              {searching && (
                <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-brand-400 animate-spin" />
              )}
              {selectedProvider && !searching && (
                <Check size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-green-500" />
              )}
            </div>

            {/* State + Specialty filters */}
            <div className="flex gap-2 mt-2">
              <div className="flex-1 min-w-0">
                <MultiSelectFilter
                  label="State"
                  options={STATE_OPTIONS}
                  selected={filterStates}
                  onChange={setFilterStates}
                />
              </div>
              <div className="flex-1 min-w-0">
                <MultiSelectFilter
                  label="Specialty"
                  options={SPECIALTY_OPTIONS}
                  selected={filterSpecialties}
                  onChange={setFilterSpecialties}
                />
              </div>
            </div>

            {/* Search results dropdown */}
            {showDropdown && searchResults.length > 0 && (
              <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-slate-200
                              rounded-xl shadow-lg max-h-64 overflow-y-auto">
                {searchResults.map((r) => (
                  <button
                    key={r.npi}
                    type="button"
                    onClick={() => selectProvider(r)}
                    className="w-full text-left px-4 py-3 hover:bg-brand-50 transition-colors
                               border-b border-slate-100 last:border-0"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-800 truncate">{r.name}</p>
                        {/* Facility name (e.g. "Monmouth Medical Center") */}
                        {r.facility && r.facility !== r.name && (
                          <p className="text-xs text-brand-600 font-medium truncate mt-0.5">{r.facility}</p>
                        )}
                        {r.specialty && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <Stethoscope size={11} className="text-brand-400 flex-shrink-0" />
                            <span className="text-xs text-slate-500 truncate">{r.specialty}</span>
                          </div>
                        )}
                        {r.address && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <MapPin size={11} className="text-slate-400 flex-shrink-0" />
                            <span className="text-xs text-slate-400 truncate">{r.address}</span>
                          </div>
                        )}
                      </div>
                      {r.phone && (
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <Phone size={11} className="text-slate-400" />
                          <span className="text-xs text-slate-500">{r.phone}</span>
                        </div>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {showDropdown && !searching && searchQuery.length >= 2 && searchResults.length === 0 && (
              <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-slate-200
                              rounded-xl shadow-lg px-4 py-3 text-sm text-slate-400">
                No providers found — you can still type the name manually.
              </div>
            )}
          </div>

          {/* Auto-populated contact info (shown when provider selected) */}
          {(phone || address) && (
            <div className="bg-brand-50 rounded-xl px-4 py-3 space-y-1.5">
              {phone && (
                <div className="flex items-center gap-2 text-sm text-brand-700">
                  <Phone size={13} className="flex-shrink-0" />
                  <span>{phone}</span>
                </div>
              )}
              {address && (
                <div className="flex items-center gap-2 text-sm text-brand-700">
                  <MapPin size={13} className="flex-shrink-0" />
                  <span>{address}</span>
                </div>
              )}
              <p className="text-xs text-brand-400 mt-1">
                From NPI Registry — tap to edit if incorrect
              </p>
            </div>
          )}

          {/* Facility / practice name (optional) */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">
              Facility / Practice Name <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={facilityName}
              onChange={(e) => setFacilityName(e.target.value)}
              placeholder="e.g. Boston Medical Center"
              className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl
                         focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
            />
          </div>

          {/* Date + Time */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1.5">Date</label>
              <input
                type="date"
                value={apptDate}
                onChange={(e) => setApptDate(e.target.value)}
                min={new Date().toISOString().split("T")[0]}
                required
                className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl
                           focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1.5">Time</label>
              <input
                type="time"
                value={apptTime}
                onChange={(e) => setApptTime(e.target.value)}
                className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl
                           focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
              />
            </div>
          </div>

          {/* Duration */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">Duration</label>
            <div className="flex flex-wrap gap-2">
              {DURATIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDuration(d)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
                    ${duration === d
                      ? "bg-brand-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                >
                  {d < 60 ? `${d} min` : `${d / 60} hr`}
                </button>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1.5">
              Notes <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Reason for visit, prep instructions, questions to bring…"
              className="w-full px-3 py-2.5 text-sm border border-slate-200 rounded-xl resize-none
                         focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200"
            />
          </div>

          {error && (
            <p className="text-sm text-red-500 bg-red-50 rounded-xl px-3 py-2">{error}</p>
          )}
        </form>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-100 flex gap-3 flex-shrink-0">
          <button
            type="button"
            onClick={handleClose}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-slate-600 bg-slate-100
                       rounded-xl hover:bg-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-brand-600
                       rounded-xl hover:bg-brand-700 transition-colors
                       disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {submitting ? <Loader2 size={15} className="animate-spin" /> : null}
            {submitting ? "Saving…" : "Create Appointment"}
          </button>
        </div>
      </div>
    </>
  );
}
