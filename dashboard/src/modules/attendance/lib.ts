/**
 * Small pure helpers shared by the attendance pages: tones for states and cells, colour slots,
 * distances, hour arithmetic on "HH:MM" strings and naive local date-times for the API.
 */
import { currentLanguage } from "@/i18n";
import { formatNumber } from "@/lib/format";
import { addDays } from "@/lib/dates";
import { toMinutes } from "@/lib/time";

import type { BoardState, CellCode } from "./types";

export const BOARD_STATES: readonly BoardState[] = ["in", "late", "not_yet", "absent", "off"];

/** Token colour of a board state (dots, column accents). */
export const STATE_COLORS: Record<BoardState, string> = {
  in: "var(--c-success)",
  late: "var(--c-warning)",
  not_yet: "var(--c-info)",
  absent: "var(--c-danger)",
  off: "var(--c-subtle)",
};

/** Timesheet cell look per code (labels are i18n keys `attendance.cell.<code>.short`). */
export const CELL_CLASSES: Record<CellCode, string> = {
  present: "bg-success-soft text-success",
  unscheduled: "bg-success-soft text-success ring-1 ring-inset ring-[color-mix(in_srgb,var(--c-success)_45%,transparent)]",
  late: "bg-warning-soft text-warning",
  absent: "bg-danger-soft text-danger",
  leave: "bg-info-soft text-info",
  holiday: "bg-surface-2 text-muted",
  excused: "bg-surface-2 text-muted",
  open: "bg-accent-soft text-accent-fg",
  auto: "bg-warning-soft text-warning ring-1 ring-inset ring-[color-mix(in_srgb,var(--c-warning)_55%,transparent)]",
  planned: "text-subtle ring-1 ring-inset ring-line-strong [background:repeating-linear-gradient(135deg,transparent_0_5px,var(--c-surface-2)_5px_6px)]",
  off: "text-subtle",
};

/** Codes that carry hours in the cell. */
export const CELL_WITH_HOURS: ReadonlySet<CellCode> = new Set(["present", "late", "auto", "unscheduled"]);

/** A schedule or template colour slot (1–8) as the chart token behind it. */
export function slotColor(slot: number | null | undefined): string {
  const index = slot && slot >= 1 && slot <= 8 ? slot : 1;
  return `var(--c-chart-${index})`;
}

/** "34 m", "1.2 km" ("1,2 km" in uz/ru). */
export function formatDistance(meters: number | null | undefined, units: { m: string; km: string }): string {
  if (meters === null || meters === undefined) return "—";
  if (meters >= 1000) return `${formatNumber(meters / 1000, currentLanguage(), 1)} ${units.km}`;
  return `${meters} ${units.m}`;
}

/** Minutes as hours with at most one decimal ("7.5", "7,5" in uz/ru), without units. */
export function hours(minutes: number): string {
  return formatNumber(Math.round((minutes / 60) * 10) / 10, currentLanguage(), 1);
}

/**
 * Where a grid of equal day columns behind pinned names should scroll to show `target`: rounded up
 * to a whole day, so the first day next to the names isn't cut in half (and the day `target` was
 * worked out for stays in view). `start` is the scroll at which the first day sits right after the
 * names; at the end of the month, where `max` stops the scroll, the furthest whole day instead.
 */
export function wholeDayScroll({ target, start, width, max }: { target: number; start: number; width: number; max: number }): number {
  if (!width) return Math.max(0, Math.min(target, max));
  let left = start + Math.ceil((target - start) / width) * width;
  if (left > max) left = start + Math.floor((max - start) / width) * width;
  return Math.max(0, left);
}

/** "08:30" → "8:30", "18:00" → "18:00": a wall-clock time as short as it can be without losing minutes. */
export function compactTime(time: string): string {
  const [h = "0", m = "00"] = time.split(":");
  return `${Number(h)}:${m.slice(0, 2).padStart(2, "0")}`;
}

/**
 * Planned minutes of a shift from "HH:MM" times (an end before the start is the next day); 0 while a
 * time is cleared (TimePicker sets null, and the dialog's render threw on it).
 */
export function spanMinutes(start: string | null, end: string | null, breakMinutes = 0): number {
  if (!start || !end) return 0;
  let span = toMinutes(end) - toMinutes(start);
  if (span <= 0) span += 24 * 60;
  return Math.max(0, span - breakMinutes);
}

/** "HH:MM" of an ISO instant that already carries the company's offset ("2026-10-21T08:57:00+05:00"). */
export function clockOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const match = /T(\d{2}:\d{2})/.exec(iso);
  return match ? match[1]! : "";
}

/** The local day of such an ISO instant. */
export function dayOf(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}

/**
 * A naive local date-time for the API ("2026-10-21T18:30"): the server reads it in the company's
 * timezone. An end time earlier than `after` (same day) rolls to the next day (overnight).
 */
export function localDateTime(day: string, time: string, after?: string | null): string {
  if (after && toMinutes(time) < toMinutes(after)) return `${addDays(day, 1)}T${time}`;
  return `${day}T${time}`;
}

/** "2026-10" → the first day "2026-10-01". */
export function monthStart(month: string): string {
  return `${month.slice(0, 7)}-01`;
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const date = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** 0 = Monday … 6 = Sunday, as the backend numbers weekdays. */
export function weekdayIndex(day: string): number {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
}

export function isWeekend(day: string): boolean {
  return weekdayIndex(day) === 6;
}

