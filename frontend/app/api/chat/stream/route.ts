/**
 * Chat stream proxy.
 *
 * Accepts POST from the browser, attaches the Auth0 access token,
 * and proxies the SSE stream from FastAPI back to the browser.
 *
 * Why a proxy instead of calling FastAPI directly from the browser?
 *  - The Auth0 access token is a server-side cookie (httpOnly)
 *  - The browser cannot read it directly — only this Route Handler can
 *  - This also prevents exposing the internal BACKEND_URL to the client
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

export async function POST(req: NextRequest) {
  let accessToken: string;

  try {
    const tokenResult = await getAccessToken();
    accessToken = tokenResult.accessToken!;
  } catch {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const body = await req.json();
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  const upstream = await fetch(`${backendUrl}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(body),
  });

  if (!upstream.ok) {
    const error = await upstream.json().catch(() => ({ detail: "Upstream error" }));
    return new Response(JSON.stringify(error), {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Pass the SSE stream directly to the browser
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
