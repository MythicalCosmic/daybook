/**
 * "Who read what" (docs/PLAN-LEARNING.md §4.1): while a page is in front of the person, the reader
 * reports `{session, seconds, scrolled}` to `knowledge/pages/{id}/view/`: when it opens, every 15 s
 * while it stays in view, and when they leave it (or the app goes to the background). `seconds`
 * is the time in view since the last report that got through (at most 30, as the server takes
 * it), `scrolled` the furthest they got down the page, in percent. Requests go with `keepalive`,
 * so the last one leaves even as the app closes; a server without the endpoint is left alone.
 */
import { useEffect, useRef, type RefObject } from "react";

import { api } from "../../api/client";

export const VIEW_EVERY_MS = 15_000;
/** The most reading time one report carries (the server takes no more). */
const MAX_SECONDS = 30;

/** How far down the scrolling screen the bottom of the view is, in percent (100 when it all fits). */
export function scrolledPercent(scroller: Element | null): number {
  if (!scroller) return 0;
  const { scrollTop, clientHeight, scrollHeight } = scroller as HTMLElement;
  if (!scrollHeight || scrollHeight <= clientHeight) return 100;
  return Math.max(0, Math.min(100, Math.round(((scrollTop + clientHeight) / scrollHeight) * 100)));
}

function newSession(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Report a page's views while `ready` (it has loaded) and `active` (it is the page in front).
 * `inside` is an element in the page; the screen that scrolls it is found from there.
 */
export function usePageViews(company: number, page: number, { ready, active, inside }: { ready: boolean; active: boolean; inside: RefObject<Element | null> }): void {
  const state = useRef({
    session: newSession(),
    opened: false,
    off: false,
    busy: false,
    unsentMs: 0,
    since: null as number | null,
    scrolled: 0,
    sentScrolled: -1,
  });
  const live = useRef({ active, ready });
  live.current = { active, ready };

  useEffect(() => {
    if (!ready || !(page > 0)) return;
    const s = state.current;
    const scroller = () => inside.current?.closest(".screen") ?? null;
    const visible = () => live.current.active && document.visibilityState === "visible";
    const settle = () => {
      if (s.since !== null) s.unsentMs += Date.now() - s.since;
      s.since = visible() ? Date.now() : null;
    };
    const measure = () => {
      s.scrolled = Math.max(s.scrolled, scrolledPercent(scroller()));
    };
    const report = (leaving = false) => {
      if (s.off || (s.busy && !leaving)) return;
      settle();
      measure();
      const seconds = Math.min(MAX_SECONDS, Math.round(s.unsentMs / 1000));
      // The opening always goes; after it, only news (more time, further down).
      if (s.opened && !seconds && s.scrolled <= s.sentScrolled) return;
      s.opened = true;
      s.sentScrolled = s.scrolled;
      s.busy = true;
      const body = { session: s.session, seconds, scrolled: s.scrolled };
      api<void>(`/companies/${company}/knowledge/pages/${page}/view/`, { method: "POST", json: body, keepalive: true }).then(
        () => {
          s.busy = false;
          s.unsentMs = Math.max(0, s.unsentMs - seconds * 1000);
        },
        (error: unknown) => {
          s.busy = false;
          // No such endpoint (an older server) or the page is gone: stop asking.
          const status = (error as { status?: unknown } | null)?.status;
          if (status === 404 || status === 405 || status === 403) s.off = true;
        },
      );
    };

    s.since = visible() ? Date.now() : null;
    measure();
    report();
    const tick = setInterval(() => {
      if (visible()) report();
    }, VIEW_EVERY_MS);
    const target = scroller();
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") report(true);
      else settle();
    };
    target?.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onVisibility);
    return () => {
      clearInterval(tick);
      if (frame) cancelAnimationFrame(frame);
      target?.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onVisibility);
      live.current = { ...live.current, active: false };
      report(true);
    };
  }, [company, page, ready, inside]);

  // Covered by another page or uncovered again: the clock in view stops or starts.
  useEffect(() => {
    const s = state.current;
    if (!s.opened) return;
    if (s.since !== null) s.unsentMs += Date.now() - s.since;
    s.since = active && document.visibilityState === "visible" ? Date.now() : null;
  }, [active]);
}
