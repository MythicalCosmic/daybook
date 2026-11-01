import { useCallback, useMemo, useSyncExternalStore } from "react";

import { baseCurrency } from "../api/membership";
import { useI18n } from "../i18n";
import { useMember } from "../state/session";
import type { ViewContext } from "./taskView";

/**
 * One clock per pace for the whole app: every screen showing "late by 5 min" or "25 min left"
 * reads the same moment and re-renders on the same tick, instead of each keeping its own timer.
 */
type Clock = { now: Date; timer: number; listeners: Set<() => void> };

const clocks = new Map<number, Clock>();

function tick(clock: Clock): void {
  clock.now = new Date();
  clock.listeners.forEach((listener) => listener());
}

function clockFor(intervalMs: number): Clock {
  let clock = clocks.get(intervalMs);
  if (!clock) {
    clock = { now: new Date(), timer: 0, listeners: new Set() };
    clocks.set(intervalMs, clock);
  }
  return clock;
}

/**
 * The clock's moment. While nobody listens it's read afresh (to the second, so one render reads
 * one value): a screen opening later never starts from an old screen's time.
 */
function read(intervalMs: number): Date {
  const clock = clockFor(intervalMs);
  if (clock.listeners.size === 0 && Math.abs(Date.now() - +clock.now) >= 1000) clock.now = new Date();
  return clock.now;
}

function subscribe(intervalMs: number, listener: () => void): () => void {
  const clock = clockFor(intervalMs);
  clock.listeners.add(listener);
  if (clock.listeners.size === 1) {
    // The first screen in a while starts from this very moment (React reads it again once subscribed).
    clock.now = new Date();
    clock.timer = window.setInterval(() => tick(clock), intervalMs);
  }
  return () => {
    clock.listeners.delete(listener);
    if (clock.listeners.size === 0) window.clearInterval(clock.timer);
  };
}

// Back from the chat or a locked phone (timers sleep meanwhile): every clock reads the time at once.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") clocks.forEach((clock) => clock.listeners.size && tick(clock));
  });
}

/** The current time, refreshed every `intervalMs` (half a minute: "late by" labels keep up). */
export function useNow(intervalMs = 30_000): Date {
  const listen = useCallback((listener: () => void) => subscribe(intervalMs, listener), [intervalMs]);
  const snapshot = useCallback(() => read(intervalMs), [intervalMs]);
  return useSyncExternalStore(listen, snapshot, snapshot);
}

export function useViewContext(): ViewContext {
  const { t, locale } = useI18n();
  const member = useMember();
  const now = useNow();
  const timeZone = member.timeZone;
  const currency = baseCurrency(member);
  // The same object until the clock ticks or the language changes, so children can skip renders.
  return useMemo(() => ({ t, locale, timeZone, now, currency }), [t, locale, timeZone, now, currency]);
}
