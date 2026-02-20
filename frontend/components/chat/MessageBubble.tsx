"use client";

import type { ChatMessage } from "@/lib/types";
import JargonHighlighter from "./JargonHighlighter";
import { AlertCircle } from "lucide-react";
import { clsx } from "clsx";

interface MessageBubbleProps {
  message: ChatMessage;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isRefusal = message.intent === "MEDICAL_ADVICE";

  return (
    <div
      className={clsx(
        "flex w-full mb-4",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={clsx(
          "max-w-[75%] rounded-2xl px-5 py-3.5 text-sm leading-relaxed",
          isUser
            ? "bg-brand-600 text-white rounded-br-sm"
            : isRefusal
            ? "bg-amber-50 border border-amber-200 text-slate-800 rounded-bl-sm"
            : "bg-white border border-slate-200 text-slate-800 shadow-sm rounded-bl-sm"
        )}
      >
        {/* Refusal badge */}
        {isRefusal && !isUser && (
          <div className="flex items-center gap-2 mb-2 text-amber-700">
            <AlertCircle size={15} />
            <span className="text-xs font-semibold uppercase tracking-wide">
              Medical advice is outside my scope
            </span>
          </div>
        )}

        {/* Message content */}
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <JargonHighlighter
            text={message.content}
            jargonMap={message.jargon_map}
          />
        )}

        {/* Jargon hint */}
        {!isUser && message.jargon_map.length > 0 && (
          <p className="mt-2 text-xs text-slate-400 italic">
            Tap underlined words for plain-English explanations from your records.
          </p>
        )}

        {/* Timestamp */}
        <p
          className={clsx(
            "mt-1.5 text-xs",
            isUser ? "text-blue-200" : "text-slate-400"
          )}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>
    </div>
  );
}
