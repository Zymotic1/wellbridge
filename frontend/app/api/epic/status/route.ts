import { getAccessToken } from "@/lib/auth0";

export async function GET() {
  let accessToken: string;
  try {
    const t = await getAccessToken();
    accessToken = t.accessToken!;
  } catch {
    return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401 });
  }

  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${backend}/epic/status`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  const data = await upstream.json();
  return new Response(JSON.stringify(data), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
