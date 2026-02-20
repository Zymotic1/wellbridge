/**
 * Login page — shown to unauthenticated users who access a protected route.
 * Redirects immediately to Auth0 Universal Login.
 */

import { redirect } from "next/navigation";

export default function LoginPage({
  searchParams,
}: {
  searchParams: { returnTo?: string };
}) {
  const returnTo = searchParams.returnTo ?? "/chat";
  redirect(`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`);
}
