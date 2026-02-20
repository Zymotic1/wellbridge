"use client";

import { X } from "lucide-react";
import type { JargonMapping } from "@/lib/types";

interface JargonTooltipProps {
  entry: JargonMapping;
  onClose: () => void;
}

export default function JargonTooltip({ entry, onClose }: JargonTooltipProps) {
  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/10"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Tooltip card */}
      <div
        role="dialog"
        aria-label={`Explanation of medical term: ${entry.term}`}
        aria-modal="true"
        className="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-sm
                   bg-white border border-slate-200 rounded-2xl shadow-2xl p-6 z-50"
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-600
                     rounded-lg p-1 transition-colors"
          aria-label="Close explanation"
        >
          <X size={18} />
        </button>

        {/* Medical term */}
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-1">
          Medical Term
        </p>
        <p className="text-lg font-bold text-slate-900 mb-4">{entry.term}</p>

        {/* Plain English */}
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-1">
          In Plain English
        </p>
        <p className="text-slate-700 mb-5 leading-relaxed">{entry.plain_english}</p>

        {/* Source sentence */}
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">
          From Your Record
        </p>
        <blockquote className="text-sm text-slate-600 italic border-l-2 border-brand-400 pl-4 leading-relaxed">
          "{entry.source_sentence}"
        </blockquote>

        <p className="mt-4 text-xs text-slate-400 text-center">
          This is a factual definition. Not medical advice.
        </p>
      </div>
    </>
  );
}
