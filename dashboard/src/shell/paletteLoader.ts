/**
 * The command palette's code, loaded once: when it first opens, or earlier, the moment a hand
 * reaches for it (Ctrl/⌘ held down, the search box hovered), so the first ⌘K opens at once.
 * Keys typed after ⌘K are never lost: until the palette has mounted they are buffered into the
 * query it opens with, then the palette catches them itself until its field has focus.
 */
let pending: Promise<typeof import("./CommandPalette.vue")> | null = null;
let mounted = false;

export function loadPalette(): Promise<typeof import("./CommandPalette.vue")> {
  pending ??= import("./CommandPalette.vue").catch((error: unknown) => {
    pending = null;
    throw error;
  });
  return pending;
}

/** The palette says when it is mounted and catching its own keys. */
export function markPaletteMounted(value: boolean): void {
  mounted = value;
}

/** A key that types a character (not a shortcut, not a key held for an IME). */
export function isTextKey(event: KeyboardEvent): boolean {
  return !event.defaultPrevented && !event.isComposing && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
}

/** Starts loading the palette when Ctrl or ⌘ goes down; returns the remover. */
export function prefetchPaletteOnModifier(target: Window = window): () => void {
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== "Control" && event.key !== "Meta") return;
    target.removeEventListener("keydown", onKey);
    void loadPalette().catch(() => undefined);
  };
  target.addEventListener("keydown", onKey);
  return () => target.removeEventListener("keydown", onKey);
}

/**
 * While the palette is open but its code still loading (its first opening), text keys go to
 * `append` (the store's opening query) instead of firing page shortcuts. Returns the remover.
 */
export function bufferKeysUntilPaletteMounts(isOpen: () => boolean, append: (key: string) => void, target: Window = window): () => void {
  const onKey = (event: KeyboardEvent) => {
    if (mounted || !isOpen() || !isTextKey(event)) return;
    event.preventDefault();
    append(event.key);
  };
  target.addEventListener("keydown", onKey, true);
  return () => target.removeEventListener("keydown", onKey, true);
}
