/**
 * Where UiTooltip goes and when it opens: plain arithmetic, no positioning library (README
 * "Budgets": the shell is full of tooltips and everything it imports is in the first load).
 */
export type TooltipSide = "top" | "right" | "bottom" | "left";

export interface TooltipPlacement {
  /** Top-left corner, in viewport pixels (the tooltip is `position: fixed`). */
  x: number;
  y: number;
  /** The side it ended up on: the asked one, or the opposite when there was no room. */
  side: TooltipSide;
  /** The arrow's style: on the edge facing the trigger, centred on it when it can be. */
  arrow: Record<string, string>;
}

interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Room kept between the tooltip and the window's edges. */
const EDGE = 8;
const ARROW = 10;
const OPPOSITE: Record<TooltipSide, TooltipSide> = { top: "bottom", bottom: "top", left: "right", right: "left" };

export function placeTooltip(
  trigger: Rect,
  size: { width: number; height: number },
  options: { side: TooltipSide; align: "start" | "center" | "end"; offset: number; viewport: { width: number; height: number } },
): TooltipPlacement {
  const { offset, viewport, align } = options;
  const vertical = (side: TooltipSide) => side === "top" || side === "bottom";
  const fits = (side: TooltipSide) => {
    switch (side) {
      case "top":
        return trigger.top - offset - size.height >= EDGE;
      case "bottom":
        return trigger.top + trigger.height + offset + size.height <= viewport.height - EDGE;
      case "left":
        return trigger.left - offset - size.width >= EDGE;
      case "right":
        return trigger.left + trigger.width + offset + size.width <= viewport.width - EDGE;
    }
  };
  const side = fits(options.side) || !fits(OPPOSITE[options.side]) ? options.side : OPPOSITE[options.side];

  const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max));
  let x: number;
  let y: number;
  if (vertical(side)) {
    y = side === "top" ? trigger.top - offset - size.height : trigger.top + trigger.height + offset;
    const start = align === "start" ? trigger.left : align === "end" ? trigger.left + trigger.width - size.width : trigger.left + (trigger.width - size.width) / 2;
    x = clamp(start, EDGE, viewport.width - EDGE - size.width);
  } else {
    x = side === "left" ? trigger.left - offset - size.width : trigger.left + trigger.width + offset;
    const start = align === "start" ? trigger.top : align === "end" ? trigger.top + trigger.height - size.height : trigger.top + (trigger.height - size.height) / 2;
    y = clamp(start, EDGE, viewport.height - EDGE - size.height);
  }

  // The arrow points at the trigger's middle, kept on the tooltip's own edge.
  const arrow: Record<string, string> = {};
  if (vertical(side)) {
    const along = clamp(trigger.left + trigger.width / 2 - x - ARROW / 2, 6, size.width - ARROW - 6);
    arrow.left = `${Math.round(along)}px`;
    if (side === "top") arrow.top = "100%";
    else Object.assign(arrow, { bottom: "100%", transform: "rotate(180deg)" });
  } else {
    const along = clamp(trigger.top + trigger.height / 2 - y - ARROW / 2, 6, size.height - ARROW - 6);
    arrow.top = `${Math.round(along + 2.5)}px`;
    if (side === "left") Object.assign(arrow, { left: "calc(100% - 2.5px)", transform: "rotate(-90deg)" });
    else Object.assign(arrow, { right: "calc(100% - 2.5px)", transform: "rotate(90deg)" });
  }
  return { x: Math.round(x), y: Math.round(y), side, arrow };
}

/**
 * The pause before a tooltip opens (450 ms), skipped when another one closed within the last
 * 250 ms: moving along a row of icon buttons reads each label at once.
 */
export const tooltipTiming = {
  delay: 450,
  skip: 250,
  lastClosed: Number.NEGATIVE_INFINITY,
  showing: 0,
  waitFor(delay?: number): number {
    if (this.showing > 0 || performance.now() - this.lastClosed < this.skip) return 0;
    return delay ?? this.delay;
  },
  opened(): void {
    this.showing += 1;
  },
  closed(): void {
    this.showing = Math.max(0, this.showing - 1);
    this.lastClosed = performance.now();
  },
};
