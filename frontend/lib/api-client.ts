/**
 * Typed fetch wrapper for calling the FastAPI backend via the Next.js
 * /api/backend/* proxy. Automatically attaches the Auth0 access token.
 *
 * Usage:
 *   const records = await apiGet<PatientRecord[]>("/records");
 *   const result  = await apiPost<ChatMessage>("/chat/send", { message });
 */

import { getAccessToken } from "@/lib/auth0";

const BACKEND_PROXY = "/api/backend";

async function getAuthHeaders(): Promise<HeadersInit> {
  try {
    const { accessToken } = await getAccessToken();
    return {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    };
  } catch {
    // If called from a client component without a session, return empty
    return { "Content-Type": "application/json" };
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BACKEND_PROXY}${path}`, { headers });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail ?? "API error");
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BACKEND_PROXY}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail ?? "API error");
  }
  return res.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BACKEND_PROXY}${path}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail ?? "API error");
  }
  return res.json() as Promise<T>;
}

/**
 * Streams a chat response as Server-Sent Events.
 * Returns an EventSource-compatible ReadableStream.
 */
export async function apiStreamChat(
  sessionId: string,
  message: string,
  accessToken: string
): Promise<Response> {
  return fetch(`${BACKEND_PROXY}/chat/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
}
