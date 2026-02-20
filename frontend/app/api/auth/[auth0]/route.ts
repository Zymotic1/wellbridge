/**
 * Auth0 dynamic route handler.
 * Handles: /api/auth/login, /api/auth/logout, /api/auth/callback, /api/auth/me
 */

import { handleAuth } from "@/lib/auth0";

export const GET = handleAuth();
export const POST = handleAuth();
