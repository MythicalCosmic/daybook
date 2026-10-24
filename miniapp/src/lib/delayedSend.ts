/**
 * Requests that wait a moment before they go out, so a toast can offer Undo for work the server
 * can't take back (Confirm, Confirm all), as the dashboard's reviews do. While one waits, closing
 * the app asks first; if the app is hidden or closed anyway, everything waiting goes out at once.
 */
import { confirmClosing } from "../telegram";

/** How long Undo stays possible (and the toast with it). */
export const UNDO_MS = 5000;

type Waiting = { timer: number; send: () => void; release: () => void };

const waiting = new Set<Waiting>();

function go(item: Waiting) {
  window.clearTimeout(item.timer);
  waiting.delete(item);
  item.release();
  item.send();
}

/** Send everything still waiting now (the app is going away). */
export function flushDelayed(): void {
  for (const item of [...waiting]) go(item);
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", flushDelayed);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushDelayed();
  });
}

/**
 * Run `send` after `delay` unless cancelled. `cancel()` returns false when it's too late (it
 * already went out), so the caller can say so instead of pretending to undo.
 */
export function sendLater(send: () => void, delay = UNDO_MS): { cancel: () => boolean; now: () => void } {
  const item: Waiting = { timer: 0, send, release: confirmClosing() };
  item.timer = window.setTimeout(() => go(item), delay);
  waiting.add(item);
  return {
    cancel: () => {
      if (!waiting.has(item)) return false;
      window.clearTimeout(item.timer);
      waiting.delete(item);
      item.release();
      return true;
    },
    now: () => {
      if (waiting.has(item)) go(item);
    },
  };
}
