"use client";

/**
 * RBACManager — UI for managing Trusted Individual Access.
 *
 * Lets the authenticated user:
 *  - View who currently has access to their records
 *  - Grant Viewer or Editor access to another user by their user ID
 *  - Revoke existing shares
 */

import { useState, useEffect } from "react";
import { Users, Plus, Trash2, Loader2, Shield } from "lucide-react";
import type { RecordShare, ShareGrantRequest, ShareRole } from "@/lib/types";

export default function RBACManager() {
  const [shares, setShares] = useState<RecordShare[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<ShareGrantRequest>({
    record_id: "",
    granted_to_user_id: "",
    role: "viewer",
  });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function loadShares() {
    try {
      const res = await fetch("/api/backend/sharing/my-shares");
      if (res.ok) {
        const data = await res.json();
        setShares(data.shares ?? []);
      }
    } catch {
      // Silently ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadShares(); }, []);

  async function handleGrant(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/backend/sharing/grant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to grant access" }));
        throw new Error(err.detail);
      }
      setShowForm(false);
      setForm({ record_id: "", granted_to_user_id: "", role: "viewer" });
      await loadShares();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to grant access");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke(shareId: string) {
    try {
      await fetch(`/api/backend/sharing/revoke/${shareId}`, { method: "DELETE" });
      setShares((prev) => prev.filter((s) => s.id !== shareId));
    } catch {
      // Silently ignore — user can retry
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield size={22} className="text-brand-600" />
          <div>
            <h2 className="text-lg font-semibold text-slate-800">Trusted Access</h2>
            <p className="text-sm text-slate-400">
              Share your records with caregivers or family members.
            </p>
          </div>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white
                     rounded-xl text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          <Plus size={16} />
          Grant Access
        </button>
      </div>

      {/* Grant form */}
      {showForm && (
        <form
          onSubmit={handleGrant}
          className="bg-white border border-slate-200 rounded-2xl p-5 space-y-4"
        >
          <h3 className="font-semibold text-slate-700">Grant Record Access</h3>

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">
              Record ID
            </label>
            <input
              type="text"
              value={form.record_id}
              onChange={(e) => setForm({ ...form, record_id: e.target.value })}
              placeholder="UUID of the record to share"
              required
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">
              User ID to share with
            </label>
            <input
              type="text"
              value={form.granted_to_user_id}
              onChange={(e) => setForm({ ...form, granted_to_user_id: e.target.value })}
              placeholder="auth0|..."
              required
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-600 mb-1">
              Access Level
            </label>
            <select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value as ShareRole })}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="viewer">Viewer — can read records only</option>
              <option value="editor">Editor — can read and add notes</option>
            </select>
          </div>

          {formError && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
              {formError}
            </p>
          )}

          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={() => { setShowForm(false); setFormError(null); }}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 px-5 py-2 bg-brand-600 text-white
                         rounded-xl text-sm font-medium hover:bg-brand-700 transition-colors
                         disabled:opacity-50"
            >
              {submitting && <Loader2 size={14} className="animate-spin" />}
              Grant Access
            </button>
          </div>
        </form>
      )}

      {/* Current shares list */}
      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 py-4">
          <Loader2 size={16} className="animate-spin" />
          Loading...
        </div>
      ) : shares.length === 0 ? (
        <div className="text-center py-10 text-slate-400">
          <Users size={36} className="mx-auto mb-3 text-slate-300" />
          <p className="font-medium">No active shares</p>
          <p className="text-sm mt-1">
            You haven't shared any records with anyone yet.
          </p>
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-2xl divide-y divide-slate-100 overflow-hidden">
          {shares.map((share) => (
            <div key={share.id} className="flex items-center justify-between p-4 gap-4">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-800 truncate">
                  {share.granted_to}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      share.role === "editor"
                        ? "bg-amber-50 text-amber-700"
                        : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {share.role === "editor" ? "Editor" : "Viewer"}
                  </span>
                  {share.expires_at && (
                    <span className="text-xs text-slate-400">
                      Expires {new Date(share.expires_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleRevoke(share.id)}
                className="flex-shrink-0 p-2 text-slate-400 hover:text-red-600
                           hover:bg-red-50 rounded-lg transition-colors"
                aria-label="Revoke access"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
