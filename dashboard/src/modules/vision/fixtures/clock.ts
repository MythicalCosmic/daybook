/**
 * Fixture mode only: where in the seven-minute cycle the pharmacy is. `?koz_at=<seconds>` on the
 * first page load starts the cycle there (`koz_at=180` the queue alert, `koz_at=392` the empty
 * counter) so a screenshot or a demo can go straight to a moment; time runs on from it.
 */
import { CYCLE } from "./sim";

const loadedAt = Date.now() / 1000;
const start = (() => {
  try {
    const raw = new URLSearchParams(window.location.search).get("koz_at");
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? ((value % CYCLE) + CYCLE) % CYCLE : null;
  } catch {
    return null;
  }
})();

/** Seconds of the simulated clock (the real one unless `koz_at` moved it). */
export function simSeconds(): number {
  const now = Date.now() / 1000;
  if (start === null) return now;
  return loadedAt - (loadedAt % CYCLE) + start + (now - loadedAt);
}

/** The position in the cycle and which cycle it is, for a scene shifted by `offset` seconds. */
export function cyclePosition(offset = 0): { t: number; cycle: number } {
  const shifted = simSeconds() + offset;
  return { t: ((shifted % CYCLE) + CYCLE) % CYCLE, cycle: Math.floor(shifted / CYCLE) };
}

export function isoAgo(seconds: number): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

export function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });
}
