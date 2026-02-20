"use client";

/**
 * Epic MyChart OAuth callback page.
 *
 * Epic redirects here after the user completes MyChart login:
 *   /epic/callback?code={auth_code}&state={state}
 *
 * Steps:
 *   1. Read code + state from URL search params
 *   2. Read code_verifier + expected_state from sessionStorage (set during connect)
 *   3. Verify state matches (CSRF protection)
 *   4. POST to /api/epic/exchange with code + code_verifier
 *   5. On success → show confirmation + redirect to chat
 *   6. On error → show message + link to retry
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle, AlertCircle, Loader2 } from "lucide-react";

type Status = "loading" | "success" | "error" | "csrf_error";

interface SyncSummary {
  medications?: number;
  conditions?: number;
  appointments?: number;
  encounters?: number;
  allergies?: number;
}

export default function EpicCallbackPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [orgName, setOrgName] = useState("");
  const [syncSummary, setSyncSummary] = useState<SyncSummary>({});
  const [errorMsg, setErrorMsg] = useState("");

  useEffect(() => {
    async function handleCallback() {
      // Detect whether we were opened as a popup by EpicConnectModal
      const isPopup = !!(window.opener && !window.opener.closed);

      function sendToOpener(msg: Record<string, unknown>) {
        if (isPopup) {
          window.opener.postMessage(msg, window.location.origin);
          setTimeout(() => window.close(), 1500);
        }
      }

      const code = searchParams.get("code");
      const state = searchParams.get("state");
      const error = searchParams.get("error");

      // Epic returned an error
      if (error) {
        const msg = searchParams.get("error_description") ?? error;
        setErrorMsg(msg);
        setStatus("error");
        sendToOpener({ type: "epic_error", message: msg });
        return;
      }

      if (!code || !state) {
        const msg = "Missing authorization code or state parameter.";
        setErrorMsg(msg);
        setStatus("error");
        sendToOpener({ type: "epic_error", message: msg });
        return;
      }

      // Read PKCE verifier and state from sessionStorage
      const storedState = sessionStorage.getItem("epic_oauth_state");
      const codeVerifier = sessionStorage.getItem("epic_code_verifier");
      const fhirBaseUrl = sessionStorage.getItem("epic_fhir_base_url");

      if (!storedState || !codeVerifier || !fhirBaseUrl) {
        const msg = "Session data missing. Please start the connection process again.";
        setErrorMsg(msg);
        setStatus("error");
        sendToOpener({ type: "epic_error", message: msg });
        return;
      }

      // CSRF check
      if (state !== storedState) {
        const msg = "State mismatch — possible CSRF attack. Connection aborted.";
        setErrorMsg(msg);
        setStatus("csrf_error");
        sessionStorage.removeItem("epic_oauth_state");
        sessionStorage.removeItem("epic_code_verifier");
        sessionStorage.removeItem("epic_fhir_base_url");
        sendToOpener({ type: "epic_error", message: msg });
        return;
      }

      // Clean up sessionStorage
      sessionStorage.removeItem("epic_oauth_state");
      sessionStorage.removeItem("epic_code_verifier");
      sessionStorage.removeItem("epic_fhir_base_url");

      try {
        const res = await fetch("/api/epic/exchange", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, code_verifier: codeVerifier, fhir_base_url: fhirBaseUrl }),
        });

        const data = await res.json();

        if (!res.ok) {
          const msg = data.detail ?? "Connection failed. Please try again.";
          setErrorMsg(msg);
          setStatus("error");
          sendToOpener({ type: "epic_error", message: msg });
          return;
        }

        setOrgName(data.organization_name ?? "your health system");
        setSyncSummary(data.sync ?? {});
        setStatus("success");

        if (isPopup) {
          // Send result back to the modal, then close popup
          sendToOpener({
            type: "epic_connected",
            organization_name: data.organization_name,
            sync: data.sync,
          });
        } else {
          // Standalone navigation — auto-redirect to chat after 4 seconds
          setTimeout(() => router.push("/chat"), 4000);
        }
      } catch {
        const msg = "Network error during connection. Please try again.";
        setErrorMsg(msg);
        setStatus("error");
        sendToOpener({ type: "epic_error", message: msg });
      }
    }

    handleCallback();
  }, [searchParams, router]);

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4 text-slate-600">
        <Loader2 size={40} className="animate-spin text-brand-500" />
        <p className="text-lg font-medium">Connecting to your MyChart account…</p>
        <p className="text-sm text-slate-400">This usually takes a few seconds.</p>
      </div>
    );
  }

  if (status === "success") {
    const total =
      (syncSummary.medications ?? 0) +
      (syncSummary.conditions ?? 0) +
      (syncSummary.appointments ?? 0) +
      (syncSummary.encounters ?? 0) +
      (syncSummary.allergies ?? 0);

    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-6 px-6 text-center">
        <CheckCircle size={56} className="text-green-500" />
        <div>
          <h1 className="text-2xl font-bold text-slate-800">MyChart Connected!</h1>
          <p className="mt-2 text-slate-500">
            Successfully linked to <strong>{orgName}</strong>.
          </p>
        </div>

        {total > 0 && (
          <div className="bg-green-50 border border-green-200 rounded-xl px-6 py-4 text-sm text-left w-full max-w-sm">
            <p className="font-semibold text-green-800 mb-2">Records imported:</p>
            <ul className="space-y-1 text-green-700">
              {!!syncSummary.medications && (
                <li>• {syncSummary.medications} medication{syncSummary.medications !== 1 ? "s" : ""}</li>
              )}
              {!!syncSummary.conditions && (
                <li>• {syncSummary.conditions} condition{syncSummary.conditions !== 1 ? "s" : ""}</li>
              )}
              {!!syncSummary.appointments && (
                <li>• {syncSummary.appointments} appointment{syncSummary.appointments !== 1 ? "s" : ""}</li>
              )}
              {!!syncSummary.encounters && (
                <li>• {syncSummary.encounters} past visit{syncSummary.encounters !== 1 ? "s" : ""}</li>
              )}
              {!!syncSummary.allergies && (
                <li>• {syncSummary.allergies} allerg{syncSummary.allergies !== 1 ? "ies" : "y"}</li>
              )}
            </ul>
          </div>
        )}

        <p className="text-sm text-slate-400">Redirecting you to chat in a moment…</p>
        <button
          onClick={() => router.push("/chat")}
          className="px-6 py-2.5 rounded-xl bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          Go to Chat Now
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 px-6 text-center">
      <AlertCircle size={56} className="text-red-500" />
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Connection Failed</h1>
        <p className="mt-2 text-slate-500 max-w-sm">{errorMsg}</p>
      </div>
      <div className="flex gap-3">
        <button
          onClick={() => router.push("/chat")}
          className="px-5 py-2.5 rounded-xl border border-slate-200 text-slate-700 text-sm hover:bg-slate-50 transition-colors"
        >
          Back to Chat
        </button>
        <button
          onClick={() => router.back()}
          className="px-5 py-2.5 rounded-xl bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
