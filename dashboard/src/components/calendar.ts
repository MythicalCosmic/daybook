/**
 * Calendar arithmetic for the date pickers and calendar views. Days are company-local "YYYY-MM-DD"
 * strings and months "YYYY-MM"; weeks start on Monday (Uzbekistan and Russia), like the backend.
 */
import type { Range } from "@/api/types";
import { addDays, addMonths, diffDays, startOfWeek } from "@/lib/dates";

export type Month = string;

export function monthOf(day: string): Month {
  return day.slice(0, 7);
}

export function shiftMonth(month: Month, amount: number): Month {
  return addMonths(`${month}-01`, amount).slice(0, 7);
}

/** Six weeks of days covering `month`, Monday first, so every month has the same height. */
export function monthGrid(month: Month): string[][] {
  const first = startOfWeek(`${month}-01`);
  const weeks: string[][] = [];
  for (let w = 0; w < 6; w++) {
    const week: string[] = [];
    for (let d = 0; d < 7; d++) week.push(addDays(first, w * 7 + d));
    weeks.push(week);
  }
  return weeks;
}

/** The weeks of a month that actually contain its days (4–6 rows), for month views that shouldn't pad. */
export function monthWeeks(month: Month): string[][] {
  return monthGrid(month).filter((week) => week.some((day) => monthOf(day) === month));
}

/** Monday-based weekday: 0 = Monday … 6 = Sunday (Python's `date.weekday()`). */
export function weekdayOf(day: string): number {
  const date = new Date(`${day}T00:00:00Z`);
  return (date.getUTCDay() + 6) % 7;
}

export function isWeekend(day: string): boolean {
  return weekdayOf(day) >= 5;
}

export function inRange(day: string, range: Range | null | undefined): boolean {
  return !!range && day >= range.from && day <= range.to;
}

/** A range from two clicks in any order. */
export function orderedRange(a: string, b: string): Range {
  return a <= b ? { from: a, to: b } : { from: b, to: a };
}

export function rangeLength(range: Range): number {
  return diffDays(range.from, range.to) + 1;
}

export function clampDay(day: string, min?: string | null, max?: string | null): string {
  if (min && day < min) return min;
  if (max && day > max) return max;
  return day;
}

/** Where keyboard focus goes from `day` for a calendar key, or null for other keys. */
export function keyTarget(day: string, key: string, shift = false): string | null {
  switch (key) {
    case "ArrowLeft":
      return addDays(day, -1);
    case "ArrowRight":
      return addDays(day, 1);
    case "ArrowUp":
      return addDays(day, -7);
    case "ArrowDown":
      return addDays(day, 7);
    case "PageUp":
      return addMonths(day, shift ? -12 : -1);
    case "PageDown":
      return addMonths(day, shift ? 12 : 1);
    case "Home":
      return startOfWeek(day);
    case "End":
      return addDays(startOfWeek(day), 6);
    default:
      return null;
  }
}

/**
 * The next state of a range being picked by clicks: the first click starts it, the second ends it
 * (in either order), a third starts again.
 */
export interface RangeDraft {
  anchor: string | null;
  range: Range | null;
}

export function pickRangeDay(draft: RangeDraft, day: string): RangeDraft {
  if (draft.anchor === null) return { anchor: day, range: { from: day, to: day } };
  return { anchor: null, range: orderedRange(draft.anchor, day) };
}

/** What the grid highlights while the pointer hovers during a pick. */
export function previewRange(draft: RangeDraft, hover: string | null): Range | null {
  if (draft.anchor !== null && hover) return orderedRange(draft.anchor, hover);
  return draft.range;
}
