/**
 * Protected app layout — server component.
 *
 * Route protection is handled entirely by middleware.ts (redirects to /login
 * if no Auth0 session exists). Here we just render the AppShell which fetches
 * user info client-side via useUser() to avoid the Auth0 cookie-setting warning
 * that occurs when getSession() is called from a Server Component.
 */

import AppShell from "@/components/AppShell";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AppShell>{children}</AppShell>;
}
