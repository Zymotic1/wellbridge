import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

export async function POST(req: NextRequest) {
  let accessToken: string;
  try {
    const t = await getAccessToken();
    accessToken = t.accessToken!;
  } catch {
    return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
  }

  const body = await req.json();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

  const upstream = await fetch(`${backend}/epic/connect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(body),
  });

  const data = await upstream.json();
  return new Response(JSON.stringify(data), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
