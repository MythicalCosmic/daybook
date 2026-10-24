/**
 * Requests that wait a moment before they go out, so a toast can offer Undo for work the server
 * can't take back (Confirm, Confirm all), as the dashboard's reviews do. While one waits, closing
 * the app asks first; if the app is hidden or closed anyway, everything waiting goes out at once.
 * Offline, a send that's due waits for the connection rather than failing.
 */
import { useSyncExternalStore } from "react";

import { confirmClosing } from "../telegram";

/** How long Undo stays possible (and the toast with it). */
export const UNDO_MS = 5000;

type Waiting = { timer: number; left: number; started: number; send: () => void; release: () => void };

const waiting = new Set<Waiting>();

const offline = () => typeof navigator !== "undefined" && navigator.onLine === false;

function go(item: Waiting) {
  window.clearTimeout(item.timer);
  waiting.delete(item);
  item.release();
  if (!offline()) {
    item.send();
    return;
  }
  // No connection: send the moment it's back (the banner says so).
  const back = () => {
    window.removeEventListener("online", back);
    item.send();
  };
  window.addEventListener("online", back);
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

export type DelayedJob = {
  /** Take it back; false when it's too late (it already went out). */
  cancel: () => boolean;
  /** Hold the clock (a finger or the focus is on its toast), and let it run again. */
  pause: () => void;
  resume: () => void;
};

/** Run `send` after `delay` unless cancelled. */
export function sendLater(send: () => void, delay = UNDO_MS): DelayedJob {
  const item: Waiting = { timer: 0, left: delay, started: Date.now(), send, release: confirmClosing() };
  const arm = () => {
    item.started = Date.now();
    item.timer = window.setTimeout(() => go(item), item.left);
  };
  arm();
  waiting.add(item);
  return {
    cancel: () => {
      if (!waiting.has(item)) return false;
      window.clearTimeout(item.timer);
      waiting.delete(item);
      item.release();
      return true;
    },
    pause: () => {
      if (!waiting.has(item)) return;
      window.clearTimeout(item.timer);
      item.left = Math.max(0, item.left - (Date.now() - item.started));
    },
    resume: () => {
      if (!waiting.has(item)) return;
      window.clearTimeout(item.timer);
      // The toast lingers 2.5 s once let go: the send waits a little longer, so Undo never shows
      // for something that already went out.
      item.left = Math.max(item.left, 2600);
      arm();
    },
  };
}

// — work confirmed but not sent yet: kept out of "To check" whatever the list refetches —

const pending = new Set<number>();
let version = 0;
const listeners = new Set<() => void>();

export function setPending(ids: readonly number[], on: boolean): void {
  for (const id of ids) {
    if (on) pending.add(id);
    else pending.delete(id);
  }
  version += 1;
  listeners.forEach((listener) => listener());
}

export function isPending(id: number): boolean {
  return pending.has(id);
}

/** Re-renders when the pending set changes; returns a number that changes with it. */
export function usePendingVersion(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
    () => version,
  );
}
