/**
 * A number that glides to its new value in 400 ms (plan §6.3: "KPI numbers tween 400 ms only when
 * the value changes"). The first value shows at once; reduced motion jumps straight to the end.
 * For display only: the caller still formats the exact final value itself.
 */
import { getCurrentScope, onScopeDispose, ref, watch, type Ref, type WatchSource } from "vue";

export function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3;
}

export function useTween(source: WatchSource<number | null>, duration = 400): { value: Ref<number | null>; running: Ref<boolean> } {
  const value = ref<number | null>(null);
  const running = ref(false);
  let frame = 0;

  const reduced = () => typeof document !== "undefined" && document.documentElement.dataset.motion === "reduced";

  watch(
    source,
    (next, previous) => {
      cancelAnimationFrame(frame);
      if (next === null || previous === null || previous === undefined || value.value === null || reduced() || typeof requestAnimationFrame !== "function") {
        value.value = next;
        running.value = false;
        return;
      }
      const from = value.value;
      const start = performance.now();
      running.value = true;
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        value.value = from + (next - from) * easeOutCubic(t);
        if (t < 1) frame = requestAnimationFrame(step);
        else {
          value.value = next;
          running.value = false;
        }
      };
      frame = requestAnimationFrame(step);
    },
    { immediate: true },
  );

  if (getCurrentScope()) onScopeDispose(() => cancelAnimationFrame(frame));
  return { value, running };
}
