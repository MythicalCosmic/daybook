/**
 * The time as a ref that ticks every second, shared by every caller on the page: the waits on the
 * label pills, the big counters, an open alert's timer and the TV clock all move together on one
 * interval, turning over on the second. It stops when nobody is listening.
 */
import { getCurrentScope, onScopeDispose, readonly, ref, type Ref } from "vue";

const now = ref(Date.now());
let users = 0;
let align: ReturnType<typeof setTimeout> | undefined;
let tick: ReturnType<typeof setInterval> | undefined;

function begin(): void {
  align = setTimeout(() => {
    align = undefined;
    now.value = Date.now();
    tick = setInterval(() => (now.value = Date.now()), 1000);
  }, 1000 - (Date.now() % 1000));
}

function end(): void {
  clearTimeout(align);
  clearInterval(tick);
  align = tick = undefined;
}

export function useSecondClock(): Readonly<Ref<number>> {
  users += 1;
  now.value = Date.now();
  if (align === undefined && tick === undefined) begin();
  if (getCurrentScope()) {
    onScopeDispose(() => {
      users -= 1;
      if (users === 0) end();
    });
  }
  return readonly(now);
}
