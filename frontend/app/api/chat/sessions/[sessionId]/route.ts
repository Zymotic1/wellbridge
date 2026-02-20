/**
 * Single-session proxy — PATCH (rename) and DELETE.
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

async function getToken(): Promise<string> {
  const { accessToken } = await getAccessToken();
  return accessToken!;
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    const token = await getToken();
    const body = await request.json();
    const res = await fetch(`${BACKEND}/chat/sessions/${params.sessionId}`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    const token = await getToken();
    const res = await fetch(`${BACKEND}/chat/sessions/${params.sessionId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}
