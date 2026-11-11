/**
 * Whether a section shows its loading skeleton. True from the first moment of loading, so a page
 * never falls through to its empty state ("nothing here yet") while the answer is on its way; the
 * skeleton itself stays invisible for its first 150 ms (SkeletonBlock's CSS, plan §6.3), so a fast
 * answer never flashes a placeholder. A load that lasts past `delay` keeps the skeleton at least
 * `minVisible` ms on screen, so it never blinks.
 */
import { getCurrentScope, onScopeDispose, ref, watch, type Ref, type WatchSource } from "vue";

export interface DelayedPendingOptions {
  /** How long the skeleton stays invisible (keep in step with SkeletonBlock's CSS). */
  delay?: number;
  minVisible?: number;
}

export function useDelayedPending(pending: WatchSource<boolean>, options: DelayedPendingOptions = {}): Readonly<Ref<boolean>> {
  const delay = options.delay ?? 150;
  const minVisible = options.minVisible ?? 300;
  const visible = ref(false);
  let seenTimer: ReturnType<typeof setTimeout> | undefined;
  let hideTimer: ReturnType<typeof setTimeout> | undefined;
  // When the skeleton became visible (its delay ran out while still loading), else null.
  let seenAt: number | null = null;

  const clear = () => {
    clearTimeout(seenTimer);
    clearTimeout(hideTimer);
    seenTimer = hideTimer = undefined;
  };

  watch(
    pending,
    (isPending) => {
      if (isPending) {
        if (hideTimer !== undefined) {
          // Loading again while the last skeleton is still held: it simply stays.
          clearTimeout(hideTimer);
          hideTimer = undefined;
          return;
        }
        if (visible.value) return;
        visible.value = true;
        seenAt = null;
        seenTimer = setTimeout(() => {
          seenTimer = undefined;
          seenAt = Date.now();
        }, delay);
        return;
      }
      if (!visible.value || hideTimer !== undefined) return;
      clearTimeout(seenTimer);
      seenTimer = undefined;
      // Done before the skeleton became visible: nothing was seen, so nothing to hold.
      const remaining = seenAt === null ? 0 : minVisible - (Date.now() - seenAt);
      if (remaining <= 0) {
        visible.value = false;
        return;
      }
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
