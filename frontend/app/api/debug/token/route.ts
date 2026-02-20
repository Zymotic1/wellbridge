/**
 * DEBUG ONLY — remove before production.
 * Calls the backend /debug/token endpoint with the current user's access token
 * and returns the decoded JWT claims so you can inspect what Auth0 is putting in the token.
 *
 * Usage: open http://localhost:3000/api/debug/token in your browser while logged in.
 */

import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const { accessToken } = await getAccessToken();
    const res = await fetch(`${BACKEND}/debug/token`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 });
  }
}
