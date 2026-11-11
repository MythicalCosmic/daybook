/**
 * What Claude's helpers keep clear of on the page (BuddyCompanion.vue, AiBuddyStage.vue): anything
 * one presses or types into, the bars docked to the bottom of the window (a save bar, a selection
 * bar, a chat's composer) and open dialogs, sheets and drawers. This only reads the page; the
 * arithmetic is in `lib.ts` (`figureBox`, `overlaps`, `spotsFrom`, `floorAt`).
 */
import { overlaps, type Box } from "../lib";

/** Things people press or type into. */
export const PRESSABLE = [
  "a[href]",
  "button",
  'input:not([type="hidden"])',
  "select",
  "textarea",
  "summary",
  "label[for]",
  '[role="button"]',
  '[role="link"]',
  '[role="tab"]',
  '[role="checkbox"]',
  '[role="switch"]',
  '[role="radio"]',
  '[role="menuitem"]',
  '[role="option"]',
  '[role="slider"]',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

const OVERLAY = '[role="dialog"], [role="alertdialog"], [aria-modal="true"]';
const DOCKED = new Set(["fixed", "sticky"]);

function boxOf(element: Element): Box {
  const rect = element.getBoundingClientRect();
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

/** What a helper leaves out of its looking: its own layer (and its own self at home). */
export type Ignore = Element | null | readonly (Element | null)[];

function ignored(ignore: Ignore, element: Element): boolean {
  const list = Array.isArray(ignore) ? ignore : [ignore];
  return list.some((item) => !!item && item.contains(element));
}

function shows(box: Box): boolean {
  return box.width > 0 && box.height > 0;
}

/** A dialog, sheet or drawer is open: the helper steps out of the way until it closes. */
export function overlayOpen(root: ParentNode = document): boolean {
  return Array.from(root.querySelectorAll(OVERLAY)).some((element) => shows(boxOf(element)));
}

/** What is drawn at a point under the helper (it is left out), when the browser can tell. */
function topAt(x: number, y: number, ignore: Ignore): Element | null {
  if (typeof document.elementsFromPoint !== "function") return null;
  return document.elementsFromPoint(x, y).find((element) => !ignored(ignore, element)) ?? null;
}

/** The docked bar `element` belongs to: its nearest fixed or sticky ancestor inside the page's
 * frame, as the part of it one sees (the outermost box with a background, a border or a shadow,
 * so a sticky wrapper around a centred bar doesn't count beside the bar). None for a tall sticky
 * column, or a wrapper with nothing drawn where the point is. */
export function dockedPart(element: Element): Box | null {
  const chain: Element[] = [];
  for (let node: Element | null = element; node && node !== document.body && node.tagName !== "MAIN"; node = node.parentElement) {
    chain.push(node);
    if (!DOCKED.has(getComputedStyle(node).position)) continue;
    if (boxOf(node).height > window.innerHeight * 0.45) return null;
    const seen = [...chain].reverse().find((part) => {
      const style = getComputedStyle(part);
      const filled = !!style.backgroundColor && !/^(transparent|rgba\(0, 0, 0, 0\))$/.test(style.backgroundColor);
      return filled || parseFloat(style.borderTopWidth) > 0 || (!!style.boxShadow && style.boxShadow !== "none");
    });
    return seen ? boxOf(seen) : null;
  }
  return null;
}

/** The bars docked above the floor line `feet` between `left` and `right`: their seen part, at
 * the bottom of the window (the phone's tab bar is the floor itself, so it isn't one). */
export function dockedBars(feet: number, left: number, right: number, ignore: Ignore): Box[] {
  const found: Box[] = [];
  for (let x = left + 4; x <= right - 4; x += 36) {
    for (const lift of [8, 24, 44]) {
      const hit = topAt(x, feet - lift, ignore);
      const bar = hit ? dockedPart(hit) : null;
      if (!bar || bar.top >= feet || bar.top + bar.height < feet - 64) continue;
      if (!found.some((known) => known.left === bar.left && known.top === bar.top && known.width === bar.width)) found.push(bar);
    }
  }
  return found;
}

/** Where the things one presses are on screen right now (read once for a search of spots). */
export function pressableBoxes(ignore: Ignore): Box[] {
  const found: Box[] = [];
  for (const element of document.querySelectorAll(PRESSABLE)) {
    if (ignored(ignore, element)) continue;
    const box = boxOf(element);
    if (shows(box) && box.top < window.innerHeight && box.top + box.height > 0 && box.left < window.innerWidth && box.left + box.width > 0) found.push(box);
  }
  // The page's own scrollbar (a desktop's content scrolls inside `main`): one drags it.
  const main = document.querySelector("main");
  const bar = main ? main.offsetWidth - main.clientWidth : 0;
  if (main && bar > 0) {
    const box = boxOf(main);
    found.push({ left: box.left + box.width - bar, top: box.top, width: bar, height: box.height });
  }
  return found;
}

/** Whether the helper's drawing at `figure` (lib.figureBox) covers nothing one presses, no docked
 * bar and no open dialog: what is under it may only be text, pictures or empty space. */
export function spotClear(figure: Box, ignore: Ignore, pressable: readonly Box[] = pressableBoxes(ignore)): boolean {
  if (figure.top < 0 || figure.left < 0 || figure.left + figure.width > window.innerWidth || figure.top + figure.height > window.innerHeight) return false;
  if (pressable.some((box) => overlaps(figure, box))) return false;
  for (const across of [0.2, 0.5, 0.8]) {
    for (const down of [0.25, 0.5, 0.8]) {
      const hit = topAt(figure.left + figure.width * across, figure.top + figure.height * down, ignore);
      if (!hit) continue;
      if (hit.closest(OVERLAY)) return false;
      const bar = dockedPart(hit);
      if (bar && overlaps(figure, bar)) return false;
    }
  }
  return true;
}
