/**
 * Where the label pills go on a live picture, so they never overlap. A queue seen from behind the
 * customers is a column whose boxes overlap by half; put every pill straight above its box and the
 * waits pile up into "2:" and "2:25" over each other. Instead, in pixels of the picture on screen:
 *
 * - The longest wait is placed first, in its own place above its box, so it is always readable;
 *   then the other waits by length, then people without a wait, then pharmacists.
 * - A pill that would cover one already placed looks at every way out: stacking up above the one in
 *   its way, stepping aside to the right or the left, or sitting inside the top of its own box, and
 *   takes the one that moves it least; if none fits it tries again in its short form ("2:25"
 *   without "Mijoz ·"); a pill that still can't fit isn't drawn (never the longest wait).
 * - A pill moved away from its box gets a thin leader to it.
 * - Stable while boxes glide: a pill tries last frame's choice first, and one that was moved keeps
 *   a few pixels of extra room around it before it comes back, so it never flips between two
 *   places from one frame to the next.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type PillForm = "full" | "short";
export type PillStrategy = "natural" | "up" | "right" | "left" | "inside";

export interface PillInput {
  key: number;
  /** The person's box on screen, in pixels. */
  box: Rect;
  /** Pill sizes, in pixels: its full and its short form (the same when there is no short form). */
  width: number;
  shortWidth: number;
  height: number;
  /** Higher goes first: the longest wait is the highest. */
  priority: number;
}

export interface PillPlacement {
  key: number;
  x: number;
  y: number;
  w: number;
  h: number;
  form: PillForm;
  strategy: PillStrategy;
  /** From the pill to the top of its box, when the pill sits away from it. */
  leader: { x1: number; y1: number; x2: number; y2: number } | null;
}

export interface PillMemory {
  strategy: PillStrategy;
  form: PillForm;
}

export interface LayoutOptions {
  /** Space between a pill and its box, and between pills. */
  gap?: number;
  /** Space kept free along the picture's edges. */
  margin?: number;
  /** Extra room a moved pill keeps around it before coming back (hysteresis). */
  hold?: number;
  /** Fixed things pills keep clear of (the zones' name tags). */
  obstacles?: Rect[];
  /** How many pills a pill may climb over when stacking up. */
  climb?: number;
}

const ORDER: readonly PillStrategy[] = ["natural", "up", "right", "left", "inside"];
/** Pixels a pill would rather stay where it was than move to a slightly better place. */
const STICKY = 18;
/**
 * What each way out costs beyond the distance moved: inside the box covers the person's head, so
 * it is for when the others move the pill far; up reads a little better than aside.
 */
const COST: Record<PillStrategy, number> = { natural: 0, up: 0, right: 6, left: 6, inside: 28 };

export function overlaps(a: Rect, b: Rect, pad = 0): boolean {
  return a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/** The order pills are placed in: by priority, then by key (stable). */
export function placementOrder(items: readonly PillInput[]): PillInput[] {
  return [...items].sort((a, b) => b.priority - a.priority || a.key - b.key);
}

export function layoutPills(items: readonly PillInput[], frame: { w: number; h: number }, previous: ReadonlyMap<number, PillMemory> = new Map(), options: LayoutOptions = {}): PillPlacement[] {
  const gap = options.gap ?? 3;
  const margin = options.margin ?? 4;
  const hold = options.hold ?? 6;
  const climb = options.climb ?? 4;
  const placed: Rect[] = [...(options.obstacles ?? [])];
  const out: PillPlacement[] = [];

  placementOrder(items).forEach((item, index) => {
    const memory = previous.get(item.key);
    const first = index === 0;
    // A pill that sat away from its natural place last frame wants a little more room to come back.
    const pad = memory && memory.strategy !== "natural" ? hold : 0;
    const forms: PillForm[] = memory?.form === "short" && item.shortWidth < item.width ? ["short", "full"] : ["full", "short"];
    for (const form of forms) {
      if (form === "short" && item.shortWidth >= item.width && forms[0] === "full") continue;
      const w = form === "full" ? item.width : item.shortWidth;
      const h = item.height;
      const centre = item.box.x + item.box.w / 2;
      const nx = clamp(centre - w / 2, margin, frame.w - w - margin);
      const above = item.box.y - h - gap;
      // Too close to the top edge to fit above: the natural place is inside the box's top.
      const natural: Rect = { x: nx, y: above >= margin ? above : clamp(item.box.y + gap, margin, frame.h - h - margin), w, h };
      // Every way that fits; the one that moves the pill least wins, last frame's choice if it is
      // nearly as good (so two equal places don't swap from frame to frame).
      const fits = ORDER.map((strategy) => ({ strategy, rect: attempt(strategy, natural, item.box, { placed, frame, gap, margin, climb, pad }) }))
        .filter((option): option is { strategy: PillStrategy; rect: Rect } => option.rect !== null)
        .map((option) => ({ ...option, moved: Math.hypot(option.rect.x - natural.x, option.rect.y - natural.y) + COST[option.strategy] }));
      if (fits.length) {
        const best = fits.reduce((a, b) => (b.moved < a.moved ? b : a));
        const kept = memory && memory.form === form ? fits.find((option) => option.strategy === memory.strategy) : undefined;
        const chosen = kept && kept.moved <= best.moved + STICKY ? kept : best;
        placed.push(chosen.rect);
        out.push({ key: item.key, ...chosen.rect, form, strategy: chosen.strategy, leader: leaderFor(chosen.rect, item.box, natural, chosen.strategy) });
        return;
      }
    }
    // Nothing fits: the longest wait still shows where it belongs; any other pill is left out.
    if (first) {
      const w = item.width;
      const rect = { x: clamp(item.box.x + item.box.w / 2 - w / 2, margin, frame.w - w - margin), y: clamp(item.box.y - item.height - gap, margin, frame.h - item.height - margin), w, h: item.height };
      placed.push(rect);
      out.push({ key: item.key, ...rect, form: "full", strategy: "natural", leader: null });
    }
  });
  return out;
}

interface Context {
  placed: Rect[];
  frame: { w: number; h: number };
  gap: number;
  margin: number;
  climb: number;
  /** Extra room on a strategy's first check (a pill that moved last frame): near counts as in the way. */
  pad: number;
}

function hit(rect: Rect, ctx: Context, pad = 0): Rect | null {
  for (const other of ctx.placed) if (overlaps(rect, other, pad)) return other;
  return null;
}

function inside(rect: Rect, ctx: Context): boolean {
  return rect.x >= ctx.margin - 0.01 && rect.y >= ctx.margin - 0.01 && rect.x + rect.w <= ctx.frame.w - ctx.margin + 0.01 && rect.y + rect.h <= ctx.frame.h - ctx.margin + 0.01;
}

function attempt(strategy: PillStrategy, natural: Rect, box: Rect, ctx: Context): Rect | null {
  if (strategy === "natural") return hit(natural, ctx, ctx.pad) ? null : natural;
  if (strategy === "inside") {
    const rect = { ...natural, y: box.y + ctx.gap };
    return inside(rect, ctx) && rect.y + rect.h <= box.y + box.h && !hit(rect, ctx) ? rect : null;
  }
  let rect = { ...natural };
  for (let step = 0; step <= ctx.climb; step++) {
    // The first check uses the extra room, so a pill that moved stays moved while its neighbour is near.
    const other = hit(rect, ctx, step === 0 ? ctx.pad : 0);
    if (!other) return step === 0 ? null : inside(rect, ctx) ? rect : null;
    if (strategy === "up") rect = { ...rect, y: other.y - rect.h - ctx.gap };
    else if (strategy === "right") rect = { ...rect, x: other.x + other.w + ctx.gap };
    else rect = { ...rect, x: other.x - rect.w - ctx.gap };
    if (!inside(rect, ctx)) return null;
  }
  return null;
}

/** A leader from the pill's nearest edge to the top centre of its box, when the pill moved away. */
function leaderFor(rect: Rect, box: Rect, natural: Rect, strategy: PillStrategy): PillPlacement["leader"] {
  if (strategy === "natural" || strategy === "inside") return null;
  const tx = box.x + box.w / 2;
  const ty = box.y;
  const moved = Math.abs(rect.x - natural.x) > 2 || Math.abs(rect.y - natural.y) > 2;
  if (!moved) return null;
  const x1 = clamp(tx, rect.x + 4, rect.x + rect.w - 4);
  const y1 = ty < rect.y ? rect.y : rect.y + rect.h;
  if (Math.hypot(tx - x1, ty - y1) < 4) return null;
  return { x1, y1, x2: tx, y2: ty };
}

/** What the next frame remembers of this layout. */
export function memoryOf(placements: readonly PillPlacement[]): Map<number, PillMemory> {
  return new Map(placements.map((p) => [p.key, { strategy: p.strategy, form: p.form }]));
}

/** A pill's width for its text, without a canvas (tests, first paint): a little generous. */
export function estimateWidth(text: string, fontSize: number, chrome: number): number {
  return Math.ceil(text.length * fontSize * 0.56 + chrome);
}
