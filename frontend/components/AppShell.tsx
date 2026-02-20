"use client";

/**
 * AppShell — responsive application wrapper.
 *
 * Desktop (md+):  permanent left sidebar with logo, nav links, and user footer.
 * Mobile (<md):   top bar with hamburger button; nav sidebar slides in as a drawer.
 *
 * Active nav item is highlighted using usePathname() so the highlight updates
 * client-side without a full page reload.
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@auth0/nextjs-auth0/client";
import {
  Home,
  MessageCircle,
  MapPin,
  Users,
  CalendarDays,
  LogOut,
  Menu,
} from "lucide-react";
import WellbridgeLogo from "@/components/WellbridgeLogo";
import ProfileSetupModal from "@/components/ProfileSetupModal";
import Drawer from "@/components/ui/Drawer";

const NAV_ITEMS = [
  { href: "/home",             icon: Home,          label: "Home"       },
  { href: "/chat",             icon: MessageCircle, label: "Talk"       },
  { href: "/journey",          icon: MapPin,        label: "My Journey" },
  { href: "/settings/sharing", icon: Users,         label: "People"     },
  { href: "/appointments",     icon: CalendarDays,  label: "Schedule"   },
];

interface AppShellProps {
  children: React.ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const { user } = useUser();

  // Prefer given_name; fall back to first word of name only if it's not an email.
  const rawName = String(user?.given_name ?? user?.name ?? user?.nickname ?? "");
  const displayName = rawName && !rawName.includes("@") ? rawName.split(" ")[0] : "You";
  const userPicture = user?.picture ?? undefined;
  const [navOpen, setNavOpen] = useState(false);
  const pathname = usePathname();

  // Close the nav drawer whenever the route changes
  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  // ── Shared sub-components ────────────────────────────────────────────────

  function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
    return (
      <nav className="flex-1 p-3 space-y-0.5">
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
          const active = pathname?.startsWith(href) ?? false;
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              className={[
                "flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors font-medium text-sm",
                active
                  ? "bg-brand-50 text-brand-700"
                  : "text-slate-500 hover:bg-brand-50 hover:text-brand-700",
              ].join(" ")}
            >
              <Icon size={17} className="flex-shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>
    );
  }

  function UserFooter() {
    return (
      <div className="p-3 border-t border-slate-100 flex-shrink-0">
        <div className="flex items-center gap-2.5 mb-2 px-1">
          {userPicture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={userPicture}
              alt={displayName}
              className="w-7 h-7 rounded-full flex-shrink-0"
            />
          ) : (
            <div className="w-7 h-7 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0">
              <span className="text-xs font-semibold text-brand-600">
                {displayName.charAt(0).toUpperCase()}
              </span>
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-slate-700 truncate">{displayName}</p>
          </div>
        </div>
        <a
          href="/api/auth/logout"
          className="flex items-center gap-2 px-3 py-2 rounded-xl text-slate-400
                     hover:bg-red-50 hover:text-red-500 transition-colors text-xs w-full"
        >
          <LogOut size={14} />
          Sign out
        </a>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">

      {/* ── Desktop sidebar (md and up) ──────────────────────────────────── */}
      <aside className="hidden md:flex w-56 bg-white border-r border-slate-200 flex-col shadow-sm flex-shrink-0">
        <div className="p-5 border-b border-slate-100 flex-shrink-0">
          <WellbridgeLogo size="sm" showText={true} />
        </div>
        <NavLinks />
        <UserFooter />
      </aside>

      {/* ── Right side: mobile top bar + page content ─────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        {/* Mobile top bar — hidden on md+ */}
        <header className="md:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-slate-200 flex-shrink-0">
          <button
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            className="p-2 -ml-1 rounded-xl text-slate-500 hover:bg-slate-100 transition-colors flex-shrink-0"
          >
            <Menu size={20} />
          </button>
          <div className="flex-1 flex justify-center">
            <WellbridgeLogo size="sm" showText={true} />
          </div>
          {/* Right spacer keeps logo centred */}
          <div className="w-9 flex-shrink-0" />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto min-w-0">
          {children}
        </main>
      </div>

      {/* ── Mobile nav drawer ────────────────────────────────────────────── */}
      <Drawer
        open={navOpen}
        onClose={() => setNavOpen(false)}
        title="WellBridge"
      >
        <div className="flex flex-col h-full">
          <NavLinks onNavigate={() => setNavOpen(false)} />
          <UserFooter />
        </div>
      </Drawer>

      {/* Name collection modal — shown once on first login */}
      <ProfileSetupModal />
    </div>
  );
}
