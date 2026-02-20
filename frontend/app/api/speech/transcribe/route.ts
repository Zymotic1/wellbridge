/**
 * Speech transcription proxy — POST /api/speech/transcribe
 *
 * Receives an audio blob from the chat UI (multipart/form-data, field "audio"),
 * forwards it to the FastAPI /speech/transcribe endpoint with the user's
 * Bearer token, and returns { text: "..." }.
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  try {
    const { accessToken } = await getAccessToken();
    const formData = await request.formData();

    const res = await fetch(`${BACKEND}/speech/transcribe`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        // Do NOT set Content-Type — let fetch set it with the boundary for multipart
      },
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      console.error(`[speech/transcribe] backend returned ${res.status}:`, data);
    }

    // Pass through both the body and status so the client can surface the real error
    return Response.json(data, { status: res.status });
  } catch (err) {
    console.error("[speech/transcribe] proxy error:", err);
    return Response.json(
      { detail: "Transcription service unavailable. Ensure the backend is running." },
      { status: 503 },
    );
  }
}
