"use client";

/**
 * JargonHighlighter — renders assistant messages as formatted markdown with
 * clickable medical term highlights.
 *
 * The LLM embeds [JARGON: term | plain_english] markers in its output. This
 * component:
 *   1. Strips those markers (replacing them with just the term text)
 *   2. Renders the cleaned string as Markdown (bold, bullets, paragraphs)
 *   3. Highlights every jargon term found in the text by name-match and
 *      wraps it in a clickable <button> that opens JargonTooltip
 *
 * Name-based matching is used instead of char offsets because markdown
 * rendering removes ** / - / • symbols, shifting all character positions.
 */

import { useState, useMemo, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { JargonMapping } from "@/lib/types";
import JargonTooltip from "./JargonTooltip";

interface JargonHighlighterProps {
  text: string;
  jargonMap: JargonMapping[];
}

/** Remove [JARGON: term | plain_english] markers, keeping only the term. */
function stripJargonMarkers(text: string): string {
  return text.replace(/\[JARGON:\s*([^|]+?)\s*\|[^\]]+\]/g, (_, term) =>
    term.trim()
  );
}

/**
 * Split a plain string by jargon terms (longest-first to avoid partial matches).
 * Returns an array of string segments and JargonMapping objects for the matched terms.
 */
function splitByJargonTerms(
  text: string,
  entries: JargonMapping[]
): (string | JargonMapping)[] {
  if (!entries.length) return [text];

  // Longest terms first so "myocardial infarction" matches before "infarction"
  const sorted = [...entries].sort((a, b) => b.term.length - a.term.length);
  const result: (string | JargonMapping)[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    let firstIdx = Infinity;
    let firstEntry: JargonMapping | null = null;

    for (const entry of sorted) {
      const idx = remaining.toLowerCase().indexOf(entry.term.toLowerCase());
      if (idx !== -1 && idx < firstIdx) {
        firstIdx = idx;
        firstEntry = entry;
      }
    }

    if (!firstEntry) {
      result.push(remaining);
      break;
    }

    if (firstIdx > 0) result.push(remaining.slice(0, firstIdx));

    result.push(firstEntry);
    remaining = remaining.slice(firstIdx + firstEntry.term.length);
  }

  return result;
}

export default function JargonHighlighter({
  text,
  jargonMap,
}: JargonHighlighterProps) {
  const [activeJargon, setActiveJargon] = useState<JargonMapping | null>(null);

  // Strip [JARGON: ...] markers once
  const cleanText = useMemo(() => stripJargonMarkers(text), [text]);

  // Highlight jargon terms within a plain string segment
  const highlightString = useCallback(
    (str: string, keyPrefix: string): React.ReactNode => {
      if (!jargonMap.length) return str;
      const parts = splitByJargonTerms(str, jargonMap);
      if (parts.length === 1 && typeof parts[0] === "string") return str;

      return parts.map((part, i) => {
        if (typeof part === "string") {
          return <span key={`${keyPrefix}-t${i}`}>{part}</span>;
        }
        return (
          <button
            key={`${keyPrefix}-j${i}`}
            className="jargon-term"
            onClick={() => setActiveJargon(part)}
            aria-label={`Medical term: ${part.term}. Tap for plain-English explanation.`}
          >
            {part.term}
          </button>
        );
      });
    },
    [jargonMap]
  );

  /**
   * Process react-markdown children: apply jargon highlighting to any string
   * children; pass React elements through untouched.
   */
  const processChildren = useCallback(
    (children: React.ReactNode, keyPrefix: string): React.ReactNode => {
      if (typeof children === "string") {
        return highlightString(children, keyPrefix);
      }
      if (Array.isArray(children)) {
        return children.map((child, i) => {
          if (typeof child === "string") {
            return (
              <span key={`${keyPrefix}-c${i}`}>
                {highlightString(child, `${keyPrefix}-c${i}`)}
              </span>
            );
          }
          return child;
        });
      }
      return children;
    },
    [highlightString]
  );

  // Custom components for react-markdown
  const components = useMemo(
    () => ({
      // Paragraphs — apply jargon highlighting and section-header styling
      p({
        children,
        ...props
      }: React.HTMLAttributes<HTMLParagraphElement> & {
        children?: React.ReactNode;
      }) {
        const processed = processChildren(children, "p");
        // Bold-only paragraph = section header (e.g. **Why You Were Seen**)
        const isBoldHeader =
          Array.isArray(children)
            ? children.every(
                (c) =>
                  typeof c !== "string" || c.trim() === ""
              )
            : false;
        return (
          <p
            className={
              isBoldHeader
                ? "mt-4 first:mt-0 mb-1"
                : "mb-2 last:mb-0 leading-relaxed"
            }
            {...props}
          >
            {processed}
          </p>
        );
      },

      // Bold text — section headers
      strong({ children }: { children?: React.ReactNode }) {
        return (
          <strong className="font-semibold text-slate-900">{children}</strong>
        );
      },

      // Unordered lists
      ul({ children }: { children?: React.ReactNode }) {
        return <ul className="mb-2 space-y-1 pl-0">{children}</ul>;
      },

      // Ordered lists
      ol({ children }: { children?: React.ReactNode }) {
        return (
          <ol className="mb-2 space-y-1 pl-4 list-decimal">{children}</ol>
        );
      },

      // List items — apply jargon highlighting
      li({
        children,
        ...props
      }: React.LiHTMLAttributes<HTMLLIElement> & {
        children?: React.ReactNode;
      }) {
        return (
          <li
            className="flex gap-2 leading-relaxed before:content-['•'] before:text-slate-400 before:flex-shrink-0"
            {...props}
          >
            <span>{processChildren(children, "li")}</span>
          </li>
        );
      },

      // Horizontal rules (dividers)
      hr() {
        return <hr className="my-3 border-slate-200" />;
      },
    }),
    [processChildren]
  );

  return (
    <>
      <div className="prose-sm max-w-none text-slate-800">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {cleanText}
        </ReactMarkdown>
      </div>

      {activeJargon && (
        <JargonTooltip
          entry={activeJargon}
          onClose={() => setActiveJargon(null)}
        />
      )}
    </>
  );
}
