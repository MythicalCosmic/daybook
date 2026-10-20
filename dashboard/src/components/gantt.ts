/**
 * Date and pixel math behind GanttTimeline (Projects timeline and Roadmap), kept pure for tests.
 * Days are company-local "YYYY-MM-DD"; a bar's `end` is its last day (inclusive).
 */
import type { Range } from "@/api/types";
import { addDays, addMonths, diffDays, startOfMonth, startOfWeek } from "@/lib/dates";

export type GanttZoom = "day" | "week" | "month";

export const PX_PER_DAY: Record<GanttZoom, number> = { day: 40, week: 16, month: 5 };

export interface GanttBar {
  id: string | number;
  start: string;
  end: string;
  label?: string;
  /** 0–100, drawn as a darker part of the bar. */
  progress?: number | null;
  color?: string | null;
  /** Default true. */
  editable?: boolean;
}

export interface GanttMilestone {
  id: string | number;
  date: string;
  label: string;
  done?: boolean;
  color?: string | null;
  editable?: boolean;
}

export interface GanttRow {
  id: string | number;
  label: string;
  sublabel?: string;
  color?: string | null;
  avatar?: { name: string; src?: string | null } | null;
  bars: GanttBar[];
  milestones?: GanttMilestone[];
}

export type DragMode = "move" | "start" | "end";

/** Whole days for a pixel distance at a zoom (rounded to the nearest day). */
export function pxToDays(px: number, zoom: GanttZoom): number {
  const days = px / PX_PER_DAY[zoom];
  return days < 0 ? -Math.round(-days) : Math.round(days);
}

/** Left offset and width of a bar, in px, from the timeline's first day. */
export function barBox(bar: Pick<GanttBar, "start" | "end">, from: string, zoom: GanttZoom): { left: number; width: number } {
  const ppd = PX_PER_DAY[zoom];
  const end = bar.end < bar.start ? bar.start : bar.end;
  return { left: diffDays(from, bar.start) * ppd, width: (diffDays(bar.start, end) + 1) * ppd };
}

/** Center of a day, in px (milestone diamonds, the today line). */
export function dayCenter(day: string, from: string, zoom: GanttZoom): number {
  return (diffDays(from, day) + 0.5) * PX_PER_DAY[zoom];
}

/** New dates after dragging by `delta` days: move shifts both ends; resizing never makes a bar shorter than one day. */
export function dragDates(bar: Pick<GanttBar, "start" | "end">, mode: DragMode, delta: number): { start: string; end: string } {
  if (mode === "move") return { start: addDays(bar.start, delta), end: addDays(bar.end, delta) };
  if (mode === "start") {
    const start = addDays(bar.start, delta);
    return { start: start > bar.end ? bar.end : start, end: bar.end };
  }
  const end = addDays(bar.end, delta);
  return { start: bar.start, end: end < bar.start ? bar.start : end };
}

/** Which part of a bar a pointer at `offset` px from its left edge grabs: the edges resize. */
export function dragModeAt(offset: number, width: number, edge = 7): DragMode {
  if (width >= edge * 3) {
    if (offset <= edge) return "start";
    if (offset >= width - edge) return "end";
  }
  return "move";
}

/** The days the timeline shows: every bar and milestone, today, and some room, aligned to the zoom. */
export function timelineRange(rows: readonly GanttRow[], today: string, zoom: GanttZoom, minDays = 42): Range {
  let first = today;
  let last = today;
  for (const row of rows) {
    for (const bar of row.bars) {
      if (bar.start < first) first = bar.start;
      if (bar.end > last) last = bar.end;
    }
    for (const milestone of row.milestones ?? []) {
      if (milestone.date < first) first = milestone.date;
      if (milestone.date > last) last = milestone.date;
    }
  }
  const pad = zoom === "day" ? 3 : zoom === "week" ? 10 : 31;
  let from = addDays(first, -pad);
  let to = addDays(last, pad);
  if (zoom === "week" || zoom === "day") from = startOfWeek(from);
  if (zoom === "month") from = startOfMonth(from);
  if (diffDays(from, to) + 1 < minDays) to = addDays(from, minDays - 1);
  if (zoom === "month") to = addDays(addMonths(startOfMonth(to), 1), -1);
  return { from, to };
}

export interface Tick {
  /** First day of the tick. */
  day: string;
  left: number;
  width: number;
}

/** Header ticks: months over days/weeks for day and week zoom, years over months for month zoom. */
export function ticks(range: Range, zoom: GanttZoom): { top: Tick[]; bottom: Tick[] } {
  const ppd = PX_PER_DAY[zoom];
  const total = diffDays(range.from, range.to) + 1;
  const span = (start: string, next: string) => {
    const a = Math.max(0, diffDays(range.from, start));
    const b = Math.min(total, diffDays(range.from, next));
    return { left: a * ppd, width: Math.max(0, b - a) * ppd };
  };
  const months: Tick[] = [];
  for (let month = startOfMonth(range.from); month <= range.to; month = addMonths(month, 1)) {
    months.push({ day: month, ...span(month, addMonths(month, 1)) });
  }
  if (zoom === "month") {
    const years: Tick[] = [];
    for (let year = Number(range.from.slice(0, 4)); year <= Number(range.to.slice(0, 4)); year++) {
      const start = `${year}-01-01`;
      years.push({ day: start, ...span(start < range.from ? range.from : start, `${year + 1}-01-01`) });
    }
    return { top: years, bottom: months };
  }
  const bottom: Tick[] = [];
  if (zoom === "day") {
    for (let day = range.from; day <= range.to; day = addDays(day, 1)) bottom.push({ day, ...span(day, addDays(day, 1)) });
  } else {
    for (let week = startOfWeek(range.from); week <= range.to; week = addDays(week, 7)) bottom.push({ day: week, ...span(week, addDays(week, 7)) });
  }
  return { top: months, bottom };
}

/** ISO week number (weeks start Monday; week 1 holds the first Thursday). */
export function isoWeek(day: string): number {
  const date = new Date(`${day}T00:00:00Z`);
  const weekday = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - weekday + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((date.getTime() - firstThursday.getTime()) / 86_400_000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
}
