export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export const STALE_MS = 5000;
export const RECONNECT_MS = 5000;

// EventSource.readyState values.
export const ES_CONNECTING = 0;
export const ES_OPEN = 1;
export const ES_CLOSED = 2;

/** PLAN.md §10 connection rules: readyState combined with how recently data arrived. */
export function deriveStatus(
  readyState: number,
  lastEventAt: number | null,
  now: number,
): ConnectionStatus {
  if (readyState === ES_CLOSED) return "disconnected";
  if (readyState === ES_OPEN && lastEventAt !== null && now - lastEventAt <= STALE_MS) {
    return "connected";
  }
  return "reconnecting";
}
