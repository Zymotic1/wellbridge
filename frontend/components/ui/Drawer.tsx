"use client";

/**
 * Drawer — a slide-in panel from the left edge of the screen.
 *
 * Used for:
 *  - Mobile navigation menu (replacing the fixed sidebar)
 *  - Mobile chat session list
 *
 * Accessibility:
 *  - Closes on Escape key
 *  - Closes when backdrop is tapped/clicked
 *  - Prevents body scroll while open
 */

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Optional header label shown above the close button */
  title?: string;
  /** Width of the drawer panel (Tailwind width class). Defaults to "w-72". */
  width?: string;
}

export default function Drawer({
  open,
  onClose,
  children,
  title,
  width = "w-72",
}: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Lock body scroll while open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={[
          "fixed inset-0 z-40 bg-black/40 backdrop-blur-sm transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        ].join(" ")}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        className={[
          "fixed left-0 top-0 bottom-0 z-50 flex flex-col bg-white shadow-2xl",
          "transform transition-transform duration-300 ease-in-out",
          width,
          open ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        {/* Drawer header */}
        <div className="flex items-center justify-between px-4 py-3.5 border-b border-slate-100 flex-shrink-0">
          {title ? (
            <span className="text-sm font-semibold text-slate-700">{title}</span>
          ) : (
            <span />
          )}
          <button
            onClick={onClose}
            aria-label="Close menu"
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
    </>
  );
}
