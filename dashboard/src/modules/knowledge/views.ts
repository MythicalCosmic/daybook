/**
 * "Who read what" from the dashboard's page view (docs/PLAN-LEARNING.md §4.1), like the mini
 * app's reader: a report on open, every 15 s while the page is in front of the person, and on
 * leaving, with the time since the last report and how far down they got. Reports never toast:
 * a lost one only loses a few seconds.
 */
import { onBeforeUnmount, onMounted, toValue, watch, type MaybeRefOrGetter } from "vue";

import { http, ownerPath } from "@/api/http";
import { useCompanyId } from "@/stores/company";

export const REPORT_EVERY_MS = 15_000;

/** How far down the window is, in percent (all of a page shorter than the window counts). */
export function scrolledPercent(scrollTop: number, viewport: number, height: number): number {
  if (height <= viewport) return 100;
  return Math.max(0, Math.min(100, Math.round(((scrollTop + viewport) / height) * 100)));
}

export function useViewReport(pageId: MaybeRefOrGetter<number | null>) {
  const cid = useCompanyId();
  const session = Math.random().toString(36).slice(2, 14);
  let last = Date.now();
  let deepest = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  const measure = () => {
    const doc = document.documentElement;
    deepest = Math.max(deepest, scrolledPercent(window.scrollY, window.innerHeight, doc.scrollHeight));
  };

  function send(): void {
    const id = toValue(pageId);
    if (!id || cid.value <= 0) return;
    measure();
    const now = Date.now();
    const seconds = Math.min(30, Math.max(0, (now - last) / 1000));
    last = now;
    void http.post(ownerPath(cid.value, `knowledge/pages/${id}/view/`), { session, seconds, scrolled: deepest }, { toast: false }).catch(() => undefined);
  }

  const onVisibility = () => {
    if (document.visibilityState === "hidden") send();
    else last = Date.now();
  };

  onMounted(() => {
    window.addEventListener("scroll", measure, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    timer = setInterval(() => {
      if (document.visibilityState === "visible") send();
    }, REPORT_EVERY_MS);
  });
  // A new page (or the first one once it loaded): a report on open.
  watch(
    () => toValue(pageId),
    (id, before) => {
      if (before) send();
      last = Date.now();
      deepest = 0;
      if (id) send();
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    send();
    if (timer) clearInterval(timer);
    window.removeEventListener("scroll", measure);
    document.removeEventListener("visibilitychange", onVisibility);
  });
}
