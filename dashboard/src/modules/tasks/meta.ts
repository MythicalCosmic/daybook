/** Colors, icons and words for task statuses, priorities and deadlines, shared by every view. */
import { TZDate } from "@date-fns/tz";
import { CalendarClock, CircleCheck, CircleDashed, CircleDot, CircleSlash, Hourglass, RotateCcw } from "@lucide/vue";
import type { Component } from "vue";

import type { StatusTone } from "@/components/StatusPill.vue";

import type { BoardColumnId, TaskPriority, TaskStatus } from "./types";

export const STATUS_TONE: Record<TaskStatus, StatusTone> = {
  todo: "neutral",
  in_progress: "info",
  review: "warning",
  returned: "danger",
  done: "success",
  cancelled: "neutral",
};

export const STATUS_ICON: Record<TaskStatus, Component> = {
  todo: CircleDashed,
  in_progress: CircleDot,
  review: Hourglass,
  returned: RotateCcw,
  done: CircleCheck,
  cancelled: CircleSlash,
};

/** Column dot colors on the board: tokens only. */
export const COLUMN_COLOR: Record<BoardColumnId, string> = {
  todo: "var(--c-subtle)",
  in_progress: "var(--c-info)",
  review: "var(--c-warning)",
  returned: "var(--c-danger)",
  done: "var(--c-success)",
};

export const PRIORITY_TONE: Record<TaskPriority, StatusTone> = {
  urgent: "danger",
  high: "warning",
  normal: "neutral",
  low: "neutral",
};

export const DUE_ICON = CalendarClock;

/** Minutes between two instants (positive when `later` is after `earlier`). */
export function minutesBetween(earlier: string | Date, later: string | Date): number {
  return Math.round((new Date(later).getTime() - new Date(earlier).getTime()) / 60_000);
}

/** "2 h 10 min", "45 min", "3 d" for a lateness in minutes. */
export function lateness(minutes: number, words: { min: string; h: string; d: string }): string {
  const value = Math.max(0, minutes);
  if (value < 60) return `${value} ${words.min}`;
  const hours = Math.floor(value / 60);
  if (hours < 24) {
    const rest = value % 60;
    return rest ? `${hours} ${words.h} ${rest} ${words.min}` : `${hours} ${words.h}`;
  }
  return `${Math.floor(hours / 24)} ${words.d}`;
}

/** A company-local day and wall-clock time ("2026-10-21", "18:00") as an ISO instant. */
export function zonedIso(day: string, time: string, timeZone: string): string {
  const [year, month, date] = day.split("-").map(Number) as [number, number, number];
  const [hour, minute] = time.split(":").map(Number) as [number, number];
  return new TZDate(year, month - 1, date, hour, minute, timeZone).toISOString();
}

/** The company-local day and time ("2026-10-21", "18:00") of an ISO instant. */
export function zonedParts(iso: string, timeZone: string): { day: string; time: string } {
  const zoned = new TZDate(new Date(iso).getTime(), timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    day: `${zoned.getFullYear()}-${pad(zoned.getMonth() + 1)}-${pad(zoned.getDate())}`,
    time: `${pad(zoned.getHours())}:${pad(zoned.getMinutes())}`,
  };
}
