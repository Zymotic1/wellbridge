/**
 * Chat note upload proxy — POST multipart/form-data.
 *
 * Receives a file from the chat ActionCard upload button, forwards it
 * to the backend /chat/sessions/{id}/upload endpoint with the bearer token,
 * and returns the analysis result (summary + action_cards + jargon_map).
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    const { accessToken } = await getAccessToken();

    // Pass the multipart form data straight through to FastAPI
    const formData = await request.formData();

    const res = await fetch(
      `${BACKEND}/chat/sessions/${params.sessionId}/upload`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          // Do NOT set Content-Type — the browser boundary is in the FormData
        },
        body: formData,
      }
    );

    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Upload failed" }, { status: 500 });
  }
}
