"use client";

import { useCallback, useRef, useState } from "react";

export interface Toast {
  id: number;
  message: string;
}

const TOAST_MS = 6000;

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const pushError = useCallback(
    (message: string) => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { id, message }]);
      setTimeout(() => dismiss(id), TOAST_MS);
    },
    [dismiss],
  );

  return { toasts, pushError, dismiss };
}

export default function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed bottom-3 left-3 z-50 flex max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          data-testid="toast"
          role="alert"
          className="pointer-events-auto flex items-start gap-3 rounded-[3px] border border-down/60 border-l-4 border-l-down bg-raised px-3 py-2 shadow-lg shadow-black/40"
        >
          <span data-testid="error-message" className="flex-1 text-[13px] leading-snug text-ink">
            {t.message}
          </span>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            className="text-muted hover:text-ink"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
