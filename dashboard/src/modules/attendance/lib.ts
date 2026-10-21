/**
 * Small pure helpers shared by the attendance pages: tones for states and cells, colour slots,
 * distances, hour arithmetic on "HH:MM" strings and naive local date-times for the API.
 */
import type { StatusTone } from "@/components/StatusPill.vue";
import { currentLanguage } from "@/i18n";
import { addDays } from "@/lib/dates";

import type { BoardState, CellCode, RecordFlag, ShiftStatus, SwapKind } from "./types";

export const BOARD_STATES: readonly BoardState[] = ["in", "late", "not_yet", "absent", "off"];

export const STATE_TONES: Record<BoardState, StatusTone> = {
  in: "success",
  late: "warning",
  not_yet: "info",
  absent: "danger",
  off: "neutral",
};

/** Token colour of a board state (dots, column accents). */
export const STATE_COLORS: Record<BoardState, string> = {
  in: "var(--c-success)",
  late: "var(--c-warning)",
  not_yet: "var(--c-info)",
  absent: "var(--c-danger)",
  off: "var(--c-subtle)",
};

export interface CellStyle {
  /** Background and text classes from the design tokens. */
  classes: string;
  /** Short label inside the cell when it has no hours ("A", "L"…), from i18n. */
  short?: string;
}

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

export const SHIFT_STATUS_TONES: Record<ShiftStatus, StatusTone> = {
  planned: "primary",
  open: "warning",
  leave: "info",
  cancelled: "neutral",
};

export const SWAP_TONES: Record<SwapKind, StatusTone> = { cover: "info", swap: "primary", claim: "warning" };

/** Flags worth a warning next to a check-in (the rest are informational). */
export const WARNING_FLAGS: ReadonlySet<RecordFlag> = new Set(["outside_geofence", "auto_closed", "no_location"]);

/** A schedule or template colour slot (1–8) as the chart token behind it. */
export function slotColor(slot: number | null | undefined): string {
  const index = slot && slot >= 1 && slot <= 8 ? slot : 1;
  return `var(--c-chart-${index})`;
}

/** The UI language's decimal mark: "7.5" in English, "7,5" in Uzbek and Russian. */
function decimal(text: string): string {
  return currentLanguage() === "en" ? text : text.replace(".", ",");
}

/** "34 m", "1.2 km" ("1,2 km" in uz/ru). */
export function formatDistance(meters: number | null | undefined, units: { m: string; km: string }): string {
  if (meters === null || meters === undefined) return "—";
  if (meters >= 1000) return `${decimal((meters / 1000).toFixed(1))} ${units.km}`;
  return `${meters} ${units.m}`;
}

/** Minutes as hours with one decimal ("7.5", "7,5" in uz/ru), without units. */
export function hours(minutes: number): string {
  return decimal((Math.round((minutes / 60) * 10) / 10).toFixed(minutes % 60 === 0 ? 0 : 1));
}

/** "08:30" → "8:30", "18:00" → "18:00": a wall-clock time as short as it can be without losing minutes. */
export function compactTime(time: string): string {
  const [h = "0", m = "00"] = time.split(":");
  return `${Number(h)}:${m.slice(0, 2).padStart(2, "0")}`;
}

export function toMinutes(time: string): number {
  const [h = "0", m = "0"] = time.split(":");
  return Number(h) * 60 + Number(m);
}

/** Planned minutes of a shift from "HH:MM" times (an end before the start is the next day). */
export function spanMinutes(start: string, end: string, breakMinutes = 0): number {
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

/** First names are enough on dense boards ("Alisher V."). */
export function shortName(name: string): string {
  const [first = name, last] = name.split(" ");
  return last ? `${first} ${last.charAt(0)}.` : first;
}
