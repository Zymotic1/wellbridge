"use client";

/**
 * EpicConnectModal — MyChart / SMART on FHIR connection UI.
 *
 * Shows two states:
 *   1. Connected   — org name, last sync time, Re-sync + Disconnect buttons
 *   2. Not connected — hospital search → Connect button → redirect to Epic
 *
 * PKCE flow (frontend side):
 *   - Generates code_verifier (random 64-char URL-safe string)
 *   - Computes code_challenge = base64url(sha256(code_verifier))
 *   - Stores verifier + state + fhir_base_url in sessionStorage
 *   - Sends code_challenge + state to backend → gets back auth_url
 *   - window.location.href = auth_url  (full page redirect to Epic)
 *   - Epic redirects to /epic/callback where sessionStorage values are consumed
 */

import { useState, useEffect, useCallback } from "react";
import { X, Search, CheckCircle, Loader2, RefreshCw, Link2Off, ExternalLink } from "lucide-react";

interface Endpoint {
  organization_name: string;
  fhir_base_url: string;
}

interface ConnectionStatus {
  connected: boolean;
  organization_name?: string;
  last_sync_at?: string;
  sync_status?: string;
}

interface EpicConnectModalProps {
  onClose: () => void;
}

// ── PKCE helpers ──────────────────────────────────────────────────────────────

function generateCodeVerifier(): string {
  const array = new Uint8Array(48);
  crypto.getRandomValues(array);
  return btoa(Array.from(array).map((b) => String.fromCharCode(b)).join(""))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "")
    .slice(0, 128);
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return btoa(Array.from(new Uint8Array(digest)).map((b) => String.fromCharCode(b)).join(""))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

function generateState(): string {
  const array = new Uint8Array(16);
  crypto.getRandomValues(array);
  return Array.from(array)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function EpicConnectModal({ onClose }: EpicConnectModalProps) {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus | null>(null);
  const [search, setSearch] = useState("");
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [selectedEndpoint, setSelectedEndpoint] = useState<Endpoint | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Load connection status on mount
  useEffect(() => {
    fetch("/api/epic/status")
      .then((r) => r.json())
      .then(setConnectionStatus)
      .catch(() => setConnectionStatus({ connected: false }));
  }, []);

  // Listen for postMessage from the Epic callback popup
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (event.data?.type === "epic_connected") {
        const s = event.data.sync ?? {};
        const parts: string[] = [];
        if (s.medications) parts.push(`${s.medications} medication${s.medications !== 1 ? "s" : ""}`);
        if (s.conditions) parts.push(`${s.conditions} condition${s.conditions !== 1 ? "s" : ""}`);
        if (s.appointments) parts.push(`${s.appointments} appointment${s.appointments !== 1 ? "s" : ""}`);
        if (s.encounters) parts.push(`${s.encounters} visit${s.encounters !== 1 ? "s" : ""}`);
        setConnectionStatus({ connected: true, organization_name: event.data.organization_name });
        setSyncMessage(parts.length ? `Synced: ${parts.join(", ")}` : "Connected successfully!");
        setIsConnecting(false);
      }
      if (event.data?.type === "epic_error") {
        setErrorMsg(event.data.message ?? "Connection failed.");
        setIsConnecting(false);
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  // Debounced hospital search
  useEffect(() => {
    if (search.length < 2) {
      setEndpoints([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(
          `/api/epic/endpoints?search=${encodeURIComponent(search)}`
        );
        const data = await res.json();
        setEndpoints(data.endpoints ?? []);
      } catch {
        setEndpoints([]);
      } finally {
        setIsSearching(false);
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  const handleConnect = useCallback(async () => {
    if (!selectedEndpoint) return;
    setIsConnecting(true);
    setErrorMsg("");

    try {
      const codeVerifier = generateCodeVerifier();
      const codeChallenge = await generateCodeChallenge(codeVerifier);
      const state = generateState();

      // Store PKCE data — consumed by the callback page
      sessionStorage.setItem("epic_code_verifier", codeVerifier);
      sessionStorage.setItem("epic_oauth_state", state);
      sessionStorage.setItem("epic_fhir_base_url", selectedEndpoint.fhir_base_url);

      const res = await fetch("/api/epic/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fhir_base_url: selectedEndpoint.fhir_base_url,
          organization_name: selectedEndpoint.organization_name,
          state,
          code_challenge: codeChallenge,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(data.detail ?? "Failed to start connection.");
        setIsConnecting(false);
        return;
      }

      // Open Epic MyChart login in a popup — result comes back via postMessage
      const w = 520;
      const h = 680;
      const left = Math.round((screen.width - w) / 2);
      const top = Math.round((screen.height - h) / 2);
      const popup = window.open(
        data.auth_url,
        "epic_mychart_auth",
        `popup,width=${w},height=${h},left=${left},top=${top}`
      );

      if (!popup) {
        // Popup blocked — fall back to full-page redirect
        window.location.href = data.auth_url;
        return;
      }

      // isConnecting stays true while the popup is open; cleared by postMessage handler
    } catch (err) {
      setErrorMsg("Network error. Please try again.");
      setIsConnecting(false);
    }
  }, [selectedEndpoint]);

  const handleSync = useCallback(async () => {
    setIsSyncing(true);
    setSyncMessage("");
    try {
      const res = await fetch("/api/epic/sync", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        const s = data.summary ?? {};
        const parts = [];
        if (s.medications) parts.push(`${s.medications} medication${s.medications !== 1 ? "s" : ""}`);
        if (s.conditions) parts.push(`${s.conditions} condition${s.conditions !== 1 ? "s" : ""}`);
        if (s.appointments) parts.push(`${s.appointments} appointment${s.appointments !== 1 ? "s" : ""}`);
        if (s.encounters) parts.push(`${s.encounters} visit${s.encounters !== 1 ? "s" : ""}`);
        setSyncMessage(parts.length ? `Synced: ${parts.join(", ")}` : "Sync complete — no new records.");
        // Refresh status
        const statusRes = await fetch("/api/epic/status");
        setConnectionStatus(await statusRes.json());
      } else {
        setSyncMessage(data.detail ?? "Sync failed.");
      }
    } catch {
      setSyncMessage("Network error during sync.");
    } finally {
      setIsSyncing(false);
    }
  }, []);

  const handleDisconnect = useCallback(async () => {
    if (!confirm("Disconnect from MyChart? Your imported records will remain, but no new data will be synced.")) return;
    try {
      await fetch("/api/epic/disconnect", { method: "DELETE" });
      setConnectionStatus({ connected: false });
      setSyncMessage("");
    } catch {
      setErrorMsg("Failed to disconnect.");
    }
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm px-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
              <span className="text-white text-xs font-bold">M</span>
            </div>
            <div>
              <h2 className="font-semibold text-slate-800 text-sm">Link to MyChart</h2>
              <p className="text-xs text-slate-400">Powered by Epic SMART on FHIR</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">

          {/* ── CONNECTED STATE ─────────────────────────────────────────── */}
          {connectionStatus?.connected && (
            <div className="space-y-4">
              <div className="flex items-start gap-3 p-4 bg-green-50 border border-green-200 rounded-xl">
                <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
                <div className="text-sm">
                  <p className="font-semibold text-green-800">
                    Connected to {connectionStatus.organization_name}
                  </p>
                  {connectionStatus.last_sync_at && (
                    <p className="text-green-600 mt-0.5">
                      Last synced:{" "}
                      {new Date(connectionStatus.last_sync_at).toLocaleString([], {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  )}
                  {connectionStatus.sync_status === "error" && (
                    <p className="text-amber-600 mt-1">Last sync had an error — try syncing again.</p>
                  )}
                </div>
              </div>

              {syncMessage && (
                <p className="text-sm text-slate-600 text-center">{syncMessage}</p>
              )}

              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={handleSync}
                  disabled={isSyncing}
                  className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                             border border-slate-200 text-slate-700 text-sm font-medium
                             hover:bg-slate-50 disabled:opacity-50 transition-colors"
                >
                  {isSyncing ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <RefreshCw size={15} />
                  )}
                  {isSyncing ? "Syncing…" : "Sync Now"}
                </button>
                <button
                  onClick={handleDisconnect}
                  className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl
                             border border-red-200 text-red-600 text-sm font-medium
                             hover:bg-red-50 transition-colors"
                >
                  <Link2Off size={15} />
                  Disconnect
                </button>
              </div>

              <p className="text-xs text-slate-400 text-center">
                Your records are updated each time you sync.
                WellBridge only reads your data — it cannot write to Epic.
              </p>
            </div>
          )}

          {/* ── NOT CONNECTED STATE ─────────────────────────────────────── */}
          {connectionStatus && !connectionStatus.connected && (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                Link your MyChart account to automatically import your medications,
                conditions, appointments, and visit history.
              </p>

              {/* Hospital search */}
              <div className="relative">
                <Search
                  size={16}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  type="text"
                  placeholder="Search for your hospital or health system…"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setSelectedEndpoint(null);
                  }}
                  className="w-full pl-9 pr-4 py-2.5 border border-slate-200 rounded-xl
                             text-sm text-slate-800 placeholder-slate-400
                             focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                />
                {isSearching && (
                  <Loader2
                    size={14}
                    className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-slate-400"
                  />
                )}
              </div>

              {/* Results list */}
              {endpoints.length > 0 && (
                <div className="max-h-48 overflow-y-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
                  {endpoints.map((ep) => (
                    <button
                      key={ep.fhir_base_url}
                      onClick={() => {
                        setSelectedEndpoint(ep);
                        setSearch(ep.organization_name);
                        setEndpoints([]);
                      }}
                      className={`w-full text-left px-4 py-3 text-sm transition-colors
                        ${
                          selectedEndpoint?.fhir_base_url === ep.fhir_base_url
                            ? "bg-brand-50 text-brand-800"
                            : "text-slate-700 hover:bg-slate-50"
                        }`}
                    >
                      <span className="font-medium">{ep.organization_name}</span>
                    </button>
                  ))}
                </div>
              )}

              {search.length >= 2 && !isSearching && endpoints.length === 0 && (
                <p className="text-sm text-slate-400 text-center py-2">
                  No matching hospitals found. Try a different search term.
                </p>
              )}

              {errorMsg && (
                <p className="text-sm text-red-600 text-center">{errorMsg}</p>
              )}

              {/* Connect button */}
              <button
                onClick={handleConnect}
                disabled={!selectedEndpoint || isConnecting}
                className="w-full py-3 rounded-xl bg-blue-600 text-white text-sm font-semibold
                           flex items-center justify-center gap-2
                           hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed
                           transition-colors"
              >
                {isConnecting ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Connecting…
                  </>
                ) : (
                  <>
                    <ExternalLink size={16} />
                    {selectedEndpoint
                      ? `Connect to ${selectedEndpoint.organization_name}`
                      : "Select a hospital to connect"}
                  </>
                )}
              </button>

              <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-500 space-y-1">
                <p className="font-medium text-slate-700">What gets imported:</p>
                <p>Medications · Conditions · Appointments · Visit history · Allergies</p>
                <p className="pt-1">
                  WellBridge connects read-only. Your MyChart login is handled entirely
                  by Epic — we never see your Epic password.
                </p>
              </div>
            </div>
          )}

          {/* Loading state (fetching connection status) */}
          {connectionStatus === null && (
            <div className="flex items-center justify-center py-8 text-slate-400 gap-3">
              <Loader2 size={20} className="animate-spin" />
              <span className="text-sm">Checking connection status…</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
