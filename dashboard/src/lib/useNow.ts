/**
 * The current time as a ref that ticks every 30 s, shared by every caller on the page (one interval
 * however many "5 min ago" labels are showing). It stops when nobody is listening.
 */
import { getCurrentScope, onScopeDispose, readonly, ref, type Ref } from "vue";

const now = ref(Date.now());
let users = 0;
let timer: ReturnType<typeof setInterval> | undefined;

export const NOW_TICK_MS = 30_000;

export function useNow(): Readonly<Ref<number>> {
  users += 1;
  // Every new listener starts from the time it is now, not the last tick (up to 30 s old).
  now.value = Date.now();
  if (timer === undefined) {
    timer = setInterval(() => (now.value = Date.now()), NOW_TICK_MS);
  }
  if (getCurrentScope()) {
    onScopeDispose(() => {
      users -= 1;
      if (users === 0 && timer !== undefined) {
        clearInterval(timer);
        timer = undefined;
      }
    });
  }
  return readonly(now);
}
