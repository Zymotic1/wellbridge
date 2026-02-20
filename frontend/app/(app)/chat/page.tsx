/**
 * Chat page — agentic conversation experience.
 *
 * Responsive layout:
 *  - Desktop (md+): permanent session list sidebar + full-height chat area
 *  - Mobile (<md):  full-screen chat area; session list opens in a slide-in drawer
 *
 * Key behaviors:
 *  - On first load with no sessions, auto-creates one so the agent can greet immediately
 *  - New sessions return an opener_message from the backend (stored in DB and passed
 *    directly to ChatWindow so the greeting appears instantly without a second fetch)
 *  - Users never see a blank "select a session" screen — there's always a conversation
 *  - Session items have a ⋯ menu for inline rename and delete with confirmation
 */

"use client";

import { useState, useEffect, useRef } from "react";
import {
  Plus, MessageSquare, Loader2, MoreHorizontal,
  Pencil, Trash2, Check, X, PanelLeft,
} from "lucide-react";
import ChatWindow from "@/components/chat/ChatWindow";
import Drawer from "@/components/ui/Drawer";
import type { ChatSession } from "@/lib/types";

interface ActiveSession {
  session: ChatSession;
  openerMessage?: string;
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [active, setActive] = useState<ActiveSession | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [creatingSession, setCreatingSession] = useState(false);

  // Mobile session drawer
  const [sessionsDrawerOpen, setSessionsDrawerOpen] = useState(false);

  // Rename state
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

  // Delete confirm state
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Context menu
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  useEffect(() => {
    initSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Close context menu on outside click
  useEffect(() => {
    if (!menuOpenId) return;
    function handleClick() { setMenuOpenId(null); }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, [menuOpenId]);

  // Focus rename input when it appears
  useEffect(() => {
    if (renamingId) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [renamingId]);

  async function initSessions() {
    try {
      const res = await fetch("/api/chat/sessions");
      if (res.ok) {
        const data = await res.json();
        const sessionList: ChatSession[] = data.sessions ?? [];
        setSessions(sessionList);
        if (sessionList.length > 0) {
          setActive({ session: sessionList[0] });
        } else {
          await createNewSession();
        }
      }
    } catch {
      // Ignore
    } finally {
      setLoadingSessions(false);
    }
  }

  async function createNewSession() {
    if (creatingSession) return;
    setCreatingSession(true);
    try {
      const res = await fetch("/api/chat/sessions", { method: "POST" });
      if (res.ok) {
        const session: ChatSession = await res.json();
        setSessions((prev) => [session, ...prev]);
        setActive({ session, openerMessage: session.opener_message });
        setSessionsDrawerOpen(false); // close mobile drawer after creating
      }
    } catch {
      // Ignore
    } finally {
      setCreatingSession(false);
    }
  }

  function selectSession(session: ChatSession) {
    if (renamingId) return;
    setActive({ session });
    setSessionsDrawerOpen(false); // close mobile drawer on selection
  }

  // ── Rename ──────────────────────────────────────────────────────────────────

  function startRename(session: ChatSession) {
    setMenuOpenId(null);
    setRenamingId(session.id);
    setRenameValue(session.title ?? "Conversation");
  }

  async function commitRename(sessionId: string) {
    const title = renameValue.trim();
    if (!title) { cancelRename(); return; }
    setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title } : s)));
    if (active?.session.id === sessionId) {
      setActive((prev) => prev ? { ...prev, session: { ...prev.session, title } } : prev);
    }
    setRenamingId(null);
    try {
      await fetch(`/api/chat/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    } catch { /* optimistic update already applied */ }
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameValue("");
  }

  // ── Delete ──────────────────────────────────────────────────────────────────

  function confirmDelete(sessionId: string) {
    setMenuOpenId(null);
    setDeletingId(sessionId);
  }

  async function executeDelete(sessionId: string) {
    setDeletingId(null);
    const wasActive = active?.session.id === sessionId;
    const remaining = sessions.filter((s) => s.id !== sessionId);
    setSessions(remaining);
    if (wasActive) {
      if (remaining.length > 0) {
        setActive({ session: remaining[0] });
      } else {
        setActive(null);
        await createNewSession();
      }
    }
    try {
      await fetch(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
    } catch { /* ignore */ }
  }

  // ── Shared session list JSX ─────────────────────────────────────────────────

  function SessionList() {
    return (
      <>
        {/* New Conversation button */}
        <div className="p-3 border-b border-slate-100 flex-shrink-0">
          <button
            onClick={createNewSession}
            disabled={creatingSession}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5
                       bg-brand-600 text-white rounded-xl text-sm font-medium
                       hover:bg-brand-700 transition-colors
                       disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {creatingSession ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            New Conversation
          </button>
        </div>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto p-2">
          {loadingSessions ? (
            <div className="flex items-center gap-2 text-slate-400 text-sm p-3">
              <Loader2 size={14} className="animate-spin" />
              Loading…
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = active?.session.id === session.id;
              const isRenaming = renamingId === session.id;
              const isConfirmingDelete = deletingId === session.id;
              const isMenuOpen = menuOpenId === session.id;

              return (
                <div
                  key={session.id}
                  className={`group relative rounded-lg mb-1 transition-colors
                    ${isActive ? "bg-brand-50" : "hover:bg-slate-50"}`}
                >
                  {isConfirmingDelete ? (
                    <div className="px-3 py-2.5">
                      <p className="text-xs text-slate-600 mb-2">Delete this conversation?</p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => executeDelete(session.id)}
                          className="flex-1 text-xs px-2 py-1 bg-red-500 text-white rounded-md hover:bg-red-600 transition-colors"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="flex-1 text-xs px-2 py-1 bg-slate-100 text-slate-600 rounded-md hover:bg-slate-200 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : isRenaming ? (
                    <div className="px-3 py-2 flex items-center gap-1">
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename(session.id);
                          if (e.key === "Escape") cancelRename();
                        }}
                        className="flex-1 text-sm bg-white border border-brand-300 rounded px-1.5 py-0.5 outline-none focus:border-brand-500"
                      />
                      <button onClick={() => commitRename(session.id)} className="text-brand-600 hover:text-brand-800" aria-label="Save">
                        <Check size={14} />
                      </button>
                      <button onClick={cancelRename} className="text-slate-400 hover:text-slate-600" aria-label="Cancel">
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => selectSession(session)}
                      className={`w-full text-left px-3 py-2.5 rounded-lg
                        ${isActive ? "text-brand-700" : "text-slate-600"}`}
                    >
                      <div className="flex items-center gap-2 pr-6">
                        <MessageSquare size={14} className="flex-shrink-0 opacity-60" />
                        <span className="text-sm truncate">{session.title ?? "Conversation"}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-0.5 pl-5">
                        {new Date(session.updated_at).toLocaleDateString()}
                      </p>
                    </button>
                  )}

                  {/* Three-dot context menu */}
                  {!isRenaming && !isConfirmingDelete && (
                    <div className="absolute right-1 top-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpenId(isMenuOpen ? null : session.id);
                        }}
                        className={`p-1 rounded transition-colors
                          ${isMenuOpen
                            ? "opacity-100 bg-slate-100 text-slate-600"
                            : "opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-600 hover:bg-slate-100"
                          }`}
                        aria-label="Session options"
                      >
                        <MoreHorizontal size={14} />
                      </button>
                      {isMenuOpen && (
                        <div
                          className="absolute right-0 top-7 w-36 bg-white border border-slate-200 rounded-lg shadow-lg z-50 py-1"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            onClick={() => startRename(session)}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                          >
                            <Pencil size={13} />
                            Rename
                          </button>
                          <button
                            onClick={() => confirmDelete(session.id)}
                            className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-red-500 hover:bg-red-50 transition-colors"
                          >
                            <Trash2 size={13} />
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </>
    );
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">

      {/* ── Desktop: permanent session sidebar (md+) ── */}
      <aside className="hidden md:flex w-64 border-r border-slate-200 bg-white flex-col flex-shrink-0">
        <SessionList />
      </aside>

      {/* ── Chat area ── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        {/* Mobile-only chat header: session title + drawer toggle */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-slate-200 flex-shrink-0">
          <button
            onClick={() => setSessionsDrawerOpen(true)}
            aria-label="Open conversations"
            className="p-2 -ml-1 rounded-xl text-slate-500 hover:bg-slate-100 transition-colors flex-shrink-0"
          >
            <PanelLeft size={19} />
          </button>
          <span className="flex-1 text-sm font-medium text-slate-700 truncate">
            {active?.session.title ?? "Conversation"}
          </span>
          <button
            onClick={createNewSession}
            disabled={creatingSession}
            aria-label="New conversation"
            className="p-2 -mr-1 rounded-xl text-brand-600 hover:bg-brand-50 transition-colors flex-shrink-0 disabled:opacity-40"
          >
            {creatingSession ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
          </button>
        </div>

        {/* Chat window */}
        <div className="flex-1 overflow-hidden">
          {active ? (
            <ChatWindow
              sessionId={active.session.id}
              openerMessage={active.openerMessage}
            />
          ) : loadingSessions ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 size={24} className="animate-spin text-brand-400" />
            </div>
          ) : null}
        </div>
      </div>

      {/* ── Mobile: sessions drawer ── */}
      <Drawer
        open={sessionsDrawerOpen}
        onClose={() => setSessionsDrawerOpen(false)}
        title="Conversations"
        width="w-80"
      >
        <div className="flex flex-col h-full">
          <SessionList />
        </div>
      </Drawer>
    </div>
  );
}
