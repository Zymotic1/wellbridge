"use client";

/**
 * Root landing page. Redirects authenticated users to /chat,
 * unauthenticated users see a marketing/login page.
 *
 * Uses useUser() (client-side) instead of getSession() (server-side) to avoid
 * the Auth0 cookie-setting warning that occurs in Server Components.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@auth0/nextjs-auth0/client";
import Link from "next/link";
import WellbridgeLogo from "@/components/WellbridgeLogo";

export default function HomePage() {
  const { user, isLoading } = useUser();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/chat");
    }
  }, [user, isLoading, router]);

  // While checking auth, show nothing to avoid flash
  if (isLoading) return null;

  // Authenticated — redirect in progress
  if (user) return null;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
      <div className="max-w-2xl">
        <div className="flex justify-center mb-6">
          <WellbridgeLogo size="xl" showText={false} />
        </div>
        <h1 className="text-5xl font-bold text-brand-700 mb-4">WellBridge</h1>
        <p className="text-xl text-slate-600 mb-8 leading-relaxed">
          Understand your health records in plain language.
          <br />
          Ask questions. Never receive medical advice — only facts from your own records.
        </p>

        <div className="flex gap-4 justify-center">
          <Link
            href="/api/auth/login"
            className="px-8 py-3 bg-brand-600 text-white rounded-xl font-semibold
                       hover:bg-brand-700 transition-colors shadow-md"
          >
            Sign In
          </Link>
          <Link
            href="/api/auth/login?screen_hint=signup"
            className="px-8 py-3 border-2 border-brand-600 text-brand-700 rounded-xl
                       font-semibold hover:bg-brand-50 transition-colors"
          >
            Create Account
          </Link>
        </div>

        <p className="mt-8 text-sm text-slate-400">
          WellBridge does not provide medical diagnoses or treatment recommendations.
          Always consult your healthcare provider.
        </p>
      </div>
    </main>
  );
}
