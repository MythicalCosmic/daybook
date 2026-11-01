/**
 * "Back" closes the overlay on top before it leaves the page. Inside Telegram the BackButton (and
 * Android's back gesture, which Telegram hands to it) shows while a sheet, dialog, palette or
 * lightbox is open and closes it; without this, Back on the first screen closed the whole console
 * with a sheet open. Overlays register here while they are open; TelegramBridge asks here first.
 */
import { computed, onScopeDispose, shallowRef, watch, type WatchSource } from "vue";

const closers = shallowRef<ReadonlyArray<() => void>>([]);

/** Whether an overlay that Back can close is open. */
export const overlayOpen = computed(() => closers.value.length > 0);

/** Closes the overlay opened last; false when none is open. */
export function closeTopOverlay(): boolean {
  const top = closers.value.at(-1);
  if (!top) return false;
  top();
  return true;
}

/** While `open` is true, Back calls `close`. Call from a component's setup (released on unmount). */
export function useBackCloses(open: WatchSource<boolean>, close: () => void): void {
  let entry: (() => void) | null = null;
  const release = () => {
    if (!entry) return;
    const leaving = entry;
    entry = null;
    closers.value = closers.value.filter((closer) => closer !== leaving);
  };
  watch(
    open,
    (isOpen) => {
      if (!isOpen) return release();
      if (entry) return;
      entry = () => close();
      closers.value = [...closers.value, entry];
    },
    { immediate: true },
  );
  onScopeDispose(release);
}
