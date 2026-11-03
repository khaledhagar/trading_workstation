"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

import { ChatActions } from "./ChatActions";

const EXAMPLES = [
  "How diversified is my portfolio?",
  "Buy 5 NVDA",
  "Add PYPL to my watchlist",
];

export function ChatPanel({
  onActions,
  collapsed,
  onToggle,
}: {
  onActions: (msg: ChatMessage) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory().then(setMessages).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, waiting, collapsed]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || waiting) return;
    setInput("");
    setError(null);
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: message,
      actions: null,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);
    setWaiting(true);
    try {
      const reply = await api.chat(message);
      setMessages((m) => [...m, reply]);
      onActions(reply);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chat request failed");
    } finally {
      setWaiting(false);
    }
  };

  if (collapsed) {
    return (
      <button
        onClick={onToggle}
        data-testid="chat-toggle"
        className="flex h-full w-9 shrink-0 items-center justify-center rounded-md border border-border bg-panel text-[11px] font-semibold uppercase tracking-[0.2em] text-accent [writing-mode:vertical-rl] hover:bg-panel-2"
      >
        AI Copilot ◂
      </button>
    );
  }

  return (
    <aside
      data-testid="chat-panel"
      className="flex h-full w-[340px] shrink-0 flex-col rounded-md border border-border bg-panel xl:w-[380px]"
    >
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-border px-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">AI Copilot</h2>
        <button onClick={onToggle} data-testid="chat-toggle" className="text-xs text-muted hover:text-text">
          ▸ Hide
        </button>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" data-testid="chat-messages">
        {messages.length === 0 && !waiting && (
          <div className="rounded-md border border-border bg-panel-2 p-3 text-xs text-muted" data-testid="chat-welcome">
            <p className="mb-2 text-text">
              Hi, I&apos;m <span className="text-accent">trading_workstation</span>. I can analyze your portfolio,
              place trades and manage your watchlist.
            </p>
            <p className="mb-1.5">Try:</p>
            <div className="flex flex-col gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => send(ex)}
                  className="rounded border border-border px-2 py-1 text-left text-blue hover:border-blue"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              data-testid={`chat-${m.role}`}
              className={`max-w-[88%] whitespace-pre-wrap rounded-lg px-3 py-2 text-xs leading-relaxed ${
                m.role === "user" ? "bg-blue/20 text-text" : "border border-border bg-panel-2 text-text"
              }`}
            >
              {m.content}
              {m.role === "assistant" && <ChatActions actions={m.actions} />}
            </div>
          </div>
        ))}

        {waiting && (
          <div className="flex gap-1 px-2 py-1" data-testid="chat-typing" aria-label="Assistant is typing">
            {[0, 1, 2].map((i) => (
              <span key={i} className="typing-dot h-1.5 w-1.5 rounded-full bg-accent" />
            ))}
          </div>
        )}
        {error && <p className="text-xs text-down">{error}</p>}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="flex gap-2 border-t border-border p-2"
      >
        <input
          data-testid="chat-input"
          value={input}
          disabled={waiting}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your portfolio or place a trade…"
          className="min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-blue disabled:opacity-50"
        />
        <button
          type="submit"
          data-testid="chat-send"
          disabled={waiting || !input.trim()}
          className="rounded bg-purple px-3 py-1.5 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
