/**
 * Skeletons appear only after 150 ms of loading (plan §6.3), so fast responses never flash a
 * placeholder; once shown, a skeleton stays at least `minVisible` ms so it never blinks.
 */
import { getCurrentScope, onScopeDispose, ref, watch, type Ref, type WatchSource } from "vue";

export interface DelayedPendingOptions {
  delay?: number;
  minVisible?: number;
}

export function useDelayedPending(pending: WatchSource<boolean>, options: DelayedPendingOptions = {}): Readonly<Ref<boolean>> {
  const delay = options.delay ?? 150;
  const minVisible = options.minVisible ?? 300;
  const visible = ref(false);
  let showTimer: ReturnType<typeof setTimeout> | undefined;
  let hideTimer: ReturnType<typeof setTimeout> | undefined;
  let shownAt = 0;

  const clear = () => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    showTimer = hideTimer = undefined;
  };

  watch(
    pending,
    (isPending) => {
      if (isPending) {
        clearTimeout(hideTimer);
        hideTimer = undefined;
        if (!visible.value && showTimer === undefined) {
          showTimer = setTimeout(() => {
            showTimer = undefined;
            visible.value = true;
            shownAt = Date.now();
          }, delay);
        }
        return;
      }
      clearTimeout(showTimer);
      showTimer = undefined;
      if (!visible.value) return;
      const remaining = minVisible - (Date.now() - shownAt);
      if (remaining <= 0) visible.value = false;
      else
        hideTimer = setTimeout(() => {
          hideTimer = undefined;
          visible.value = false;
        }, remaining);
    },
    { immediate: true },
  );

  if (getCurrentScope()) onScopeDispose(clear);
  return visible;
}
