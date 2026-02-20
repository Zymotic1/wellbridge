"use client";

/**
 * ProfileSetupModal — prompts new users for their first and last name.
 *
 * Shown automatically on mount when the backend has no stored first_name
 * for this user. After saving, the page reloads so the layout and greeting
 * pick up the new name immediately.
 */

import { useState, useEffect } from "react";
import { UserRound } from "lucide-react";

export default function ProfileSetupModal() {
  const [show, setShow] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // On mount: check whether a name is already stored
  useEffect(() => {
    async function checkProfile() {
      try {
        const res = await fetch("/api/users");
        if (!res.ok) return;
        const data = await res.json();
        if (!data.first_name) {
          setShow(true);
        }
      } catch {
        // Non-blocking — don't interrupt the app if this fails
      }
    }
    checkProfile();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!firstName.trim()) {
      setError("Please enter your first name so we can address you properly.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await fetch("/api/users", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          first_name: firstName.trim(),
          last_name: lastName.trim(),
        }),
      });
      if (!res.ok) throw new Error("Save failed");
      // Reload so the layout and home page greetings pick up the new name
      window.location.reload();
    } catch {
      setError("Something went wrong — please try again.");
    } finally {
      setSaving(false);
    }
  }

  if (!show) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl shadow-2xl p-8 w-full max-w-sm">
        {/* Icon */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 rounded-2xl bg-brand-50 flex items-center justify-center mb-4">
            <UserRound size={28} className="text-brand-600" />
          </div>
          <h2 className="text-xl font-semibold text-slate-800 text-center">
            What should we call you?
          </h2>
          <p className="text-sm text-slate-400 text-center mt-1.5 leading-relaxed">
            WellBridge uses your name to make conversations feel more personal.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* First name */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">
              First name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="e.g. Sarah"
              autoFocus
              autoComplete="given-name"
              className="w-full border border-slate-200 rounded-xl px-4 py-2.5 text-sm
                         text-slate-800 placeholder-slate-300 focus:outline-none
                         focus:ring-2 focus:ring-brand-400 focus:border-transparent"
            />
          </div>

          {/* Last name */}
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1.5">
              Last name
            </label>
            <input
              type="text"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="e.g. Johnson"
              autoComplete="family-name"
              className="w-full border border-slate-200 rounded-xl px-4 py-2.5 text-sm
                         text-slate-800 placeholder-slate-300 focus:outline-none
                         focus:ring-2 focus:ring-brand-400 focus:border-transparent"
            />
          </div>

          {error && (
            <p className="text-xs text-red-500 leading-relaxed">{error}</p>
          )}

          <button
            type="submit"
            disabled={saving}
            className="w-full mt-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-60
                       text-white font-medium rounded-xl py-2.5 text-sm transition-colors"
          >
            {saving ? "Saving…" : "Continue"}
          </button>
        </form>
      </div>
    </div>
  );
}
