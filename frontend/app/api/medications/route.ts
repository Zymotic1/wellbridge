/**
 * Medications proxy — GET /api/medications
 * Proxies to the FastAPI /medications endpoint.
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

async function getToken(): Promise<string> {
  const { accessToken } = await getAccessToken();
  return accessToken!;
}

export async function GET(request: NextRequest) {
  try {
    const token = await getToken();
    const qs = request.nextUrl.searchParams.toString();
    const url = `${BACKEND}/medications/${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}
