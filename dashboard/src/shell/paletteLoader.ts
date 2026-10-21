/**
 * The command palette's code, loaded once: when it first opens, or earlier, the moment a hand
 * reaches for it (Ctrl/⌘ held down, the search box hovered), so the first ⌘K opens at once and
 * catches every key typed after it.
 */
let pending: Promise<typeof import("./CommandPalette.vue")> | null = null;

export function loadPalette(): Promise<typeof import("./CommandPalette.vue")> {
  pending ??= import("./CommandPalette.vue").catch((error: unknown) => {
    pending = null;
    throw error;
  });
  return pending;
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
