/**
 * Chat sessions proxy — GET (list) and POST (create).
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

async function getToken(): Promise<string> {
  const { accessToken } = await getAccessToken();
  return accessToken!;
}

export async function GET() {
  try {
    const token = await getToken();
    const res = await fetch(`${BACKEND}/chat/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}

export async function POST() {
  try {
    const token = await getToken();
    const res = await fetch(`${BACKEND}/chat/sessions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}
