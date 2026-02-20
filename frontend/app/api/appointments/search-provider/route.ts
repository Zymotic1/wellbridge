/**
 * Proxy to the backend /appointments/search-provider endpoint.
 * Searches the CMS NPI Registry (free public API, no key required).
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  try {
    const { accessToken } = await getAccessToken();
    const qs = request.nextUrl.searchParams.toString();
    const res = await fetch(`${BACKEND}/appointments/search-provider?${qs}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}
