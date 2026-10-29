"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import type { ChatActions as Actions, ChatMessage } from "@/lib/types";
import ChatActions from "./ChatActions";

const EXAMPLES = ["How concentrated is my portfolio?", "Buy 5 NVDA", "Add PYPL to my watchlist"];

interface Props {
  open: boolean;
  onToggle: () => void;
  onActions: (actions: Actions) => void;
  onError: (message: string) => void;
}

function Bubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === "user") {
    return (
      <div data-testid="chat-message-user" className="ml-8 self-end rounded-[3px] bg-blue/15 px-3 py-2 text-[13.5px] leading-snug text-ink">
        {msg.content}
      </div>
    );
  }
  return (
    <div data-testid="chat-message-assistant" className="mr-4 border-l-2 border-accent/70 pl-3 text-[13.5px] leading-relaxed text-ink">
      <p className="whitespace-pre-wrap">{msg.content}</p>
      <ChatActions actions={msg.actions} />
    </div>
  );
}

export default function ChatPanel({ open, onToggle, onActions, onError }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [waiting, setWaiting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api
      .chatHistory()
      .then((history) => setMessages((current) => (current.length ? current : history)))
      .catch((err) => onError(errorMessage(err)));
  }, [onError]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, waiting, open]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || waiting) return;
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: message,
      actions: null,
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);
    setInput("");
    setWaiting(true);
    try {
      const reply = await api.chat(message);
      setMessages((m) => [...m, reply]);
      if (reply.actions) onActions(reply.actions);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setWaiting(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    send(input);
  }

  if (!open) {
    return (
      <aside data-testid="chat-panel" data-open="false" className="panel w-full items-center py-2 lg:w-11">
        <button
          data-testid="chat-toggle"
          type="button"
          onClick={onToggle}
          aria-expanded={false}
          aria-label="Open AI assistant"
          className="flex items-center gap-2 rounded-[2px] px-2 py-1 text-[13px] font-semibold text-accent hover:bg-raised lg:flex-col"
        >
          <span aria-hidden="true">‹</span>
          <span className="lg:[writing-mode:vertical-rl]">AI assistant</span>
        </button>
      </aside>
    );
  }

  return (
    <aside data-testid="chat-panel" data-open="true" className="panel h-[520px] w-full lg:h-auto lg:w-[360px]">
      <div className="panel-title">
        <span className="h-2 w-2 rotate-45 bg-accent" aria-hidden="true" />
        <strong>AI assistant</strong>
        <button
          data-testid="chat-toggle"
          type="button"
          onClick={onToggle}
          aria-expanded={true}
          aria-label="Collapse AI assistant"
          className="ml-auto rounded-[2px] px-1.5 text-[16px] leading-none text-muted hover:bg-raised hover:text-ink"
        >
          ›
        </button>
      </div>

      <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 py-3">
        {messages.length === 0 && (
          <div className="border-l-2 border-accent/70 pl-3 text-[13.5px] leading-relaxed text-ink">
            <p>
              I can read your portfolio, explain your risk and P&amp;L, and place trades or edit your watchlist when you
              ask.
            </p>
            <p className="mt-3 text-[12px] text-muted">Try one of these:</p>
            <div className="mt-1.5 flex flex-col items-start gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => send(ex)}
                  disabled={waiting}
                  className="rounded-[2px] border border-line px-2 py-1 text-left text-[12.5px] text-blue hover:border-blue hover:bg-blue/10"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} />
        ))}
        {waiting && (
          <div data-testid="chat-typing" className="flex items-center gap-1 pl-3" aria-label="Assistant is typing">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex items-end gap-2 border-t border-line p-2">
        <textarea
          ref={inputRef}
          data-testid="chat-input"
          className="field min-h-[34px] flex-1 resize-none py-1.5 text-[13.5px] leading-snug"
          rows={2}
          maxLength={4000}
          placeholder="Ask about your portfolio or place a trade"
          aria-label="Message the AI assistant"
          value={input}
          disabled={waiting}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button
          data-testid="chat-send"
          type="submit"
          disabled={waiting || !input.trim()}
          className="h-[34px] rounded-[2px] bg-purple px-3.5 text-[13px] font-semibold text-white hover:bg-purple-hi disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
