"use client";

/**
 * MultiSelectFilter
 *
 * A compact multi-select dropdown with:
 *  - Click-to-toggle options (with checkboxes)
 *  - Inline search to filter long lists
 *  - Active selections shown as dismissible badges below the trigger
 *  - Click outside to close
 */

import { useState, useRef, useEffect } from "react";
import { ChevronDown, X, Check, Search } from "lucide-react";

export interface FilterOption {
  value: string;
  /** Full label shown in the dropdown list */
  label: string;
  /** Short label shown in the badge (falls back to value) */
  badgeLabel?: string;
}

interface Props {
  label: string;
  options: FilterOption[];
  selected: string[];
  onChange: (values: string[]) => void;
  /** Show search input inside dropdown. Default true. */
  searchable?: boolean;
}

export default function MultiSelectFilter({
  label,
  options,
  selected,
  onChange,
  searchable = true,
}: Props) {
  const [open, setOpen]   = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  const filtered = query.trim()
    ? options.filter((o) =>
        o.label.toLowerCase().includes(query.toLowerCase())
      )
    : options;

  function toggle(value: string) {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value]
    );
  }

  function remove(value: string) {
    onChange(selected.filter((v) => v !== value));
  }

  const hasSelection = selected.length > 0;

  return (
    <div ref={ref} className="relative">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => { setOpen(!open); setQuery(""); }}
        className={`flex items-center justify-between gap-1.5 w-full px-2.5 py-2 text-xs
                    border rounded-lg transition-colors
                    ${hasSelection
                      ? "border-brand-400 bg-brand-50 text-brand-700 font-medium"
                      : "border-slate-200 bg-white text-slate-500 hover:border-slate-300"
                    }`}
      >
        <span>
          {label}
          {hasSelection && (
            <span className="ml-1 px-1.5 py-0.5 bg-brand-600 text-white rounded-full text-[10px] font-bold">
              {selected.length}
            </span>
          )}
        </span>
        <ChevronDown
          size={12}
          className={`flex-shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute z-50 left-0 right-0 mt-1 bg-white border border-slate-200
                        rounded-xl shadow-lg overflow-hidden">
          {searchable && (
            <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100">
              <Search size={12} className="text-slate-400 flex-shrink-0" />
              <input
                autoFocus
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter…"
                className="w-full text-xs outline-none text-slate-700 placeholder-slate-400"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="text-slate-300 hover:text-slate-500"
                >
                  <X size={11} />
                </button>
              )}
            </div>
          )}

          {/* Option list */}
          <div className="max-h-52 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="px-3 py-3 text-xs text-slate-400">No matches</p>
            ) : (
              filtered.map((opt) => {
                const isSelected = selected.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggle(opt.value)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 text-xs text-left
                                transition-colors border-b border-slate-50 last:border-0
                                ${isSelected
                                  ? "bg-brand-50 text-brand-700"
                                  : "hover:bg-slate-50 text-slate-700"
                                }`}
                  >
                    {/* Checkbox */}
                    <span
                      className={`w-3.5 h-3.5 rounded border flex items-center justify-center
                                  flex-shrink-0 transition-colors
                                  ${isSelected
                                    ? "bg-brand-600 border-brand-600"
                                    : "border-slate-300 bg-white"
                                  }`}
                    >
                      {isSelected && <Check size={9} className="text-white" />}
                    </span>
                    {opt.label}
                  </button>
                );
              })
            )}
          </div>

          {/* Footer: clear all */}
          {hasSelection && (
            <div className="px-3 py-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => { onChange([]); setOpen(false); }}
                className="text-xs text-slate-400 hover:text-red-500 transition-colors"
              >
                Clear all
              </button>
            </div>
          )}
        </div>
      )}

      {/* Active selection badges */}
      {hasSelection && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {selected.map((val) => {
            const opt = options.find((o) => o.value === val);
            const display = opt?.badgeLabel ?? opt?.label ?? val;
            return (
              <span
                key={val}
                className="inline-flex items-center gap-1 px-2 py-0.5
                           bg-brand-100 text-brand-700 rounded-full text-[11px] font-medium"
              >
                {display}
                <button
                  type="button"
                  onClick={() => remove(val)}
                  className="hover:text-brand-900 transition-colors"
                  aria-label={`Remove ${display}`}
                >
                  <X size={10} />
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
