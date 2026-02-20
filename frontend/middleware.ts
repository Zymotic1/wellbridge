/**
 * Next.js middleware — runs on every matched route before the page renders.
 *
 * Responsibilities:
 *  1. Protect all routes under /(app)/* — redirect unauthenticated users to /login
 *  2. Inject tenant context headers (x-tenant-id, x-user-id) for use in
 *     Route Handlers that proxy to FastAPI
 *
 * Auth0 custom claims namespace: https://wellbridge.app/
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { getSession } from "@auth0/nextjs-auth0/edge";

const CLAIM_NS = "https://wellbridge.app/";

// Routes that do NOT require authentication
const PUBLIC_PATHS = [
  "/api/auth",
  "/login",
  "/_next",
  "/favicon.ico",
  "/health",
];

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;  // Landing page — reachable after logout
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const res = NextResponse.next();
  const session = await getSession(request, res);

  if (!session?.user) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("returnTo", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Forward tenant context to Route Handlers and Server Components
  const tenantId: string = session.user[`${CLAIM_NS}tenant_id`] ?? "";
  const userId: string = session.user.sub ?? "";

  res.headers.set("x-tenant-id", tenantId);
  res.headers.set("x-user-id", userId);

  return res;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     *  - _next internals & static assets
     *  - /api/auth/* (Auth0 handlers set cookies that middleware can strip)
     */
    "/((?!_next/static|_next/image|favicon.ico|api/auth/|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
