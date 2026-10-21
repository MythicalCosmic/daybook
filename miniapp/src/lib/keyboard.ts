/**
 * The on-screen keyboard shrinks the page (Android) or covers its lower part (iOS), and the
 * browser doesn't always bring the field being typed into back in sight, least of all above the
 * page's own action bar. This keeps the focused field visible wherever it scrolls: in a screen,
 * a sheet or a form.
 */

const TYPED = new Set(["text", "search", "email", "tel", "url", "password", "number", "date", "time", "datetime-local", "month", "week"]);
/** Time for the keyboard's animation to resize the page before measuring. */
const SETTLE_MS = 260;
const MARGIN = 12;

function isField(node: Element | null): node is HTMLElement {
  if (node instanceof HTMLTextAreaElement || node instanceof HTMLSelectElement) return true;
  if (node instanceof HTMLInputElement) return TYPED.has(node.type);
  return node instanceof HTMLElement && node.isContentEditable;
}

/** The nearest ancestor that scrolls: the field is cut off at its edges. */
function scrollerOf(node: HTMLElement): HTMLElement | null {
  for (let parent = node.parentElement; parent; parent = parent.parentElement) {
    const { overflowY } = getComputedStyle(parent);
    if (overflowY === "auto" || overflowY === "scroll") return parent;
  }
  return null;
}

/**
 * The visible band for a field: the visual viewport, within the box it scrolls in, above any
 * action bar below it.
 */
function visibleBand(field: HTMLElement, box: DOMRect): { top: number; bottom: number } {
  const view = window.visualViewport;
  let top = view ? view.offsetTop : 0;
  let bottom = view ? view.offsetTop + view.height : window.innerHeight;
  const clip = scrollerOf(field)?.getBoundingClientRect();
  if (clip && clip.height > 0) {
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  for (const bar of document.querySelectorAll(".action-bar")) {
    const rect = bar.getBoundingClientRect();
    if (rect.height > 0 && rect.top > box.top) bottom = Math.min(bottom, rect.top);
  }
  return { top, bottom };
}

/** Bring the focused field into view when it's hidden. Exported for tests. */
export function revealFocusedField(): void {
  const field = document.activeElement;
  if (!isField(field)) return;
  const box = field.getBoundingClientRect();
  const band = visibleBand(field, box);
  if (box.top >= band.top + MARGIN && box.bottom <= band.bottom - MARGIN) return;
  field.scrollIntoView({ block: "center", behavior: "smooth" });
}

/** Watch focus and viewport changes for the life of the app. Returns the cleanup. */
export function keepFieldsInView(): () => void {
  let timer = 0;
  const later = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(revealFocusedField, SETTLE_MS);
  };
  document.addEventListener("focusin", later);
  window.addEventListener("resize", later);
  window.visualViewport?.addEventListener("resize", later);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener("focusin", later);
    window.removeEventListener("resize", later);
    window.visualViewport?.removeEventListener("resize", later);
  };
}
