/**
 * How much of the bottom of the window the on-screen keyboard covers, while `active`, and the
 * height left above it. iOS (Telegram's webview included) keeps the layout viewport when the
 * keyboard opens, so whatever is fixed to the bottom (a sheet's lower fields and its Save) ends up
 * under the keyboard; `window.visualViewport` tells how much. 0 / null without a keyboard, or where
 * the browser shrinks the page itself (Android).
 */
import { onScopeDispose, readonly, ref, watch, type Ref } from "vue";

/** Less than this is browser chrome (a toolbar), not a keyboard. */
const KEYBOARD_MIN_PX = 80;

export function useKeyboardInset(active: Readonly<Ref<boolean>>) {
  const inset = ref(0);
  const height = ref<number | null>(null);
  const viewport = typeof window === "undefined" ? null : window.visualViewport;

  function measure(): void {
    if (!viewport) return;
    const covered = Math.round(window.innerHeight - viewport.height - viewport.offsetTop);
    const keyboard = covered >= KEYBOARD_MIN_PX;
    inset.value = keyboard ? covered : 0;
    height.value = keyboard ? Math.round(viewport.height) : null;
  }

  function stop(): void {
    viewport?.removeEventListener("resize", measure);
    viewport?.removeEventListener("scroll", measure);
    inset.value = 0;
    height.value = null;
  }

  watch(
    active,
    (on) => {
      if (!viewport) return;
      if (!on) return stop();
      viewport.addEventListener("resize", measure);
      viewport.addEventListener("scroll", measure);
      measure();
    },
    { immediate: true },
  );
  onScopeDispose(stop);

  return { inset: readonly(inset), height: readonly(height) };
}
