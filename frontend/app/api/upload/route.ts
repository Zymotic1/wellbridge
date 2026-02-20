/**
 * Document upload proxy — forwards multipart form data to the FastAPI OCR endpoint.
 *
 * Using a proxy instead of calling FastAPI directly because:
 *  1. The Auth0 access token is server-side only
 *  2. CORS would block direct browser → FastAPI file uploads
 */

import { NextRequest } from "next/server";
import { getAccessToken } from "@/lib/auth0";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  try {
    const { accessToken } = await getAccessToken();
    const formData = await req.formData();

    const res = await fetch(`${BACKEND}/ocr/upload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        // Do NOT set Content-Type here — let fetch set it with the boundary for multipart
      },
      body: formData,
    });

    const data = await res.json().catch(() => ({ detail: "Processing failed" }));
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
}
