"use client";

/**
 * ChatWindow — the main chat interface component.
 *
 * Handles:
 *  - Fetching chat history for the current session (including the agent opener)
 *  - Streaming new messages via SSE (Server-Sent Events)
 *  - Accumulating token stream into a full message string
 *  - Receiving jargon_map, action_cards, and suggested_replies trailing SSE events
 *  - Rendering MessageBubble + ActionCard components
 *  - Contextual loading states that reflect the agentic nature of responses
 *  - Quick-reply pill buttons below the latest assistant message (AI-generated)
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useUser } from "@auth0/nextjs-auth0/client";
import { Send, Loader2, Mic, MicOff, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, JargonMapping, ActionCard, SSEEvent } from "@/lib/types";
import MessageBubble from "./MessageBubble";
import ActionCardComponent from "./ActionCard";
import EpicConnectModal from "./EpicConnectModal";

interface ChatWindowProps {
  sessionId: string;
  // If provided (from session creation), show as first message immediately
  openerMessage?: string;
}

// Contextual thinking phrases — rotated to feel less robotic
const THINKING_PHRASES = [
  "Listening...",
  "Looking through your records...",
  "Thinking about that...",
  "Putting this together for you...",
];

export default function ChatWindow({ sessionId, openerMessage }: ChatWindowProps) {
  const { user } = useUser();
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    // If we have an opener from session creation, show it immediately
    // before the history load completes — avoids a blank flash
    if (openerMessage) {
      return [{
        id: "opener",
        role: "assistant",
        content: openerMessage,
        jargon_map: [],
        action_cards: [],
        created_at: new Date().toISOString(),
      }];
    }
    return [];
  });
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingJargonMap, setStreamingJargonMap] = useState<JargonMapping[]>([]);
  const [streamingActionCards, setStreamingActionCards] = useState<ActionCard[]>([]);
  const [thinkingPhrase, setThinkingPhrase] = useState(THINKING_PHRASES[0]);
  // Suggested replies shown below the latest assistant message
  const [latestSuggestedReplies, setLatestSuggestedReplies] = useState<string[]>([]);
  // Epic / MyChart connect modal
  const [showEpicModal, setShowEpicModal] = useState(false);

  // Voice input state
  type MicPermission = "unknown" | "checking" | "granted" | "denied" | "unavailable";
  const [micPermission, setMicPermission] = useState<MicPermission>("unknown");
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micError, setMicError] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const thinkingPhraseRef = useRef(0);

  // Fetch message history on mount / session change
  useEffect(() => {
    async function loadHistory() {
      try {
        const res = await fetch(`/api/chat/${sessionId}/messages`);
        if (res.ok) {
          const data = await res.json();
          const loaded: ChatMessage[] = data.messages ?? [];
          // Only replace if we got real messages — don't wipe the optimistic opener
          if (loaded.length > 0) {
            setMessages(loaded);
          }
        }
      } catch {
        // Silently ignore — new session may have no messages yet
      }
    }
    loadHistory();
  }, [sessionId]);

  // Auto-scroll to bottom on new messages or streaming content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  // Rotate thinking phrase during long waits
  useEffect(() => {
    if (!isStreaming) return;
    const interval = setInterval(() => {
      thinkingPhraseRef.current = (thinkingPhraseRef.current + 1) % THINKING_PHRASES.length;
      setThinkingPhrase(THINKING_PHRASES[thinkingPhraseRef.current]);
    }, 2500);
    return () => clearInterval(interval);
  }, [isStreaming]);

  // ── Voice input ────────────────────────────────────────────────────────────

  /** Detect device type from userAgent for permission instructions. */
  function getDeviceType(): "ios" | "android" | "desktop" {
    if (typeof navigator === "undefined") return "desktop";
    const ua = navigator.userAgent.toLowerCase();
    if (/ipad|iphone|ipod/.test(ua)) return "ios";
    if (/android/.test(ua)) return "android";
    return "desktop";
  }

  /** Return the denial help text appropriate for the current device/browser. */
  function getMicDeniedMessage(): string {
    const device = getDeviceType();
    if (device === "ios") {
      return "Microphone access is blocked. On iOS: go to Settings → Safari (or your browser) → Microphone, and allow this site.";
    }
    if (device === "android") {
      return "Microphone access is blocked. Tap the lock or camera icon in the address bar, then set Microphone to Allow.";
    }
    return "Microphone access is blocked. Click the lock icon in your browser's address bar and set Microphone to Allow, then refresh.";
  }

  /** Return the best audio MIME type MediaRecorder supports on this device. */
  function getSupportedMimeType(): string {
    if (typeof MediaRecorder === "undefined") return "";
    const candidates = [
      "audio/webm;codecs=opus", // Chrome / Edge (desktop + Android)
      "audio/webm",
      "audio/mp4",              // Safari / iOS 14.3+
      "audio/ogg;codecs=opus",  // Firefox
    ];
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  }

  /**
   * Pre-flight check — called on mic button click.
   * Returns true only when it is safe to call getUserMedia.
   */
  function canUseMicrophone(): boolean {
    // 1. Secure context is required by all browsers for getUserMedia
    if (!window.isSecureContext) {
      setMicPermission("unavailable");
      setMicError(
        "Voice input requires a secure connection (HTTPS). " +
        "The app is running over HTTP — please ask your administrator to enable HTTPS."
      );
      return false;
    }

    // 2. API availability (undefined on very old browsers or after above check)
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicPermission("unavailable");
      setMicError(
        "Your browser does not support voice input. " +
        "Try the latest version of Chrome, Safari, or Edge."
      );
      return false;
    }

    // 3. MediaRecorder availability
    if (typeof MediaRecorder === "undefined") {
      setMicPermission("unavailable");
      setMicError(
        "Audio recording is not supported in this browser. " +
        "Try Chrome, Edge, or Safari."
      );
      return false;
    }

    return true;
  }

  // Check mic permission silently on mount so the button icon can reflect state
  useEffect(() => {
    if (typeof navigator === "undefined" || !window.isSecureContext) {
      setMicPermission("unavailable");
      return;
    }
    if (!navigator.permissions) return; // API not available — stay "unknown"

    navigator.permissions
      .query({ name: "microphone" as PermissionName })
      .then((status) => {
        setMicPermission(status.state === "granted" ? "granted"
                        : status.state === "denied"  ? "denied"
                        : "unknown");
        // Keep in sync if the user changes the setting while the tab is open
        status.onchange = () => {
          setMicPermission(status.state === "granted" ? "granted"
                          : status.state === "denied"  ? "denied"
                          : "unknown");
          if (status.state !== "denied") setMicError("");
        };
      })
      .catch(() => {/* Permissions API may not support microphone — stay "unknown" */});
  }, []);

  async function startRecording() {
    setMicError("");

    // Run pre-flight checks before touching any media API
    if (!canUseMicrophone()) return;

    // If permission is already known to be denied, show help and bail
    if (micPermission === "denied") {
      setMicError(getMicDeniedMessage());
      return;
    }

    setMicPermission("checking");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Permission was granted (may have been "prompt" → now "granted")
      setMicPermission("granted");
      setMicError("");

      const mimeType = getSupportedMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop()); // release mic immediately
        const blob = new Blob(audioChunksRef.current, {
          type: mimeType || "audio/webm",
        });
        await transcribeBlob(blob, mimeType || "audio/webm");
      };

      recorder.start(250); // 250ms timeslice — ensures data is flushed even on short recordings
      setIsRecording(true);

    } catch (err: unknown) {
      if (err instanceof DOMException) {
        if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
          setMicPermission("denied");
          setMicError(getMicDeniedMessage());
        } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
          setMicPermission("unavailable");
          setMicError("No microphone was found on this device.");
        } else if (err.name === "NotReadableError" || err.name === "TrackStartError") {
          setMicError("The microphone is in use by another app. Close it and try again.");
          setMicPermission("unknown");
        } else {
          setMicError(`Microphone error: ${err.message}`);
          setMicPermission("unknown");
        }
      } else {
        setMicError("Could not start the microphone. Please try again.");
        setMicPermission("unknown");
      }
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  }

  async function transcribeBlob(blob: Blob, mimeType: string) {
    // Pre-flight: empty blob means no audio was captured
    if (blob.size === 0) {
      setMicError("Nothing was heard — please try again.");
      return;
    }

    setIsTranscribing(true);
    setMicError("");
    try {
      const formData = new FormData();
      const ext = mimeType.split(";")[0].split("/")[1] ?? "webm";
      formData.append("audio", blob, `recording.${ext}`);

      const res = await fetch("/api/speech/transcribe", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        // Surface the actual error detail from the backend instead of a generic message
        const detail: string = data?.detail ?? data?.error ?? "Transcription failed.";
        setMicError(detail);
        return;
      }

      const text: string = data.text ?? "";
      if (text) {
        setInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
        inputRef.current?.focus();
      } else {
        setMicError("Nothing was heard — please try again.");
      }
    } catch {
      setMicError("Transcription failed — please try again or type your message.");
    } finally {
      setIsTranscribing(false);
    }
  }

  // ── Message sending ────────────────────────────────────────────────────────

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    // Optimistically add user message
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      jargon_map: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);
    setStreamingContent("");
    setStreamingJargonMap([]);
    setStreamingActionCards([]);
    setLatestSuggestedReplies([]);   // Clear pills when user sends a message
    thinkingPhraseRef.current = 0;
    setThinkingPhrase(THINKING_PHRASES[0]);

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (!res.ok || !res.body) {
        throw new Error("Stream failed");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      let finalJargonMap: JargonMapping[] = [];
      let finalActionCards: ActionCard[] = [];
      let finalSuggestedReplies: string[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event: SSEEvent = JSON.parse(jsonStr);

            if (event.type === "token") {
              accumulated += event.content;
              setStreamingContent(accumulated);
            } else if (event.type === "jargon_map") {
              finalJargonMap = event.data;
              setStreamingJargonMap(finalJargonMap);
            } else if (event.type === "action_cards") {
              finalActionCards = event.data;
              setStreamingActionCards(finalActionCards);
            } else if (event.type === "suggested_replies") {
              finalSuggestedReplies = event.data;
            } else if (event.type === "done") {
              const assistantMsg: ChatMessage = {
                id: crypto.randomUUID(),
                role: "assistant",
                content: accumulated,
                jargon_map: finalJargonMap,
                action_cards: finalActionCards,
                suggested_replies: finalSuggestedReplies,
                created_at: new Date().toISOString(),
              };
              setMessages((prev) => [...prev, assistantMsg]);
              setLatestSuggestedReplies(finalSuggestedReplies);
              setStreamingContent("");
              setStreamingJargonMap([]);
              setStreamingActionCards([]);
            } else if (event.type === "error") {
              throw new Error((event as { type: "error"; message: string }).message);
            }
          } catch {
            // Skip malformed SSE events
          }
        }
      }
    } catch {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "I'm having trouble connecting right now. Please try again in a moment.",
        jargon_map: [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Send a quick-reply pill as if the user typed it
  const sendQuickReply = useCallback((text: string) => {
    if (isStreaming) return;
    setInput(text);
    // Use a short delay so the input value is set before sendMessage reads it
    setTimeout(() => {
      setInput(""); // Will be read by sendMessage via closure below
      const trimmed = text.trim();
      if (!trimmed) return;

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
        jargon_map: [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLatestSuggestedReplies([]);
      setIsStreaming(true);
      setStreamingContent("");
      setStreamingJargonMap([]);
      setStreamingActionCards([]);
      thinkingPhraseRef.current = 0;
      setThinkingPhrase(THINKING_PHRASES[0]);

      (async () => {
        try {
          const res = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, message: trimmed }),
          });
          if (!res.ok || !res.body) throw new Error("Stream failed");

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let accumulated = "";
          let finalJargonMap: JargonMapping[] = [];
          let finalActionCards: ActionCard[] = [];
          let finalSuggestedReplies: string[] = [];

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            for (const line of chunk.split("\n")) {
              if (!line.startsWith("data: ")) continue;
              const jsonStr = line.slice(6).trim();
              if (!jsonStr) continue;
              try {
                const event: SSEEvent = JSON.parse(jsonStr);
                if (event.type === "token") { accumulated += event.content; setStreamingContent(accumulated); }
                else if (event.type === "jargon_map") { finalJargonMap = event.data; }
                else if (event.type === "action_cards") { finalActionCards = event.data; }
                else if (event.type === "suggested_replies") { finalSuggestedReplies = event.data; }
                else if (event.type === "done") {
                  setMessages((prev) => [...prev, {
                    id: crypto.randomUUID(), role: "assistant", content: accumulated,
                    jargon_map: finalJargonMap, action_cards: finalActionCards,
                    suggested_replies: finalSuggestedReplies, created_at: new Date().toISOString(),
                  }]);
                  setLatestSuggestedReplies(finalSuggestedReplies);
                  setStreamingContent("");
                }
              } catch { /* skip */ }
            }
          }
        } catch {
          setMessages((prev) => [...prev, {
            id: crypto.randomUUID(), role: "assistant",
            content: "I'm having trouble connecting right now. Please try again.",
            jargon_map: [], created_at: new Date().toISOString(),
          }]);
        } finally {
          setIsStreaming(false);
        }
      })();
    }, 0);
  }, [isStreaming, sessionId]);

  const handleUpload = useCallback(async (file: File) => {
    // Upload the file directly in the chat session and show the result here
    setIsStreaming(true);
    setStreamingContent("");
    setLatestSuggestedReplies([]);
    thinkingPhraseRef.current = 0;
    setThinkingPhrase("Reading your document...");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`/api/chat/sessions/${sessionId}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error("Upload failed");

      const data = await res.json();
      const uploadSuggestions: string[] = data.suggested_replies ?? [];
      const assistantMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.message ?? "I've read your document.",
        jargon_map: data.jargon_map ?? [],
        action_cards: data.action_cards ?? [],
        suggested_replies: uploadSuggestions,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setLatestSuggestedReplies(uploadSuggestions);
    } catch {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "I had trouble reading that file. Please try again, or type out what your note says and I'll help explain it.",
        jargon_map: [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setIsStreaming(false);
    }
  }, [sessionId]);

  return (
    <div className="flex flex-col h-full">
      {showEpicModal && <EpicConnectModal onClose={() => setShowEpicModal(false)} />}
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-1">
        {messages.map((msg, idx) => {
          const isLatestAssistant =
            msg.role === "assistant" && idx === messages.length - 1 && !isStreaming;
          return (
            <div key={msg.id}>
              <MessageBubble message={msg} />

              {/* Action cards appear below the assistant message that triggered them */}
              {msg.role === "assistant" && msg.action_cards && msg.action_cards.length > 0 && (
                <div className="flex flex-wrap gap-2 pl-1 mb-2">
                  {msg.action_cards.map((card) => (
                    <ActionCardComponent
                      key={card.id}
                      card={card}
                      onUpload={handleUpload}
                    />
                  ))}
                </div>
              )}

              {/* Quick-reply pills — only on the latest assistant message */}
              {isLatestAssistant && latestSuggestedReplies.length > 0 && (
                <div className="flex flex-wrap gap-2 pl-1 mb-3 mt-1">
                  {latestSuggestedReplies.map((reply) => (
                    <button
                      key={reply}
                      onClick={() => sendQuickReply(reply)}
                      className="px-3.5 py-1.5 rounded-full border border-brand-200
                                 bg-white text-sm text-brand-700 font-medium
                                 hover:bg-brand-50 hover:border-brand-400
                                 transition-colors shadow-sm"
                    >
                      {reply}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {/* In-progress streaming message */}
        {isStreaming && streamingContent && (
          <div className="flex justify-start mb-4">
            <div className="max-w-[78%] bg-white border border-slate-200 shadow-sm
                            rounded-2xl rounded-bl-sm px-5 py-3.5 text-sm text-slate-800">
              <div className="prose-sm max-w-none leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {streamingContent.replace(/\[JARGON:\s*([^|]+?)\s*\|[^\]]+\]/g, (_, t) => t.trim())}
                </ReactMarkdown>
              </div>
              <div className="mt-2 flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 rounded-full bg-slate-300 animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}

        {/* Thinking indicator — shown before first tokens arrive */}
        {isStreaming && !streamingContent && (
          <div className="flex justify-start mb-4">
            <div className="bg-white border border-slate-200 shadow-sm rounded-2xl rounded-bl-sm px-5 py-3.5">
              <div className="flex items-center gap-2 text-slate-400 text-sm">
                <Loader2 size={14} className="animate-spin flex-shrink-0" />
                <span className="transition-all">{thinkingPhrase}</span>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-slate-200 bg-white p-4">
        {/* Persistent quick-action pills above the input */}
        <div className="flex flex-wrap gap-2 mb-3">
          <button
            onClick={() => setShowEpicModal(true)}
            disabled={isStreaming}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full
                       border border-blue-200 bg-blue-50 text-xs text-blue-700 font-medium
                       hover:bg-blue-100 hover:border-blue-300 disabled:opacity-40
                       transition-colors shadow-sm"
          >
            <span className="w-3.5 h-3.5 rounded-full bg-blue-600 text-white
                             text-[8px] flex items-center justify-center font-bold flex-shrink-0">
              M
            </span>
            Link to MyChart
          </button>
        </div>

        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isRecording ? "Listening…" : "What's on your mind?"}
            rows={2}
            disabled={isStreaming || isRecording}
            className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50
                       px-4 py-3 text-sm text-slate-800 placeholder-slate-400
                       focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent
                       disabled:opacity-50 disabled:cursor-not-allowed"
          />

          {/* Mic button — appearance reflects permission + recording state */}
          <button
            onClick={isRecording ? stopRecording : startRecording}
            disabled={isStreaming || isTranscribing || micPermission === "checking"}
            aria-label={isRecording ? "Stop recording" : "Start voice input"}
            title={
              micPermission === "unavailable" ? "Voice input unavailable"
              : micPermission === "denied"    ? "Microphone access blocked — click for help"
              : isRecording                   ? "Tap to stop recording"
              : "Speak your message"
            }
            className={[
              "flex-shrink-0 w-11 h-11 rounded-xl flex items-center justify-center transition-all",
              isRecording
                ? "bg-red-500 hover:bg-red-600 text-white animate-pulse shadow-lg shadow-red-200"
              : isTranscribing || micPermission === "checking"
                ? "bg-slate-100 text-slate-400 cursor-wait"
              : micPermission === "unavailable"
                ? "bg-slate-100 text-slate-300 cursor-not-allowed"
              : micPermission === "denied"
                ? "bg-amber-50 border border-amber-200 text-amber-500 hover:bg-amber-100"
              : "bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-700",
              isStreaming ? "opacity-40 cursor-not-allowed" : "",
            ].join(" ")}
          >
            {isTranscribing || micPermission === "checking" ? (
              <Loader2 size={18} className="animate-spin" />
            ) : isRecording ? (
              <Square size={16} fill="white" />
            ) : micPermission === "denied" || micPermission === "unavailable" ? (
              <MicOff size={18} />
            ) : (
              <Mic size={18} />
            )}
          </button>

          {/* Send button */}
          <button
            onClick={sendMessage}
            disabled={!input.trim() || isStreaming || isRecording || isTranscribing}
            aria-label="Send message"
            className="flex-shrink-0 w-11 h-11 rounded-xl bg-brand-600 text-white
                       flex items-center justify-center hover:bg-brand-700 transition-colors
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isStreaming ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <Send size={18} />
            )}
          </button>
        </div>

        {/* Mic status / error bar */}
        {(isRecording || isTranscribing || micPermission === "checking" || micError) && (
          <div className={[
            "mt-2 flex items-start gap-1.5 text-xs rounded-lg px-2 py-1.5",
            micError && (micPermission === "denied" || micPermission === "unavailable")
              ? "bg-amber-50 text-amber-700"
              : micError
              ? "text-red-500"
              : "text-slate-400",
          ].join(" ")}>
            {isRecording && !micError && (
              <>
                <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse flex-shrink-0 mt-0.5" />
                <span>Recording — tap the button to stop</span>
              </>
            )}
            {(isTranscribing || micPermission === "checking") && !micError && (
              <>
                <Loader2 size={11} className="animate-spin flex-shrink-0 mt-0.5" />
                <span>Transcribing your message…</span>
              </>
            )}
            {micError && (
              <>
                <MicOff size={11} className="flex-shrink-0 mt-0.5" />
                <span>{micError}</span>
              </>
            )}
          </div>
        )}

        <p className="mt-2 text-xs text-slate-400 text-center">
          WellBridge shares information from your records only — not medical advice.
        </p>
      </div>
    </div>
  );
}
